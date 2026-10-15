###############################################################################
# Input variables
###############################################################################

variable "region" {
  description = "Tencent Cloud region for all resources"
  type        = string
  default     = "ap-singapore"
}

variable "availability_zone" {
  description = "Availability zone for the CVM instance"
  type        = string
  default     = "ap-singapore-1"
}

variable "cvm_image_id" {
  description = "CVM image ID for Ubuntu 22.04. The CAM user may not have cvm:DescribeImages permission, so provide the image ID directly. Find it in the CVM console > Images, or use the Tencent Cloud CLI: tccli cvm DescribeImages --filter Name:image-type,Values:PUBLIC_IMAGE --filter Name:platform,Values:Ubuntu --Region ap-singapore"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Credentials — provide via TF_VAR_* environment variables or a terraform.tfvars
# file. NEVER commit real values.
# ---------------------------------------------------------------------------

variable "secret_id" {
  description = "Tencent Cloud CAM SecretId (provider auth + TTS/KMS/COS)"
  type        = string
  sensitive   = true
}

variable "secret_key" {
  description = "Tencent Cloud CAM SecretKey (provider auth + TTS/KMS/COS)"
  type        = string
  sensitive   = true
}

# Provider credentials can also be set directly on the provider block,
# but passing them as variables keeps the state file portable across machines.

variable "trtc_sdk_app_id" {
  description = "TRTC SDKAppID for ASR v3"
  type        = string
  default     = "20048881"
}

variable "trtc_sdk_secret_key" {
  description = "TRTC SDKSecretKey for UserSig generation"
  type        = string
  sensitive   = true
}

variable "adp_app_key" {
  description = "ADP application AppKey (from the published app's Call dialog)"
  type        = string
  sensitive   = true
}

variable "adp_base_url" {
  description = "ADP endpoint — must match the console that issued the AppKey"
  type        = string
  default     = "https://wss.lke.tencentcloud.com/adp/v2/chat"
}

variable "dbs_payment_api_url" {
  description = "DBS payment API endpoint (mock by default)"
  type        = string
  default     = "https://mock-dbs-payment.example.com"
}

variable "dbs_payment_api_key" {
  description = "DBS payment API key"
  type        = string
  default     = ""
  sensitive   = true
}

# ---------------------------------------------------------------------------
# CVM
# ---------------------------------------------------------------------------

variable "cvm_instance_type" {
  description = "CVM instance type"
  type        = string
  default     = "S5.MEDIUM4" # 2 vCPU, 4 GB
}

variable "cvm_disk_size" {
  description = "System disk size in GB"
  type        = number
  default     = 50
}

variable "ssh_public_key" {
  description = "SSH public key for CVM access (paste your ~/.ssh/id_rsa.pub contents)"
  type        = string
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

variable "db_instance_type" {
  description = "TDSQL-C PostgreSQL instance type"
  type        = string
  default     = "pg.es.4g.mechanical" # ~2 vCPU, 4 GB
}

variable "db_root_password" {
  description = "TDSQL-C root password (will be generated if empty)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "dbs_dcta"
}

variable "db_user" {
  description = "Application database user"
  type        = string
  default     = "dcta_user"
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.8.0.0/16"
}

variable "subnet_cidr" {
  description = "Subnet CIDR block"
  type        = string
  default     = "10.8.1.0/24"
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

variable "project_name" {
  description = "Project name used for resource naming prefixes"
  type        = string
  default     = "dbs-dcta"
}

variable "app_id" {
  description = "Tencent Cloud AppID (from console top-right account menu). Needed for COS bucket naming because the CAM user may not have cam:DescribeSubAccounts permission."
  type        = string
}

variable "high_value_threshold" {
  description = "Freeze threshold for large transfers (SGD)"
  type        = number
  default     = 50000
}

variable "enable_cos" {
  description = "Create COS buckets (requires identity verification on Tencent Cloud account). Set to false if not verified yet."
  type        = bool
  default     = true
}
