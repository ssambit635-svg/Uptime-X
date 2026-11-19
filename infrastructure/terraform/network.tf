module "primary_network" {
  source = "./modules/network"
  name   = "${local.name}-primary"
  cidr   = "10.40.0.0/16"
  tags   = local.tags
}
module "secondary_network" {
  source    = "./modules/network"
  providers = { aws = aws.secondary }
  name      = "${local.name}-secondary"
  cidr      = "10.41.0.0/16"
  tags      = local.tags
}
resource "aws_vpc_peering_connection" "regions" {
  vpc_id      = module.primary_network.vpc_id
  peer_vpc_id = module.secondary_network.vpc_id
  peer_region = var.secondary_region
  auto_accept = false
  tags        = local.tags
}
resource "aws_vpc_peering_connection_accepter" "regions" {
  provider                  = aws.secondary
  vpc_peering_connection_id = aws_vpc_peering_connection.regions.id
  auto_accept               = true
  tags                      = local.tags
}
resource "aws_route" "to_secondary" {
  route_table_id            = module.primary_network.private_route_table
  destination_cidr_block    = "10.41.0.0/16"
  vpc_peering_connection_id = aws_vpc_peering_connection_accepter.regions.id
}
resource "aws_route" "to_primary" {
  provider                  = aws.secondary
  route_table_id            = module.secondary_network.private_route_table
  destination_cidr_block    = "10.40.0.0/16"
  vpc_peering_connection_id = aws_vpc_peering_connection_accepter.regions.id
}
resource "aws_security_group" "database" {
  name_prefix = "${local.name}-database-"
  vpc_id      = module.primary_network.vpc_id
  description = "Only primary API/worker tasks and peered regional workers on PostgreSQL TLS"
}
resource "aws_vpc_security_group_ingress_rule" "database_api" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "database_primary_worker" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = module.primary_workers.security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "database_secondary_worker" {
  security_group_id = aws_security_group.database.id
  cidr_ipv4         = "10.41.0.0/16"
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
}
resource "aws_db_subnet_group" "database" {
  name       = local.name
  subnet_ids = module.primary_network.private_subnets
}
resource "aws_db_parameter_group" "database" {
  name_prefix = "${local.name}-"
  family      = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}
resource "aws_db_instance" "database" {
  identifier                      = local.name
  engine                          = "postgres"
  engine_version                  = "16"
  instance_class                  = "db.t4g.micro"
  allocated_storage               = 20
  max_allocated_storage           = 40
  storage_encrypted               = true
  storage_type                    = "gp3"
  db_name                         = "uptimex"
  username                        = "uptimex_owner"
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.database.name
  parameter_group_name            = aws_db_parameter_group.database.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  publicly_accessible             = false
  backup_retention_period         = 7
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final"
  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  copy_tags_to_snapshot           = true
}
resource "aws_secretsmanager_secret" "api_database" {
  name                    = "${local.name}/api-database"
  recovery_window_in_days = 7
}
resource "aws_secretsmanager_secret" "worker_database" {
  name = "${local.name}/worker-database"
  replica { region = var.secondary_region }
  recovery_window_in_days = 7
}
resource "aws_ecr_repository" "app" {
  name                 = "${local.name}-app"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Expire untagged build remnants", selection = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 14 }, action = { type = "expire" } }] })
}
resource "aws_budgets_budget" "monthly" {
  name         = local.name
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
