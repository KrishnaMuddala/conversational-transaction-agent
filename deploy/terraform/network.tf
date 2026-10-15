###############################################################################
# Networking — VPC, subnet, security groups
###############################################################################

resource "tencentcloud_vpc" "main" {
  name         = "${var.project_name}-vpc"
  cidr_block   = var.vpc_cidr
  dns_servers  = ["183.60.83.19", "183.60.82.98"]
}

resource "tencentcloud_subnet" "main" {
  name              = "${var.project_name}-subnet"
  vpc_id            = tencentcloud_vpc.main.id
  cidr_block        = var.subnet_cidr
  availability_zone = var.availability_zone
  is_multicast      = false
}

# ---------------------------------------------------------------------------
# CVM security group — allows SSH (22), HTTP (80), HTTPS (443) from anywhere
# and all internal traffic within the VPC.
# ---------------------------------------------------------------------------
resource "tencentcloud_security_group" "cvm" {
  name        = "${var.project_name}-cvm-sg"
  description = "DCTA CVM — SSH + HTTP + HTTPS"
  project_id  = 0
}

resource "tencentcloud_security_group_rule" "ssh" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "22"
  cidr_ip           = "0.0.0.0/0"
  policy            = "accept"
}

resource "tencentcloud_security_group_rule" "http" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "80"
  cidr_ip           = "0.0.0.0/0"
  policy            = "accept"
}

resource "tencentcloud_security_group_rule" "https" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "443"
  cidr_ip           = "0.0.0.0/0"
  policy            = "accept"
}

resource "tencentcloud_security_group_rule" "internal_tcp" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "1-65535"
  cidr_ip           = var.vpc_cidr
  policy            = "accept"
}

resource "tencentcloud_security_group_rule" "internal_udp" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "ingress"
  ip_protocol       = "udp"
  port_range        = "1-65535"
  cidr_ip           = var.vpc_cidr
  policy            = "accept"
}

resource "tencentcloud_security_group_rule" "egress_tcp" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "egress"
  ip_protocol       = "tcp"
  port_range        = "1-65535"
  cidr_ip           = "0.0.0.0/0"
  policy            = "accept"
}

resource "tencentcloud_security_group_rule" "egress_udp" {
  security_group_id = tencentcloud_security_group.cvm.id
  type              = "egress"
  ip_protocol       = "udp"
  port_range        = "1-65535"
  cidr_ip           = "0.0.0.0/0"
  policy            = "accept"
}

# ---------------------------------------------------------------------------
# Database security group — only accepts traffic from the CVM SG
# ---------------------------------------------------------------------------
resource "tencentcloud_security_group" "db" {
  name        = "${var.project_name}-db-sg"
  description = "DCTA TDSQL-C — CVM only"
  project_id  = 0
}

resource "tencentcloud_security_group_rule" "db_pg" {
  security_group_id = tencentcloud_security_group.db.id
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "5432"
  source_sgid       = tencentcloud_security_group.cvm.id
  policy            = "accept"
}
