# DCTA Deployment Status

_Last updated: 2026-10-02 (chitchat no longer produces a confirmable draft; 73 tests)_

Stack runs locally via Docker Compose. The intent parser runs on **Tencent Cloud Agent
Development Platform (ADP)** in production mode — `USE_MOCK_PARSER=false` — and is
verified end-to-end through nginx on all seven acceptance cases. See §2 for the endpoint
trap that had been blocking it, and `DEPLOYMENT.md` Phase 11 for the move off the
deprecated v1 path.

ASR is **resolved** — replaced by TRTC ASR v3 (`asr-intl.cloud-rtc.com/v3/transcribe`),
which uses SDKAppID + SDKSecretKey (UserSig) instead of the separately-activated
SentenceRecognition service. See §1. What remains unverified is *real-speech* quality:
only a synthetic non-speech WAV has been sent, which proved auth and routing but returned
an empty transcript.

Two live issues are open, neither a deployment blocker:

1. **Non-transactional speech could reach the confirmable draft surface** — fixed, see §2c.
2. **`/confirm` does not re-read balances** — a real bug, not yet fixed. See
   `DESIGN_PAYEE_DIRECTORY.md` §2.4.

---

## Resolved

### 2c. Chitchat returned a confirmable draft, and acknowledgements returned HTTP 500

Found 2026-10-02 while testing ordinary speech rather than transactions.

`/intent` had no branch for "the parser found no transaction". After the parser returned,
control fell through to the draft response unconditionally, so the user saw *"I've
prepared a transaction draft. Please review and confirm with biometrics"* for:

```
good morning, oh no, hi, hello, thank you, yes, no, what is my balance, cancel
```

Each response carried an **empty** intent list and no signature. The confirmable surface
was reachable with nothing in it to confirm — a fail-open in the exact path the handbook
requires to be hard-bounded.

A second failure sat on the same line. When ADP answers a non-transactional turn it uses
its own envelope, e.g. `{"Type": "request_ack", "rawTranscript": ...}`. That has no
`intents` key, so `Draft(**data)` raised a pydantic validation error and the turn became
**HTTP 500**. `thank you` and `no` were 500s, not drafts — same root cause, different
symptom, which is why only some greetings looked broken.

**Fix:**

- `models.py` — added `"chat"` to the `IntentResponse.type` union. The type had no way to
  express "no transaction found".
- `main.py` — added `_has_transaction_intent()` and a gate immediately after the parser,
  before the shield, ambiguity gate and validator. Empty intents, or a lone `unknown`
  intent, return `type="chat"` with `draft: null` and a message naming what the agent
  can do (transfers, investments, safety demo, balances).
- `services/parser.py` — both the v1 and v2 ADP paths normalise a non-transaction
  envelope to an empty intent list instead of failing validation. The heuristic fallback
  now returns an empty list too, rather than a placeholder `unknown` intent.
- `frontend` — `Chat.tsx` renders `chat` as plain text; `types.ts` mirrors the union.

**Verified live through nginx:** 9/9 non-transaction inputs → `chat`, `draft: null`, no
500. Real transactions unaffected — `Transfer $100 to mom` → `draft`, multi-intent → 2
intents, `Send fifty to John` → `clarify`, injection → `blocked`, relative amount →
`clarify`. 11 new tests; suite now **73 passed, 1 skipped**.

### 1. ASR `FailedOperation.UserNotRegistered` — RESOLVED via TRTC ASR v3

The legacy Tencent Cloud ASR `SentenceRecognition` API returned
`FailedOperation.UserNotRegistered` across all regions because the ASR service was not
activated on the account (and no console activation option was visible).

**Resolution:** `backend/services/asr.py` has been rewritten to use the **TRTC ASR v3
sentence-recognition HTTP API** instead. This endpoint:

- Uses `SDKAppID` + `SDKSecretKey` (UserSig HMAC-SHA256) — not SecretId/SecretKey.
- Does not require separate service activation.
- Is part of the TRTC Conversational AI product (10,000 free minutes/month).
- Accepts WAV, PCM, MP3, M4A, and OGG-Opus (including browser WebM/Opus).

**Credentials verified working** (2026-10-01):
- SDKAppID: `20048881` ✅
- SDKSecretKey: valid for UserSig generation ✅
- A live call to the v3 endpoint returns `code: 0` with no error, so auth, endpoint and
  request shape are all correct.

**What is not yet verified:** recognition quality. A synthetic non-speech WAV returned
`{'transcript': '', 'confidence': None}` — an empty result with no error, which confirms
the service is reachable and authorised but proves nothing about speech being recognised.
A real speech recording has not been transcribed end to end, because microphone access is
blocked at the OS level on this machine (Windows has `microphone` consent set to `Deny`
under `HKCU\...\CapabilityAccessManager\ConsentStore`; browser permissions cannot
override that). Testing with a supplied audio file is the unblocked path.

**Files changed:**
- `backend/services/asr.py` — full rewrite (Tencent ASR SDK → TRTC ASR v3 HTTP API)
- `backend/config.py` — added `TRTC_SDK_APP_ID`, `TRTC_SDK_SECRET_KEY`, `TRTC_ASR_ENDPOINT`
- `backend/.env` — added TRTC credentials
- `frontend/components/Chat.tsx` — `MediaRecorder` now detects browser-supported MIME types
- `frontend/lib/api.ts` — `uploadAudio` derives the correct file extension from blob MIME type

**TTS is unchanged** — the existing Tencent Cloud TTS (`tts:TextToVoice`) was already
activated and working (verified with a 14KB audio response).

### 2. ADP AppKey rejected (`4505004`) — RESOLVED: wrong endpoint generation

The key was never wrong, and neither was the request shape. **Host and request schema must
agree**, and only two of the four combinations authenticate:

| Console | Endpoint | Auth field | Wire schema |
|---------|----------|-----------|-------------|
| International `adp.tencentcloud.com` | `wss.lke.tencentcloud.com` `/adp/v2/chat` | `AppKey` | v2 |
| International | `wss.lke.tencentcloud.com` `/v1/qbot/chat/sse` | `bot_app_key` | v1 |
| China `adp.cloud.tencent.com` | `wss.lke.cloud.tencent.com` `/adp/v2/chat` | `AppKey` | v2 |
| China | `wss.lke.cloud.tencent.com` `/v1/qbot/chat/sse` | `bot_app_key` | v1 |

Measured against this application:

| Probe | Result |
|---|---|
| **v2 intl host + `AppKey`** (Hackathon Guide) | **`reply` event — accepted** |
| **v1 intl host + `bot_app_key`** | **`reply` event — accepted** |
| v2 China host + `AppKey` | `4505004` APPKEY invalid |
| v1 China host + `bot_app_key` | `4505004` APPKEY invalid |
| v2 intl host + `bot_app_key` (wrong field for path) | no reply — rejected |

What made this expensive to diagnose: **every mismatch returns the identical
`4505004` code**, and it arrives as **HTTP 200** with the error delivered as an SSE
event. The failure looked the same whether the app was unpublished,
the key was the wrong type, or the host was wrong — three very different causes, one
symptom. The discriminating test is simply to call both hosts and compare.

Note the hosts differ by a `.cloud.`: `wss.lke.tencentcloud.com` (international) vs
`wss.lke.cloud.tencent.com` (China). v1 is labelled "Previous Version" in the docs but is
what the international console currently issues, so it is a live path, not a dead one.

`parser.py` now selects the wire format from `ADP_BASE_URL`, so the same code serves
either console; `config.py` documents the pairing.

### 2a. Bugs found while getting ADP live — FIXED

1. **Wrong endpoint generation** (above). The parser only spoke v2.
2. **`system_role` is ignored by agent-mode applications.** The v1 docs state
   `system_role` "only takes effect in standard mode"; this app answers with
   `reply_method: 18` (Intelligent Agent reply), i.e. agent mode. Measured JSON yield
   over six prompts: `system_role` 4/6, contract inline in `content` 6/6. The contract
   now travels in `content`.
3. **The user-message echo was parsed as the answer.** v1 emits the caller's own text
   back as a `reply` event with `reply_method: 0` and `is_llm_generated: false` before
   the real answer. Now filtered.
4. **Multi-line events broke line-oriented SSE parsing.** v1 streams `thought` and
   `reference` payloads spanning several physical lines. The decoder now scans for
   complete JSON values rather than trusting line framing, and accepts both the
   `data:{...}` and `data:["reply",{...}]` framings.
5. **Non-ASCII corruption.** `requests` decodes `text/event-stream` as ISO-8859-1, so
   any non-ASCII answer was mangled. Now decoded explicitly from `resp.content`.
6. **Error events parsed as data.** Now raised with the ADP code, message, trace id, and
   an actionable hint per documented error code.
7. **Model drift.** The app intermittently emitted `"balance": null` (rejected by
   `Account`), Payee/Asset fragments missing required keys, and wrapped the JSON in
   prose. Now repaired or salvaged before validation.
8. **Hallucinated payee identities.** The model invents plausible Payee objects
   (`id: "***9921"`, `id: "mom_2201"`, wrong bank). Entity identity is now
   **registry-authoritative**: the model may only nominate a name, and the canonical
   `Payee`/`Asset` from `services/accounts.py` is what reaches the draft, so no
   fabricated id can flow into confirmation or execution.
9. **Stale clarifications.** ADP flags gaps before the backfill runs, so an
   `amount_resolution` question could survive against an already-resolved amount and
   block confirmation for no reason. Ambiguities are now reconciled against the final
   draft.
10. **Unknown payees silently dead-ended.** An unverifiable payee had its destination
    dropped with no question asked. Now always raises a `payee_disambiguation`.
11. **Model-authored clarifications could dead-end the user.** The live model sometimes
    pre-populates its own `payee_disambiguation` ("Which payee do you mean?") with an
    empty `options` list. Because a `payee_disambiguation` already existed, the backfill
    treated the question as answered and skipped it, so the user got a choice that did
    not exist and no way forward. A model-supplied question with no options is now
    reworded with what the registry actually knows — `"Zi Wei" is not among your saved
    payees. Who would you like to send the money to?` Verified 3/3 live runs.
12. **`"everything left"` was not recognised** as a relative amount — a gap the
    heuristic shared. `_RELATIVE_RE` is now shared by both paths.
13. **Shield bug, pre-existing and unrelated to ADP:** the account-number pattern
    `\b\d{4,}[-]?\d+\b` matched plain 5+ digit **amounts**, so `Transfer $60000 to John
    Tan` returned `blocked` ("Unregistered account number") instead of reaching the
    validation layer and returning `frozen`. The shield now excludes money (currency
    marker before/after) and requires account context or a hyphenated form. Verified:
    `large_transfer` now returns `frozen`.

Test suite: **73 passed, 1 skipped** (was 19). The skip is `test_api.py:141`, which
asserts the ASR 503 path and cannot run while TRTC credentials are configured.

### 2b. Live verification through nginx

`USE_MOCK_PARSER=false`, all cases HTTP 200. Two consecutive warm passes, **14/14**:

| Case | Type | Detail |
|------|------|--------|
| `prompt_injection` | `blocked` | screened on the raw transcript, independent of the parser |
| `large_transfer` | `frozen` | $60,000 over the velocity threshold |
| `clean_transfer` | `draft` | transfer 250.0 → John Tan (`payee_john_tan`) |
| `multi_intent` | `clarify` | 2 intents; 2nd raises `payee_disambiguation` |
| `invest` | `clarify` | "index funds" is not a specific security → asks which |
| `unknown_payee` | `clarify` | "Zi Wei" is not in the registry → asks who to send to |
| `relative_amount` | `draft` | resolves to 4820.5 from the savings balance |

Latency is **5–9 s per parse**, which is the non-streaming round trip plus a real model
call. That is the dominant cost of the current design. The first request after a
container rebuild can be slower still.

Note on `invest`: this returns `clarify`, not `draft`. "index funds" names no security,
and asking which one is the correct banking behaviour — but the model has produced
`draft` for this input before, so treat the outcome as model-dependent rather than
guaranteed. Everything else above was stable across every repeat run.

---

## Resolved

### 3. Direct Hunyuan model access retired — RESOLVED (replaced by ADP)

The original `hunyuan.v20230901` / `ChatCompletions` path is dead and cannot be
revived with a CAM policy edit. Tencent retired the old models on 2026-06-22:

```
code:2000  Message: "This model has been decommissioned. Please follow the migration
           guide to use the latest model services on the TokenHub platform."
```

(The server returns this in Chinese; the text above is the English meaning, kept so a
support ticket carries the exact wording.)

The project deliberately does **not** integrate TokenHub directly. Parser traffic now
goes to ADP. The old `HUNYUAN_MODEL` / `HUNYUAN_BASE_URL` / `HUNYUAN_API_KEY` settings
have been removed from `backend/config.py`, `backend/.env`, and `backend/.env.example`.

ADP notes:

- **The endpoint determines the schema.** This deployment uses the international
  console, so traffic goes to `POST https://wss.lke.tencentcloud.com/adp/v2/chat` with
  the v2 field names. See §2. The v1 international path and both China paths remain
  supported and are selected by changing `ADP_BASE_URL` alone.
- The v1 path is labelled "Previous Version" in the docs and sunsets 2026-12-31, so it
  is a fallback only. An earlier note here claimed v2 was unavailable internationally and
  that migrating would require recreating the app on the China console — that was wrong.
  The Hackathon Guide documents the international v2 endpoint, it was verified working,
  and the deployment moved to it.
- ADP is an agent platform, not a raw completion endpoint: the model and base prompt
  live on the published application in the console, not in the request. That is why
  `ADP_MODEL_NAME` was removed — there is no per-request model override.
- ADP returns free text, so there is no JSON-schema guarantee. `_loads_json_object()`
  tolerates code fences and surrounding prose (with `_loads_json_object_salvage()` for
  conversational answers), then Pydantic validates the result into `Draft`. A malformed
  reply surfaces as a `RuntimeError`, not a silent bad draft.

### 4. `Draft.rawTranscript` was never requested from the model — FIXED

`Draft.rawTranscript` is required, but `PARSER_SYSTEM_PROMPT` only asks for `intents`
and `ambiguities`. Every real ADP response would have failed Pydantic validation. The
transcript is now injected in code (`data.setdefault("rawTranscript", raw)`) rather
than trusting the model to echo it.

### 5. Live secrets hardcoded in compose — FIXED

Secrets moved from `deploy/docker-compose.yml` to `backend/.env`. Compose uses
`env_file: ../backend/.env`. No credentials remain in the compose file.

### 6. `backend/.env` was inert — FIXED

`backend/config.py` calls `load_dotenv()`, and compose passes the same file via
`env_file`. The two are now consistent, so host runs and container runs agree.

### 7. Tests needed a manual env var — FIXED

`backend/tests/conftest.py` sets `USE_MOCK_PARSER=true`. `USE_MOCK_PARSER` also now
defaults to `true` in `backend/config.py`, so a fresh clone runs without setup.

### 8. `crypto.py` called an unauthorizable API — FIXED

Ported from `kms:Verify` (not in CAM) to `kms:VerifyByAsymmetricKey`. Verified in
`backend/services/crypto.py:84,90`.

### 9. Redundant nginx location blocks — FIXED

Duplicate per-route blocks removed; the `/api/` location with rewrite handles all
backend routing. `client_max_body_size 10M` added for ASR uploads.

---

## Environment notes

**Ports were remapped** because another local stack already held them:

| Service | Host port | Conflict |
|---------|-----------|----------|
| nginx | 8080 | — |
| frontend | 3010 (was 3000) | `netops-web-ui` |
| backend | 8010 (was 8000) | `mcp-forward` |
| db | **5433, loopback only** (was 5432) | native PostgreSQL 18 owns 5432 |

The database is bound to `127.0.0.1:5433`, not `0.0.0.0:5432`. Two reasons: a native
PostgreSQL 18 already holds 5432 on this machine, and a bare `5432:5432` would publish
`postgres`/`postgres` credentials to every network the host is on. The backend is
unaffected — it reaches the database as `db:5432` inside the compose network. Host
clients use `127.0.0.1:5433`, database `dbs_dcta`, SSL mode `disable`.

Safe because `nginx.conf` proxies to internal service names (`backend:8000`,
`frontend:3000`), not host ports. `CORS_ORIGINS` matches.

**Open http://localhost:8080 only.** The raw frontend port (3010) bypasses nginx, so
`/api/*` hits Next.js and 404s.

**Docker registry:** the daemon's corporate PAC proxy was dead,
blocking Docker Hub. Fixed with a registry mirror. The host reaches Docker Hub directly.

**There is no `/health` route.** Liveness must be inferred from a real route.

---

## Verified working

Verified 2026-10-02 against the rebuilt container:

- Container runs the ADP parser: `grep -c ADP_BASE_URL /app/services/parser.py` → 1,
  and no `tokenhub` / `HUNYUAN_` references remain.
- ADP path fails fast and actionably with no key:
  `RuntimeError: ADP_APP_KEY is not set. Publish an application in the ADP console...`
- All 3 demo scenarios return HTTP 200 with correct agent behaviour:
  - `prompt_injection` → **blocked**
  - `hallucination` → **clarify** (disambiguates "John" → John Tan / John Lim)
  - `large_transfer_velocity` → **frozen** ($90,000 vs $4,820.50 balance)
- Multi-intent: `"Transfer $500 to mom and invest the rest in Apple shares"` → 2 intents,
  second resolves to 4320.5
- Non-transaction input is refused safely (§2c): 9/9 greetings/refusals → `chat`,
  `draft: null`, no 500.
- 49 audit events persisted to Postgres
- Test suite: **73 passed, 1 skipped**

**Superseded on 2026-10-01 — do not re-verify these.** The CAM policy probe below refers
to the legacy Tencent ASR path, which is no longer used. TRTC ASR authenticates with
SDKAppID + SDKSecretKey and does not consult CAM at all, so the actions below neither
help nor hinder the current voice path.

- ~~`name/asr:SentenceRecognition` → allowed (reaches service logic)~~
- ~~`asr:GetUsageByDate` → `AuthFailure.UnauthorizedOperation` (correctly blocked)~~
- ~~TRTC ASR v3 TTS round-trip "Transfer five hundred dollars to mom" → "Transfer 500
  dollars to mom."~~ — re-tested 2026-10-02 with a synthetic non-speech WAV, which came
  back with an empty transcript and no error. Auth and routing are confirmed; actual
  speech recognition is **not**. See §1.

## Open issues

Not deployment blockers, but they are real and none should be described as working.

| # | Issue | Detail |
|---|-------|--------|
| 1 | `/confirm` does not re-read balances | A relative amount ("the rest of my savings") is resolved at parse time and executed minutes later from the same stale number. The executor never reads a balance. `DESIGN_PAYEE_DIRECTORY.md` §2.4 |
| 2 | Signing is a placeholder | `toySign` runs in page context — not a secure enclave or WebAuthn. The agent and the gateway share one process, so the zero-trust split is logical, not deployment-enforced |
| 3 | No velocity throttling | `HIGH_VALUE_THRESHOLD` freezes large transfers, but there is no rate counter for many-small-transfers, and the freeze message promises an out-of-band step that does not exist |
| 4 | No nonce | A captured signed envelope is replayable within the 60 s TTL |
| 5 | Audio never archived | `archive_audio_to_cos` is defined but never called, so the handbook's "raw audio stored for audit" is not met |
| 6 | Exposed credentials | Live ADP AppKey, TRTC SDKSecretKey and CAM key pair were exposed during development. All need rotating |
| 7 | No auth on any route | Acceptable on localhost; not acceptable before exposing a payee directory or `/audit` |
| 8 | Scenario 2 and KYC absent | Voice digital services (e.g. ordering) not built; no KYC integration |
| 9 | Shield runs after the parser | It screens the raw transcript, which is what the handbook asks for, but `parse_transcript` runs at `main.py:144` and the shield at `main.py:162` — so a blocked phrase has already been sent to ADP. Nothing is confirmed or paid. See `ARCHITECTURE.md` §2 |
| 10 | TTS never called by the UI | `/tts` works; the frontend has no caller, so the app is voice-in/text-out. The handbook lists TRTC TTS; the backend uses Tencent Cloud `TextToVoice` |

## Verification commands

```powershell
# stack health
docker compose -f deploy/docker-compose.yml ps

# agent behaviour
curl.exe -X POST http://localhost:8080/api/demo/prompt_injection
curl.exe -X POST http://localhost:8080/api/demo/hallucination
curl.exe -X POST http://localhost:8080/api/demo/large_transfer_velocity

# voice (TRTC ASR v3 — auth/routing confirmed; real speech unverified, see §1)
curl.exe -F "file=@test.wav" http://localhost:8080/api/asr

# audit trail
curl.exe http://localhost:8080/api/audit

# tests (self-contained, no env var needed).
# On Windows, plain `pytest` can fail during capture teardown with
# "ValueError: I/O operation on closed file" — disable capture explicitly.
cd backend
.\venv\Scripts\python.exe -m pytest tests -p no:cacheprovider --capture=no -q

# confirm the container is on the ADP path, not the retired SDK path
docker compose -f deploy/docker-compose.yml exec -T backend grep -c ADP_BASE_URL /app/services/parser.py
```

---

## Not relevant to current blockers

`cloudbase` skill installed at `.agents/skills/cloudbase/` (Tencent CloudBase
serverless). Covers Hunyuan only as a model called through CloudBase's own endpoint,
not the CAM-signed `hunyuan.tencentcloudapi.com` path this project used. Does not help
with ASR activation, the CAM policy, or ADP.
