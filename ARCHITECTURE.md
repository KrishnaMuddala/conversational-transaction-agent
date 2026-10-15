# DBS DCTA — Technical Stack & Architecture

Direct Conversational Transaction Agent. Turns a spoken or typed instruction into a
validated, biometric-confirmed transaction draft.

---

## 1. Runtime topology

Everything runs as four containers in one Compose project. Only nginx is meant to be
exposed to a user.

```
                      ┌──────────────────────────────────────────────┐
   user               │  nginx  (nginx:1.27-alpine)   :8080 -> :80     │
   ──────▶  HTTP      │                                              │
                      │   /            ──▶ frontend:3000             │
                      │   /api/*       ──▶ backend:8000              │
                      │      (strips the /api prefix)                │
                      └──────────┬────────────────────┬──────────────┘
                                 │                    │
                    ┌────────────▼─────────┐  ┌───────▼─────────────────┐
                    │ frontend             │  │ backend                │
                    │ Next.js 14.2.3       │  │ FastAPI 0.111.0        │
                    │ React 18.3.1         │  │ Uvicorn 0.30.0         │
                    │ TypeScript 5.4.5     │  │ Python 3.11-slim       │
                    │ :3010 -> :3000       │  │ :8010 -> :8000         │
                    │                     │  │                       │
                    │ components/Chat.tsx │  │  main.py   REST layer  │
                    │ lib/api.ts          │  │  models.py Pydantic    │
                    │                     │  │  config.py settings    │
                    └─────────────────────┘  └───────┬─────────────────┘
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    │                  │                  │
                        ┌───────────▼────────┐ ┌───────▼────────┐ ┌───────▼────────┐
                        │ db                │ │ Tencent Cloud  │ │  DBS           │
                        │ postgres:15-      │ │ (external)     │ │  (external)    │
                        │ alpine            │ │                │ │                │
                        │ 127.0.0.1:5433    │ │ ADP     parse  │ │ payment API    │
                        │ SQLAlchemy 2.0.30 │ │ TRTC    voice  │ │ (mock URL)     │
                        │ alembic 1.13.1    │ │ TTS     audio  │ │                │
                        │                   │ │ KMS     sign   │ │                │
                        │ audit event rows  │ │ COS     archv  │ │                │
                        │ hash chain        │ └────────────────┘ └────────────────┘
                        │ payees (seeded)   │
                        └───────────────────┘
```

The database is published on `127.0.0.1:5433` only — loopback, and remapped from 5432
because a native PostgreSQL 18 already owns 5432 on this machine. The backend reaches it
as `db:5432` over the compose network. See §5.

`localhost:3010` and `localhost:8010` are reachable directly for debugging, but the
frontend's API calls are nginx-relative (`/api/...`), so hitting port 3010 directly
gives 404s on every request. **Use `http://localhost:8080`.**

---

## 2. Request path

The important property of this design is that **no single component is trusted**. The
model proposes, and independent code disposes.

```
POST /api/intent  { rawTranscript }
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │ Layer 0 — Audit                       audit/logger.py             │
  │   turn_id = turn_<ms>_<rand6>        append-only event, chained   │
  └───────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │ Layer 2 — Parser  (semantics)        services/parser.py           │
  │   ADP chat SSE  ──▶  Intent[]                                       │
  │   decides: type, amount, confidence, candidate payee              │
  │   ✗ NOT trusted for: ids, balances, payee identity                │
  └───────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │ Layer 2a — No-intent gate          main.py _has_transaction_...  │
  │   an empty (or lone "unknown") intent list is NOT a transaction   │
  │   ── no intent ──▶ return chat, stop. Never reaches the draft     │
  │                     surface, so chitchat cannot become confirmable │
  └───────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │ Layer 1 — Safety shield               services/shield.py          │
  │   runs on the RAW transcript, not on the parsed draft             │
  │   INJECTION_PATTERNS + account-number check                       │
  │   ── hit ──▶ return blocked, stop. Nothing is confirmed or sent.  │
  └───────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │ Layer 2b — Registry backfill         services/parser.py           │
  │   services/accounts.py is AUTHORITATIVE                           │
  │   · source account balance  ← real balance, never the model's     │
  │   · payee/asset identity    ← canonical object, model may only    │
  │                                nominate a *name*                   │
  │   · relative amount "everything left" → balance − already spent    │
  │   · reconcile ambiguities that the backfill just answered         │
  └───────────────────────────────────────────────────────────────────┘
        │
        ├─ ambiguities non-empty ──▶ return clarify   ──────────────┐
        │                                                      │     │
        ▼                                                      │     │
  ┌────────────────────────────────────────────────────────┐   │     │
  │ Layer 3 — Validation agent    services/validator.py   │   │     │
  │   re-derives amount from the transcript independently   │   │     │
  │   re-checks payee against the registry                  │   │     │
  │   ── discrepancy ──▶ return frozen (manual review)     │   │     │
  └────────────────────────────────────────────────────────┘   │     │
        │                                                        │     │
        ▼                                                        │     │
  ┌────────────────────────────────────────────────────────┐   │     │
  │ return draft  →  user reviews  →  POST /api/confirm     │◀──┘     │
  │                                services/crypto.py               │
  │                                KMS VerifyByAsymmetricKey        │
  └────────────────────────────────────────────────────────┘          │
                                                                     │
POST /api/resolve { turnId, field, choice } ───────────────────────┘
    replays the audited draft and answers one open question
```

> **Ordering note — the shield does not run before the model.** It screens the *raw
> transcript* rather than the model's output, which is what the handbook requires, but in
> `main.py` the parser call is line 144 and the shield is line 162. A blocked phrase has
> therefore already been sent to ADP by the time the block fires. Nothing is confirmed,
> drafted for execution, or paid on a blocked turn, and the raw screen is what stops the
> injected instruction from *acting* — but "the model never runs" is not literally true
> today. Moving the shield above the parser is a small change with a real latency
> benefit for obvious attacks, and it is the honest reading of the diagram. Not yet done.

### Five response types

| Type | Meaning | Produced by |
|------|---------|-------------|
| `draft` | ready for biometric confirmation | all layers passed |
| `clarify` | needs one more answer from the user | unresolved ambiguity |
| `frozen` | discrepancy — held for manual review | validation agent |
| `blocked` | refused before any model call | safety shield |
| `chat` | no transaction was found in the utterance | no-intent gate |

`chat` exists so the agent can turn away ordinary speech without inventing a
transaction. ADP answers a greeting or a refusal with its own non-transaction envelope
(`{"Type": "request_ack"}`), which carries no `intents` key; the parser normalises that
to an empty intent list and the gate returns `chat` with `draft: null`.

This gate is a security boundary, not a UX affordance. An empty intent list used to
fall through to the draft response, so `"good morning"` produced a draft telling the
user to "review and confirm with biometrics", and `"thank you"` returned HTTP 500
because ADP's envelope failed `Draft` validation. Both are the same gap: nothing
distinguished non-transactional speech from a real instruction, so conversational input
reached the confirmable surface. See `STATUS.md` §2c.

---

## 3. Component responsibilities

### Backend — Python 3.11 / FastAPI

| Module | Role |
|--------|------|
| `main.py` | REST endpoints: `/intent`, `/resolve`, `/confirm`, `/asr`, `/tts`, `/audit`, `/demo/{scenario}`; the no-intent gate |
| `config.py` | pydantic-settings; holds the ADP endpoint default and the console/endpoint/schema pairing |
| `models.py` | Pydantic v2 schemas: `Draft`, `Intent`, `Account`, `Payee`, `Asset`, `Ambiguity` |
| `services/parser.py` | ADP transport (v1 + v2), SSE/UTF-8 decoding, JSON salvage, registry backfill |
| `services/shield.py` | injection patterns + money-vs-account-number discrimination |
| `services/validator.py` | independent re-derivation; freezes on mismatch |
| `services/accounts.py` | static payee / account / asset registry — the authoritative resolver |
| `services/payee_store.py` | PostgreSQL payee table, ORM, idempotent `--init`, drift guard. **Seeded but unread**; the parser still uses `accounts.py` |
| `services/crypto.py` | biometric signature verify via KMS, with a local-key path and a demo signer |
| `services/asr.py` | TRTC ASR v3 sentence recognition (HTTP, UserSig auth) |
| `services/tts.py` | Tencent Cloud `TextToVoice` (MP3 out) |
| `audit/logger.py` | SQLAlchemy audit rows with a hash chain; `archive_audio_to_cos` is defined but never called |
| `ledger/executor.py` | DBS payment API executor (mock URL by default) |

### Frontend — Next.js 14 / React 18

| Path | Role |
|------|------|
| `components/Chat.tsx` | transcript UI, draft review, confirm button, mic capture |
| `lib/api.ts` | nginx-relative client; surfaces detailed backend errors |
| `lib/types.ts` | shared TS schemas; mirrors the backend `IntentResponse` union |

Two honest limitations in the frontend:

- `Chat.tsx` signs with a placeholder `toySign` digest in page context. It is a stand-in,
  not a device secure enclave or WebAuthn, so the zero-trust boundary is logical rather
  than enforced. See `review.md` §4.
- The UI is **voice-in / text-out**. `/tts` exists on the backend but the frontend has no
  caller and no audio playback, so nothing is spoken back yet.

### Data — PostgreSQL 15

`sqlalchemy` 2.0.30 + `psycopg2-binary`, with `alembic` for migrations. Stores audit
events as append-only rows linked by a hash chain. `asyncpg` is present but the
synchronous `psycopg2` path is what is wired up.

A second table, `payees`, is created and seeded by `services/payee_store.py` (4 rows, no
balance column). It is storage only — no application code reads it, and the parser still
resolves payees from `accounts.py`. `DESIGN_PAYEE_DIRECTORY.md` covers the intended
migration and why balances are deliberately excluded.

---

## 4. External services

| Service | SDK | Used for | Credential |
|---------|-----|----------|-----------|
| **ADP** — Agent Development Platform | `requests` over HTTPS | Intent parsing (Layer 2) | `ADP_APP_KEY` only |
| **TRTC ASR** — Speech Recognition | `httpx` (direct HTTP) | Voice → text | `TRTC_SDK_APP_ID` / `TRTC_SDK_SECRET_KEY` (UserSig) |
| **TTS** — Text to Speech | `tencentcloud-sdk-python` | Text → audio | `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` |
| **KMS** — Key Management | `tencentcloud-sdk-python` | `VerifyByAsymmetricKey` | CAM + `KMS_KEY_ID` |
| **COS** — Object Storage | `cos-python-sdk-v5` | Audio archive | `COS_SECRET_ID` / `COS_SECRET_KEY` |
| **DBS** — core banking | `httpx` | Payment execution | `DBS_PAYMENT_API_KEY` |

ADP chat authentication is **AppKey only** — CAM credentials are not involved in
parsing. TRTC ASR uses **SDKAppID + SDKSecretKey** (HMAC-SHA256 UserSig), not the
cloud API SecretId/SecretKey. TTS and KMS use the cloud API key pair.

### The ADP endpoint trap

Keys are not portable between the two ADP consoles, and host and field names must
agree. A mismatch returns `4505004 APPKEY is invalid` — the identical error you
get from a genuinely bad key.

| Console | Endpoint | Auth field |
|---------|----------|-----------|
| International `adp.tencentcloud.com` | `wss.lke.tencentcloud.com/adp/v2/chat` | `AppKey` |
| International (fallback) | `wss.lke.tencentcloud.com/v1/qbot/chat/sse` | `bot_app_key` |
| China `adp.cloud.tencent.com` | `wss.lke.cloud.tencent.com/adp/v2/chat` | `AppKey` |
| China (fallback) | `wss.lke.cloud.tencent.com/v1/qbot/chat/sse` | `bot_app_key` |

The hosts differ by a `.cloud.`. Both generations return **HTTP 200** and deliver the
error as an SSE event, so status codes never reveal it. `parser.py` dispatches on the
URL, so switching is a one-variable change.

This project uses the **international v2** endpoint, per the AI CAN DO IT Hackathon
Guide, verified 7/7 on the live acceptance suite. The v1 path is a fallback only: it
is labelled "Previous Version" upstream and documented to sunset 2026-12-31.

---

## 5. Configuration

All backend config is environment-driven from `backend/.env` (gitignored).
`backend/.env.example` is the template.

| Variable | Purpose |
|----------|---------|
| `USE_MOCK_PARSER` | `true` = heuristic fallback, `false` = live ADP. Currently `false`. |
| `ADP_APP_KEY` | AppKey from the app's **Call** dialog |
| `ADP_BASE_URL` | must match the console that issued the key |
| `DATABASE_URL` | overridden by Compose to `postgresql://…@db:5432/dbs_dcta` — see the warning below |
| `DBS_PAYMENT_API_URL` | execution endpoint; mock by default |

> **`db:5432` is not reachable from the host laptop.** `db` is the Compose service
> name and only resolves inside the compose network, so a DB client on the host
> fails with `getaddrinfo failed` / "No such host is known". Two other hosts on this
> machine make it worse: a native PostgreSQL 18 already owns port 5432, and the
> container is published on loopback only, so the machine hostname resolves but is
> then refused.
>
> | Client location | Host | Port |
> |---|---|---|
> | backend container | `db` | 5432 |
> | host laptop / VS Code / psql | `127.0.0.1` or `localhost` | **5433** |
>
> Database `dbs_dcta`, user `postgres`, password `postgres`, **SSL mode `disable`**
> (the container has no SSL configured). Full details in
> `DESIGN_PAYEE_DIRECTORY.md` §10.

---

## 6. Verification status

| Check | Result |
|-------|--------|
| Backend test suite | **73 passed, 1 skipped** (skip is the credential-dependent ASR 503 test) |
| Live acceptance via nginx | **7/7**, repeated 14/14 over two warm passes |
| Non-transaction input | `chat` for greetings/refusals, `draft: null`, no 500 — verified 9/9 live |
| Parse latency | 5–9 s (non-streaming model round trip) |
| ASR | **working** — TRTC ASR v3 (`asr-intl.cloud-rtc.com/v3/transcribe`), UserSig auth, no activation needed |
| ASR audio formats | WAV ✅, PCM ✅, OGG-Opus ✅, WebM/Opus ✅, **MP3 ❌** (code=5000) |
| ASR real-speech quality | **unverified** — only a synthetic non-speech WAV has been sent; it returned an empty transcript with no error, which proves auth and routing but not recognition |
| TTS | backend endpoint works — Tencent Cloud TTS (`tts.tencentcloudapi.com`), CAM auth, MP3. **No frontend caller yet**, so the app does not speak back |
| Tencent Cloud ASR (legacy) | retired — superseded by TRTC ASR. `FailedOperation.UserNotRegistered` is historical, not a current blocker |

Acceptance outcomes: `blocked` (injection), `frozen` (large transfer), `draft` (clean
transfer), `clarify` (multi-intent, vague invest, unknown payee), `draft` (relative
amount). See `STATUS.md` for the full record.

---

## 7. Voice path

Text input goes straight to `/intent`. Voice adds one step in front of it.

```
mic ──▶ MediaRecorder (WebM/Opus) ──▶ POST /api/asr ──▶ TRTC ASR v3 ──▶ transcript
                                                                             │
                                                                             ▼
                                                              POST /api/intent  (as above)
                                                                             │
                                                                     text response
                                                              (no TTS playback in the UI)
```

`POST /api/asr` takes a multipart upload and returns the transcript. The frontend then
puts that text into the same input the keyboard would have used, so voice and text share
one code path — there is no separate voice intent route.

| Step | Component | What happens |
|------|-----------|--------------|
| 1 | User speaks | e.g. "Transfer five hundred dollars to mom" |
| 2 | Frontend | `MediaRecorder` captures WebM/Opus; `lib/api.ts` picks the extension from the blob MIME type |
| 3 | TRTC ASR v3 | `asr-intl.cloud-rtc.com/v3/transcribe`; SDKAppID + SDKSecretKey (UserSig), no CAM |
| 4 | Backend | transcript becomes `rawTranscript` on the normal `/intent` path |

Two things to know about this path:

- **MP3 is rejected by ASR with `code=5000`.** TTS emits MP3, so do not loop TTS output
  back into ASR. Browser capture is WebM/Opus, which ASR accepts as `ogg-opus`, so the
  real path needs no conversion.
- **The app does not speak.** `/tts` works and returns base64 MP3, but nothing in the
  frontend calls it, so responses are text-only. The handbook lists TTS from Tencent Cloud
  TRTC; the backend currently uses Tencent Cloud `TextToVoice`. Worth reconciling.

### Tencent Cloud service status

| Service | Auth | Status |
|---------|------|--------|
| ADP Parser | AppKey | working (v2 international, SSE) |
| TRTC ASR v3 | SDKAppID + UserSig | working (wav, pcm, ogg-opus, webm) |
| Tencent TTS | SecretId/SecretKey (CAM) | working (MP3 out) — no frontend caller |
| KMS | SecretId/SecretKey + `KMS_KEY_ID` | configured, untested |
| Postgres (project) | `DATABASE_URL` | working (audit chain + seeded payees) |
| COS | SecretId/SecretKey | configured, untested; `archive_audio_to_cos` never called |
| DBS payment API | `DBS_PAYMENT_API_KEY` | mock URL by default |

### Known gaps

Not aspirational — these are open, and `review.md` ranks them.

1. **Signing is `toySign` in page context**, not a secure enclave or WebAuthn. The
   zero-trust split is logical, not deployment-enforced: the agent and the gateway run in
   one process.
2. **No velocity throttling.** `HIGH_VALUE_THRESHOLD` freezes large transfers, but there
   is no rate counter for many-small-transfers, and the freeze message promises an
   out-of-band step that does not exist.
3. **No nonce**, so a captured signed envelope is replayable inside the 60 s TTL.
4. **Audio is never archived** — `archive_audio_to_cos` is defined but not called.
5. **Scenario 2** (voice digital services, e.g. ordering) and **KYC** are not implemented.
6. **Live secrets in `backend/.env`** were exposed during development and must be rotated
   (ADP AppKey, TRTC SDKSecretKey, CAM SecretId/SecretKey).
7. **No authentication on any backend route.** Acceptable on localhost; not acceptable
   before exposing a payee directory or the audit log.
8. **`/confirm` does not re-read balances.** A relative amount resolved at parse time is
   executed minutes later from the same stale number. `DESIGN_PAYEE_DIRECTORY.md` §2.4.

