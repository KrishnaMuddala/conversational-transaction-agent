# Deployment Record

_What was done to get this project running locally. Chronological._
_Current state and open issues: see `STATUS.md`._

---

## Phase 1 — Repository restructure

The project started as a flat pile of files at the repo root. Reorganised in place
into a conventional layout:

```
backend/     FastAPI app, services, ledger, audit, tests, venv
frontend/    Next.js app
deploy/      Dockerfiles, compose, nginx.conf
scripts/     run_local.sh, run_tests.sh
```

- `README_DEPLOY.md` consolidated; duplicate `README (1).md` removed
- Duplicate `config (1).py` removed
- Verified all 42 documented files present
- `dbs_summary.md` is user-added (43 total) — **do not delete**

Added:
- `frontend/next.config.js` — `output: "standalone"`, `reactStrictMode: true`
- `.dockerignore` at repo root — keeps `venv`, `node_modules`, `.git` out of build context

## Phase 2 — Docker build fixes

| Problem | Fix |
|---------|-----|
| `Dockerfile.frontend` copied a `public/` dir that doesn't exist | Removed the `COPY` |
| Frontend had no way to reach the API | Added `ARG`/`ENV NEXT_PUBLIC_API_BASE_URL`, default `/api` |
| Compose used the deprecated `version:` key | Removed |
| Backend started before Postgres was ready | Added `pg_isready` healthcheck + `depends_on: service_healthy` |
| No single entry point | Added nginx service proxying `/api/*` → backend, everything else → frontend |

## Phase 3 — Application bug fixes

Bugs surfaced during cold-stack validation:

| File | Bug | Fix |
|------|-----|-----|
| `backend/audit/logger.py` | `ts` column overflowed PostgreSQL `Integer` | `BigInteger` |
| `backend/audit/logger.py` | Lost writes when DB wasn't up yet | Retry, 10 attempts × 1.5s |
| `backend/main.py` | Demo endpoint sent the wrong request shape | Corrected mode/text fields |
| `backend/main.py` | ASR failed opaquely with no credentials | 503 when unconfigured, 502 with detail on failure |
| `backend/main.py` | Valid-signature confirm path broken | Corrected execution dict |
| `backend/services/crypto.py` | Pydantic v2 rejected `dict` where model expected | Coerce `Draft` |
| `backend/services/ledger/executor.py` | Destination model not serialisable into DBS payload | `_dest_attr` helper |
| `frontend/components/Chat.tsx` | Timestamp computed twice, signature mismatch | Single timestamp, canonical payload |
| `frontend/components/Chat.tsx` | JS unsigned hash went negative | `>>> 0` |

Regression tests added to `backend/tests/test_api.py` for the signing and confirm paths.

**Validation result: 7/7 passing.** Cold-stack E2E through nginx confirmed: valid
confirm executed both transfer and investment legs, tampered confirm was rejected,
audit events persisted, frontend returned 200, ASR returned 503 without credentials.

Stack was then torn down (`down -v`) leaving the unrelated `netops` stack untouched.

## Phase 4 — Tencent CAM policy debugging

The original policy was rejected by the console with *"the input action is invalid"*.
Three distinct problems found and fixed:

**1. Missing `name/` prefix.** CAM API actions must be written `name/<service>:<Action>`.
Bare `asr:SentenceRecognition` is invalid.

**2. `kms:Verify` does not exist.** The KMS CAM action list has no `Verify`. The real
actions are `VerifyByAsymmetricKey` and `PostQuantumCryptoVerify`.

**3. Sixth-segment resource format.** `qcs::project:service:region:account:resource` —
segment 5 must be `uin/<digits>` or `uid/<digits>`, no placeholders or `${...}`.

Final working policy (ASR only, sufficient for voice):

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": [
        "asr:SentenceRecognition",
        "asr:ActivateService",
        "asr:DescribeOpenStatus"
      ],
      "resource": ["*"]
    }
  ]
}
```

`SentenceRecognition` is operation-level, so `resource` must be `*` — narrowing it
makes CAM deny the call outright.

At this point the plan was to add `hunyuan:ChatCompletions` to the action list to enable
Hunyuan. That became moot — the model itself was retired, see Phase 8.

**Verified by probing the live API:**

| Action | Result | Meaning |
|--------|--------|---------|
| `asr:SentenceRecognition` | `MissingParameter` | allowed, reached service logic |
| `asr:DescribeTaskStatus` | `AuthFailure.UnauthorizedOperation` | correctly blocked |
| `asr:CreateRecTask` | `AuthFailure.UnauthorizedOperation` | correctly blocked |
| `asr:CreateAsrVocab` | `AuthFailure.UnauthorizedOperation` | correctly blocked |

Credentials authenticate, policy is honoured, least-privilege is enforced.

## Phase 5 — Stack bring-up

**Blocked: Docker could not pull base images.** `docker info` reported a proxy at
`http.docker.internal:3128`, inherited from a Windows PAC file pointing at the
corporate network's proxy host. That proxy was dead
(TCP timeout; PAC host didn't even resolve). The **host** reached Docker Hub fine
(HTTP 401 from `/v2/` = successful unauthenticated connection), so this was purely a
daemon config problem. Fixed with a registry mirror.

**Blocked: port conflicts.** Another local stack already owned both ports:
`mcp-forward` on 8000, `netops-web-ui` on 3000. Remapped the host side —
backend `8010:8000`, frontend `3010:3000` — and updated `CORS_ORIGINS`. Safe
because `nginx.conf` proxies to internal service names, not host ports.

**`USE_MOCK_PARSER` was declared twice** (`true` then `false`). Compose takes the
last, so the container called Hunyuan, which isn't in the policy → HTTP 500 on every
demo. Duplicate removed, value set to `true`.

**Secrets were found hardcoded** at `deploy/docker-compose.yml:13-14` — a real
SecretId/SecretKey. Flagged; remediation tracked in `STATUS.md` §3.

## Phase 6 — Frontend voice upload bug

Symptom: *"Voice upload failed: ASR failed"* in the UI, with **zero** ASR errors in
the backend logs.

Two separate causes, the first masking the second:

1. **Wrong entry point.** The app was opened on the raw frontend port (3010), which
   bypasses nginx. The browser requested `/api/asr` on its own origin → Next.js
   returned 404 → request never reached the backend.
2. **Error swallowing.** `frontend/lib/api.ts:51` threw a bare `"ASR failed"`,
   discarding status and body — so a routing 404 looked identical to a Tencent 502.

Fixes:
- `api.ts:8` — fallback `http://localhost:8000` → `/api`. The old default was wrong
  twice over: wrong port, and cross-origin direct-to-backend bypassed the proxy.
- `api.ts:51` — now reports HTTP status and response detail.

After the fix the real error surfaced: `FailedOperation.UserNotRegistered` — ASR
service not activated. Tracked in `STATUS.md` §1.

---

## Phase 7 — ASR re-diagnosis and structural debt fixes

**ASR "resolved" — this conclusion was WRONG, see Phase 9.** A `SentenceRecognition`
probe with empty `Data` returns `InvalidParameter: need param 'Data'`, and that was
read as proof the service was active. It is not: parameter validation runs before the
registration check, so the probe never reached it.

**Corrections to previous diagnostics:**

- `tccli asr DescribeUserStatus` — does not exist. Confirmed against
  `asr/v20190614/api.json` (33 actions) in Phase 9. The full action list contains no
  status or activation endpoint for OneSentence ASR.
- `asr:DescribeOpenStatus` and `asr:ActivateService` — also not real actions. They are
  in the CAM policy but CAM ignores unknown actions.
- `kms:Verify` — confirmed not in CAM. Ported to `VerifyByAsymmetricKey`.

**Hunyuan blocker confirmed.** `hunyuan:ChatCompletions` reached Tencent and was denied
on CAM policy. This later became moot — see Phase 8.

**Structural debt fixed (5 items):** secrets moved to `.env`, `load_dotenv()` added,
`conftest.py` for self-contained tests, KMS API ported, nginx cleaned up. See `STATUS.md`.

---

## Phase 8 — Hunyuan retired; parser moved to Tencent Cloud ADP

**Hunyuan could not be revived with a policy edit.** After the `hunyuan:ChatCompletions`
permission was granted, the error changed from `AuthFailure.UnauthorizedOperation` to a
model-layer rejection:

```
code:2000  Message: "This model has been decommissioned. Please follow the migration
           guide to use the latest model services on the TokenHub platform."
```

(The server returns this in Chinese; the text above is the English meaning.)

The old models (`hunyuan-lite`, `hunyuan-standard`, `hunyuan-turbo`) were retired on
2026-06-22, and the `hunyuan.tencentcloudapi.com` console/API is pre-decommission.

**Direction:** the project integrates **Tencent Cloud Agent Development Platform
(ADP)**, not TokenHub directly.

| Aspect | Finding |
|--------|---------|
| Console | https://adp.tencentcloud.com |
| Chat endpoint (current) | `POST https://wss.lke.tencentcloud.com/adp/v2/chat` |
| Chat endpoint (deprecated) | `POST /v1/qbot/chat/sse` with `bot_app_key` — sunsets 2026-12-31 |
| Auth | `AppKey` of a **published** application, read from the app's Call dialog |
| Request fields | `RequestId`, `ConversationId`, `AppKey`, `Contents[]`, `VisitorId`, `Incremental`, `EnableMultiIntent`, `Stream` |
| Response | SSE terminated by `event: done` / `data: [DONE]` |
| Reference client | `TencentCloudADP/adp-chat-client` (Docker-deployable) |

> **Superseded — see Phase 10.** The rows above are the v2 / China-console generation and
> are recorded here as written at the time. This application belongs to the
> **international** console, where the working endpoint is the v1 `/v1/qbot/chat/sse`
> path with `bot_app_key`; the hosts differ by a `.cloud.`. Treat the table as history.

ADP is an agent platform, not a raw completion endpoint — the model and base prompt are
configured on the published application, which is why there is no per-request model
override and `ADP_MODEL_NAME` was dropped.

### Bugs found and fixed during the integration

| Bug | Fix |
|-----|-----|
| `parse_transcript()` called `_adp_parse()` but the function was still named `_hunyuan_parse` | `NameError` on every production call — renamed |
| Sent `UserId` | Documented v2 field is `VisitorId` |
| Sent undocumented `SystemRole` and `ModelName` | Removed; parser contract now travels inside `Contents[].Text` |
| `RequestId`/`ConversationId` had to match `^[a-zA-Z0-9_-]{32,64}$` | `uuid4().hex` — 32 chars, always valid |
| `Draft.rawTranscript` required but never requested by the prompt | Injected in code via `setdefault` |
| Reply-event field names differ per app type | `_adp_event_text()` probes the known shapes instead of hard-coding one |
| ADP may return the Draft JSON with no text wrapper | Falls back to the raw payload |
| `raise_for_status()` discarded the response body | Errors now include HTTP status + first 500 chars, and re-raise `RuntimeError` unwrapped |
| Stale `HUNYUAN_*` settings in `config.py` and both env files | Removed; `ADP_APP_KEY`, `ADP_VISITOR_ID`, `ADP_TIMEOUT_SECONDS` added |
| `USE_MOCK_PARSER` defaulted to `false`, so a fresh clone broke | Defaults to `true` |

### Tests added

`backend/tests/test_adp_parser.py` — 10 tests with `requests.post` stubbed, so the ADP
contract is covered **without a published application**:

- request matches the v2 contract (and contains no `UserId`/`SystemRole`/`ModelName`)
- `RequestId`/`ConversationId` satisfy the documented length/charset rule
- the parser contract travels with the transcript
- single-JSON body, `response.completed` SSE event, and plain-text SSE deltas all decode
- code-fenced and prose-wrapped JSON both parse
- HTTP error surfaces status + body
- missing `ADP_APP_KEY` fails fast with console instructions
- empty answer surfaces the body

Two of these tests failed on first run and caught genuine decoder bugs (direct-JSON
bodies and JSON-string deltas both produced empty output), which were then fixed.

**Validation result: 17/17 passing.** Container rebuilt and confirmed to run the ADP
path with no TokenHub references. All three demo scenarios, multi-intent resolution,
and audit persistence re-verified through nginx.

---

## Phase 9 — ASR blocker re-opened

Re-tested with a real 1s 16 kHz mono WAV through nginx: still HTTP 502,
`FailedOperation.UserNotRegistered [appid: 1498015770] [biz: ASR_OneSentence]`.

The Phase 7 "resolved" conclusion was based on an empty-`Data` probe returning
`InvalidParameter`. That is a false positive — parameter validation precedes the
registration check, so the probe proved CAM authorization only.

Checked the local tccli service definition to settle what is actually possible:

```
backend/venv/Lib/site-packages/tccli/services/asr/v20190614/api.json  (33 actions)
SentenceRecognition    EXISTS
CreateRecTask          EXISTS
DescribeUserStatus     NOT FOUND
CreateAsrUser          NOT FOUND
ActivateService        NOT FOUND
DescribeOpenStatus     NOT FOUND
```

There is **no API to query or activate ASR OneSentence** — activation is console-only,
and the sole API-level diagnostic is calling `SentenceRecognition` with real audio.
Earlier advice to run `tccli asr DescribeUserStatus` or `CreateAsrUser` was incorrect and
has been removed from `STATUS.md`.

Remaining hypothesis: activation was completed against a different APPID, product line,
or region than the one the API is calling. See `STATUS.md` §1.

---

## Phase 10 — ADP live: the endpoint generation trap

The AppKey was rejected with `4505004` "application key is invalid" from the v2 China
endpoint. The key was never wrong.

**Root cause: the host and the request schema must agree, and only two of the four
combinations authenticate.**

| Console | Endpoint | Auth field |
|---------|----------|-----------|
| International `adp.tencentcloud.com` | `wss.lke.tencentcloud.com/adp/v2/chat` | `AppKey` |
| International | `wss.lke.tencentcloud.com/v1/qbot/chat/sse` | `bot_app_key` |
| China `adp.cloud.tencent.com` | `wss.lke.cloud.tencent.com/adp/v2/chat` | `AppKey` |
| China | `wss.lke.cloud.tencent.com/v1/qbot/chat/sse` | `bot_app_key` |

Probe results against this application:

```
v2  wss.lke.cloud.tencent.com     + AppKey          -> 4505004 APPKEY invalid   (China host)
v1  wss.lke.tencentcloud.com      + bot_app_key     -> reply event             (accepted)
v1  wss.lke.cloud.tencent.com     + bot_app_key     -> 4505004 APPKEY invalid   (China host)
```

Why this took so long to pin down: both generations return the **same** `4505004` code
for a wrong host, and both return **HTTP 200** with the error delivered as an SSE
event rather than an HTTP status. Unpublished app, wrong credential type, and wrong host
all produced byte-identical symptoms. The only discriminator is calling every host.

Note the hosts differ by a `.cloud.`.

> **Later correction (Phase 11).** The probe set above only ever tried the v2 *path* on
> the China host. The Hackathon Guide documents the v2 path on the **international**
> host, which was the combination actually missing. That is the endpoint this project
> runs on today.

**Changes made:**

- `config.py`: `ADP_BASE_URL` default set to the v1 international endpoint (Phase 10), with the
  console/endpoint/schema pairing documented inline. Phase 11 moved it to v2.
- `parser.py`: `_adp_parse` dispatches on the URL to `_adp_v1_parse` or `_adp_v2_parse`,
  so either console is supported by changing one env var.
- `parser.py`: the parser contract moved from `system_role` into `content`. The v1 docs
  say `system_role` "only takes effect in standard mode" and this app replies with
  `reply_method: 18` (Intelligent Agent reply), i.e. agent mode, where it is ignored.
  Measured JSON yield over six prompts: `system_role` 4/6, inline 6/6.
- `parser.py`: filter the v1 user-message echo (`reply_method: 0`,
  `is_llm_generated: false`) before reading the answer.
- `parser.py`: decode v1 events by scanning for complete JSON values, because `thought`
  and `reference` payloads span several physical lines; accept both the `data:{...}` and
  `data:["reply",{...}]` framings.
- `parser.py`: map documented v1 error codes to actionable hints; reject `is_evil`
  (sensitive-content filtered) responses.
- `parser.py`: repair model drift before validation — null balances, half-populated
  Payee/Asset objects, JSON wrapped in prose.
- `parser.py`: make entity identity **registry-authoritative**. The model was inventing
  Payee objects (`id: "***9921"`, `id: "mom_2201"`); it may now only nominate a name, and
  the canonical object from `services/accounts.py` is what reaches the draft.
- `parser.py`: reconcile ambiguities against the final draft, so a clarification is not
  raised for something the backfill already answered.
- `parser.py`: reword a model-authored `payee_disambiguation` that arrived with no
  `options`. The model sometimes writes "Which payee do you mean?" with an empty list;
  the `already_asked` guard then treated the question as answered and skipped it, so the
  user got an unanswerable choice. The registry knows the name is unknown and now says
  so. A model question that already lists candidates is left alone.
- `shield.py`: fix a pre-existing bug. The account-number pattern `\b\d{4,}[-]?\d+\b`
  matched plain 5+ digit **amounts**, so `Transfer $60000 to John Tan` returned `blocked`
  ("Unregistered account number") instead of reaching validation and returning `frozen`.
  Money is now excluded by currency marker, and an account number requires account
  context or a hyphenated form.

**Result:** `USE_MOCK_PARSER=false`, 59/59 tests green, and all seven acceptance cases
pass through nginx on HTTP 200 (`blocked`, `frozen`, `clarify` x3, `draft` x2), verified
over two consecutive warm passes (14/14). Parse latency is 5–9 s, which is the cost of a
real non-streaming model call.

ASR remains the only open blocker.

---

---

## Phase 11 — Hackathon Guide review: off the deprecated v1 endpoint

Reviewed `ADP_Hackathon_Guide_EN.pdf` (AI CAN DO IT Hackathon Singapore 2026, 9 pages).
The guide's API section documents:

```
Endpoint     https://wss.lke.tencentcloud.com/adp/v2/chat
Auth         Send the AppKey with the request. HTTP SSE needs the Appkey alone
```

That is the **v2 path on the international host** — a combination never probed in
Phase 10, which had only tried v2 against the *China* host. Probed it:

```
v2  wss.lke.tencentcloud.com/adp/v2/chat     + AppKey        -> reply event   (accepted)
v1  wss.lke.tencentcloud.com/adp/v2/chat     + bot_app_key   -> no reply       (rejected)
v1  wss.lke.tencentcloud.com/v1/qbot/chat/sse+ bot_app_key   -> reply event    (accepted)
```

The second row also confirms the rule more sharply than Phase 10 could: on the *same*
host, the wrong field name for the path fails. Field names follow the **path**, hosts
follow the **console**.

**Why this matters.** v1 is labelled "Previous Version" upstream and documented to
sunset 2026-12-31. Phase 10 settled on it only because the alternative had been tested
on the wrong host. The guide's endpoint is the supported one, so this removes the
sunset risk outright rather than deferring it.

**Changes:**

- `config.py`: default `ADP_BASE_URL` → `https://wss.lke.tencentcloud.com/adp/v2/chat`.
  The comment now documents all four host/path combinations instead of the incorrect
  two-console claim.
- `parser.py`: v2 docstring notes the endpoint is served on both hosts; v1 docstring
  marks it a fallback.
- `backend/.env`: switched to the v2 international endpoint.
- `.env.example`, `ARCHITECTURE.md`: endpoint tables updated.

Live acceptance on the v2 international endpoint: **7/7**, identical outcomes to v1.
59/59 unit tests pass (they are host-agnostic — they stub `requests.post`).

The v1 path is kept working for the China console and as a fallback. Nothing is lost
by moving.

**Other things the guide settles, all matching what is already implemented:**

- *"HTTP SSE calls need the Appkey alone, while the WebSocket API needs the Appkey
  together with the API Secret."* Confirms CAM credentials have no part in parsing.
- AppKey is the only calling credential, must not be committed or screenshotted. This
  is why the exposed key needs rotating.
- *"Uploaded files are accepted but not used — attach and publish a knowledge base."*
- Experience URL is for humans (judges, demo video); AppKey is for software. The
  Experience URL is not yet recorded in this repo.

**Not adopted:** the guide suggests reusing `ConversationId` across calls for
multi-turn context. This parser deliberately issues a fresh `ConversationId`/`session_id`
per request, so each instruction is parsed without inherited context. For money
instructions, stateless parsing is the safer default.

---

## Phase 12 — Non-transactional input produced a confirmable draft

Found 2026-10-02 by typing ordinary speech instead of transactions. None of the seven
acceptance cases is a greeting, so no test covered this path.

`/intent` had no branch for "the parser found no transaction". After `parse_transcript`
returned, control fell through to the draft response unconditionally:

```
good morning, oh no, hi, hello, thank you, yes, no, what is my balance, cancel
  → type: draft
  → "I've prepared a transaction draft. Please review and confirm with biometrics."
  → intents: []   ambiguities: []   signature: null
```

The confirmable surface was reachable with nothing in it to confirm.

A second failure sat on the same line. ADP answers non-transactional turns with its own
envelope — `{"Type": "request_ack", "rawTranscript": ...}` — which has no `intents` key,
so `Draft(**data)` raised a pydantic `ValidationError` and `main.py` converted it to
**HTTP 500**. `thank you` and `no` were 500s, not drafts. Same root cause, different
symptom, which is why only some greetings looked broken.

**Root cause:** a handbook hard requirement — conversational output may create a draft but
never an executable instruction — had no representation in the code. The response type
union was `draft | clarify | frozen | blocked | error`, with no way to say "no
transaction", so the fallthrough was the only thing left to do.

**Changes:**

| File | Change |
|------|--------|
| `models.py` | added `"chat"` to the `IntentResponse.type` union |
| `main.py` | added `_has_transaction_intent()`; gate runs after the parser, before the shield / ambiguity / validator stages, and returns `type="chat"` with `draft: null` |
| `main.py` | `NO_INTENT_MESSAGE` names what the agent can do (transfers, investments, safety demo, balances) rather than just refusing |
| `services/parser.py` | v1 and v2 ADP paths normalise a no-`intents` envelope to an empty intent list instead of raising |
| `services/parser.py` | heuristic fallback returns an empty list instead of a placeholder `unknown` intent |
| `frontend/components/Chat.tsx` | renders `chat` as plain text, clears any pending draft |
| `frontend/lib/types.ts` | mirrors the union |

`_has_transaction_intent()` treats a lone `unknown` intent as no intent as well, so a
parser that emits that placeholder is caught too.

**Verified live through nginx:** 9/9 non-transaction inputs → `chat`, `draft: null`, no
500. Transactions unaffected: `Transfer $100 to mom` → `draft`; multi-intent → 2 intents;
`Send fifty to John` → `clarify`; injection → `blocked`; relative amount → `clarify`
(the amount is not yet a number, so asking is correct — an earlier version of the test
asserted `draft` here and was wrong).

11 new tests in `backend/tests/test_api.py`. Suite: **73 passed, 1 skipped**.

One thing noticed while writing these tests and not fixed: the safety shield screens the
raw transcript, which is what the handbook asks for, but it runs *after* the parser
(`main.py:144` is the parse, `main.py:162` is the shield). A blocked phrase has therefore
already been sent to ADP. Nothing is confirmed, drafted for execution, or paid on a
blocked turn, so the boundary holds — but "the model never runs" is not literally true.
Moving the shield above the parser is a small change and would also save a 5–9 s round
trip on obvious attacks. Tracked in `STATUS.md`.

---

## Final deployed state

| Service | URL | Status |
|---------|-----|--------|
| nginx | http://localhost:8080 | 200 — **the only supported entry point** |
| frontend | http://localhost:3010 | 200 (bypasses nginx; API calls will 404) |
| backend | http://localhost:8010 | 200 |
| postgres | `127.0.0.1:5433` | healthy (loopback only; 5432 taken by a native install) |

Parser runs on **live ADP** via the international **v2** endpoint
`https://wss.lke.tencentcloud.com/adp/v2/chat` (`USE_MOCK_PARSER=false`), the endpoint
documented in the Hackathon Guide. **73 passed, 1 skipped.** 7/7 acceptance cases verified
through nginx, 14/14 across two passes, plus 9/9 non-transaction inputs returning `chat`.
Parse latency 5–9 s. Voice uses TRTC ASR v3 (`SDKAppID` + UserSig), auth and routing
confirmed; real-speech recognition still unverified. No backend `/health` route exists.

Open issues are listed in `STATUS.md` — the two that matter most are that `/confirm`
does not re-read balances, and that signing is a browser-side placeholder rather than a
secure enclave.
