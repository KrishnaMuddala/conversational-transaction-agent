# Code Review & Architecture Validation — DCTA vs. dbs_summary.md

**Repo:** `dcta_tentcent` | **Date:** 2026-10-02 | **Basis:** `dbs_summary.md` requirements vs. actual code (backend, frontend, deploy) | **Tests:** 73 passed, 1 skipped (`backend/tests`, pytest)

## Verdict

The repo is a faithful, well-structured implementation of the 5-layer architecture in `dbs_summary.md` — roughly **80–85% aligned**. All seven required capabilities exist in some form. The gaps concentrate in velocity throttling, the real cryptographic strength of the zero-trust boundary, and Scenario 2.

## Requirement-by-requirement alignment

### 1. Zero-UI multi-intent transaction parsing — IMPLEMENTED
- `backend/services/parser.py` (~900 lines) extracts transfer/invest intents into structured JSON drafts (`backend/models.py`).
- ADP/Hunyuan LLM path plus deterministic regex fallback (colloquial amounts, relative amounts like "whatever is left").

### 2. Dynamic ambiguity resolution — IMPLEMENTED
- `/intent` returns `clarify` responses with disambiguation cards (payee lookup in `services/accounts.py`); `/resolve` re-processes with the user's choices.
- Per-intent `confidence` gates below-threshold prompts.
- **Caveat:** dbs_summary.md asks for *per-field* confidence; code has per-intent confidence only.

### 3. Dual-engine semantic validation — IMPLEMENTED, with a caveat
- `services/validator.py` freezes drafts on discrepancy (`VALIDATION_FREEZE`).
- Default engine is the rule-based re-extractor (`_rule_validate`); the independent second-LLM cross-check (`_adp_validate`) runs only when `use_hunyuan=True`.
- The summary calls the dual-engine "the most critical safety layer" — running one deterministic re-check instead of a truly independent LLM second opinion is weaker than spec (documented as a deliberate prod-vs-rule tradeoff).

### 4. Deterministic HITL biometric authorization — SIMULATED ONLY (biggest gap vs. the "Key Risk to Watch")
- `BiometricOverlay.tsx` is a deterministic confirmation overlay, but signing is `toySign()` — a JS digest in `Chat.tsx`, running in page context, **not** a device secure enclave or WebAuthn.
- Backend (`services/crypto.py`) supports Tencent KMS and RSA/PEM verification, so the boundary is real when configured; in the demo path it is cryptographically meaningless.
- dbs_summary.md's explicit warning — "signature must originate from the device's secure enclave, not any server-side component the LLM can influence" — is the one requirement not even structurally honored: same-process FastAPI host runs both the agent and the gateway, so the zero-trust split is logical, not deployment-enforced.

### 5. Zero-Trust API gateway — ARCHITECTURALLY CORRECT
- Verified: `ledger/executor.py` is imported only by `/confirm`, after `verify_biometric_signature` returns ok; the conversational path (`/intent`, `/resolve`) has no ledger access and no payment credentials until execution.
- Signature TTL (60 s) enforced.
- **Weakness:** no nonce/replay defense — a captured envelope is replayable within the TTL window.

### 5a. Non-transactional input could reach the confirmable surface — FIXED 2026-10-02
This was not in the original review because it only appears when you type something that is *not* a transaction, which no acceptance case does.

`/intent` had no branch for "the parser found nothing". Control fell through to the draft response unconditionally, so `good morning` returned a draft telling the user to "review and confirm with biometrics" — with an empty intent list and no signature. Separately, ADP answers greetings and refusals with its own `{"Type": "request_ack"}` envelope, which has no `intents` key, so `Draft(**data)` raised and `thank you` was an HTTP 500.

This is the same class of defect as the zero-trust boundary itself: a hard requirement (conversational output may never become an executable instruction) was not enforced in code, and the type union had no way to express the correct outcome. Fixed with a `chat` response type and a no-intent gate placed before the shield, ambiguity and validator stages. 9/9 non-transaction inputs now return `chat` with `draft: null`; transactions are unaffected.

**Ordering note:** the shield screens the raw transcript, which is right, but it runs *after* `parse_transcript` (`main.py:144` vs `main.py:162`). A blocked phrase has already reached ADP. Nothing is confirmed or paid, so the boundary holds, but "the model never runs" is not literally true.

### 6. Adversarial prompt shielding — IMPLEMENTED, naive
- `shield.py` blocks a substring blocklist ("ignore previous instructions", etc.) plus unregistered account numbers; parser isolates user text behind system-prompt delimiters.
- Blocks the exact demo injection, but paraphrases ("disregard what you were told before") would evade the literal matcher. No semantic/embedding classifier.

### 7. Dynamic risk & velocity throttling — LARGELY MISSING
- `HIGH_VALUE_THRESHOLD` ($50k) exists and freezes high-value transfers.
- **No** rate/velocity counter for "small frequent transfers" anywhere in the code.
- **No** real out-of-band secondary confirmation channel — high-value is a hard freeze whose message promises an OOB step that doesn't exist.

### 8. Fully traceable audit ledger — MOSTLY IMPLEMENTED
- `audit/logger.py`: SHA-256 hash-chained events (RAW_INPUT, PARSE_RESULT, VALIDATION, GATEWAY_ACCEPT/REJECT, EXECUTION_COMPLETE) to Postgres/TDSQL with memory fallback; `/audit` exposes the trail with per-turn fingerprint.
- **Gap:** `archive_audio_to_cos()` is defined but never called — raw voice audio is not actually archived, contradicting "raw audio... stored for audit."

### 9. Scenarios
- **Scenario 1:** covered (voice via `/asr` + payment API, mock or real). **KYC integration absent.**
  - Caveat: TRTC ASR auth and routing are confirmed, but only a synthetic non-speech WAV
    has been transcribed. Recognition quality is unverified.
- **Scenario 2:** (voice digital services, e.g. food ordering) **not implemented.**

### 10. Demo differentiators
- `/demo/{prompt_injection|hallucination|large_transfer_velocity}` endpoints exist and are wired to frontend buttons.
- End-to-end latency (<5 s target) is not instrumented.

## Summary of gaps, ranked

1. Signing happens in browser JS (toy HMAC), not a secure enclave/WebAuthn — the core zero-trust claim is simulated; LLM + gateway share one process with no deployment isolation.
2. No velocity throttling and no real out-of-band confirmation path (requirement 7).
3. Second-LLM validation is optional, not the default dual-engine.
4. Audio never reaches COS — `archive_audio_to_cos` is dead code.
5. Scenario 2 missing; KYC missing.
6. Injection shield is literal-pattern, not semantic.
7. Replay window: TTL without nonce.
8. `/confirm` does not re-read balances, so a relative amount executes from a stale number.
9. Credentials exposed during development (ADP AppKey, TRTC SDKSecretKey, CAM key pair) — all need rotating.
10. No authentication on any route; `/audit` is open.

Gaps 1–4 and 8 are code changes. Gap 9 is a console action. Gap 10 is a prerequisite for
exposing anything beyond localhost.

## Limitations worth stating honestly (not bugs)

- The rule-based validator's amount re-extraction shares `_extract_amount` with the parser — they cannot disagree on amounts the parser's own function produced, so the "independent audit" for amounts mainly catches LLM-path drift.
- Overlay shows the aggregate total, not per-intent detail in the signing surface; the summary asks for "exact transaction details."
- Payment executor's invest path has no real API-call branch (mock-only); reference IDs are time-derived, not ledger-assigned.

## Overall

Structure, layering, and safety-flow match the architecture document and 73 tests pass. The honest weak points are **crypto-boundary realism (#1)** and **velocity controls (#2)**. Cheapest fixes: wire `archive_audio_to_cos` into the ASR path and add a nonce store to the gateway.

The 2026-10-02 chitchat bug (§5a) is worth noting for what it says about coverage: every
acceptance case is a transaction or an attack, so a whole response type went missing
without any test failing. Greetings, refusals and acknowledgements are the cheapest
adversarial input available, and they found a real fail-open. Worth keeping that test
group.
