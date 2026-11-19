resource "aws_sqs_queue" "primary_dlq" {
  name                      = "${local.name}-checks-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "secondary_dlq" {
  provider                  = aws.secondary
  name                      = "${local.name}-checks-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "primary" {
  name                       = "${local.name}-checks"
  visibility_timeout_seconds = 90
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.primary_dlq.arn, maxReceiveCount = 5 })
}
resource "aws_sqs_queue" "secondary" {
  provider                   = aws.secondary
  name                       = "${local.name}-checks"
  visibility_timeout_seconds = 90
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.secondary_dlq.arn, maxReceiveCount = 5 })
}
resource "aws_sqs_queue_redrive_allow_policy" "primary" {
  queue_url            = aws_sqs_queue.primary_dlq.url
  redrive_allow_policy = jsonencode({ redrivePermission = "byQueue", sourceQueueArns = [aws_sqs_queue.primary.arn] })
}
resource "aws_sqs_queue_redrive_allow_policy" "secondary" {
  provider             = aws.secondary
  queue_url            = aws_sqs_queue.secondary_dlq.url
  redrive_allow_policy = jsonencode({ redrivePermission = "byQueue", sourceQueueArns = [aws_sqs_queue.secondary.arn] })
}
resource "aws_sqs_queue_policy" "primary_tls" {
  queue_url = aws_sqs_queue.primary.url
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "sqs:*", Resource = aws_sqs_queue.primary.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
resource "aws_sqs_queue_policy" "secondary_tls" {
  provider  = aws.secondary
  queue_url = aws_sqs_queue.secondary.url
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "sqs:*", Resource = aws_sqs_queue.secondary.arn, Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
module "primary_workers" {
  source                = "./modules/worker_pool"
  name                  = local.name
  region                = var.primary_region
  account_id            = data.aws_caller_identity.current.account_id
  vpc_id                = module.primary_network.vpc_id
  subnets               = module.primary_network.private_subnets
  primary_database_cidr = "10.40.0.0/16"
  image                 = local.image
  repository_arn        = aws_ecr_repository.app.arn
  database_secret_arn   = aws_secretsmanager_secret.worker_database.arn
  regions               = local.regions
  queue_urls            = local.queues
  queue_arn             = aws_sqs_queue.primary.arn
  queue_name            = aws_sqs_queue.primary.name
  dlq_name              = aws_sqs_queue.primary_dlq.name
  enabled               = var.enable_services
  max_tasks             = var.max_worker_tasks
  alert_email           = var.alert_email
  tags                  = local.tags
}
module "secondary_workers" {
  source                = "./modules/worker_pool"
  providers             = { aws = aws.secondary }
  name                  = local.name
  region                = var.secondary_region
  account_id            = data.aws_caller_identity.current.account_id
  vpc_id                = module.secondary_network.vpc_id
  subnets               = module.secondary_network.private_subnets
  primary_database_cidr = "10.40.0.0/16"
  image                 = local.image
  repository_arn        = aws_ecr_repository.app.arn
  # ECS secret injection cannot read another region's secret. The regional
  # replica is managed below, and uses the same restricted worker DB identity.
  database_secret_arn = replace(aws_secretsmanager_secret.worker_database.arn, ":${var.primary_region}:", ":${var.secondary_region}:")
  regions             = local.regions
  queue_urls          = local.queues
  queue_arn           = aws_sqs_queue.secondary.arn
  queue_name          = aws_sqs_queue.secondary.name
  dlq_name            = aws_sqs_queue.secondary_dlq.name
  enabled             = var.enable_services
  max_tasks           = var.max_worker_tasks
  alert_email         = var.alert_email
  tags                = local.tags
  depends_on          = [aws_vpc_peering_connection_accepter.regions, aws_route.to_primary, aws_route.to_secondary]
}
