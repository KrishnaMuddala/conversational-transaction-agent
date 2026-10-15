###############################################################################
# Outputs — useful after `terraform apply`
###############################################################################

output "app_url" {
  description = "Public URL of the DCTA application"
  value       = "https://${tencentcloud_eip.main.public_ip}"
}

output "cvm_public_ip" {
  description = "CVM public IP (for SSH access)"
  value       = tencentcloud_eip.main.public_ip
}

output "cvm_ssh_command" {
  description = "SSH command to access the CVM"
  value       = "ssh ubuntu@${tencentcloud_eip.main.public_ip}"
}

output "database_endpoint" {
  description = "TDSQL-C PostgreSQL endpoint (internal)"
  value       = "${tencentcloud_postgresql_instance.main.private_access_ip}:${tencentcloud_postgresql_instance.main.private_access_port}"
}

output "database_name" {
  description = "Database name"
  value       = var.db_name
}

output "cos_bucket" {
  description = "COS bucket for audio archives"
  value       = var.enable_cos ? tencentcloud_cos_bucket.audit[0].bucket : "COS disabled (set enable_cos=true after identity verification)"
}

output "kms_key_id" {
  description = "KMS key ID for biometric verification"
  value       = tencentcloud_kms_key.verify.id
}

output "terraform_state_bucket" {
  description = "COS bucket for Terraform remote state"
  value       = var.enable_cos ? tencentcloud_cos_bucket.tfstate[0].bucket : "COS disabled (set enable_cos=true after identity verification)"
}
