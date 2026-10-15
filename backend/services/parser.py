"""
Intent parser (Layer 2).

Production mode:
  - Calls Tencent Cloud Agent Development Platform (ADP) over HTTP SSE.

Mock / local dev mode:
  - Falls back to a heuristic parser ported from the Gadget prototype.

Set USE_MOCK_PARSER=true in config.py or the environment to use the heuristic.
"""

from __future__ import annotations

import json
import re
from typing import Any

from config import get_settings
from models import Draft, Intent, Ambiguity, Account, Payee, Asset
from services.accounts import (
    get_account,
    resolve_payee,
    resolve_asset,
    resolve_account_destination,
    KNOWN_ACCOUNTS,
    KNOWN_ASSETS,
    KNOWN_PAYEES,
)


# ---------------------------------------------------------------------------
# System prompt for ADP JSON-mode parsing
# ---------------------------------------------------------------------------
PARSER_SYSTEM_PROMPT = """You are the Intent Parser for a Singapore banking conversational transaction agent.
Extract transaction intents from the user's message.

Output strictly valid JSON with this schema:
{
  "intents": [
    {
      "type": "transfer | invest | unknown",
      "confidence": 0.0-1.0,
      "amount": number | null,
      "currency": "SGD",
      "sourceAccount": {"id": string, "type": string, "balance": number, "currency": string} | null,
      "destinationName": string | null,
      "destination": {"id": string, "name": string, "bank": string, "account": string} | {"symbol": string, "name": string} | null,
      "destinationCandidates": [same as destination shape],
      "isRelativeAmount": boolean,
      "note": string
    }
  ],
  "ambiguities": [
    {
      "intentIndex": number,
      "field": "payee_disambiguation | amount_resolution | account_selection",
      "question": string,
      "options": [same as destination shape]
    }
  ]
}

Rules:
- Accounts: savings, current, cpf. Default source is savings.
- Payees: John Tan (***9921), John Lim (***7734), Mary Ong (***1140), Mom (***2201).
- Securities: Apple/AAPL, NVIDIA/NVDA, Tesla/TSLA, DBS/D05.
- Amounts in SGD. "a grand" = 1000, "five hundred" = 500.
- "the rest", "whatever is left", "remaining" mean balance after prior intents.
- Confidence must reflect ambiguity: 0.5 for ambiguous payees, 0.95 when resolved.
- If an amount or payee is missing or ambiguous, add to ambiguities and do not guess.

Output contract (this overrides any other behaviour you have been configured for):
- Reply with a single raw JSON object matching the schema above. Nothing else.
- No prose, no preamble, no explanation, no markdown code fences.
- Never ask the user a question and never offer to do something else. Missing
  details are reported through `ambiguities`, not by replying in prose.
- Never output null inside a nested object. If a nested value is unknown, use
  your best estimate (balance 0, currency "SGD") or omit that nested object.
- Always include "intents" and "ambiguities" keys, even when empty.
- This is a machine-parsed response: a single non-JSON character breaks the caller.
"""


def parse_transcript(raw: str) -> Draft:
    settings = get_settings()
    if settings.USE_MOCK_PARSER:
        return _heuristic_parse(raw)
    return _adp_parse(raw)


# The v1 chat endpoint documented for the international console.
_ADP_V1_MARKER = "/v1/qbot/chat/sse"

# Documented v1 error codes, mapped to something an operator can act on.
_ADP_V1_ERROR_HINTS = {
    400: "malformed request; check the v1 parameter names",
    460001: "token verification failed",
    460004: "application does not exist; the AppKey does not match a published "
            "application on this endpoint's console/region",
    460006: "message does not exist or permissions are insufficient",
    460009: "visitor does not exist; try a different visitor_biz_id",
    460011: "concurrency limit exceeded for this application",
    460032: "insufficient balance on the application's model",
    4505004: "AppKey is invalid; either it was copied from the wrong console's "
             "endpoint, or the application is not published",
}


def _adp_uses_v1(url: str) -> bool:
    return _ADP_V1_MARKER in url


def _adp_parse(raw: str) -> Draft:
    """Production path: Tencent Cloud Agent Development Platform (ADP).

    Dispatches on ADP_BASE_URL because the international and China consoles
    expose different chat generations with incompatible request schemas. See
    config.py for the endpoint/credential pairing.
    """
    settings = get_settings()
    if not settings.ADP_APP_KEY:
        raise RuntimeError(
            "ADP_APP_KEY is not set. Publish an application in the ADP console "
            "(https://adp.tencentcloud.com), then copy its AppKey from the "
            "application's Call dialog into ADP_APP_KEY."
        )

    if _adp_uses_v1(settings.ADP_BASE_URL):
        draft = _adp_v1_parse(raw, settings)
    else:
        draft = _adp_v2_parse(raw, settings)

    _backfill_from_registry(draft, raw)
    return draft


def _adp_v1_parse(raw: str, settings: Any) -> Draft:
    """ADP v1 chat: POST /v1/qbot/chat/sse.

    Fallback only. Upstream labels this generation "Previous Version" and
    documents a 2026-12-31 sunset, so prefer the v2 endpoint in config.py.

    The parser contract is prepended to the transcript in `content` rather than
    sent in `system_role`: the v1 docs state system_role "only takes effect in
    standard mode", and an application replying with `reply_method: 18`
    (Intelligent Agent reply) is in agent mode, where it is ignored. Measured
    against this application, `content` yielded JSON on 6/6 prompts and
    `system_role` on 4/6.

    Web search is disabled: parsing a transaction never needs it and it adds
    latency and cost.
    """
    try:
        import uuid

        import requests

        payload: dict[str, Any] = {
            "request_id": uuid.uuid4().hex,
            "session_id": uuid.uuid4().hex,
            "bot_app_key": settings.ADP_APP_KEY,
            "visitor_biz_id": settings.ADP_VISITOR_ID,
            "content": f"{PARSER_SYSTEM_PROMPT}\n\nUser message:\n{raw}",
            "incremental": False,
            "stream": "disable",
            "streaming_throttle": 10,
            "search_network": "disable",
            "visitor_labels": [],
            "custom_variables": {},
        }

        resp = requests.post(
            settings.ADP_BASE_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=settings.ADP_TIMEOUT_SECONDS,
        )
        if not resp.ok:
            detail = resp.content.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ADP HTTP {resp.status_code}: {detail}")

        # ADP answers with text/event-stream, for which requests defaults to
        # ISO-8859-1. Decode explicitly or any non-ASCII answer is corrupted.
        body = resp.content.decode("utf-8", errors="replace")

        text = _adp_v1_answer(body)
        if not text:
            raise RuntimeError(f"ADP returned no answer text. Body: {body[:500]}")

        data = _adp_parse_answer(text, raw)
        if not isinstance(data, dict) or "intents" not in data:
            # See the v2 path: a conversational ADP envelope carries no
            # "intents" key, so normalise rather than fail the turn.
            return Draft(rawTranscript=raw, intents=[], ambiguities=[], signature=None)
        return Draft(**data)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ADP parser failed: {e}")


def _adp_v1_events(body: str) -> list[dict]:
    """Decode a v1 chat body into its event objects.

    Scans for complete JSON values rather than trusting SSE line framing: v1
    writes `thought` and `reference` payloads that span several physical lines,
    so a line-oriented reader truncates or rejects them. Framing is also
    inconsistent between the documented `data:{...}` and `data:["reply",{...}]`
    forms, and the wrapper is irrelevant here because the inner object carries
    `type`.
    """
    decoder = json.JSONDecoder()
    events: list[dict] = []
    index = 0
    while index < len(body):
        start = body.find("{", index)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(body, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = end
        if isinstance(value, list):
            events.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            events.append(value)
    return events


def _adp_v1_answer(body: str) -> str:
    """Extract the agent's answer from a v1 chat body, or raise on an error.

    v1 emits the user's own message back as a `reply` event with
    `reply_method: 0` and `is_llm_generated: false` before the real answer.
    That echo must be skipped or it gets parsed as the model's output.
    """
    answer: str | None = None

    for event in _adp_v1_events(body):
        kind = event.get("type")

        if kind == "error":
            error = event.get("error") or {}
            code = error.get("code")
            hint = _ADP_V1_ERROR_HINTS.get(code, "")
            raise RuntimeError(
                f"ADP rejected the request: code={code} "
                f"message={error.get('message')!r} {hint}".rstrip()
            )

        if kind != "reply":
            continue

        payload = event.get("payload") or {}

        if payload.get("is_evil"):
            raise RuntimeError(
                "ADP blocked the request: the message was rejected by sensitive "
                "content filtering (is_evil=true)."
            )

        if not payload.get("is_llm_generated"):
            continue

        content = payload.get("content")
        if isinstance(content, str) and content:
            # `incremental: false` means each reply event carries the full
            # answer so far, so the last one wins. Joining would duplicate.
            answer = content

    return answer or ""


def _adp_v2_parse(raw: str, settings: Any) -> Draft:
    """ADP v2 chat: POST /adp/v2/chat.

    This is the endpoint documented in the AI CAN DO IT Hackathon Guide and the
    one this project now uses. It is served on the international host
    (wss.lke.tencentcloud.com) and the China host (wss.lke.cloud.tencent.com);
    the field names below are the same for both.

    The model and base system prompt are configured on the published application
    in the ADP console; the parser contract is pinned here by prepending
    PARSER_SYSTEM_PROMPT to the transcript.

    Streaming is disabled so ADP returns one complete answer, which is then
    validated into the Draft model.
    """
    try:
        import uuid

        import requests

        payload: dict[str, Any] = {
            "RequestId": uuid.uuid4().hex,
            "ConversationId": uuid.uuid4().hex,
            "AppKey": settings.ADP_APP_KEY,
            "VisitorId": settings.ADP_VISITOR_ID,
            "Contents": [
                {
                    "Type": "text",
                    "Text": f"{PARSER_SYSTEM_PROMPT}\n\nUser message:\n{raw}",
                }
            ],
            "Incremental": True,
            "EnableMultiIntent": True,
            "Stream": "disable",
        }

        resp = requests.post(
            settings.ADP_BASE_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=settings.ADP_TIMEOUT_SECONDS,
        )
        if not resp.ok:
            detail = resp.content.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ADP HTTP {resp.status_code}: {detail}")

        # ADP answers with text/event-stream, for which requests defaults to
        # ISO-8859-1. Decode explicitly or any non-ASCII answer is corrupted.
        body = resp.content.decode("utf-8", errors="replace")

        stream_error = _adp_stream_error(body)
        if stream_error:
            raise RuntimeError(f"ADP rejected the request: {stream_error}")

        text = _adp_reply_text(body)
        if not text:
            raise RuntimeError(f"ADP returned no answer text. Body: {body[:500]}")

        data = _adp_parse_answer(text, raw)
        if not isinstance(data, dict) or "intents" not in data:
            # ADP answers non-transactional turns (greetings, refusals, "thank
            # you") with its own conversational envelope, e.g.
            # {"Type": "request_ack", "rawTranscript": ...}. That has no
            # "intents" key, so Draft(**data) raised a validation error and the
            # turn surfaced as HTTP 500. Such turns carry no transaction, so
            # normalise them to an empty intent list and let the caller route
            # them to the no-intent path.
            return Draft(rawTranscript=raw, intents=[], ambiguities=[], signature=None)
        return Draft(**data)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ADP parser failed: {e}")


def _adp_parse_answer(text: str, raw: str) -> dict:
    """Turn an ADP answer into a Draft payload, tolerating common model drift.

    The application is a customer-facing banking agent, so it sometimes answers
    conversationally instead of emitting the contract. That is recoverable, so
    try to pull JSON out of the prose before giving up.
    """
    try:
        data = _loads_json_object(text)
    except ValueError:  # json.JSONDecodeError is a ValueError subclass
        salvaged = _loads_json_object_salvage(text)
        if salvaged is None:
            raise
        data = salvaged

    _normalize_draft_payload(data)
    # The prompt does not ask ADP to echo the transcript, so supply the
    # authoritative value here rather than trusting the model to repeat it.
    data.setdefault("rawTranscript", raw)
    return data


def _loads_json_object_salvage(text: str) -> dict | None:
    """Best-effort JSON recovery from a conversational answer.

    A banking agent asked to return JSON often wraps the object in a sentence,
    or emits a truncated document. Returns None when nothing usable is present.
    """
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(text)):
                char = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == opener:
                    depth += 1
                elif char == closer:
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:index + 1]
                        try:
                            value = json.loads(candidate)
                        except json.JSONDecodeError:
                            break
                        if isinstance(value, dict) and "intents" in value:
                            return value
                        break
            start = text.find(opener, start + 1)
    return None


def _normalize_draft_payload(data: dict) -> None:
    """Repair nested nulls and half-populated objects before validation.

    The model intermittently emits `"sourceAccount": {"balance": null}`, which
    fails Account's non-nullable balance, and emits Payee/Asset fragments that
    lack required keys. Fix those in place rather than failing the turn: a
    missing balance is a display detail, not a reason to reject the draft.
    """
    intents = data.get("intents")
    if not isinstance(intents, list):
        return

    for intent in intents:
        if not isinstance(intent, dict):
            continue

        account = intent.get("sourceAccount")
        if isinstance(account, dict):
            if account.get("balance") is None:
                account["balance"] = 0.0
            if account.get("currency") is None:
                account["currency"] = "SGD"
            if not account.get("id") or not account.get("type"):
                intent["sourceAccount"] = None

        intent["destination"] = _coerce_entity(intent.get("destination"))
        candidates = intent.get("destinationCandidates")
        if isinstance(candidates, list):
            intent["destinationCandidates"] = [
                entity for entity in (_coerce_entity(c) for c in candidates) if entity
            ]


def _coerce_entity(value: Any) -> Any:
    """Return a Payee/Asset-shaped dict, or None if it cannot be completed.

    Accepts either {"symbol", "name"} (Asset) or
    {"id", "name", "bank", "account"} (Payee).
    """
    if not isinstance(value, dict):
        return None
    if value.get("symbol") and value.get("name"):
        return {"symbol": value["symbol"], "name": value["name"]}
    if all(value.get(key) for key in ("id", "name", "bank", "account")):
        return {key: value[key] for key in ("id", "name", "bank", "account")}
    return None


_RELATIVE_RE = re.compile(
    r"\b(the rest|rest of|remaining|all of it"
    r"|whatever(?:'s| is)? left|what(?:'s| is) left"
    r"|everything left|all that's left|all that is left)\b"
)


def _backfill_from_registry(draft: Draft, raw: str) -> None:
    """Fill in the canonical entities and balances ADP left unresolved.

    ADP is the semantic layer: it decides intent type, amount, confidence and
    ambiguity. The account registry stays authoritative for ids, live balances
    and payee/asset resolution, so validation and the UI never depend on the
    model echoing a balance or inventing a payee id.
    """
    lower = raw.lower()
    is_relative = bool(_RELATIVE_RE.search(lower))
    by_id = {account.id: account for account in KNOWN_ACCOUNTS.values()}

    for index, intent in enumerate(draft.intents):
        # Source account: keep the model's account choice, take the real balance.
        if intent.sourceAccount and intent.sourceAccount.id in by_id:
            intent.sourceAccount = by_id[intent.sourceAccount.id]
        else:
            intent.sourceAccount = get_account(_extract_source_name(lower))

        if intent.type == "invest":
            _backfill_asset(intent, lower)
        elif intent.type == "transfer":
            _backfill_payee(intent, index, draft)

        if is_relative:
            intent.isRelativeAmount = True
            if intent.amount is None and intent.sourceAccount is not None:
                spent = sum(
                    (other.amount or 0.0)
                    for other in draft.intents[:index]
                    if other.sourceAccount is not None
                    and other.sourceAccount.id == intent.sourceAccount.id
                )
                intent.amount = round(intent.sourceAccount.balance - spent, 2)

        # Format the display string for any resolved amount. ADP returns a bare
        # number and no amountDisplay, so without this the draft card renders
        # an em-dash next to the amount while the total line — which is computed
        # from the numeric value — shows the real figure. The backfill is the one
        # place every intent passes through, so derive it here rather than
        # trusting the model or each parser path to remember.
        if intent.amount is not None and not intent.amountDisplay:
            intent.amountDisplay = _format_currency(intent.amount)

    _reconcile_ambiguities(draft)


def _reconcile_ambiguities(draft: Draft) -> None:
    """Drop clarification requests the deterministic layer has since answered.

    ADP flags gaps before the registry backfill runs, so a question about an
    amount or payee can survive even though the amount or payee is now known.
    Asking the user something the draft already answers is worse than silence,
    because it blocks confirmation for no reason.
    """
    kept: list[Ambiguity] = []
    for ambiguity in draft.ambiguities:
        if not 0 <= ambiguity.intentIndex < len(draft.intents):
            continue
        intent = draft.intents[ambiguity.intentIndex]
        if ambiguity.field == "amount_resolution" and intent.amount is not None:
            continue
        if ambiguity.field == "payee_disambiguation" and intent.destination is not None:
            continue
        kept.append(ambiguity)
    draft.ambiguities = kept


def _exact_payee(name: str | None) -> Payee | None:
    """Match a full payee name against the registry, ignoring case."""
    if not name:
        return None
    target = name.strip().lower()
    for payees in KNOWN_PAYEES.values():
        for payee in payees:
            if payee.name.lower() == target:
                return payee
    return None


def _exact_asset(name: str | None) -> Asset | None:
    """Match an instrument by company name or ticker against the registry."""
    if not name:
        return None
    target = name.strip().lower()
    for asset in KNOWN_ASSETS.values():
        if asset.name.lower() == target or asset.symbol.lower() == target:
            return asset
    return None


def _backfill_asset(intent: Intent, lower_raw: str) -> None:
    """Resolve an invest intent's instrument against the asset registry.

    The registry is the only source of instrument identity: the model routinely
    invents plausible-looking assets, so anything it supplies is discarded in
    favour of the canonical object.
    """
    candidates = [intent.destinationName]
    if intent.destination is not None:
        candidates.extend([intent.destination.name, intent.destination.symbol])

    asset = next((a for a in (_exact_asset(name) for name in candidates) if a), None)

    if asset is None:
        # destinationName may hold a company name or a ticker, so try both keys.
        found = resolve_asset(intent.destinationName, intent.destinationName)
        if not found["selected"]:
            for known in KNOWN_ASSETS.values():
                if known.name.lower() in lower_raw or known.symbol.lower() in lower_raw:
                    found = {
                        "selected": known,
                        "candidates": [known],
                        "confidence": 0.95,
                        "name": known.name,
                    }
                    break
        if not found["selected"]:
            # Unverifiable instrument: do not trust the model's object.
            intent.destination = None
            return
        asset = found["selected"]
        intent.confidence = max(intent.confidence, found["confidence"])

    intent.destination = asset
    intent.destinationCandidates = [asset]
    intent.destinationName = asset.name


def _backfill_payee(intent: Intent, index: int, draft: Draft) -> None:
    """Resolve a transfer intent's payee, and surface an unresolved one.

    Identities always come from the registry. A model-supplied Payee is only a
    hint about the name; the object that ends up in the draft is the canonical
    one, so payee ids reaching confirmation and execution are real.
    """
    names = [intent.destinationName]
    if intent.destination is not None:
        names.append(intent.destination.name)

    payee = next((p for p in (_exact_payee(name) for name in names) if p), None)
    if payee is not None:
        intent.destination = payee
        intent.destinationCandidates = [payee]
        intent.destinationName = payee.name
        intent.confidence = max(intent.confidence, 0.95)
        return

    found = resolve_payee(intent.destinationName)
    if not found["selected"] and intent.destinationName:
        # "John Tan" must fall back to the "john" key to surface both candidates.
        first_word = intent.destinationName.split()[0]
        if first_word.lower() != intent.destinationName.lower():
            found = resolve_payee(first_word)

    intent.destination = None  # unverified identity is never trusted

    if found["selected"]:
        intent.destination = found["selected"]
        intent.destinationName = found["name"] or intent.destinationName
        intent.destinationCandidates = found["candidates"]
        intent.confidence = max(intent.confidence, found["confidence"])
        return

    for ambiguity in draft.ambiguities:
        if ambiguity.intentIndex != index or ambiguity.field != "payee_disambiguation":
            continue
        if not ambiguity.options and not found["candidates"]:
            # The model already asked about this payee, but with nothing to pick
            # from. "Which payee do you mean?" over an empty list is a dead end,
            # so word it with what the registry actually knows.
            ambiguity.question = _unknown_payee_question(intent.destinationName)
        return

    if found["candidates"]:
        # Several known payees match and none was chosen.
        intent.destinationCandidates = found["candidates"]
        draft.ambiguities.append(Ambiguity(
            intentIndex=index,
            field="payee_disambiguation",
            question=f'Which payee did you mean by "{intent.destinationName}"?',
            options=found["candidates"],
        ))
        return

    # Unknown payee. A transfer cannot proceed without a verified recipient, so
    # ask rather than leaving a destination-less draft that goes nowhere.
    draft.ambiguities.append(Ambiguity(
        intentIndex=index,
        field="payee_disambiguation",
        question=_unknown_payee_question(intent.destinationName),
        options=[],
    ))


def _unknown_payee_question(name: str | None) -> str:
    label = (name or "that recipient").strip() or "that recipient"
    return (
        f'"{label}" is not among your saved payees. '
        f"Who would you like to send the money to?"
    )


def _adp_events(body: str) -> list[tuple[Any, str]]:
    """Decode an ADP chat body into (event, raw) pairs.

    The endpoint is documented as SSE, so `data:` lines are the normal framing;
    a single JSON object body is also accepted. A `data:` line that is not JSON
    is kept as a plain-text delta.
    """
    events: list[tuple[Any, str]] = []

    if body.lstrip().startswith("{"):
        try:
            events.append((json.loads(body), body))
            return events
        except json.JSONDecodeError:
            pass

    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            break
        try:
            events.append((json.loads(data), data))
        except json.JSONDecodeError:
            events.append((data, data))

    return events


def _adp_stream_error(body: str) -> str | None:
    """Return a readable description if the stream is an ADP error event."""
    for event, _ in _adp_events(body):
        if isinstance(event, dict) and event.get("Type") == "error":
            error = event.get("Error") or {}
            return (
                f"code={error.get('Code')} message={error.get('Message')} "
                f"trace={error.get('TraceId')}"
            )
    return None


def _adp_reply_text(body: str) -> str:
    """Extract the assistant answer from an ADP chat response body.

    Reply-event field names differ between application types, so probe the
    known shapes instead of hard-coding one.
    """
    events = _adp_events(body)
    chunks = [t for t in (_adp_event_text(event) for event, _ in events) if t]

    if chunks:
        return "".join(chunks)

    # ADP replied with structured JSON that carries no recognised answer field,
    # which means the application is emitting the Draft document directly.
    for _, raw in events:
        return raw
    return ""


def _adp_event_text(event: Any) -> str | None:
    if isinstance(event, str):
        return event or None
    if not isinstance(event, dict):
        return None

    messages = (event.get("Response") or {}).get("Messages") or []
    for message in messages:
        for content in message.get("Contents") or []:
            if content.get("Type", "text") == "text" and content.get("Text"):
                return content["Text"]

    for key in ("Text", "Content", "Answer", "Reply", "Message", "Result",
                "text", "content", "answer", "reply", "message", "result"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value

    return None


def _loads_json_object(text: str) -> dict:
    """Pull the JSON document out of an ADP answer, tolerating prose and fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"No JSON object found in ADP answer: {text[:300]}")
    return json.loads(cleaned[start:end + 1])


# ---------------------------------------------------------------------------
# Heuristic fallback parser (mirrors the Gadget prototype)
# ---------------------------------------------------------------------------
def _heuristic_parse(raw: str) -> Draft:
    lower = raw.lower()
    clauses = [c.strip() for c in re.split(r",\s*|\s+and\s+", raw, flags=re.IGNORECASE) if c.strip()]
    intents: list[Intent] = []

    for clause in clauses:
        clause_lower = clause.lower()

        transfer_keywords = ["transfer", "send", "pay", "wire"]
        if any(k in clause_lower for k in transfer_keywords):
            amount = _extract_amount(clause_lower, clause)
            source_account = get_account(_extract_source_name(clause_lower))
            dest_resolution = _extract_transfer_destination(clause_lower, clause)

            intents.append(Intent(
                type="transfer",
                confidence=round(amount["confidence"] * dest_resolution["confidence"], 4),
                amount=amount["value"],
                amountDisplay=amount["display"],
                currency="SGD",
                sourceAccount=source_account,
                destinationName=dest_resolution["name"],
                destination=dest_resolution["selected"],
                destinationCandidates=dest_resolution["candidates"],
                note="",
            ))
            continue

        if "invest" in clause_lower or "buy" in clause_lower or "shares" in clause_lower:
            amount = _extract_amount(clause_lower, clause)
            asset = resolve_asset(clause_lower)
            source_account = get_account(_extract_source_name(clause_lower))
            is_relative = bool(_RELATIVE_RE.search(clause_lower))
            amount_value = (_resolve_relative_amount(source_account, intents)
                            if is_relative
                            else (amount["value"] or _resolve_relative_amount(source_account, intents)))
            amount_confidence = 0.92 if is_relative else amount["confidence"]

            intents.append(Intent(
                type="invest",
                confidence=round(amount_confidence * asset["confidence"], 4),
                amount=amount_value,
                amountDisplay=_format_currency(amount_value) if amount_value is not None else None,
                currency="SGD",
                sourceAccount=source_account,
                destinationName=asset["name"],
                destination=asset["selected"],
                destinationCandidates=asset["candidates"],
                isRelativeAmount=is_relative,
                note="",
            ))
            continue

    # No transaction was recognised. Return an empty list rather than a
    # placeholder "unknown" intent: main._has_transaction_intent treats an
    # "unknown"-only draft as no intent, and an empty list keeps the Draft
    # honest about there being nothing to confirm.
    if not intents:
        return Draft(rawTranscript=raw, intents=[], ambiguities=[], signature=None)

    ambiguities = _collect_ambiguities(intents, raw)
    return Draft(rawTranscript=raw, intents=intents, ambiguities=ambiguities, signature=None)


def _extract_amount(lower_raw: str, raw_original: str) -> dict:
    if "a grand" in lower_raw:
        return {"value": 1000.0, "display": "$1,000", "confidence": 0.95}
    if re.search(r"\bgrand\b", lower_raw):
        return {"value": 1000.0, "display": "$1,000", "confidence": 0.85}
    if "a hundred" in lower_raw:
        return {"value": 100.0, "display": "$100", "confidence": 0.95}
    if "five hundred" in lower_raw:
        return {"value": 500.0, "display": "$500", "confidence": 0.95}

    digits = re.search(r"\$?(\d[\d,]*(?:\.\d{1,2})?)\s*(?:dollars?|sgd|bucks)?", raw_original)
    if digits:
        val = float(digits.group(1).replace(",", ""))
        return {"value": val, "display": f"${val:,.2f}", "confidence": 0.95}

    written = _parse_written_number(lower_raw)
    if written is not None:
        return {"value": float(written), "display": f"${written:,.2f}", "confidence": 0.75}

    return {"value": None, "display": "unspecified", "confidence": 0.3}


def _parse_written_number(text: str) -> int | None:
    units = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
    teens = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
             "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
    tens = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
    scales = {"hundred": 100, "thousand": 1000, "million": 1000000}

    total = 0
    current = 0
    for token in text.split():
        t = re.sub(r"[^a-z]", "", token.lower())
        if t in units:
            current += units[t]
        elif t in teens:
            current += teens[t]
        elif t in tens:
            current += tens[t]
        elif t in scales:
            current = (current if current else 1) * scales[t]
            if t in ("thousand", "million"):
                total += current
                current = 0
    result = total + current
    return result if result > 0 else None


def _extract_payee_name(raw_original: str) -> str | None:
    patterns = [
        r"(?:to|for)\s+([a-z]+)(?:\s|$|\,)",
        r"send\s+(?:\S+\s+)?(?:to\s+)?([a-z]+)",
        r"pay\s+([a-z]+)",
    ]
    for p in patterns:
        m = re.search(p, raw_original, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_source_name(lower_raw: str) -> str | None:
    for name in KNOWN_ACCOUNTS:
        if name in lower_raw:
            return name
    return None


def _extract_transfer_destination(lower_raw: str, raw_original: str) -> dict:
    to_match = re.search(r"\b(?:to|into)\s+([a-z]+(?:\s+(?:account|acc))?)", raw_original, re.IGNORECASE)
    dest_name = to_match.group(1).strip() if to_match else _extract_payee_name(raw_original)

    account_dest = resolve_account_destination(dest_name)
    if account_dest["selected"]:
        return account_dest

    return resolve_payee(dest_name)


def _resolve_relative_amount(source_account: Account, prior_intents: list[Intent]) -> float | None:
    committed = sum(
        (i.amount or 0) for i in prior_intents
        if (i.sourceAccount or Account(id="", type="", balance=0)).id == source_account.id
    )
    return source_account.balance - committed


def _collect_ambiguities(intents: list[Intent], raw: str) -> list[Ambiguity]:
    ambiguities: list[Ambiguity] = []
    for i, intent in enumerate(intents):
        if intent.type == "transfer" and intent.destinationCandidates and len(intent.destinationCandidates) > 1 and not intent.destination:
            candidates = intent.destinationCandidates
            ambiguities.append(Ambiguity(
                intentIndex=i,
                field="payee_disambiguation",
                question=f'Which "{intent.destinationName}" did you mean?',
                options=candidates,
            ))
        if intent.type == "transfer" and intent.amount is None and intent.confidence < 0.5:
            ambiguities.append(Ambiguity(
                intentIndex=i,
                field="amount_resolution",
                question="How much would you like to send?",
                options=[],
            ))
        if intent.type == "invest" and intent.amount is None:
            ambiguities.append(Ambiguity(
                intentIndex=i,
                field="amount_resolution",
                question="How much would you like to invest?",
                options=[],
            ))
    return ambiguities


def _format_currency(n: float) -> str:
    return f"${n:,.2f}"
