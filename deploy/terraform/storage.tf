###############################################################################
# Storage — COS bucket for audio archives + Terraform state
#
# COS requires identity verification on the Tencent Cloud account. If not
# verified, the buckets will fail (HTTP 451) — this does NOT block the core
# application (audit logs fall back to database storage). Use -target or
# comment out if your account isn't verified yet.
###############################################################################

# COS bucket for raw audio + audit archives
resource "tencentcloud_cos_bucket" "audit" {
  count  = var.enable_cos ? 1 : 0
  bucket = "${var.project_name}-audit-${var.app_id}"
  acl    = "private"

  cors_rules {
    allowed_origins = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_headers = ["*"]
    max_age_seconds = 3600
  }
}

# COS bucket for Terraform remote state (optional — local state works for a
# single-person team; switch to remote when multiple operators are involved)
resource "tencentcloud_cos_bucket" "tfstate" {
  count  = var.enable_cos ? 1 : 0
  bucket = "${var.project_name}-tfstate-${var.app_id}"
  acl    = "private"
}
