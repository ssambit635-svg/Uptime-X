terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # Configure an encrypted, access-controlled S3 backend using -backend-config.
  # Never commit state or account-specific backend configuration.
  backend "s3" {}
}
provider "aws" {
  region = var.primary_region
  default_tags { tags = local.tags }
}
provider "aws" {
  alias  = "secondary"
  region = var.secondary_region
  default_tags { tags = local.tags }
}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
locals {
  name       = "uptimex-${var.environment}"
  tags       = { Project = "UptimeX", Environment = var.environment, Owner = var.owner, Service = "observe" }
  regions    = [var.primary_region, var.secondary_region]
  queues     = { (var.primary_region) = aws_sqs_queue.primary.url, (var.secondary_region) = aws_sqs_queue.secondary.url }
  queue_arns = [aws_sqs_queue.primary.arn, aws_sqs_queue.secondary.arn]
  image      = var.app_image == "" ? "${aws_ecr_repository.app.repository_url}:not-published" : var.app_image
}
variable "environment" {
  type    = string
  default = "staging"
  validation {
    condition     = var.environment == "staging"
    error_message = "This stack is staging-only. Public production requires the Phase 6 launch review."
  }
}
variable "owner" { type = string }
variable "primary_region" {
  type    = string
  default = "ap-south-1"
}
variable "secondary_region" {
  type    = string
  default = "ap-southeast-1"
  validation {
    condition     = var.secondary_region != var.primary_region
    error_message = "Regional worker pools must run in different AWS regions."
  }
}
variable "certificate_arn" {
  type        = string
  description = "Validated ACM HTTPS certificate in primary_region. DNS is managed explicitly by the operator."
}
variable "alert_email" { type = string }
variable "monthly_budget_usd" {
  type        = number
  description = "Required operator-approved budget alert, not a hard spend cap. NAT/RDS/Fargate incur charges."
  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 1000
    error_message = "Set an explicitly approved monthly budget within the staging safety ceiling."
  }
}
variable "app_image" {
  type        = string
  default     = ""
  description = "Immutable ECR image URI including @sha256 digest. Empty only for initial disabled provisioning."
  validation {
    condition     = var.app_image == "" || can(regex("@sha256:[a-f0-9]{64}$", var.app_image))
    error_message = "Deploy only immutable digest-pinned images."
  }
}
variable "enable_services" {
  type        = bool
  default     = false
  description = "Keep false until image publication, private bootstrap/migrations and plan review are complete."
}
variable "max_worker_tasks" {
  type    = number
  default = 2
  validation {
    condition     = var.max_worker_tasks >= 1 && var.max_worker_tasks <= 3 && floor(var.max_worker_tasks) == var.max_worker_tasks
    error_message = "Worker task capacity must remain between one and three per region."
  }
}
