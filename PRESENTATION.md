# DCTA — Presentation & Tencent Cloud Deployment Plan

**Digital Concierge for Transaction Assistance**

A voice- and text-enabled conversational banking assistant built on Tencent Cloud.
Turns spoken or typed instructions into validated, biometric-confirmed transaction drafts.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What We Built](#2-what-we-built)
3. [Architecture Overview](#3-architecture-overview)
4. [Five-Layer Security Pipeline](#4-five-layer-security-pipeline)
5. [Technology Stack](#5-technology-stack)
6. [Tencent Cloud Services Used](#6-tencent-cloud-services-used)
7. [Key Features & Demo Scenarios](#7-key-features--demo-scenarios)
8. [Verification Status](#8-verification-status)
9. [Deployment Plan — Tencent Cloud](#9-deployment-plan--tencent-cloud)
10. [Required Services & Cost Estimate](#10-required-services--cost-estimate)
11. [Step-by-Step Deployment Guide](#11-step-by-step-deployment-guide)
12. [Environment Variables Reference](#12-environment-variables-reference)
13. [Post-Deployment Checklist](#13-post-deployment-checklist)
14. [Known Limitations & Roadmap](#14-known-limitations--roadmap)

---

## 1. Executive Summary

DCTA is a **Zero-UI conversational transaction agent** that lets bank customers speak or type
natural-language instructions like *"Transfer $500 to mom and invest the rest in Apple shares"*
and get them executed safely through a multi-layer validation pipeline with biometric confirmation.

**The problem we solve:** Voice-driven banking is hard because LLMs hallucinate, can be
prompt-injected, and don't know real account IDs or balances. DCTA addresses this with a
**zero-trust architecture** where the model proposes and independent code disposes — no single
component is ever trusted.

**What makes it different:**

- Five-layer pipeline: Safety Shield → Parser → Registry Backfill → Validation → Biometric Gateway
- The conversational agent has **zero credentials** to the payment API
- Every step is logged to a tamper-evident audit chain (SHA-256 hash chain)
- Non-transactional input (greetings, refusals) is refused before reaching the confirmation surface

---

## 2. What We Built

### Backend — Python 3.11 / FastAPI

| Module | Responsibility |
|--------|---------------|
| `main.py` | REST API: `/intent`, `/resolve`, `/confirm`, `/asr`, `/tts`, `/audit`, `/demo/{scenario}` |
| `config.py` | Environment-driven settings (pydantic-settings) |
| `models.py` | Pydantic v2 schemas: `Draft`, `Intent`, `Ambiguity`, `BiometricEnvelope` |
| `services/parser.py` | ADP SSE streaming parser + heuristic fallback; registry backfill |
| `services/shield.py` | Prompt-injection detection + money-vs-account-number discrimination |
| `services/validator.py` | Independent amount re-derivation; freezes on discrepancy |
| `services/asr.py` | TRTC ASR v3 — voice-to-text (UserSig auth, no CAM) |
| `services/tts.py` | Tencent Cloud TTS — text-to-speech (CAM auth) |
| `services/crypto.py` | Biometric signature verification via KMS |
| `services/accounts.py` | Authoritative payee/account/asset registry |
| `audit/logger.py` | Immutable audit logger with hash chain (PostgreSQL + COS) |
| `ledger/executor.py` | DBS payment API executor (mock by default) |

### Frontend — Next.js 14 / React 18

| Component | Role |
|-----------|------|
| `Chat.tsx` | Main chat container; voice recording via `MediaRecorder`, text input, quick-action demos |
| `DraftCard.tsx` | Transaction draft review card with "Confirm with Biometrics" button |
| `ClarifyCard.tsx` | Ambiguity resolution UI (payee selection, amount input) |
| `BiometricOverlay.tsx` | Full-screen confirmation overlay simulating Face ID |
| `AuditPanel.tsx` | Live audit ledger sidebar (polls every 3s) |
| `lib/api.ts` | REST client; nginx-relative (`/api/...`) |

### Test Suite

- **73 tests passing**, 1 skipped
- Covers: API integration, ADP wire contract (stubbed), shield injection patterns, chitchat
  rejection, multi-intent parsing, ambiguity resolution, validation freeze

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          USER (Voice or Text)                                │
└────────────┬───────────────────────────────────────┬─────────────────────────┘
             │                                       │
        🎤 Voice                              ⌨️ Text Input
             │                                       │
             ▼                                       │
  ┌─────────────────────┐                          │
  │  Frontend (Web UI)  │                          │
  │  - Mic recording    │                          │
  │  (MediaRecorder →   │                          │
  │   audio/webm Opus)  │                          │
  │  - Audio playback   │                          │
  └────────┬────────────┘                          │
           │                                       │
           │ POST /api/asr                         │
           │ (audio file upload)                   │
           ▼                                       │
  ┌─────────────────────────────────────────────┐  │
  │  TRTC ASR v3  (HTTP, UserSig auth)          │  │
  │  asr-intl.cloud-rtc.com/v3/transcribe       │  │
  │  SDKAppID + SDKSecretKey (HMAC-SHA256)      │  │
  │  Replaces blocked Tencent ASR service       │  │
  └────────┬────────────────────────────────────┘  │
           │                                       │
           │ transcript                            │
           ▼                                       ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                    Backend (FastAPI)                         │
  │                   main.py (API Gateway)                      │
  │                                                              │
  │  ┌──────────────────────────────────────────────────────┐   │
  │  │ Layer 1 — Safety Shield          services/shield.py │   │
  │  │   Runs on RAW transcript BEFORE parser is called    │   │
  │  │   Injection patterns + account-number check          │   │
  │  │   hit → return blocked, stop. Model never runs.     │   │
  │  └────────────────────┬─────────────────────────────────┘   │
  │                       │                                     │
  │  ┌────────────────────▼─────────────────────────────────┐   │
  │  │ Layer 2 — Parser              services/parser.py     │   │
  │  │   ADP chat SSE → Intent[]                            │   │
  │  │   Model proposes; registry disposes                  │   │
  │  └────────────────────┬─────────────────────────────────┘   │
  │                       │                                     │
  │  ┌────────────────────▼─────────────────────────────────┐   │
  │  │ Layer 2b — Registry Backfill    services/accounts.py │   │
  │  │   Real balance  ← registry, never model             │   │
  │  │   Payee identity ← canonical object, model nominates│   │
  │  └────────────────────┬─────────────────────────────────┘   │
  │                       │                                     │
  │              ambiguities? ─yes→ return clarify → /resolve   │
  │                       │ no                                   │
  │                       ▼                                      │
  │  ┌──────────────────────────────────────────────────────┐  │
  │  │ Layer 3 — Validation Agent    services/validator.py │  │
  │  │   Re-derives amount independently; freezes on mismatch│  │
  │  └────────────────────┬─────────────────────────────────┘  │
  │                       │ pass                                 │
  │                       ▼                                      │
  │  ┌──────────────────────────────────────────────────────┐  │
  │  │ Layer 4 — Biometric Gateway   services/crypto.py     │  │
  │  │   KMS VerifyByAsymmetricKey (RSA_PKCS1_SHA_256)      │  │
  │  └────────────────────┬─────────────────────────────────┘  │
  │                       │ verified                             │
  │                       ▼                                      │
  │  ┌──────────────────────────────────────────────────────┐  │
  │  │ Layer 5 — Execution          ledger/executor.py     │  │
  │  │   Transfers → DBS Payment API                        │  │
  │  │   Audit trail → PostgreSQL (hash chain)              │  │
  │  └──────────────────────────────────────────────────────┘  │
  └────────────────────────────────┬─────────────────────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  TTS — Tencent Cloud TextToVoice    services/tts.py         │
  │  Voice 101001 (Zhiyu, female, English-capable)              │
  │  POST /api/tts { text } → { audio: base64, format: "mp3" }  │
  └─────────────────────────────────────────────────────────────┘
```

---

## 4. Five-Layer Security Pipeline

The key design principle: **no single component is trusted**. The model proposes, and
independent code disposes.

| Layer | Module | What it does | Outcome |
|-------|--------|-------------|---------|
| 1 | Safety Shield | Screens raw transcript for injection / unknown accounts | `blocked` — model never runs |
| 2 | Parser | ADP LLM extracts intents; registry overrides with canonical IDs | Draft with real account/balance |
| 2b | Registry Backfill | Replaces model's hallucinated payee IDs with authoritative ones | No fabricated IDs reach execution |
| 3 | Validation Agent | Independently re-derives amount; re-checks payee | `frozen` on mismatch |
| 4 | Biometric Gateway | Verifies device signature via KMS | `rejected` if invalid |
| 5 | Execution | Calls DBS Payment API; logs to audit chain | `confirmed` with reference |

### Four response types

| Type | Meaning | Produced by |
|------|---------|-------------|
| `draft` | Ready for biometric confirmation | All layers passed |
| `clarify` | Needs one more answer from the user | Unresolved ambiguity |
| `frozen` | Discrepancy — held for manual review | Validation agent |
| `blocked` | Refused before any model call | Safety shield |
| `chat` | No transaction detected (greetings, etc.) | No-intent gate |

---

## 5. Technology Stack

### Application

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | Next.js (standable output) | 14.2.3 |
| Frontend | React | 18.3.1 |
| Frontend | TypeScript | 5.4.5 |
| Backend | Python | 3.11 |
| Backend | FastAPI | 0.111.0 |
| Backend | Uvicorn | 0.30.0 |
| Backend | Pydantic | 2.7.1 |
| Database | PostgreSQL | 15 |
| ORM | SQLAlchemy + asyncpg | 2.0.30 / 0.29.0 |
| HTTP Client | httpx | 0.27.0 |

### Infrastructure

| Component | Technology |
|-----------|-----------|
| Reverse Proxy | nginx 1.27-alpine |
| Container Orchestration | Docker Compose (local) / TKE (production) |
| Container Registry | Tencent Container Registry (TCR) |
| CI/CD | Manual (no GitHub Actions yet) |

---

## 6. Tencent Cloud Services Used

| Service | Purpose | Auth Method | Status |
|---------|---------|------------|--------|
| **ADP** — Agent Development Platform | Intent parsing (Layer 2) | AppKey only | ✅ Working |
| **TRTC ASR v3** | Voice → text | SDKAppID + UserSig (HMAC-SHA256) | ✅ Working |
| **TTS** — TextToVoice | Text → audio | CAM (SecretId/SecretKey) | ✅ Working |
| **KMS** — Key Management | Biometric signature verification | CAM + KMS_KEY_ID | ⬜ Configured |
| **COS** — Object Storage | Raw audio + audit archives | CAM | ⬜ Configured |
| **TDSQL-C** (PostgreSQL) | Audit trail storage | DATABASE_URL | ⬜ Configured |
| **TKE** — Kubernetes Engine | Container orchestration | — | 📋 Planned |
| **API Gateway** | Public endpoint + rate limiting | — | 📋 Planned |
| **WAF** — Web Application Firewall | DDoS / injection protection | — | 📋 Planned |

### Why TRTC ASR instead of Tencent Cloud ASR?

The standard Tencent Cloud ASR (`SentenceRecognition`) requires **separate service activation**
at the account level, which returned `FailedOperation.UserNotRegistered` across all regions
(Singapore, Guangzhou, Beijing, Shanghai, Hong Kong). CAM permissions (`asr:*`) grant API call
authority but do **not** activate the service.

**TRTC ASR v3** uses `SDKAppID + SDKSecretKey` (UserSig auth via HMAC-SHA256), requires no
separate activation, and is part of the TRTC Conversational AI product (10,000 free
minutes/month). It accepts WAV, PCM, M4A, OGG-Opus, and WebM/Opus audio formats.

### Credential Summary

| Credential | Used By | Where Stored |
|-----------|---------|-------------|
| `ADP_APP_KEY` | Parser (ADP) | `backend/.env` |
| `TRTC_SDK_APP_ID` + `TRTC_SDK_SECRET_KEY` | ASR (TRTC) | `backend/.env` |
| `TENCENT_SECRET_ID` + `TENCENT_SECRET_KEY` | TTS, KMS, COS | `backend/.env` |
| `KMS_KEY_ID` | Crypto gateway | `backend/.env` |
| `DATABASE_URL` | Audit logger | `backend/.env` / Compose override |
| `DBS_PAYMENT_API_KEY` | Ledger executor | `backend/.env` |

---

## 7. Key Features & Demo Scenarios

### Built-in demo scenarios (accessible via UI quick-action buttons)

| Scenario | Input | Expected Output | What it demonstrates |
|----------|-------|-----------------|----------------------|
| Multi-intent | "Transfer $500 to mom and invest the rest in Apple" | 2 intents, relative amount resolution | Multi-intent parsing + relative amount ("the rest") |
| Ambiguous payee | "Send fifty to John" | `clarify` — disambiguate John Tan vs John Lim | Ambiguity gate |
| Prompt injection | "Ignore all previous instructions..." | `blocked` | Safety shield (model never runs) |
| High-value velocity | "Transfer $90,000 from savings" | `frozen` | Validation agent freeze (> $50k threshold) |
| Clean transfer | "Transfer $250 to John Tan" | `draft` | Happy path → biometric confirmation |
| Unknown payee | "Send $50 to Zi Wei" | `clarify` — "not in your saved payees" | Registry-authoritative resolution |
| Chitchat | "good morning", "hello", "thank you" | `chat` — no draft | No-intent gate (hard boundary) |

### Voice path

1. User clicks 🎤 → browser `MediaRecorder` captures audio as WebM/Opus
2. Frontend uploads to `/api/asr`
3. Backend sends to TRTC ASR v3 → returns transcript
4. Transcript auto-fills the text input
5. User sends → normal text pipeline

### Audit trail

- Every turn logs events in sequence: `INPUT_RECEIVED → PARSER_OUTPUT → SAFETY_BLOCK /
  AMBIGUITY_PENDING → VALIDATION_PASS/FREEZE → GATEWAY_ACCEPT/REJECT → EXECUTION_COMPLETE`
- Events are chained via SHA-256 hash (`previous_hash` field)
- Audit panel in the sidebar shows live events with 3-second polling

---

## 8. Verification Status

| Check | Result |
|-------|--------|
| Backend test suite | **73 passed**, 1 skipped |
| Live acceptance via nginx | **14/14** (7/7 repeated over two warm passes) |
| Parse latency | 5–9 s (non-streaming ADP round trip) |
| ASR | **Working** — TRTC ASR v3, UserSig auth, no activation needed |
| TTS | **Working** — Tencent Cloud TTS, MP3 output |
| ADP Parser | **Working** — international v2 endpoint, SSE streaming |
| Tencent ASR | **Blocked** — not activated (replaced by TRTC ASR) |

---

## 9. Deployment Plan — Tencent Cloud

### Deployment topology

```
                         Internet
                            │
                            ▼
                ┌───────────────────────┐
                │  Tencent Cloud CLB    │
                │  (Load Balancer)      │
                │  :443 (HTTPS)         │
                └───────────┬───────────┘
                            │
                ┌───────────▼───────────┐
                │  WAF + API Gateway     │
                │  (DDoS + rate limit)   │
                └───────────┬───────────┘
                            │
           ┌────────────────┼────────────────┐
           │                │                │
   ┌───────▼───────┐ ┌──────▼──────┐ ┌───────▼───────┐
   │  Frontend     │ │  Backend    │ │  (shared)     │
   │  Pod (x2)     │ │  Pod (x2)   │ │               │
   │  Next.js      │ │  FastAPI    │ │               │
   │  :3000        │ │  :8000      │ │               │
   └───────────────┘ └──────┬──────┘ │               │
                             │        │               │
              ┌──────────────┼────────┼───────────────┐
              │              │        │              │
      ┌───────▼──────┐ ┌─────▼────┐ ┌─▼────────┐ ┌──▼──────────┐
      │ TDSQL-C      │ │  COS     │ │  KMS     │ │  ADP (SaaS)  │
      │ PostgreSQL   │ │  Bucket  │ │  Key     │ │  (external)  │
      │ (audit chain)│ │ (audio)  │ │          │ │              │
      └──────────────┘ └──────────┘ └──────────┘ └──────────────┘

  External (Tencent Cloud):
      TRTC ASR  ←  Backend calls asr-intl.cloud-rtc.com
      TTS       ←  Backend calls tts.tencentcloudapi.com
      DBS API   ←  Backend calls payment endpoint (mock by default)
```

### Two deployment options

#### Option A: TKE (Tencent Kubernetes Engine) — Recommended for production

- 2 backend replicas + 2 frontend replicas
- Auto-scaling, rolling updates, health checks
- Internal service mesh (CLB → nginx → pods)
- KMS secrets via Kubernetes Secret

#### Option B: CVM (Cloud Virtual Machine) — Simpler, lower cost

- Single CVM instance (4C8G minimum)
- Docker Compose on the CVM
- CLB in front for HTTPS termination
- Good for hackathon demo / early stage

---

## 10. Required Services & Cost Estimate

### Tencent Cloud services to provision

| # | Service | Spec | Purpose | Est. Monthly Cost (SGD) |
|---|---------|------|---------|--------------------------|
| 1 | **TKE** or **CVM** | TKE: 2 nodes (4C8G) / CVM: 1× (4C8G) | Container runtime | ~$80–$150 |
| 2 | **CLB** — Cloud Load Balancer | L7 HTTPS | Public entry point | ~$20 |
| 3 | **TDSQL-C** (PostgreSQL) | 2C4G, 50GB disk | Audit trail | ~$60 |
| 4 | **COS** — Object Storage | 50 GB | Audio archive | ~$2 |
| 5 | **KMS** — Key Management | 1 asymmetric key | Signature verification | ~$5 |
| 6 | **WAF** — Web Application Firewall | Basic | DDoS + injection filter | ~$50 |
| 7 | **ADP** — Agent Development Platform | Published app | LLM intent parsing | Free tier / usage-based |
| 8 | **TRTC** — Conversational AI | SDKAppID | ASR v3 | 10,000 free min/month |
| 9 | **TTS** — TextToVoice | CAM | Text → speech | ~$1 per 10k chars |
| 10 | **TCR** — Container Registry | 1 namespace | Docker image storage | Free tier |

**Estimated total: ~$220–$300/month** (excluding ADP usage-based charges)

### Pre-requisites (already obtained)

- Tencent Cloud account with CAM user (not root)
- TRTC SDKAppID: `20048881` + SDKSecretKey (verified working)
- CAM SecretId / SecretKey with permissions: `hunyuan:ChatCompletions`, `tts:TextToVoice`,
  `trtc:TextToSpeech`, `kms:*`, `cos:*`
- ADP application published on the international console (`adp.tencentcloud.com`)
  with its AppKey

> **Note on CAM typo:** The current CAM policy includes `trct:*` which appears to be a typo
> for `trtc:*`. This should be corrected, though TRTC ASR uses UserSig auth (not CAM) so it
> does not affect the ASR path.

---

## 11. Step-by-Step Deployment Guide

### Phase 1: Provision Tencent Cloud infrastructure

#### 1.1 Create a TKE cluster (or CVM)

**TKE path (recommended):**

```bash
# Via Tencent Cloud Console:
# 1. Go to TKE > Clusters > Create
# 2. Select region: ap-singapore
# 3. Choose managed cluster, 2 nodes (4C8G each)
# 4. Select VPC (create one if needed)
# 5. Create the cluster
```

**CVM path (simpler):**

```bash
# Via Console:
# 1. Go to CVM > Instances > Create
# 2. Region: ap-singapore
# 3. Model: 4C8G (e.g., S5.MEDIUM4)
# 4. OS: Ubuntu 22.04
# 5. Login method: SSH key pair
# 6. Configure security group: open 80, 443, 22
```

#### 1.2 Create a TDSQL-C PostgreSQL instance

```bash
# Via Console:
# 1. Go to TDSQL-C > PostgreSQL > Create
# 2. Region: ap-singapore
# 3. Spec: 2C4G, 50 GB disk
# 4. Create a database: dbs_dcta
# 5. Create a user: dcta_user with a strong password
# 6. Note the connection endpoint (e.g., pgw-xxxx.sql.tencentcdb.com:5432)
# 7. Set DATABASE_URL=postgresql://dcta_user:password@endpoint:5432/dbs_dcta
```

#### 1.3 Create a COS bucket

```bash
# Via Console:
# 1. Go to COS > Bucket List > Create
# 2. Region: ap-singapore
# 3. Name: dbs-dcta-audit-<your-unique-suffix>
# 4. Access: Private (backend only)
# 5. Note: COS_BUCKET=dbs-dcta-audit-<suffix>, COS_REGION=ap-singapore
```

#### 1.4 Create a KMS asymmetric key

```bash
# Via Console:
# 1. Go to KMS > Key List > Create
# 2. Region: ap-singapore
# 3. Key type: Asymmetric (RSA 2048)
# 4. Usage: SIGN/VERIFY
# 5. Note the KMS_KEY_ID
```

#### 1.5 Configure the ADP application

```bash
# Already done:
# 1. Go to adp.tencentcloud.com (international console)
# 2. Create/publish a banking assistant application
# 3. Copy the AppKey from the app's "Call" dialog
# 4. Set ADP_APP_KEY=<your-key>
# 5. Set ADP_BASE_URL=https://wss.lke.tencentcloud.com/adp/v2/chat
```

---

### Phase 2: Build and push Docker images

#### 2.1 Create a TCR (Tencent Container Registry) namespace

```bash
# Via Console:
# 1. Go to TCR > Namespaces > Create
# 2. Region: ap-singapore
# 3. Name: your-namespace (e.g., dbs-dcta)
# 4. Note: registry = ccr.ccs.tencentyun.com/your-namespace
```

#### 2.2 Build and push images

```bash
# Login to TCR
docker login ccr.ccs.tencentyun.com -u <your-cam-id> -p <your-cam-key>

# Build backend image
cd /path/to/dcta_tentcent
docker build -t ccr.ccs.tencentyun.com/your-namespace/dbs-dcta-backend:latest \
  -f deploy/Dockerfile .

# Build frontend image (with API base URL baked in)
docker build -t ccr.ccs.tencentyun.com/your-namespace/dbs-dcta-frontend:latest \
  --build-arg NEXT_PUBLIC_API_BASE_URL=/api \
  -f deploy/Dockerfile.frontend .

# Push both
docker push ccr.ccs.tencentyun.com/your-namespace/dbs-dcta-backend:latest
docker push ccr.ccs.tencentyun.com/your-namespace/dbs-dcta-frontend:latest
```

---

### Phase 3: Deploy to TKE

#### 3.1 Create Kubernetes secrets

```bash
# Create a secret with all environment variables
kubectl create secret generic dbs-dcta-secrets \
  --from-literal=TENCENT_SECRET_ID=AKIDxxxx \
  --from-literal=TENCENT_SECRET_KEY=xxxx \
  --from-literal=TENCENT_REGION=ap-singapore \
  --from-literal=ADP_APP_KEY=xxxx \
  --from-literal=ADP_BASE_URL=https://wss.lke.tencentcloud.com/adp/v2/chat \
  --from-literal=USE_MOCK_PARSER=false \
  --from-literal=TRTC_SDK_APP_ID=20048881 \
  --from-literal=TRTC_SDK_SECRET_KEY=xxxx \
  --from-literal=TRTC_ASR_ENDPOINT=https://asr-intl.cloud-rtc.com/v3/transcribe \
  --from-literal=ASR_ENGINE=16k_en \
  --from-literal=TTS_VOICE_TYPE=101001 \
  --from-literal=TTS_PRIMARY_LANGUAGE=2 \
  --from-literal=DATABASE_URL=postgresql://dcta_user:password@tdsql-endpoint:5432/dbs_dcta \
  --from-literal=COS_BUCKET=dbs-dcta-audit-xxx \
  --from-literal=COS_REGION=ap-singapore \
  --from-literal=KMS_KEY_ID=xxxx \
  --from-literal=DBS_PAYMENT_API_URL=https://mock-dbs-payment.example.com \
  --from-literal=DBS_PAYMENT_API_KEY=xxxx \
  --from-literal=HIGH_VALUE_THRESHOLD=50000 \
  -n dbs-dcta
```

#### 3.2 Apply the deployment manifest

```bash
# The manifest is in deploy/tke-deployment.yaml
# Update the image references to match your TCR namespace

kubectl apply -f deploy/tke-deployment.yaml
```

#### 3.3 Deploy frontend and nginx (Ingress)

Create a combined deployment that includes frontend + nginx (or use a separate
Ingress controller). The existing `tke-deployment.yaml` covers the backend; extend
it for frontend:

```yaml
# Add to tke-deployment.yaml or create tke-frontend.yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dbs-dcta-frontend
  namespace: dbs-dcta
spec:
  replicas: 2
  selector:
    matchLabels:
      app: dbs-dcta-frontend
  template:
    metadata:
      labels:
        app: dbs-dcta-frontend
    spec:
      containers:
        - name: frontend
          image: ccr.ccs.tencentyun.com/your-namespace/dbs-dcta-frontend:latest
          ports:
            - containerPort: 3000
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
---
apiVersion: v1
kind: Service
metadata:
  name: dbs-dcta-frontend
  namespace: dbs-dcta
spec:
  selector:
    app: dbs-dcta-frontend
  ports:
    - port: 80
      targetPort: 3000
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  namespace: dbs-dcta
data:
  default.conf: |
    server {
        listen 80;
        server_name _;
        location / {
            proxy_pass http://dbs-dcta-frontend:80;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
        }
        location /api/ {
            rewrite ^/api/(.*)$ /$1 break;
            proxy_pass http://dbs-dcta-backend:80;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            client_max_body_size 10M;
        }
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: dbs-dcta
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:1.27-alpine
          ports:
            - containerPort: 80
          volumeMounts:
            - name: nginx-config
              mountPath: /etc/nginx/conf.d
      volumes:
        - name: nginx-config
          configMap:
            name: nginx-config
---
apiVersion: v1
kind: Service
metadata:
  name: nginx
  namespace: dbs-dcta
spec:
  type: LoadBalancer
  selector:
    app: nginx
  ports:
    - port: 80
      targetPort: 80
```

#### 3.4 Get the public URL

```bash
# Wait for the LoadBalancer to get an external IP
kubectl get svc nginx -n dbs-dcta -w

# Output will look like:
# NAME    TYPE           CLUSTER-IP     EXTERNAL-IP      PORT(S)
# nginx   LoadBalancer   10.x.x.x       119.x.x.x        80:31xxx/TCP

# Your URL is: http://119.x.x.x
# For production: point your domain's DNS A record to this IP
```

---

### Phase 3 Alternative: Deploy to CVM (simpler)

```bash
# SSH into your CVM
ssh ubuntu@<cvm-public-ip>

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Clone the repo (or copy files)
git clone <your-repo> /opt/dcta
cd /opt/dcta

# Create .env with production credentials
cp backend/.env.example backend/.env
nano backend/.env  # fill in all production values

# Start the stack
cd deploy
sudo docker compose up -d --build

# The app is now on port 8080
# Set up nginx or CLB for HTTPS on port 443
```

---

### Phase 4: Configure HTTPS and domain

```bash
# Option A: Tencent Cloud SSL certificate + CLB
# 1. Go to SSL Certificates > Apply for free certificate
# 2. Validate domain ownership
# 3. Download certificate
# 4. Upload to CLB > HTTPS listener
# 5. Point DNS A record to CLB IP

# Option B: Let's Encrypt on CVM
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d dcta.yourdomain.com
```

---

### Phase 5: Verify the deployment

```bash
# Health check (no /health route — use /docs)
curl https://dcta.yourdomain.com/api/docs

# Test demo scenarios
curl -X POST https://dcta.yourdomain.com/api/demo/prompt_injection
# Expected: {"type":"blocked","message":"Potential prompt injection..."}

curl -X POST https://dcta.yourdomain.com/api/demo/large_transfer_velocity
# Expected: {"type":"frozen","message":"Validation Agent detected..."}

curl -X POST https://dcta.yourdomain.com/api/demo/hallucination
# Expected: {"type":"clarify","message":"Before I can prepare..."}

# Test ASR
curl -F "file=@test.wav" https://dcta.yourdomain.com/api/asr

# Check audit trail
curl https://dcta.yourdomain.com/api/audit
```

---

## 12. Environment Variables Reference

| Variable | Purpose | Example |
|----------|---------|---------|
| `DEBUG` | Enable debug mode | `false` |
| `CORS_ORIGINS` | Allowed origins (comma-separated) | `https://dcta.yourdomain.com` |
| `TENCENT_SECRET_ID` | CAM user SecretId (TTS, KMS, COS) | `AKIDxxxx` |
| `TENCENT_SECRET_KEY` | CAM user SecretKey | `xxxx` |
| `TENCENT_REGION` | Tencent Cloud region | `ap-singapore` |
| `USE_MOCK_PARSER` | `true` = heuristic fallback, `false` = live ADP | `false` |
| `ADP_APP_KEY` | AppKey from ADP console "Call" dialog | `xxxx` |
| `ADP_BASE_URL` | Must match the console that issued the key | `https://wss.lke.tencentcloud.com/adp/v2/chat` |
| `ADP_VISITOR_ID` | Visitor identifier for ADP | `dcta-parser` |
| `ADP_TIMEOUT_SECONDS` | ADP request timeout | `60` |
| `TRTC_SDK_APP_ID` | TRTC SDKAppID (from TRTC console) | `20048881` |
| `TRTC_SDK_SECRET_KEY` | TRTC SDKSecretKey (for UserSig) | `xxxx` |
| `TRTC_ASR_ENDPOINT` | TRTC ASR v3 endpoint | `https://asr-intl.cloud-rtc.com/v3/transcribe` |
| `ASR_ENGINE` | ASR engine model (legacy hint) | `16k_en` |
| `TTS_VOICE_TYPE` | TTS voice ID | `101001` |
| `TTS_PRIMARY_LANGUAGE` | 1=Chinese, 2=English | `2` |
| `TTS_VOLUME` | Volume offset [-10, 10] | `0` |
| `TTS_SPEED` | Speed offset [-2, 6] | `0` |
| `KMS_KEY_ID` | KMS asymmetric key ID | `xxxx` |
| `KMS_KEY_ALGORITHM` | KMS signature algorithm | `RSA_PKCS1_SHA_256` |
| `LOCAL_PUBLIC_KEY_PEM` | Local PEM key (dev/testing fallback) | (empty) |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/dbs_dcta` |
| `COS_SECRET_ID` | COS SecretId (defaults to TENCENT_SECRET_ID) | `AKIDxxxx` |
| `COS_SECRET_KEY` | COS SecretKey (defaults to TENCENT_SECRET_KEY) | `xxxx` |
| `COS_REGION` | COS region | `ap-singapore` |
| `COS_BUCKET` | COS bucket name | `dbs-dcta-audit-xxx` |
| `DBS_PAYMENT_API_URL` | DBS payment endpoint | `https://mock-dbs-payment.example.com` |
| `DBS_PAYMENT_API_KEY` | DBS API key | `xxxx` |
| `HIGH_VALUE_THRESHOLD` | Freeze threshold for large transfers | `50000` |
| `SIGNATURE_TTL_SECONDS` | Biometric signature validity window | `60` |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend API base (baked at build time) | `/api` |

---

## 13. Post-Deployment Checklist

- [ ] **Rotate all credentials** — ADP AppKey, TRTC SDKSecretKey, CAM SecretId/SecretKey
      were exposed during development
- [ ] **Enable WAF** — Configure Web Application Firewall in front of the CLB
- [ ] **Add API authentication** — No route currently requires auth (acceptable for demo,
      not for production)
- [ ] **Enable HTTPS** — Provision SSL certificate, redirect HTTP → HTTPS
- [ ] **Configure CORS** — Set `CORS_ORIGINS` to the production domain
- [ ] **Set up log shipping** — Container logs to Tencent Cloud CLS (Log Service)
- [ ] **Configure alerts** — CLB 5xx errors, TDSQL-C CPU, COS storage growth
- [ ] **Run acceptance tests** — Execute the 7 demo scenarios via the public URL
- [ ] **Verify audit chain** — Check that `previous_hash` links are intact in TDSQL-C
- [ ] **Test voice path** — Record a real speech audio file and verify ASR transcription
- [ ] **Back up TDSQL-C** — Configure automated backups
- [ ] **Fix CAM typo** — Change `trct:*` to `trtc:*` in the CAM policy

---

## 14. Known Limitations & Roadmap

### Current limitations (not deployment blockers)

| # | Issue | Impact |
|---|-------|--------|
| 1 | `/confirm` does not re-read balances | Relative amounts resolved at parse time may be stale by execution |
| 2 | Signing is a placeholder (`toySign`) | Not a secure enclave or WebAuthn — needs real device signing |
| 3 | No nonce | Captured signed envelope is replayable within 60s TTL |
| 4 | No velocity throttling | Many-small-transfers not rate-limited |
| 5 | Audio never archived | `archive_audio_to_cos` defined but not called |
| 6 | No auth on any route | `/audit` is publicly readable |
| 7 | TTS not wired to frontend | UI is voice-in / text-out (backend `/tts` works) |
| 8 | Real speech ASR unverified | Only synthetic non-speech WAV tested (auth confirmed, quality not) |

### Roadmap

1. **Real biometric signing** — Integrate WebAuthn / device secure enclave
2. **Balance re-read at confirm** — Call DBS API for live balance before execution
3. **Audio archiving** — Wire `archive_audio_to_cos` into the ASR endpoint
4. **Route authentication** — JWT or Tencent Cloud CAM-signed requests
5. **Velocity throttling** — Rate counter for rapid small transfers
6. **Nonce + replay protection** — One-time-use signed envelopes
7. **TTS voice output** — Wire `/tts` to the frontend for voice-out responses
8. **Payee directory migration** — Move from `accounts.py` to PostgreSQL
   (see `DESIGN_PAYEE_DIRECTORY.md`)

---

## Appendix: Project Structure

```
dcta_tentcent/
├── backend/
│   ├── main.py                   # FastAPI REST layer
│   ├── config.py                 # Environment settings
│   ├── models.py                 # Pydantic schemas
│   ├── requirements.txt
│   ├── .env / .env.example
│   ├── services/
│   │   ├── parser.py             # ADP SSE parser + heuristic fallback
│   │   ├── shield.py             # Prompt-injection safety shield
│   │   ├── validator.py          # Independent validation agent
│   │   ├── asr.py                # TRTC ASR v3 (UserSig auth)
│   │   ├── tts.py                # Tencent TTS (CAM auth)
│   │   ├── crypto.py             # KMS biometric verification
│   │   ├── accounts.py           # Authoritative registry
│   │   └── payee_store.py        # PostgreSQL payee table (seeded, unread)
│   ├── ledger/executor.py        # DBS payment API executor
│   ├── audit/logger.py           # Immutable audit logger (hash chain)
│   └── tests/                    # 73 tests
├── frontend/
│   ├── pages/index.tsx           # Main chat page
│   ├── components/
│   │   ├── Chat.tsx              # Voice/text chat container
│   │   ├── DraftCard.tsx          # Transaction draft review
│   │   ├── ClarifyCard.tsx       # Ambiguity resolution
│   │   ├── BiometricOverlay.tsx  # Confirmation overlay
│   │   └── AuditPanel.tsx        # Live audit ledger
│   ├── lib/api.ts                # REST client
│   └── lib/types.ts              # TypeScript schemas
├── deploy/
│   ├── Dockerfile                # Backend image
│   ├── Dockerfile.frontend       # Frontend image (multi-stage)
│   ├── docker-compose.yml        # Local full-stack orchestration
│   ├── nginx.conf                # Reverse proxy config
│   └── tke-deployment.yaml       # TKE Kubernetes manifest
├── scripts/
│   ├── run_local.sh              # One-click local dev
│   └── run_tests.sh              # Backend test runner
├── ARCHITECTURE.md               # Technical architecture
├── STATUS.md                     # Deployment status & open issues
├── DEPLOYMENT.md                 # Chronological deployment log
├── DESIGN_PAYEE_DIRECTORY.md    # Payee directory migration design
└── README_DEPLOY.md              # Deployment scaffold README
```
