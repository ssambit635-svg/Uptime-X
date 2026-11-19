# Operational alarms only. These are not the Phase 3 customer notification system.
resource "aws_cloudwatch_metric_alarm" "api_unhealthy" {
  alarm_name          = "${local.name}-api-unhealthy"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${local.name}-api-errors"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${local.name}-api-response-time"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 3
  threshold           = 2
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "pipeline" {
  for_each            = { outbox = { metric = "OutboxAgeSeconds", threshold = 120 }, dead_jobs = { metric = "DeadJobs", threshold = 0 } }
  alarm_name          = "${local.name}-${each.key}"
  namespace           = "UptimeX/Monitoring"
  metric_name         = each.value.metric
  dimensions          = { Role = "scheduler", Region = var.primary_region }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_cloudwatch_metric_alarm" "database" {
  for_each = {
    connections = { metric = "DatabaseConnections", threshold = 60, comparison = "GreaterThanThreshold" }
    storage     = { metric = "FreeStorageSpace", threshold = 2147483648, comparison = "LessThanThreshold" }
    reads       = { metric = "ReadLatency", threshold = 0.2, comparison = "GreaterThanThreshold" }
    writes      = { metric = "WriteLatency", threshold = 0.2, comparison = "GreaterThanThreshold" }
  }
  alarm_name          = "${local.name}-database-${each.key}"
  namespace           = "AWS/RDS"
  metric_name         = each.value.metric
  dimensions          = { DBInstanceIdentifier = aws_db_instance.database.identifier }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 3
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.enable_services
  alarm_actions       = [module.primary_workers.alerts_topic_arn]
}
resource "aws_sqs_queue_policy" "primary_dlq_tls" {
  queue_url = aws_sqs_queue.primary_dlq.url
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "sqs:*", Resource = aws_sqs_queue.primary_dlq.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
resource "aws_sqs_queue_policy" "secondary_dlq_tls" {
  provider  = aws.secondary
  queue_url = aws_sqs_queue.secondary_dlq.url
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "sqs:*", Resource = aws_sqs_queue.secondary_dlq.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
resource "aws_sqs_queue_policy" "scheduler_dlq_tls" {
  queue_url = aws_sqs_queue.scheduler_dlq.url
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "sqs:*", Resource = aws_sqs_queue.scheduler_dlq.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
