# DBS DCTA — Deployment Guide

**Direct Conversational Transaction Agent** — a voice-first banking agent on Tencent Cloud.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Phase 0 — Tencent Cloud Console Setup](#3-phase-0--tencent-cloud-console-setup)
4. [Phase 1 — Configure Terraform Variables](#4-phase-1--configure-terraform-variables)
5. [Phase 2 — Deploy Infrastructure with Terraform](#5-phase-2--deploy-infrastructure-with-terraform)
6. [Phase 3 — Upload Application Code to CVM](#6-phase-3--upload-application-code-to-cvm)
7. [Phase 4 — Generate SSL Certificate & Start Docker](#7-phase-4--generate-ssl-certificate--start-docker)
8. [Phase 5 — Verify the Deployment](#8-phase-5--verify-the-deployment)
9. [Local Development Setup](#9-local-development-setup)
10. [Troubleshooting](#10-troubleshooting)
11. [Cost Estimation](#11-cost-estimation)

---

## 1. Architecture Overview

```
                    ┌─────────────┐
                    │   Browser    │  HTTPS (self-signed cert)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │    Nginx     │  Port 80 → 301 redirect → 443
                    │  (Docker)    │  SSL termination (self-signed cert)
                    │              │  Strips /api/ prefix
                    └──┬───┬──────┘
                       │   │
          ┌────────────┘   └────────────┐
          ▼                              ▼
   ┌──────────────┐            ┌──────────────┐
   │   Frontend    │            │   Backend    │
   │  Next.js 14   │            │  FastAPI     │
   │  (standalone) │            │  (Uvicorn)   │
   └──────────────┘            └──────┬───────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                  │                  │
              ┌─────▼─────┐    ┌──────▼──────┐   ┌──────▼──────┐
              │ TDSQL-C   │    │    KMS       │   │   Tencent   │
              │ Postgres  │    │  (RSA 2048   │   │   Cloud     │
              │  (VPC)    │    │  SIGN_VERIFY)│   │   APIs      │
              └──────────┘    └─────────────┘   └─────────────┘
                                                   ASR · TTS · ADP
```

**Tech Stack:**
- **Frontend:** Next.js 14 (standalone output), TypeScript, Tailwind CSS
- **Backend:** FastAPI, Python 3.11, SQLAlchemy, Pydantic v2
- **Database:** TencentDB for PostgreSQL (TDSQL-C), VPC-internal
- **ASR:** TRTC ASR v3 (`asr-intl.cloud-rtc.com/v3/transcribe`)
- **TTS:** Tencent Cloud TextToVoice (`tts.tencentcloudapi.com`)
- **NLP Parser:** Tencent ADP (Agent Development Platform)
- **Crypto:** Tencent KMS (asymmetric RSA 2048, SIGN_VERIFY key usage)
- **Storage:** COS (audit logs + Terraform state)
- **Infrastructure:** Terraform + Tencent Cloud provider

---

## 2. Prerequisites

### 2.1 Local Machine

| Tool | Version | Purpose |
|------|---------|---------|
| [Terraform](https://developer.hashicorp.com/terraform/install) | >= 1.5.0 | Infrastructure provisioning |
| [Python](https://www.python.org/downloads/) | 3.11+ | Backend development/testing |
| [Node.js](https://nodejs.org/) | 20+ | Frontend development |
| [Docker](https://docs.docker.com/get-docker/) | 24+ | Local dev + CVM runtime |
| [Docker Compose](https://docs.docker.com/compose/install/) | v2+ | Container orchestration |
| SSH key pair | ed25519 or RSA | CVM access |

### 2.2 Tencent Cloud Account

- A Tencent Cloud account with **identity verification completed** (required for COS)
- A CAM sub-user with the following **custom policy** attached:

```json
{
    "statement": [
        {
            "action": [
                "asr:*",
                "hunyuan:ChatCompletions",
                "tts:TextToVoice",
                "trtc:TextToSpeech",
                "trtc:*",
                "cam:DescribeSubAccounts",
                "cvm:DescribeImages",
                "cvm:*",
                "vpc:*",
                "cos:*",
                "kms:*",
                "tag:*",
                "postgres:*",
                "finance:*"
            ],
            "effect": "allow",
            "resource": ["*"]
        }
    ],
    "version": "2.0"
}
```

> **Note:** `finance:*` is required for billing/payment authorization when creating paid resources (EIP, PostgreSQL instances). Without it, you'll get `BalanceInsufficient` or payment authorization errors.

### 2.3 Services to Activate

Before deploying, activate these services in the Tencent Cloud Console (most are pay-as-you-go):

| Service | Console URL | Activation Required |
|---------|-------------|---------------------|
| KMS | https://console.tencentcloud.com/kms | Yes — click "Activate" |
| TDSQL-C PostgreSQL | https://console.tencentcloud.com/postgres | Yes — click "Activate" |
| TRTC | https://console.tencentcloud.com/trtc | Yes — create an application |
| ADP | https://console.tencentcloud.com/adp | Yes — publish an application |
| COS | https://console.tencentcloud.com/cos | Auto-activated with identity verification |

---

## 3. Phase 0 — Tencent Cloud Console Setup

### 3.1 Get CAM Credentials

1. Go to **CAM → Access Keys → API Keys**
2. Create a new API key for the sub-user
3. Note down:
   - **SecretId** (e.g., `AKIDxxxxxxxx...`)
   - **SecretKey** (e.g., `xxxxxxxx...`)

### 3.2 Get AppID

- Click your account name in the top-right of the console
- Note the **AppID** (e.g., `1250000000`) — needed for COS bucket naming

### 3.3 Create TRTC Application

1. Go to **TRTC Console → Application Management**
2. Click **Create Application**, select "Real-time voice call"
3. Note down:
   - **SDKAppID** (e.g., `1234567890`)
   - **SDKSecretKey** (e.g., `a 64-character hex string from the console`)
4. These are used for ASR v3 authentication (UserSig generation)

### 3.4 Create ADP Application

1. Go to **ADP Console → Applications**
2. Create a new application with your system prompt
3. Publish the application
4. In the published app's **Call** dialog, note:
   - **AppKey** (e.g., `an 88-character string shown in the Call dialog`)
   - **Endpoint URL** — must match the console:
     - International console → `https://wss.lke.tencentcloud.com/adp/v2/chat`
     - China console → `https://wss.lke.cloud.tencent.com/adp/v2/chat`

### 3.5 Generate SSH Key Pair

```bash
# On your local machine
ssh-keygen -t ed25519 -C "dcta-deploy"
cat ~/.ssh/id_ed25519.pub
```

Copy the public key output — you'll provide it to Terraform.

---

## 4. Phase 1 — Configure Terraform Variables

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:

```hcl
# Tencent Cloud CAM credentials
secret_id     = "AKID_your_secret_id"
secret_key    = "your_secret_key"

# Tencent Cloud AppID (from console top-right account menu)
app_id        = "your_cloud_app_id"

# TRTC credentials (from TRTC Console > Application Management)
trtc_sdk_app_id     = "your_trtc_sdk_app_id"
trtc_sdk_secret_key = "your_trtc_sdk_secret_key"

# ADP credentials (from ADP Console > published app > Call dialog)
adp_app_key = "your_adp_app_key"

# SSH public key for CVM access
ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... dcta-deploy"

# Optional overrides (defaults shown):
# region            = "ap-singapore"
# availability_zone = "ap-singapore-1"
# cvm_instance_type = "S5.MEDIUM4"
# db_instance_type  = "pg.es.4g.mechanical"
```

---

## 5. Phase 2 — Deploy Infrastructure with Terraform

```bash
cd deploy/terraform

# Initialize Terraform providers
terraform init

# Review the plan
terraform plan -out=tfplan

# Apply — creates all cloud resources
terraform apply "tfplan"
```

### What Terraform Creates

| Resource | Type | Purpose |
|----------|------|---------|
| VPC + Subnet | `tencentcloud_vpc` / `tencentcloud_subnet` | Network for CVM + DB |
| Security Groups (CVM + DB) | `tencentcloud_security_group` | SSH/HTTP/HTTPS + DB access control |
| SSH Key Pair | `tencentcloud_key_pair` | CVM SSH access |
| KMS Key | `tencentcloud_kms_key` | Biometric signature verification (RSA 2048 SIGN_VERIFY) |
| TDSQL-C PostgreSQL | `tencentcloud_postgresql_instance` | Transaction database |
| CVM Instance | `tencentcloud_instance` | Application host (Docker) |
| Elastic IP | `tencentcloud_eip` | Static public IP for CVM |
| COS Buckets (×2) | `tencentcloud_cos_bucket` | Audit logs + Terraform state |

### Post-Apply Outputs

```bash
terraform output
```

Key outputs:
- `app_url` — The application URL
- `cvm_ssh_command` — SSH command to access the CVM
- `kms_key_id` — KMS key ID for signature verification
- `database_endpoint` — PostgreSQL internal endpoint

---

## 6. Phase 3 — Upload Application Code to CVM

The CVM's `user_data` bootstrap script installs Docker and Docker Compose, but it expects application code at `/home/ubuntu/dcta/`. If you're not using a Git repo, upload the code manually:

```bash
# Get the CVM public IP from Terraform output
CVM_IP=$(terraform output -raw cvm_public_ip)
echo "CVM IP: $CVM_IP"

# Upload the project
cmd /c "tar --exclude=__pycache__ --exclude=*.pyc --exclude=node_modules -cf - backend frontend deploy package.json | ssh -o StrictHostKeyChecking=no ubuntu@%CVM_IP% tar -xf - -C /home/ubuntu/dcta/"

# Remove __pycache__, .pyc, and other unnecessary files from the CVM
ssh -o StrictHostKeyChecking=no ubuntu@$CVM_IP \
  "find /home/ubuntu/dcta/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
   find /home/ubuntu/dcta/ -name '*.pyc' -delete 2>/dev/null; \
   rm -rf /home/ubuntu/dcta/backend/venv /home/ubuntu/dcta/frontend/node_modules \
          /home/ubuntu/dcta/frontend/.next /home/ubuntu/dcta/frontend/dist 2>/dev/null; \
   true"

# SSH in and verify
ssh ubuntu@$CVM_IP
ls -la /home/ubuntu/dcta/
```

### Directory Structure on CVM

```
/home/ubuntu/dcta/
├── backend/
│   ├── .env              ← Generated by Terraform (auto-written on first boot)
│   ├── main.py
│   ├── config.py
│   ├── services/
│   │   ├── asr.py        ← TRTC ASR v3 integration
│   │   ├── tts.py        ← Tencent Cloud TTS
│   │   ├── crypto.py     ← KMS signature verification
│   │   ├── parser.py     ← ADP NLP parser
│   │   └── shield.py     ← Prompt injection shield
│   ├── models.py
│   └── requirements.txt
├── frontend/
│   ├── components/
│   │   ├── Chat.tsx      ← Main chat UI with voice input
│   │   ├── BiometricOverlay.tsx
│   │   ├── DraftCard.tsx
│   │   └── AuditPanel.tsx
│   ├── lib/
│   │   ├── api.ts        ← Frontend API client
│   │   └── types.ts
│   └── package.json
└── deploy/
    ├── docker-compose.yml
    ├── Dockerfile          ← Backend (Python 3.11-slim)
    ├── Dockerfile.frontend ← Frontend (Next.js standalone)
    └── nginx.conf          ← HTTPS + /api/ prefix stripping
```

---

## 7. Phase 4 — Generate SSL Certificate & Start Docker

The nginx config requires a self-signed SSL certificate for HTTPS (needed for microphone access in the browser).

### 7.1 Generate Self-Signed Certificate

The browser requires HTTPS to access the microphone (Web API security requirement). A self-signed certificate is generated on the CVM and mounted into the nginx container.

```bash
ssh ubuntu@$CVM_IP

# Generate self-signed SSL cert (valid for 365 days)
sudo mkdir -p /etc/ssl/private
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/dcta-selfsigned.key \
  -out /etc/ssl/certs/dcta-selfsigned.crt \
  -subj "/CN=dcta-selfsigned"

# Verify files exist
ls -la /etc/ssl/certs/dcta-selfsigned.crt /etc/ssl/private/dcta-selfsigned.key
```

The `docker-compose.yml` mounts these files into the nginx container:

```yaml
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/ssl/certs/dcta-selfsigned.crt:/etc/ssl/certs/dcta-selfsigned.crt:ro
      - /etc/ssl/private/dcta-selfsigned.key:/etc/ssl/private/dcta-selfsigned.key:ro
```

> **Note:** Browsers will show a "Not secure" warning for self-signed certificates. Click "Advanced → Proceed anyway" to continue. This is expected and sufficient for development/demo. For production, replace with a certificate from a trusted CA (e.g., Let's Encrypt via certbot).

### 7.2 Update Backend .env (if KMS key changed)

If you recreated the KMS key after the initial Terraform apply, update the `.env` file:

```bash
# Get the new KMS key ID from Terraform output
# Run this on your local machine:
terraform output kms_key_id

# On the CVM:
KMS_KEY_ID="<paste kms_key_id here>"
sed -i "s/^KMS_KEY_ID=.*/KMS_KEY_ID=$KMS_KEY_ID/" /home/ubuntu/dcta/backend/.env
grep KMS /home/ubuntu/dcta/backend/.env
```

### 7.3 Build and Start Docker Stack

```bash
cd /home/ubuntu/dcta/deploy

# Build and start all containers
docker compose up -d --build

# Verify all containers are running
docker ps --format '{{.Names}} {{.Status}}'
```

Expected output:
```
deploy-backend-1   Up 5 seconds
deploy-frontend-1  Up 10 seconds
deploy-nginx-1     Up 3 seconds
```

### 7.4 Run Database Migrations

```bash
# Run Alembic migrations to create tables
docker exec deploy-backend-1 python -m alembic upgrade head
```

---

## 8. Phase 5 — Verify the Deployment

### 8.1 Health Check

```bash
# Backend health
curl -k https://$CVM_IP/api/audit?limit=1

# Frontend loads
curl -k https://$CVM_IP/ | head -20
```

### 8.2 Functional Tests

Open `https://$CVM_IP` in your browser (accept the self-signed certificate warning).

**Test 1 — Text transaction:**
1. Type: `Transfer $500 to mom`
2. Verify a draft card appears with the transaction details
3. Click "Approve with Face ID"
4. Verify "Transaction confirmed" message appears with a reference number

**Test 2 — Voice input:**
1. Click the microphone icon
2. Allow microphone access when prompted
3. Speak a transaction (e.g., "Send twenty dollars to John")
4. Verify the transcript appears in the text input
5. Click Send and verify the transaction is processed

**Test 3 — Multi-intent:**
1. Type: `Transfer five hundred dollars to mom and invest the rest in Apple shares`
2. Verify two intents are detected (transfer + investment)
3. Approve the combined draft

### 8.3 Run Backend Tests

```bash
# From your local machine
cd backend
./venv/Scripts/python.exe -m pytest tests/ -v
# or on Linux/Mac: source venv/bin/activate && pytest tests/ -v
```

Expected: `76 passed, 1 skipped`

### 8.4 Check Logs

```bash
# Backend logs
ssh ubuntu@$CVM_IP "docker logs deploy-backend-1 --tail 20"

# Nginx access logs
ssh ubuntu@$CVM_IP "docker logs deploy-nginx-1 --tail 20"

# Bootstrap log (first-boot only)
ssh ubuntu@$CVM_IP "cat /var/log/dcta-bootstrap.log"
```

---

## 9. Local Development Setup

### 9.1 Quick Start

```bash
# Clone the repo
git clone <your-repo-url> dcta_tentcent
cd dcta_tentcent

# Start local PostgreSQL + backend + frontend
./scripts/run_local.sh
```

This script:
1. Starts a local PostgreSQL container
2. Creates a Python venv and installs backend deps
3. Starts the backend on `http://localhost:8000` with mock parser
4. Starts the frontend on `http://localhost:3000`

### 9.2 Manual Setup

```bash
# 1. Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Create .env for local dev
cat > .env << 'EOF'
DEBUG=true
CORS_ORIGINS=http://localhost:3000
USE_MOCK_PARSER=true
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dbs_dcta
TENCENT_SECRET_ID=your_id
TENCENT_SECRET_KEY=your_key
TENCENT_REGION=ap-singapore
TRTC_SDK_APP_ID=20048881
TRTC_SDK_SECRET_KEY=your_trtc_key
ASR_ENGINE=16k_en
TTS_VOICE_TYPE=101001
TTS_PRIMARY_LANGUAGE=2
EOF

uvicorn main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

### 9.3 Docker Compose (Local)

```bash
cd deploy
docker compose up -d --build
# Backend: http://localhost:8010
# Frontend: http://localhost:3010
# Nginx: http://localhost:8080
```

### 9.4 Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable verbose logging |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `TENCENT_SECRET_ID` | — | CAM API key ID |
| `TENCENT_SECRET_KEY` | — | CAM API key secret |
| `TENCENT_REGION` | `ap-singapore` | Tencent Cloud region |
| `USE_MOCK_PARSER` | `true` | Use mock NLP instead of ADP |
| `ADP_APP_KEY` | — | ADP application key |
| `ADP_BASE_URL` | `https://wss.lke.tencentcloud.com/adp/v2/chat` | ADP endpoint |
| `TRTC_SDK_APP_ID` | `0` | TRTC SDK App ID for ASR |
| `TRTC_SDK_SECRET_KEY` | — | TRTC SDK secret for UserSig |
| `TRTC_ASR_ENDPOINT` | `https://asr-intl.cloud-rtc.com/v3/transcribe` | ASR API URL |
| `KMS_KEY_ID` | — | KMS key ID for signature verification |
| `KMS_KEY_ALGORITHM` | `RSA_PKCS1_SHA_256` | KMS signature algorithm |
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `TTS_VOICE_TYPE` | `101001` | TTS voice type (Zhiyu) |
| `TTS_PRIMARY_LANGUAGE` | `2` | TTS language (2=English) |
| `HIGH_VALUE_THRESHOLD` | `50000` | Freeze threshold (SGD) |
| `SIGNATURE_TTL_SECONDS` | `60` | Signature validity window |

---

## 10. Troubleshooting

### 10.1 COS Bucket Creation Fails (HTTP 451)

```
Error: cos put bucket error: UnavailableForLegalReasons:
Your have not verified your identity in account center
```

**Fix:** Complete identity verification in the Tencent Cloud Console → Account Center → Identity Verification. COS requires verified identity. This does not block the core application — only audit log persistence to COS.

If you want to skip COS creation entirely (e.g., for a quick deploy before verification is done):

```bash
terraform plan -out=tfplan -var="enable_cos=false"
terraform apply "tfplan"
```

The `enable_cos` variable (default `true`) gates both COS bucket resources and outputs. Set it back to `true` after completing identity verification.

### 10.2 CVM Instance Type Understocked

```
Error: SpecifiedInstanceType understocked
```

**Fix:** Change the availability zone or instance type in `terraform.tfvars`:

```hcl
availability_zone  = "ap-singapore-3"   # try a different zone
cvm_instance_type  = "SA5.LARGE8"       # try a different type
```

Then:
```bash
terraform plan -out=tfplan && terraform apply "tfplan"
```

### 10.3 KMS `cmk keyUsage not match`

```
[TencentCloudSDKException] code:InvalidParameter message:cmk keyUsage not match
```

**Cause:** KMS key was created with `ASYMMETRIC_DECRYPT_RSA_2048` but the backend calls `VerifyByAsymmetricKey`, which requires `ASYMMETRIC_SIGN_VERIFY_RSA_2048`.

**Fix:** The Terraform config (`kms.tf`) now uses the correct `ASYMMETRIC_SIGN_VERIFY_RSA_2048`. If you have an old key:
1. Change the alias in `kms.tf` (to avoid `AliasAlreadyExists` error)
2. `terraform plan -out=tfplan && terraform apply "tfplan"`
3. Update the KMS key ID in the backend `.env` on the CVM

### 10.3.1 KMS `AliasAlreadyExists`

```
Code=InvalidParameterValue.AliasAlreadyExists, Message=alias already exists
```

**Cause:** Tencent Cloud retains KMS key aliases for a retention period (7 days) even after the key is deleted.

**Fix:** Change the alias in `kms.tf` to a new value (e.g., append a version number):
```hcl
alias = "${var.project_name}-biometric-sv2-key"
```
Then re-run `terraform plan -out=tfplan && terraform apply "tfplan"`.

### 10.4 KMS `invalid SignatureValue, base64 decode error`

**Cause:** The frontend sends a `sig_`-prefixed toy HMAC signature (demo mode), but the backend tried KMS verification first.

**Fix:** Already fixed in `backend/services/crypto.py` — signatures starting with `sig_` are routed to the toy HMAC verification path before KMS is attempted.

### 10.5 ASR Returns 404

**Cause:** Nginx was forwarding `/api/asr` to the backend, but the backend route is `/asr` (no `/api` prefix).

**Fix:** Already fixed in `deploy/nginx.conf` — the `location /api/` block uses `proxy_pass http://backend:8000/;` (trailing slash) to strip the `/api/` prefix.

### 10.6 Nginx SSL Certificate Not Found

```
nginx: [emerg] cannot load certificate "/etc/ssl/certs/dcta-selfsigned.crt"
```

**Fix:** Generate the self-signed certificate on the CVM (see Phase 4, step 7.1). The `docker-compose.yml` must also mount the cert files into the nginx container (see the volume mounts in step 7.1).

### 10.6.1 Frontend `next: Permission denied`

```
sh: next: Permission denied
```

**Cause:** `scp` from Windows copies `node_modules/.bin/next` without the execute permission bit. The file has `-rw-rw-r--` instead of `-rwxrwxr-x`.

**Fix:** Don't upload `node_modules` at all — the Docker build does `npm install` inside the container. If already uploaded:

```bash
ssh ubuntu@$CVM_IP "rm -rf /home/ubuntu/dcta/frontend/node_modules /home/ubuntu/dcta/frontend/.next"
```

A `.dockerignore` file at the project root also prevents `node_modules` from entering the Docker build context.

### 10.7 Payment Authorization Error (EIP/PostgreSQL creation)

```
BalanceInsufficient or payment authorization error
```

**Fix:** Add `finance:*` to your CAM sub-user's custom policy. This grants billing/payment authorization required for creating paid resources.

### 10.8 PostgreSQL `engine_version` Error

```
Please select the latest kernel minor version (v15.19_r1.36)
```

**Fix:** Update the `engine_version` in `database.tf` to include the kernel minor version suffix (e.g., `15.19_r1.36`).

### 10.9 Rebuild Backend After Code Changes

```bash
# Upload updated file
scp backend/services/crypto.py ubuntu@$CVM_IP:/home/ubuntu/dcta/backend/services/crypto.py

# Rebuild and restart
ssh ubuntu@$CVM_IP "cd /home/ubuntu/dcta/deploy && docker compose up -d --build backend"
```

### 10.10 Rebuild Frontend After Code Changes

```bash
# Upload updated file
scp frontend/components/Chat.tsx ubuntu@$CVM_IP:/home/ubuntu/dcta/frontend/components/Chat.tsx

# Rebuild and restart
ssh ubuntu@$CVM_IP "cd /home/ubuntu/dcta/deploy && docker compose up -d --build frontend"
```

---

## 11. Cost Estimation

Monthly costs for Singapore region (approximate):

| Resource | Spec | Est. Monthly Cost (USD) |
|----------|------|------------------------|
| CVM (S5.MEDIUM4) | 2 vCPU, 4 GB | ~$25 |
| TDSQL-C PostgreSQL | 2 vCPU, 4 GB, 50 GB | ~$35 |
| EIP (BGP) | 1 EIP + traffic | ~$3 + traffic |
| KMS | 1 key | ~$1 |
| COS (if identity verified) | 2 buckets, minimal storage | ~$1 |
| TRTC ASR | Per-request | ~$0.01/15s audio |
| TTS | Per-request | ~$0.01/100 chars |
| ADP | Per-request | Varies |
| **Total (base)** | | **~$65/month** |

> Costs vary by usage. ASR/TTS/ADP are pay-per-request. CVM and PostgreSQL are the fixed costs.

---

## File Reference

| File | Purpose |
|------|---------|
| `deploy/terraform/versions.tf` | Terraform + provider version constraints |
| `deploy/terraform/variables.tf` | All input variables with defaults |
| `deploy/terraform/terraform.tfvars.example` | Example credentials file |
| `deploy/terraform/provider.tf` | (in versions.tf) Tencent Cloud provider config |
| `deploy/terraform/network.tf` | VPC, subnet, security groups |
| `deploy/terraform/database.tf` | TDSQL-C PostgreSQL instance |
| `deploy/terraform/kms.tf` | KMS asymmetric key (RSA 2048 SIGN_VERIFY) |
| `deploy/terraform/storage.tf` | COS buckets (audit + tfstate) |
| `deploy/terraform/cvm.tf` | CVM instance + Docker bootstrap + EIP |
| `deploy/terraform/ssh.tf` | SSH key pair |
| `deploy/terraform/data.tf` | Data sources (Ubuntu image, zones) |
| `deploy/terraform/outputs.tf` | Useful outputs after apply |
| `deploy/docker-compose.yml` | Docker Compose (nginx + backend + frontend + db) |
| `deploy/Dockerfile` | Backend container (Python 3.11-slim) |
| `deploy/Dockerfile.frontend` | Frontend container (Next.js standalone) |
| `deploy/nginx.conf` | Nginx config (HTTPS + /api/ stripping) |
| `.dockerignore` | Prevents node_modules, __pycache__, venv from entering build context |
| `backend/services/asr.py` | TRTC ASR v3 integration |
| `backend/services/tts.py` | Tencent Cloud TTS |
| `backend/services/crypto.py` | KMS + toy HMAC signature verification |
| `backend/services/parser.py` | ADP NLP parser |
| `backend/services/shield.py` | Prompt injection shield |
| `backend/config.py` | Settings from environment variables |
| `backend/main.py` | FastAPI app + all endpoints |
| `frontend/lib/api.ts` | Frontend API client |
| `frontend/components/Chat.tsx` | Main chat UI with voice + text input |
