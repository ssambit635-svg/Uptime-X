locals {
  ecs_trust = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }, ArnLike = { "aws:SourceArn" = "arn:aws:ecs:${var.primary_region}:${data.aws_caller_identity.current.account_id}:*" } } }] })
}
resource "aws_security_group" "edge" {
  name_prefix = "${local.name}-edge-"
  vpc_id      = module.primary_network.vpc_id
}
resource "aws_vpc_security_group_ingress_rule" "edge" {
  for_each          = toset(["80", "443"])
  security_group_id = aws_security_group.edge.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = tonumber(each.key)
  to_port           = tonumber(each.key)
}
resource "aws_security_group" "api" {
  name_prefix = "${local.name}-api-"
  vpc_id      = module.primary_network.vpc_id
}
resource "aws_vpc_security_group_egress_rule" "edge_api" {
  security_group_id            = aws_security_group.edge.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
resource "aws_vpc_security_group_ingress_rule" "api" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.edge.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
resource "aws_vpc_security_group_egress_rule" "api_database" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "api_https" {
  security_group_id = aws_security_group.api.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_lb" "api" {
  name                       = local.name
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.edge.id]
  subnets                    = module.primary_network.public_subnets
  drop_invalid_header_fields = true
  preserve_host_header       = true
  enable_deletion_protection = true
}
resource "aws_lb_target_group" "api" {
  name                 = local.name
  port                 = 8000
  protocol             = "HTTP"
  vpc_id               = module.primary_network.vpc_id
  target_type          = "ip"
  deregistration_delay = 30
  health_check {
    path                = "/api/v1/health"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
resource "aws_cloudwatch_log_group" "api" {
  name              = "/uptimex/${local.name}/api"
  retention_in_days = 30
}
resource "aws_iam_role" "api_execution" {
  name               = "${local.name}-api-execution"
  assume_role_policy = local.ecs_trust
}
resource "aws_iam_role_policy" "api_execution" {
  role = aws_iam_role.api_execution.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = aws_ecr_repository.app.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.api.arn}:*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_secretsmanager_secret.api_database.arn },
    ]
  })
}
resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = local.ecs_trust
  # No queue, infrastructure-changing or lab permissions for the HTTP API.
}
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  task_role_arn            = aws_iam_role.api.arn
  execution_role_arn       = aws_iam_role.api_execution.arn
  container_definitions = jsonencode([{
    name             = "api", image = local.image, essential = true, user = "10001", readonlyRootFilesystem = true,
    environment      = concat(module.primary_workers.environment, [{ name = "FRONTEND_DIST", value = "/app/frontend-dist" }]),
    secrets          = [{ name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.api_database.arn}:database_url::" }],
    portMappings     = [{ containerPort = 8000, protocol = "tcp" }],
    stopTimeout      = 30,
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.api.name, "awslogs-region" = var.primary_region, "awslogs-stream-prefix" = "api" } },
    healthCheck      = { command = ["CMD", "python", "-c", "__import__('urllib.request', fromlist=['urlopen']).urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)"], interval = 30, timeout = 10, retries = 3, startPeriod = 60 },
  }])
}
resource "aws_ecs_service" "api" {
  name                              = "api"
  cluster                           = module.primary_workers.cluster_arn
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.enable_services ? 1 : 0
  launch_type                       = "FARGATE"
  platform_version                  = "1.4.0"
  wait_for_steady_state             = true
  health_check_grace_period_seconds = 90
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = module.primary_network.private_subnets
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  lifecycle {
    precondition {
      condition     = !var.enable_services || var.app_image != ""
      error_message = "Publish and pin the image, bootstrap DB identities and run migrations first."
    }
  }
  depends_on = [aws_lb_listener.https, aws_iam_role_policy.api_execution]
}
