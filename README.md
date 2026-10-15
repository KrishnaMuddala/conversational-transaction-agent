# DEX Conversational Transaction Agent (DEX DCTA)

A Direct Conversational Transaction Agent built for the Tencent TRTC + ADP hackathon:
turn a spoken or typed banking instruction — *"send 50 to Ravi for dinner"* — into a
validated, biometric-confirmed transaction, with a hash-chained audit trail.

Zero-UI by design: no forms, no menus. One conversation in, one confirmed transaction out.

## How it works

Five layers, each with an explicit gate before money moves:

```
voice/text ──► 1. Intent parser ──► 2. Disambiguator ──► 3. Dual-engine
             (ADP/Hunyuan LLM,      (/intent → ask the    validator (rules
             regex fallback)         user only what's      + LLM cross-check)
                                     genuinely ambiguous)        │
             5. Zero-trust ledger ◄── 4. HITL confirmation       ▼
             (server-side execute,    (biometric gate,            │
             audit-committed)          digest-bound draft) ◄──────┘
```

1. **Intent parsing** — `backend/services/parser.py` extracts payee, amount, and
   purpose via the Tencent ADP (Hunyuan) LLM, with a deterministic regex fallback
   so the demo works without LLM access.
2. **Ambiguity resolution** — per-field confidence; only under-confident fields
   trigger a clarifying question (`/intent`, `/resolve`).
3. **Dual-engine validation** — deterministic business rules (balance, limits,
   payee existence) plus an LLM semantic check (`/confirm` pre-gate).
4. **Human-in-the-loop** — a biometric confirmation gate binds the user's approval
   to the exact transaction digest.
5. **Zero-trust ledger** — execution is server-side only; the client can never
   submit a transaction, only approve a draft. Every state change lands in a
   SHA-256 hash-chained audit log (`GET /audit` verifies the chain).

Prompt-injection shielding sits in front of the parser, and ASR/TTS run over
TRTC so voice works end-to-end.

## Quickstart

```bash
# Backend (FastAPI, port 8010)
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # fill in your Tencent keys
uvicorn main:app --port 8010

# Frontend (Next.js, dev)
cd frontend
npm install
npm run dev                                       # http://localhost:3010

# Tests
cd backend && pytest tests/ -v                    # 59 tests
```

Or run the full stack with Docker:

```bash
cd deploy && docker compose up
# open http://localhost:8080  (nginx fronts frontend + /api → backend)
```

## API surface

| Route | Purpose |
|---|---|
| `POST /intent` | Parse natural language → transaction draft (with confidence) |
| `POST /resolve` | Answer a disambiguation, refine the draft |
| `POST /confirm` | Biometric-gated execution of the draft |
| `POST /asr` / `POST /tts` | Voice in / voice out (TRTC) |
| `POST /demo/{scenario}` | Scripted demo flows |
| `GET /audit` | Hash-chained audit trail (chain-verifiable) |

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — runtime topology, data flow, security model
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — Tencent Cloud (CVM / Terraform) setup
- [README_DEPLOY.md](README_DEPLOY.md) — docker-compose & TKE deployment + honest status of what is and isn't hardened
- [review.md](review.md) — an architecture review against the original requirements, with known gaps
- [STATUS.md](STATUS.md) / [DEPLOYMENT.md](DEPLOYMENT.md) — build-out log and infra decisions

## Known limitations (deliberately unhidden)

This is a hackathon demo, not production banking. Browser-side "biometric"
signing is a toy digest, not a secure enclave; the zero-trust gateway has no
nonce/replay defense; velocity/risk throttling is stubbed. The list is complete,
with fixes ranked by cost, in [README_DEPLOY.md](README_DEPLOY.md) and
[review.md](review.md).

## License

Tencent TRTC + ADP hackathon project. Third-party names and product references
belong to their owners.
