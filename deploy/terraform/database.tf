###############################################################################
# Database — TDSQL-C PostgreSQL Serverless
###############################################################################

# Generate a random password if one isn't provided
resource "random_password" "db_root" {
  length           = 24
  special          = true
  override_special = "!@#$%^&*()-_=+"
}

locals {
  db_password = var.db_root_password != "" ? var.db_root_password : random_password.db_root.result
}

resource "tencentcloud_postgresql_instance" "main" {
  name              = "${var.project_name}-pg"
  availability_zone = var.availability_zone
  db_major_version  = "15"
  engine_version    = "15.19"
  root_user         = "dbsadmin"
  root_password     = local.db_password
  charset           = "UTF8"
  project_id        = 0
  security_groups   = [tencentcloud_security_group.db.id]
  subnet_id         = tencentcloud_subnet.main.id
  vpc_id            = tencentcloud_vpc.main.id
  # pg.es.4g.mechanical -> 2 vCPU / 4 GB; provider requires explicit cpu+memory+storage
  cpu    = 2
  memory = 4
  storage = 50
}

# The connection string passed to the backend
locals {
  database_url = "postgresql://${var.db_user}:${local.db_password}@${tencentcloud_postgresql_instance.main.private_access_ip}:${tencentcloud_postgresql_instance.main.private_access_port}/${var.db_name}?sslmode=disable"
}
