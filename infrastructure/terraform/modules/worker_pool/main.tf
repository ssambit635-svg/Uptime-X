terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 6.0" } }
}
variable "name" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "vpc_id" { type = string }
variable "subnets" { type = list(string) }
variable "primary_database_cidr" { type = string }
variable "image" { type = string }
variable "repository_arn" { type = string }
variable "database_secret_arn" { type = string }
variable "regions" { type = list(string) }
variable "queue_urls" { type = map(string) }
variable "queue_arn" { type = string }
variable "queue_name" { type = string }
variable "dlq_name" { type = string }
variable "enabled" { type = bool }
variable "max_tasks" { type = number }
variable "alert_email" { type = string }
variable "tags" { type = map(string) }
locals {
  prefix = "${var.name}-${var.region}"
  trust  = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnLike = { "aws:SourceArn" = "arn:aws:ecs:${var.region}:${var.account_id}:*" } } }] })
  environment = [
    { name = "APP_ENV", value = "production" },
    { name = "SESSION_COOKIE_SECURE", value = "true" },
    { name = "MONITORING_ENABLED", value = "true" },
    { name = "QUEUE_BACKEND", value = "sqs" },
    { name = "MONITOR_REGIONS", value = jsonencode(var.regions) },
    { name = "SQS_QUEUE_URLS", value = jsonencode(var.queue_urls) },
    { name = "AWS_REGION", value = var.region },
    { name = "WORKER_REGION", value = var.region },
    { name = "JOB_LEASE_SECONDS", value = "90" },
    { name = "MAX_JOB_ATTEMPTS", value = "5" },
    { name = "CHECK_RETENTION_DAYS", value = "90" },
  ]
}
resource "aws_ecs_cluster" "this" {
  name = local.prefix
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = var.tags
}
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/uptimex/${local.prefix}/worker"
  retention_in_days = 30
  tags              = var.tags
}
resource "aws_security_group" "worker" {
  name_prefix = "${local.prefix}-worker-"
  vpc_id      = var.vpc_id
  description = "No inbound connections; bounded public HTTP and TLS Postgres only"
  tags        = var.tags
}
resource "aws_vpc_security_group_egress_rule" "http" {
  for_each          = toset(["80", "443"])
  security_group_id = aws_security_group.worker.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = tonumber(each.key)
  to_port           = tonumber(each.key)
}
resource "aws_vpc_security_group_egress_rule" "database" {
  security_group_id = aws_security_group.worker.id
  cidr_ipv4         = var.primary_database_cidr
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
}
resource "aws_iam_role" "execution" {
  name               = "${local.prefix}-execution"
  assume_role_policy = local.trust
  tags               = var.tags
}
resource "aws_iam_role_policy" "execution" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = var.repository_arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.worker.arn}:*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.database_secret_arn },
    ]
  })
}
resource "aws_iam_role" "worker" {
  name               = "${local.prefix}-worker"
  assume_role_policy = local.trust
  tags               = var.tags
}
resource "aws_iam_role_policy" "consume" {
  role   = aws_iam_role.worker.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], Resource = var.queue_arn }] })
}
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker.arn
  container_definitions = jsonencode([{
    name             = "worker", image = var.image, essential = true,
    user             = "10001", readonlyRootFilesystem = true,
    command          = ["python", "-m", "app.workers.cli", "worker", "--loop"],
    environment      = local.environment,
    secrets          = [{ name = "DATABASE_URL", valueFrom = "${var.database_secret_arn}:database_url::" }],
    stopTimeout      = 30,
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.worker.name, "awslogs-region" = var.region, "awslogs-stream-prefix" = "worker" } },
    healthCheck      = { command = ["CMD", "python", "-m", "app.workers.cli", "health", "--role", "worker"], interval = 30, timeout = 10, retries = 3, startPeriod = 60 },
  }])
  tags = var.tags
}
resource "aws_ecs_service" "worker" {
  name                               = "worker"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.worker.arn
  desired_count                      = var.enabled ? 1 : 0
  wait_for_steady_state              = true
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = var.subnets
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
  lifecycle {
    precondition {
      condition     = !var.enabled || strcontains(var.image, "@sha256:")
      error_message = "Pin a published image digest before enabling services."
    }
  }
  depends_on = [aws_iam_role_policy.execution, aws_iam_role_policy.consume]
  tags       = var.tags
}
resource "aws_appautoscaling_target" "workers" {
  max_capacity       = var.max_tasks
  min_capacity       = var.enabled ? 1 : 0
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
  suspended_state {
    dynamic_scaling_in_suspended  = !var.enabled
    dynamic_scaling_out_suspended = !var.enabled
    scheduled_scaling_suspended   = !var.enabled
  }
}
resource "aws_appautoscaling_policy" "out" {
  name               = "${local.prefix}-out"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.workers.resource_id
  scalable_dimension = aws_appautoscaling_target.workers.scalable_dimension
  service_namespace  = "ecs"
  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 90
    metric_aggregation_type = "Maximum"
    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}
resource "aws_appautoscaling_policy" "in" {
  name               = "${local.prefix}-in"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.workers.resource_id
  scalable_dimension = aws_appautoscaling_target.workers.scalable_dimension
  service_namespace  = "ecs"
  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 180
    metric_aggregation_type = "Maximum"
    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = -1
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "scale_out" {
  alarm_name          = "${local.prefix}-scale-out"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.queue_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 20
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_appautoscaling_policy.out.arn]
  actions_enabled     = var.enabled
  treat_missing_data  = "notBreaching"
}
resource "aws_cloudwatch_metric_alarm" "scale_in" {
  alarm_name          = "${local.prefix}-scale-in"
  comparison_operator = "LessThanOrEqualToThreshold"
  evaluation_periods  = 5
  threshold           = 0
  actions_enabled     = var.enabled
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.in.arn]
  metric_query {
    id = "visible"
    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      period      = 60
      stat        = "Maximum"
      dimensions  = { QueueName = var.queue_name }
    }
  }
  metric_query {
    id = "inflight"
    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesNotVisible"
      period      = 60
      stat        = "Maximum"
      dimensions  = { QueueName = var.queue_name }
    }
  }
  metric_query {
    id          = "total"
    expression  = "visible + inflight"
    label       = "All pending messages"
    return_data = true
  }
}
resource "aws_sns_topic" "alerts" { name = "${local.prefix}-alerts" }
resource "aws_sns_topic_subscription" "alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
resource "aws_sns_topic_policy" "cloudwatch" {
  arn    = aws_sns_topic.alerts.arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.alerts.arn, Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnLike = { "aws:SourceArn" = "arn:aws:cloudwatch:${var.region}:${var.account_id}:alarm:*" } } }] })
}
resource "aws_cloudwatch_metric_alarm" "heartbeat" {
  alarm_name          = "${local.prefix}-worker-silent"
  namespace           = "UptimeX/Monitoring"
  metric_name         = "Heartbeat"
  dimensions          = { Role = "worker", Region = var.region }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  actions_enabled     = var.enabled
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "${local.prefix}-dead-letters"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.dlq_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enabled
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "age" {
  alarm_name          = "${local.prefix}-queue-lag"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = var.queue_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 300
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enabled
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${local.prefix}-worker-internal-errors"
  namespace           = "UptimeX/Monitoring"
  metric_name         = "ServiceErrors"
  dimensions          = { Role = "worker", Region = var.region }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enabled
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
output "cluster_arn" { value = aws_ecs_cluster.this.arn }
output "cluster_name" { value = aws_ecs_cluster.this.name }
output "security_group_id" { value = aws_security_group.worker.id }
output "execution_role_arn" { value = aws_iam_role.execution.arn }
output "task_definition_arn" { value = aws_ecs_task_definition.worker.arn }
output "environment" { value = local.environment }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }

output "log_group_name" { value = aws_cloudwatch_log_group.worker.name }
