resource "aws_scheduler_schedule_group" "monitoring" { name = local.name }
resource "aws_sqs_queue" "scheduler_dlq" {
  name                      = "${local.name}-scheduler-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}
resource "aws_iam_role" "scheduler_task" {
  name               = "${local.name}-scheduler"
  assume_role_policy = local.ecs_trust
}
resource "aws_iam_role_policy" "publish" {
  role   = aws_iam_role.scheduler_task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["sqs:SendMessage"], Resource = local.queue_arns }] })
}
resource "aws_ecs_task_definition" "scheduled" {
  for_each = {
    scheduler = ["python", "-m", "app.workers.cli", "scheduler"]
    retention = ["python", "-m", "app.workers.cli", "prune"]
  }
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = module.primary_workers.execution_role_arn
  task_role_arn            = aws_iam_role.scheduler_task.arn
  container_definitions = jsonencode([{
    name             = each.key, image = local.image, essential = true, user = "10001", readonlyRootFilesystem = true,
    command          = each.value, stopTimeout = 30,
    environment      = module.primary_workers.environment,
    secrets          = [{ name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.worker_database.arn}:database_url::" }],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = module.primary_workers.log_group_name, "awslogs-region" = var.primary_region, "awslogs-stream-prefix" = each.key } },
  }])
}
resource "aws_iam_role" "scheduler_invoke" {
  name               = "${local.name}-scheduler-invoke"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }, ArnEquals = { "aws:SourceArn" = aws_scheduler_schedule_group.monitoring.arn } } }] })
}
resource "aws_iam_role_policy" "scheduler_invoke" {
  role = aws_iam_role.scheduler_invoke.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Effect = "Allow", Action = ["ecs:RunTask"], Resource = [for task in aws_ecs_task_definition.scheduled : task.arn], Condition = { ArnEquals = { "ecs:cluster" = module.primary_workers.cluster_arn } } },
      { Effect = "Allow", Action = ["iam:PassRole"], Resource = [module.primary_workers.execution_role_arn, aws_iam_role.scheduler_task.arn], Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.scheduler_dlq.arn },
    ]
  })
}
resource "aws_scheduler_schedule" "monitoring" {
  for_each                     = { scheduler = "rate(1 minute)", retention = "cron(15 2 * * ? *)" }
  name                         = "${local.name}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.monitoring.name
  schedule_expression          = each.value
  schedule_expression_timezone = "UTC"
  state                        = var.enable_services ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = module.primary_workers.cluster_arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.scheduled[each.key].arn
      launch_type         = "FARGATE"
      platform_version    = "1.4.0"
      task_count          = 1
      network_configuration {
        subnets          = module.primary_network.private_subnets
        security_groups  = [module.primary_workers.security_group_id]
        assign_public_ip = false
      }
    }
    retry_policy {
      maximum_event_age_in_seconds = 60
      maximum_retry_attempts       = 2
    }
    dead_letter_config { arn = aws_sqs_queue.scheduler_dlq.arn }
  }
  depends_on = [aws_iam_role_policy.scheduler_invoke]
}
resource "aws_cloudwatch_metric_alarm" "scheduler" {
  alarm_name          = "${local.name}-scheduler-silent"
  namespace           = "UptimeX/Monitoring"
  metric_name         = "Heartbeat"
  dimensions          = { Role = "scheduler", Region = var.primary_region }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "scheduler_dlq" {
  alarm_name          = "${local.name}-scheduler-launch-failures"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.scheduler_dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_cloudwatch_dashboard" "monitoring" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6, properties = {
          title = "Worker and scheduler heartbeats", region = var.primary_region, view = "timeSeries", period = 60, stat = "Sum", metrics = [
            ["UptimeX/Monitoring", "Heartbeat", "Role", "worker", "Region", var.primary_region],
            ["UptimeX/Monitoring", "Heartbeat", "Role", "scheduler", "Region", var.primary_region],
            ["UptimeX/Monitoring", "Heartbeat", "Role", "worker", "Region", var.secondary_region, { region = var.secondary_region }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6, properties = {
          title = "Queue age (seconds)", region = var.primary_region, view = "timeSeries", period = 60, stat = "Maximum", metrics = [
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.primary.name],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.secondary.name, { region = var.secondary_region }],
          ]
        }
      },
    ]
  })
}
