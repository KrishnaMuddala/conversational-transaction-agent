# Design Note — Payee Directory as a Service

> **Status: PROPOSAL, with storage started.** §10 describes the only part that exists —
> `backend/services/payee_store.py` and a seeded 4-row `payees` table. Everything in
> §3–§9 is design discussion and **is not implemented**; no file or route described
> there should be assumed to exist. Current deployed state is in `STATUS.md`; the stack
> as built is in `ARCHITECTURE.md`.

**Author:** review session, 2026-09-30
**Related:** `ARCHITECTURE.md`, `STATUS.md`, `dbs_summary.md`

---

## 1. Problem

Payee, account, and asset data is hardcoded in `backend/services/accounts.py`:

| Symbol | Line | Content |
|--------|------|---------|
| `KNOWN_ACCOUNTS` | 10 | 3 accounts, each with a **static balance** |
| `KNOWN_PAYEES` | 17 | 3 payee groups / 4 payees |
| `KNOWN_ASSETS` | 27 | 4 securities |
| `resolve_payee()` | 41 | returns `{selected, candidates, confidence, name}` |
| `get_account()` | 35 | name → `Account` |

Line numbers are indicative; the symbols are the contract that matters.

This is a prototype limitation, not a design choice. Four payees cannot transact
realistically. The intent is to move the directory into PostgreSQL — which is
already running for the audit log — and expose resolution as an API, so the shape
resembles what a real DBS integration would look like.

> **Partially started.** The table now exists and is seeded — see
> `backend/services/payee_store.py` and §11. Nothing reads it yet; the parser still
> uses `KNOWN_PAYEES`.

### What is already right

`accounts.py` is **not a CRUD store, it is a resolver.** `resolve_payee()` takes a
name string and returns a decision. That distinction should survive the migration
intact, and it is the reason the change is cheap: the *source* of the data moves,
the *contract* does not. Callers in `services/parser.py` and
`services/validator.py` should require little or no modification.

---

## 2. Invariants

These are the parts that must not be traded away. Each exists because something
already went wrong without it.

### 2.1 The model never touches the directory

ADP nominates a **name**. Code returns the **canonical object**. The model never
resolves a payee and never emits an identifier.

This is not theoretical. The model was observed inventing `id: "***9921"` and
`id: "mom_2201"`. `services/parser.py` `_backfill_payee()` exists to overwrite
exactly that class of output. Handing the ADP application a tool that queries the
payee table would create a second resolution path and reopen the hole.

**Consequence:** database access stays strictly server-side. Resolution is a
function call inside the backfill, never a capability granted to the model. This is
also the correct answer to "should payees go in the ADP knowledge base" — a
resolver endpoint is the right tool shape; a vector store is not, because
nearest-neighbour retrieval cannot be trusted to pick between `John Tan` and
`John Lim` on the strength of embedding distance.

### 2.2 Read-only from this backend

No route in this service may create or modify a payee, an account, or an asset.

A payee-creation endpoint reachable from a parsed transcript is a fraud amplifier:
the model proposes a recipient, the system drafts a transfer, and there is no
out-of-band check. In real banking, onboarding a payee requires verification
(OTP, micro-deposit verification, a cooling-off period) that is structurally
outside a conversation. This backend is not where that lives.

Any future write path belongs to a separate authenticated service.

### 2.3 DBS stays authoritative for money movement

The local table is a **read-through cache** of a DBS-sourced directory. It is not
the system of record for payee identity.

If it becomes the system of record, it becomes a shadow of core banking that can
drift. Drift on a payee directory means money sent to the wrong person, and the
plausible explanation after the fact is always "the database said so".

### 2.4 Balances are never snapshotted into a draft

This is the live landmine, and it is called out separately because it is an
*account* problem, not a payee problem.

Today, "move everything left" resolves at **parse time**:

```
parser.py  _backfill_from_registry()  →  intent.amount = sourceAccount.balance - spent
main.py    /confirm                   →  execute_transactions(draft)
executor.py execute_transactions()    →  no balance read anywhere
```

`grep -n balance backend/main.py backend/ledger/executor.py` returns nothing. The
amount is computed once, from a hardcoded `4820.50`, and executed minutes later
without re-verification.

That is currently self-evidently a stub, which is the only reason it is tolerable.
**Moving accounts and balances into a database destroys that safety signal.** A
stale balance in Postgres reads as authoritative. Nobody reviewing a transaction
would flag it.

A relative amount is a promise about a *live* balance. It must be re-derived at
confirm, immediately before execution, not frozen into a draft at parse time. If
the balance moved, the amount must move with it — or the transfer must fail.

**This is the single most important item in this note.** It is a prerequisite, not
a follow-up, and it applies whether or not the payee directory ever gets built.

### 2.5 Resolution is deterministic

Exact-match against the registry, never semantic. Where multiple payees match, the
existing `candidates` + `clarify` behaviour stands and must not be softened into a
best-guess pick.

---

## 3. Proposed API surface

### 3.1 Resolution, not enumeration

Expose a resolution endpoint, not a listing endpoint.

| | Resolution endpoint | Listing endpoint |
|---|---|---|
| Input | a name string | nothing |
| Output | matched candidates | every payee for the customer |
| Enumerable | no | **yes** |
| Use | parser backfill, validator cross-check | admin tooling only, authenticated |

`GET /payees` returning the full directory would be a bulk PII disclosure to every
caller that can reach it. Resolution is also what the code already wants: it maps
1:1 onto `resolve_payee()`.

Response shape should stay compatible with the existing resolver:

```json
{
  "selected":  { "id": "...", "name": "...", "bank": "...", "account": "***9921" },
  "candidates": [ ... ],
  "confidence": 0.95,
  "name": "John Tan"
}
```

### 3.2 Not client-facing

The browser should not call a payee endpoint. The frontend asks the backend, the
backend asks the database. Exposing directory access to the client widens the
attack surface for no benefit — the client already receives whatever the resolved
draft contains.

### 3.3 Authentication is a prerequisite

**There is currently no authentication on any backend route.** `backend/main.py`
contains no `Depends`, no `Security`, and no `Authorization` handling. Every route
is open, including `GET /audit`, which returns the transaction audit log.

That is acceptable for a local prototype. It is not acceptable for a service that
returns a customer's payee directory. **Add auth before exposing the directory** —
in that order. A resolution endpoint behind no auth is a PII disclosure wearing an
API shape.

---

## 4. Proposed schema

Direction only. Field names to be agreed with the DBS integration.

| Concern | Guidance |
|---|---|
| Identity | Store what DBS returns — a payee token or mandate id. **Not** a raw account number. |
| Masking | Mask at the edge. The frontend sees `***9921`; the token never leaves the backend. |
| Naming | `effective_from` / `effective_to` rather than in-place updates, so any resolution is traceable to what the directory said at that moment. |
| Provenance | Record the source system and last sync time per record. |
| Deletion | Soft-delete / revoke, never hard delete. A revoked payee must stop resolving immediately. |

Effective-dating and revocation are not gold-plating. A payee directory that
overwrites in place cannot answer "what did the directory contain when this
transaction was executed", which is exactly the question a dispute asks.

---

## 5. Freshness and caching

A payee read on every request costs ~1 ms against a 5–9 s model round trip, so
caching is a correctness concern rather than a performance one.

- **Payee revocation must invalidate the cache.** A revoked payee resolving as valid
  is a live risk, not a stale-read nuisance.
- The write happens in DBS. This service can only observe it by polling or by
  webhook, so cache entries need a short TTL and/or a version stamp.
- **Balances need their own, much shorter TTL** than payees — see 2.4.

---

## 6. Audit requirements

The hash-chained audit log already exists (`audit/logger.py`: `AuditEventORM:29`,
`AuditLogger:43`, `hash_chain():199`).

Two additions would be needed:

1. **Snapshot the resolved payee record into the turn's audit events** at execution
   time. If the payee record is later edited, the historical transaction must still
   show what was used. Without a snapshot, an edit silently rewrites history for any
   transaction that referenced it.
2. **Record the directory version or sync watermark** alongside the resolution, so a
   dispute can be traced to a specific state of the directory.

Both compose with the existing chain; neither requires changing its structure.

---

## 7. Sequencing

Ordered by dependency, not by convenience.

| Step | Item | Blocking? |
|------|------|-----------|
| 0 | Re-read balance at `/confirm`; re-derive relative amounts there | **Yes — precondition for any balance work** |
| 0 | Add authentication to backend routes | **Yes — precondition for exposing the directory** |
| 1 | Read-only payees only, balances untouched | — |
| 2 | Assets and accounts (non-balance fields) | — |
| 3 | Live balances, with the step-0 re-read in place | — |
| 4 | Sync/revocation mechanism from DBS | — |

Step 0 is listed first deliberately. Both items are preconditions for the parts they
gate, and item 0.1 is a correctness fix that stands on its own regardless of whether
this work happens.

**Payees-only (step 1) avoids the entire balance landmine**, because a stale-balance
transfer is an account problem. That is the smaller and safer first increment, and
it is the one to build first.

---

## 8. Open decisions

Unresolved, and each materially changes the design.

**1. Read-only directory, or read plus a write path behind a separate service?**
Recommendation: read-only from this backend (§2.2). Revisit only when a real payee-onboarding
flow is specified.

**2. Local cache table, or a live call to a DBS customer-profile API per resolution?**
| | Local table | Live DBS call |
|---|---|---|
| Latency | ~1 ms | one network hop per resolution |
| Staleness | possible; needs TTL + revocation | none |
| Shadow-record risk | yes | no |
| Demo without DBS access | yes | no |
| Offline tolerance | yes | no |

The second avoids the cache-invalidation and shadow-record problems outright. The
first is faster and self-contained. This is a real trade-off, not a question with a
correct answer — it depends on whether a DBS sandbox is available.

**3. Are balances in scope, or payees only?**
Recommendation: payees only for the first increment (§7). This defers the riskiest
part of the design.

**4. Where does the model stop and the resolver start?**
Recommendation: unchanged from today — the model nominates a name, nothing more
(§2.1). Worth stating explicitly so it is not eroded by a future "helpful" tool.

**5. Should the ADP application get a payee-lookup tool at all?**
Recommendation: no. The backend resolver already runs inside the request path
(§2.1). If a tool is ever added, it should be a resolution-only tool with the same
contract, and it should never return raw identifiers to the model.

---

## 9. What this does not change

- The four-layer request path in `ARCHITECTURE.md` §2.
- The registry-authoritative design. It gets a different data source, not weaker rules.
- ADP's role as the semantic layer. The model still decides *type*, *amount*,
  *confidence*, and *candidate name* — and still nothing else.
- The knowledge-base split: prose (policies, fee schedules, help articles) belongs in
  ADP knowledge; structured identity belongs in the database.
- The v2 ADP endpoint, now the live one.

---

## 10. What exists so far

Storage only. **No application code reads the table**, and the running parser is
unaffected — verified with the current suite (73 passed, 1 skipped) plus a live `draft`
resolving to `payee_john_tan` from `accounts.py`.

`backend/services/payee_store.py` provides the ORM, an idempotent `--init`, and a
drift guard. Run it with an explicit host URL, because `DATABASE_URL` is written for
the Docker network (`db:5432`) and will not resolve from the laptop:

```
cd backend
venv\Scripts\python.exe -m services.payee_store --init ^
  --database-url postgresql://postgres:postgres@127.0.0.1:5433/dbs_dcta
```

Seeded 4 payees, no balance column — §7 step 1 scope. The table carries
`match_key`, `status`, `effective_from` / `effective_to`, and `source_system` per §4.

The drift guard (`_assert_matches_static_registry`) refuses to seed if the seed data and
`KNOWN_PAYEES` disagree, so the two sources cannot quietly diverge — the shadow-record
risk from §2.3. Note its limit: it compares **the seed against the dict**, not existing
database rows. Running `--init` twice is safe, but a hand-edit of a *row* in the table is
not detected by this guard, and the next `--init` will overwrite it via upsert. Catching
row-level drift needs a separate read-back comparison.

### Host access

| | |
|---|---|
| Host | `127.0.0.1` (or `localhost`) |
| Port | **5433** |
| Database | `dbs_dcta` |
| User / password | `postgres` / `postgres` |
| SSL mode | `disable` — the container has no SSL configured |
| Client | `C:\Program Files\PostgreSQL\18\bin\psql.exe` |

```
psql -h 127.0.0.1 -p 5433 -U postgres -d dbs_dcta
```

`SELECT id, name, bank, account_masked, status FROM payees ORDER BY name;`

**Do not use `db` as the host.** It is the Compose service name, copied from
`backend/.env` and `docker-compose.yml`, and it resolves only inside the compose
network. From a host-laptop client it fails with
`[Errno 11001] getaddrinfo failed` / "No such host is known". Verified on this
machine:

| Host | Resolves from the laptop? | Connects? |
|---|---|---|
| `db` | no | no |
| `OB-OB9300936` (this machine) | yes → 192.168.40.230, Tailscale, Hyper-V | **no** — loopback-only bind refuses them |
| `127.0.0.1` / `localhost` | yes | yes, 4 payees |

**The port is 5433, not 5432.** This laptop already runs a native PostgreSQL 18 on
5432, unrelated to this project, holding `0.0.0.0:5432` with its own credentials.
The Docker database was moved to 5433 to avoid the collision. Do not "fix" this
back to 5432 — it will not bind, and the native install is not ours to touch.

A GUI client that defaults to the `postgres` database will find no `payees` table;
it lives in `dbs_dcta`.

Loopback-only. The backend is unaffected: it reaches the database over the compose
network as `db:5432`. See `STATUS.md` for the exposure that was closed here.

### Still outstanding

Everything in §7 step 0. The table is inert until:

1. `/confirm` re-reads the balance and re-derives relative amounts (§2.4). Still a
   live bug, and now provably *not* addressed by this table, since it has no
   balance column.
2. Backend routes gain authentication, before any directory route is exposed (§3.3).

Switching resolution over from `KNOWN_PAYEES` to this table is deliberately **not**
done here. When it happens, `KNOWN_PAYEES` should be deleted rather than left
alongside, or the two become competing sources of truth.

---

## 11. Summary

The migration is cheap because the code is already a resolver, and the design is
mostly settled by constraints that already exist. Three things carry the risk, and
none of them are the database:

1. **A write path reachable from a parsed transcript** — a fraud amplifier.
2. **A resolution path handed to the model** — reopens the hallucinated-identifier
   class of bug just fixed.
3. **Snapshotted balances** — currently a visible stub, and a silent hazard the
   moment it sits in a database.

Items 1 and 2 are avoided by keeping the existing shape. Item 3 is a bug today,
independent of this work, and should be fixed on its own merits.
