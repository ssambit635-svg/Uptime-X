terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 6.0" } }
}
variable "name" { type = string }
variable "cidr" { type = string }
variable "tags" { type = map(string) }

data "aws_availability_zones" "available" { state = "available" }
resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(var.tags, { Name = var.name })
}
resource "aws_internet_gateway" "this" { vpc_id = aws_vpc.this.id }
resource "aws_subnet" "public" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags              = merge(var.tags, { Name = "${var.name}-public-${count.index}" })
}
resource "aws_subnet" "private" {
  count                   = 2
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.cidr, 8, 10 + count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
  tags                    = merge(var.tags, { Name = "${var.name}-private-${count.index}" })
}
resource "aws_eip" "nat" { domain = "vpc" }
resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.this]
  tags          = var.tags
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }
}
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
# HTTP(S) to private/control-plane ranges is denied before the general return-
# traffic rule. Security groups separately restrict outbound ports and DB CIDRs.
# AWS link-local task credentials/Route53 have platform-specific routing
# The application socket policy also rejects ALL non-public target destinations.
resource "aws_network_acl" "private" {
  vpc_id     = aws_vpc.this.id
  subnet_ids = aws_subnet.private[*].id
  tags       = var.tags
}
# Keep every rule standalone: mixing inline and standalone rules causes drift.
resource "aws_network_acl_rule" "allow_inbound" {
  network_acl_id = aws_network_acl.private.id
  egress         = false
  rule_number    = 900
  protocol       = "-1"
  rule_action    = "allow"
  cidr_block     = "0.0.0.0/0"
  from_port      = 0
  to_port        = 0
}
resource "aws_network_acl_rule" "allow_outbound" {
  network_acl_id = aws_network_acl.private.id
  egress         = true
  rule_number    = 900
  protocol       = "-1"
  rule_action    = "allow"
  cidr_block     = "0.0.0.0/0"
  from_port      = 0
  to_port        = 0
}
locals {
  denied_http = { for item in setproduct(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8"], [80, 443]) : "${item[0]}:${item[1]}" => { cidr = item[0], port = item[1] } }
}
resource "aws_network_acl_rule" "no_private_http" {
  for_each       = local.denied_http
  network_acl_id = aws_network_acl.private.id
  egress         = true
  rule_number    = 100 + index(sort(keys(local.denied_http)), each.key)
  protocol       = "tcp"
  rule_action    = "deny"
  cidr_block     = each.value.cidr
  from_port      = each.value.port
  to_port        = each.value.port
}
output "vpc_id" { value = aws_vpc.this.id }
output "private_subnets" { value = aws_subnet.private[*].id }
output "public_subnets" { value = aws_subnet.public[*].id }
output "private_route_table" { value = aws_route_table.private.id }
