###############################################################################
# Terraform configuration — Tencent Cloud provider
###############################################################################
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    tencentcloud = {
      source  = "tencentcloudstack/tencentcloud"
      version = "~> 1.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  # Uncomment after creating the COS bucket for state (Phase 0 below)
  # backend "cos" {
  #   region = "ap-singapore"
  #   bucket = "dbs-dcta-tfstate-XXXX"
  #   prefix = "terraform/state"
  # }
}

provider "tencentcloud" {
  region = var.region
}
