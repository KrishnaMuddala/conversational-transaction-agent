# DCTA Terraform Deployment — Tencent Cloud CVM (Option B)

Provisions the complete Tencent Cloud infrastructure for DCTA and bootstraps the CVM
with Docker Compose in a single `terraform apply`.

## What Terraform creates

| Resource | Type | Purpose |
|----------|------|---------|
| VPC + Subnet | `tencentcloud_vpc` / `tencentcloud_subnet` | Private network |
| Security Groups (x2) | `tencentcloud_security_group` | CVM (SSH/HTTP/HTTPS) + DB (CVM-only) |
| CVM instance | `tencentcloud_instance` | 4C8G Ubuntu, Docker, app |
| Elastic IP | `tencentcloud_eip` | Static public IP |
| SSH Key Pair | `tencentcloud_ssh_key` | Your public key |
| TDSQL-C PostgreSQL | `tencentcloud_postgresql_instance` | Audit trail database |
| COS Bucket | `tencentcloud_cos_bucket` | Audio + audit archives |
| COS Bucket (state) | `tencentcloud_cos_bucket` | Terraform remote state |
| KMS Key | `tencentcloud_kms_key` | RSA 2048 biometric verification |

**What Terraform does NOT create (manual):**
- ADP application — must be published in the ADP console (`adp.tencentcloud.com`)
- SSL certificate — apply via Tencent Cloud SSL or Let's Encrypt after deploy
- Docker image build/push — handled by CVM bootstrap (builds from source on first boot)

## Prerequisites

1. **Tencent Cloud CLI or Console access** with CAM credentials
2. **Terraform >= 1.5.0** installed (`terraform -version`)
3. **SSH key pair** on your machine (`cat ~/.ssh/id_rsa.pub` — if you don't have one,
   run `ssh-keygen -t rsa -b 2048`)
4. **ADP AppKey** from the published application in the ADP console
5. **TRTC SDKSecretKey** (from TRTC Console → Application Management; keep it secret)

## Quick start

```bash
cd deploy/terraform

# 1. Copy the example tfvars and fill in your values
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your editor of choice

# 2. Initialize Terraform (downloads provider plugins)
terraform init

# 3. Preview what will be created
terraform plan

# 4. Apply — this provisions everything and bootstraps the CVM
terraform apply
```

After `apply` completes, Terraform will output:

```
app_url           = "http://119.x.x.x"
cvm_ssh_command   = "ssh ubuntu@119.x.x.x"
database_endpoint = "10.x.x.x:5432"
cos_bucket        = "dbs-dcta-audit-xxxx"
kms_key_id        = "xxxx-xxxx-xxxx"
```

Open `app_url` in your browser — the app should be live within ~5 minutes
(CVM bootstrap takes a few minutes to install Docker and build images).

## What the CVM bootstrap does

The `user_data` script runs automatically on first boot:

1. Installs Docker + Docker Compose
2. Writes `backend/.env` with all production secrets (injected from Terraform variables)
3. Writes `docker-compose.override.yml` (points backend at TDSQL-C, removes internal Postgres)
4. Runs `docker compose up -d --build`
5. Waits for backend health (polls `/api/docs`)

> **Note:** The bootstrap assumes the project source code is already on the CVM.
> Either:
> - Push your code to a Git repo and uncomment the `git clone` line in `cvm.tf`
> - Or `scp` the project to `/opt/dcta` after the CVM is up, then SSH in and run
>   `cd /opt/dcta/deploy && docker compose up -d --build`

## Verify the deployment

```bash
# Check the app is live
curl http://$(terraform output -raw cvm_public_ip)/api/docs

# Run demo scenarios
curl -X POST http://$(terraform output -raw cvm_public_ip)/api/demo/prompt_injection
curl -X POST http://$(terraform output -raw cvm_public_ip)/api/demo/large_transfer_velocity
curl -X POST http://$(terraform output -raw cvm_public_ip)/api/demo/hallucination

# Check audit trail
curl http://$(terraform output -raw cvm_public_ip)/api/audit

# SSH into the CVM to check logs
ssh ubuntu@$(terraform output -raw cvm_public_ip)
docker compose -f /opt/dcta/deploy/docker-compose.yml ps
docker compose -f /opt/dcta/deploy/docker-compose.yml logs -f backend
```

## Enabling remote state (recommended for teams)

After the first `apply` creates the COS bucket for state, uncomment the `backend "cos"`
block in `versions.tf`:

```hcl
backend "cos" {
  region = "ap-singapore"
  bucket = "dbs-dcta-tfstate-XXXX"  # use the value from terraform output terraform_state_bucket
  prefix = "terraform/state"
}
```

Then re-initialize:

```bash
terraform init -migrate-state
```

## Adding HTTPS

After the CVM is running, SSH in and set up Let's Encrypt:

```bash
ssh ubuntu@<public-ip>
sudo apt install -y nginx certbot python3-certbot-nginx

# Point nginx at the Docker stack (port 8080)
sudo tee /etc/nginx/sites-available/default <<EOF
server {
    listen 80;
    server_name dcta.yourdomain.com;
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
sudo systemctl reload nginx

# Get SSL certificate
sudo certbot --nginx -d dcta.yourdomain.com
```

Alternatively, apply for a free SSL certificate in the Tencent Cloud console and
attach it to a CLB in front of the CVM.

## Teardown

```bash
# Destroy everything (keeps the COS buckets — remove manually if needed)
terraform destroy
```

## Cost estimate (ap-singapore)

| Resource | Monthly Cost (SGD) |
|----------|-------------------|
| CVM SA5.LARGE8 (4C8G) | ~$80 |
| TDSQL-C PostgreSQL 4G | ~$60 |
| COS (2 buckets, < 50GB) | ~$2 |
| KMS (1 key) | ~$5 |
| Elastic IP + traffic | ~$10 |
| **Total** | **~$157/month** |

## Files

| File | Purpose |
|------|---------|
| `versions.tf` | Provider configuration |
| `variables.tf` | Input variables |
| `data.tf` | Data sources (images, zones) |
| `network.tf` | VPC, subnet, security groups |
| `storage.tf` | COS buckets |
| `database.tf` | TDSQL-C PostgreSQL |
| `kms.tf` | KMS asymmetric key |
| `ssh.tf` | SSH key pair |
| `cvm.tf` | CVM instance + bootstrap script + Elastic IP |
| `outputs.tf` | Outputs (URL, IPs, DB endpoint) |
| `terraform.tfvars.example` | Example variable values |
