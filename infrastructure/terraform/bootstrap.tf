resource "aws_iam_role" "bootstrap" {
  name               = "${local.name}-bootstrap"
  assume_role_policy = local.ecs_trust
}
resource "aws_iam_role_policy" "bootstrap" {
  role = aws_iam_role.bootstrap.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_db_instance.database.master_user_secret[0].secret_arn, aws_secretsmanager_secret.api_database.arn, aws_secretsmanager_secret.worker_database.arn] },
      { Effect = "Allow", Action = ["secretsmanager:PutSecretValue"], Resource = [aws_secretsmanager_secret.api_database.arn, aws_secretsmanager_secret.worker_database.arn] },
    ]
  })
}
resource "aws_ecs_task_definition" "bootstrap" {
  family                   = "${local.name}-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = module.primary_workers.execution_role_arn
  task_role_arn            = aws_iam_role.bootstrap.arn
  container_definitions = jsonencode([{
    name                   = "bootstrap", image = local.image, essential = true, user = "10001",
    readonlyRootFilesystem = true, stopTimeout = 30,
    command                = ["python", "-m", "app.workers.bootstrap"],
    environment = concat(module.primary_workers.environment, [
      { name = "MASTER_SECRET_ARN", value = aws_db_instance.database.master_user_secret[0].secret_arn },
      { name = "API_DATABASE_SECRET_ARN", value = aws_secretsmanager_secret.api_database.arn },
      { name = "WORKER_DATABASE_SECRET_ARN", value = aws_secretsmanager_secret.worker_database.arn },
      { name = "DB_HOST", value = aws_db_instance.database.address },
      { name = "DB_NAME", value = aws_db_instance.database.db_name },
    ]),
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = module.primary_workers.log_group_name, "awslogs-region" = var.primary_region, "awslogs-stream-prefix" = "bootstrap" } },
  }])
}
output "deployment" {
  value = {
    image_repository         = aws_ecr_repository.app.repository_url
    alb_hostname             = aws_lb.api.dns_name
    cluster                  = module.primary_workers.cluster_arn
    bootstrap_task           = aws_ecs_task_definition.bootstrap.arn
    private_subnets          = module.primary_network.private_subnets
    bootstrap_security_group = module.primary_workers.security_group_id
    api_service              = aws_ecs_service.api.name
    worker_clusters          = { (var.primary_region) = module.primary_workers.cluster_arn, (var.secondary_region) = module.secondary_workers.cluster_arn }
    queues                   = local.queues
    worker_secret_arn        = aws_secretsmanager_secret.worker_database.arn
  }
}
