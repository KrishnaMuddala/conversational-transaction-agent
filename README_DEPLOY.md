# DBS DCTA — Tencent Cloud Deployment Scaffold

This folder contains a complete, deployable FastAPI + Next.js implementation of the Direct Conversational Transaction Agent, ready to run on Tencent Cloud.

## Structure

```
.
├── README_DEPLOY.md              # This file
├── backend/                      # FastAPI backend
│   ├── main.py                   # REST endpoints
│   ├── config.py                 # Environment configuration
│   ├── models.py                 # Pydantic request/response schemas
│   ├── requirements.txt          # Python dependencies
│   ├── .env.example              # Environment variable template
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py           # sets USE_MOCK_PARSER=true for self-contained runs
│   │   ├── test_api.py           # API integration tests
│   │   ├── test_adp_parser.py    # ADP wire contract, requests.post stubbed
│   │   └── test_shield.py        # injection / account-number discrimination
│   ├── services/
│   │   ├── __init__.py
│   │   ├── accounts.py           # Known payees, accounts, assets (authoritative)
│   │   ├── asr.py                # TRTC ASR v3 client (SDKAppID + UserSig)
│   │   ├── crypto.py             # Biometric signature / KMS verification
│   │   ├── parser.py             # ADP parser (v1 + v2) + heuristic fallback
│   │   ├── payee_store.py        # PostgreSQL payee table + drift guard (seeded, unread)
│   │   ├── shield.py             # Prompt-injection safety shield
│   │   ├── tts.py                # Tencent Cloud TextToVoice
│   │   └── validator.py          # Independent validation agent
│   ├── ledger/
│   │   ├── __init__.py
│   │   └── executor.py           # DBS payment API executor (mock by default)
│   └── audit/
│       ├── __init__.py
│       └── logger.py             # TDSQL / COS immutable audit logger
├── frontend/                     # Next.js frontend
│   ├── next.config.js            # Next.js + standalone output config
│   ├── package.json              # NPM dependencies
│   ├── tsconfig.json             # TypeScript config
│   ├── next-env.d.ts
│   ├── .env.local.example        # Frontend API base URL template
│   ├── styles/
│   │   └── globals.css           # Global styles / CSS variables
│   ├── pages/
│   │   ├── _app.tsx              # Next.js app entry
│   │   └── index.tsx             # Main chat page
│   ├── lib/
│   │   ├── api.ts                # REST client
│   │   └── types.ts              # Shared TypeScript schemas
│   └── components/
│       ├── AuditPanel.tsx        # Live audit ledger sidebar
│       ├── BiometricOverlay.tsx  # Deterministic confirmation overlay
│       ├── Chat.tsx              # Main voice/text chat container
│       ├── ClarifyCard.tsx       # Ambiguity resolution UI
│       └── DraftCard.tsx         # Transaction draft review card
├── deploy/                       # Deployment artifacts
│   ├── Dockerfile                # FastAPI container image
│   ├── Dockerfile.frontend       # Next.js container image
│   ├── docker-compose.yml        # Local full-stack orchestration
│   ├── nginx.conf                # Reverse proxy config (serves compose stack on :8080)
│   └── tke-deployment.yaml       # Tencent Kubernetes Engine manifest
├── scripts/
│   ├── run_local.sh              # One-click local dev launcher
│   └── run_tests.sh              # Backend test runner
└── .dockerignore                 # Build-context excludes (context root is this dir)
```

## Quick start (local)

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create a .env file (see config.py for required keys)
cp .env.example .env

# Run with mock parser (no Tencent credentials needed)
USE_MOCK_PARSER=true uvicorn main:app --reload --port 8000
```

Then in another terminal:

```bash
cd frontend
npm install
npm run dev
```

## Run the full stack (Docker)

```bash
cd deploy
docker compose up --build
```

This starts four services: `db` (Postgres 15), `backend`, `frontend`, and `nginx` (:8080).
The backend waits on a `pg_isready` healthcheck, so it will not start against an unready
database.

**Open http://localhost:8080** — go through nginx, not the frontend port directly. The
frontend bundle is built with `NEXT_PUBLIC_API_BASE_URL=/api`, and nginx is what maps
`/api/*` to the backend. Hitting the frontend port directly will 404 on every API call.

Host ports are remapped from the in-container defaults to avoid collisions with other
local stacks on this machine:

| Service | URL | Notes |
|---------|-----|-------|
| nginx (app entrypoint) | http://localhost:8080 | Serves UI and proxies `/api/*` — **use this one** |
| frontend | http://localhost:3010 | container 3000; direct access bypasses the API proxy |
| backend | http://localhost:8010 | container 8000; Swagger UI at `/docs` |
| postgres | `127.0.0.1:5433` | container 5432; `postgres` / `postgres`, db `dbs_dcta` |

The database is published on **loopback only**, and on 5433 because a native PostgreSQL 18
already owns 5432 on this laptop. A bare `5432:5432` would both fail to bind and publish
default credentials to every network the host is on. Inside the compose network the
backend still reaches it as `db:5432`.

## Deploy to Tencent Cloud (recommended path)

1. **Create Tencent Cloud resources**
   - CVM / TKE cluster in `ap-singapore`
   - TDSQL-C PostgreSQL instance
   - COS bucket for raw audio + audit archives
    - KMS key for signing verification
    - API Gateway + WAF
    - Agent Development Platform application, published, with its AppKey

2. **Set environment variables** (use CAM credentials, not root keys)
   ```bash
    TENCENT_SECRET_ID=...
    TENCENT_SECRET_KEY=...
    TENCENT_REGION=ap-singapore

    # Speech recognition uses TRTC ASR v3, which authenticates with its own key
    # pair (UserSig), not the CAM key above. The legacy Tencent Cloud
    # SentenceRecognition API is not used.
    TRTC_SDK_APP_ID=...
    TRTC_SDK_SECRET_KEY=...
    TRTC_ASR_ENDPOINT=https://asr-intl.cloud-rtc.com/v3/transcribe
    ASR_ENGINE=16k_en

    ADP_APP_KEY=...            # from the published app's Call dialog in the ADP console

    # The endpoint must match the console the app was created in, because the
    # two consoles use different hosts *and* different request schemas, and a
    # wrong-host key returns the same 4505004 error as a bad key.
    #   International console (adp.tencentcloud.com) — v2, current default:
    ADP_BASE_URL=https://wss.lke.tencentcloud.com/adp/v2/chat
    #   International, deprecated v1 fallback (bot_app_key auth, sunsets 2026-12-31):
    # ADP_BASE_URL=https://wss.lke.tencentcloud.com/v1/qbot/chat/sse
    #   China console (adp.cloud.tencent.com):
    # ADP_BASE_URL=https://wss.lke.cloud.tencent.com/adp/v2/chat

    USE_MOCK_PARSER=false      # set true to fall back to the heuristic parser
    KMS_KEY_ID=...
    DATABASE_URL=postgresql://user:pass@host/db
    COS_BUCKET=dbs-dcta-audit-12345
    COS_REGION=ap-singapore
    DBS_PAYMENT_API_URL=https://mock-dbs-payment.example.com
    ```

   The chat endpoint authenticates with `ADP_APP_KEY` only — no CAM signature is
   sent. `TENCENT_SECRET_ID`/`TENCENT_SECRET_KEY` are used by the TTS, COS and KMS paths
   only; TRTC ASR uses its own `TRTC_SDK_SECRET_KEY`.


3. **Build and push Docker image**
   ```bash
   cd deploy
   docker build -t ccr.ccs.tencentyun.com/your-ns/dbs-dcta:latest ..
   docker push ccr.ccs.tencentyun.com/your-ns/dbs-dcta:latest
   ```

4. **Deploy to TKE / CVM and expose through API Gateway**

5. **Connect the frontend** by rebuilding with `NEXT_PUBLIC_API_BASE_URL` set to your API
   Gateway domain. This variable is inlined into the client bundle at **build** time, so
   changing it at runtime has no effect:
   ```bash
   docker build -f deploy/Dockerfile.frontend \
     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com \
     -t ccr.ccs.tencentyun.com/your-ns/dbs-dcta-web:latest ..
   ```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/intent` | Submit transcript, return `draft` / `clarify` / `frozen` / `blocked` / `chat` |
| POST | `/resolve` | Resolve ambiguities and re-validate |
| POST | `/confirm` | Submit biometric-signed draft for execution |
| GET  | `/audit` | Retrieve audit log |
| POST | `/asr` | Upload audio, return the TRTC ASR transcript |
| POST | `/tts` | Text → base64 MP3 (backend works; no frontend caller yet) |
| POST | `/demo/{scenario}` | Run demo attack scenarios |

`chat` means the utterance contained no transaction — a greeting, a refusal, or an
acknowledgement. It returns `draft: null` and never reaches the confirmation surface.

## Security model

- The conversational agent (parser/validator) has **zero** credentials to the DBS payment API.
- Only the gateway executor can call the ledger, and only after signature verification.
- Device biometric signature is verified with Tencent KMS.
- All inputs, drafts, validation decisions, signatures, and executions are appended to the audit chain.
- Output that contains no transaction is refused before it can reach the draft surface, so
  conversational input cannot become a confirmable instruction.

### Not yet true — do not describe these as implemented

- Signing uses a placeholder digest in browser page context, not a secure enclave or WebAuthn.
- No nonce: a captured signed envelope is replayable inside the 60 s TTL.
- No velocity throttling for many-small-transfers.
- Raw audio is never archived (`archive_audio_to_cos` is defined but not called).
- No authentication on any route, including `/audit`.
- Live credentials in `backend/.env` were exposed during development and must be rotated.

## Notes

- The backend ships with a `USE_MOCK_PARSER=true` mode so you can demo locally without real Tencent credentials. For production, set `USE_MOCK_PARSER=false` and point `ADP_BASE_URL` at the console that issued the AppKey.
- `services/parser.py` includes both the heuristic fallback and the Tencent ADP integration. ADP is dispatched on `ADP_BASE_URL`, so either the v1 international or v2 China request schema is supported. See `ARCHITECTURE.md` §4 for the endpoint pairing and the `4505004` trap.
- The frontend uses browser `MediaRecorder` for audio capture and sends it to `/asr`. Replace this with a native mobile SDK when building iOS/Android apps. Audio playback is not wired up, so the UI is voice-in / text-out.
- Run the tests from `backend/`. On Windows, add `--capture=no -p no:cacheprovider` to avoid a capture-teardown error.
  ```bash
  cd backend && python -m pytest tests -q
  ```
- `backend/services/payee_store.py` creates and seeds a `payees` table, but no application code reads it; the parser still resolves payees from `accounts.py`. See `DESIGN_PAYEE_DIRECTORY.md`.
