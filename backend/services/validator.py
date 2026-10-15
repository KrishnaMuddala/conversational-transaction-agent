"""
Independent Validation Agent (Layer 3).
Re-derives fields from the raw transcript and freezes on discrepancies.

Production:
  - Use a second ADP application (independent prompt) for cross-checking in
    high-assurance environments, OR
  - Use the rule-based validator below as a safety net.
"""

from __future__ import annotations

import re
from typing import Any

from config import get_settings
from models import Draft, Intent
from services.accounts import resolve_payee
from services.parser import _extract_amount


def validate_parse(raw: str, draft: Draft, use_hunyuan: bool = False) -> dict[str, Any]:
    if use_hunyuan:
        return _adp_validate(raw, draft)
    return _rule_validate(raw, draft)


def _rule_validate(raw: str, draft: Draft) -> dict[str, Any]:
    lower = raw.lower()
    issues: list[str] = []
    settings = get_settings()

    for i, intent in enumerate(draft.intents):
        # Independent amount re-extraction (skip relative-amount intents).
        if not intent.isRelativeAmount:
            re_extracted = _extract_amount(lower, lower)["value"]
            if intent.type == "transfer" and intent.amount is not None and re_extracted is not None:
                if abs(intent.amount - re_extracted) > 0.01:
                    issues.append(
                        f"Intent {i + 1}: amount mismatch (parser={intent.amount}, validator={re_extracted})."
                    )

        # Ambiguous payee safety net.
        if intent.type == "transfer" and intent.destinationName:
            resolved = resolve_payee(intent.destinationName)
            if len(resolved["candidates"]) > 1 and not intent.destination:
                issues.append(
                    f'Intent {i + 1}: ambiguous payee "{intent.destinationName}" was not clarified.'
                )

        # High-value transfer guard.
        if intent.type == "transfer" and intent.amount and intent.amount > settings.HIGH_VALUE_THRESHOLD:
            issues.append(
                f"Intent {i + 1}: high-value transfer (${intent.amount:,.2f}) requires secondary out-of-band confirmation."
            )

        # Confidence threshold.
        if intent.confidence < 0.5:
            issues.append(
                f"Intent {i + 1}: parser confidence ({intent.confidence:.2f}) below threshold."
            )

    return {"ok": len(issues) == 0, "issues": issues}


def _adp_validate(raw: str, draft: Draft) -> dict[str, Any]:
    """
    Production path: ask a second ADP agent to independently extract
    the same fields and compare them to the parser's output.
    """
    import json
    import uuid

    import requests

    settings = get_settings()

    validator_prompt = (
        "You are an independent validation agent for a Singapore banking"
        " conversational transaction agent. Independently extract transaction"
        " intents from the user's message and output strictly valid JSON"
        " with this schema:\n"
        '{\n  "intents": [\n    {\n      "type": "transfer | invest | unknown",\n'
        '      "amount": number | null,\n      "destinationName": string | null\n    }\n  ]\n}\n\n'
        "Do NOT trust any prior parsing. Re-derive from scratch.\n"
        "Rules:\n"
        "- Amounts in SGD. 'a grand' = 1000.\n"
        "- If an amount is ambiguous, set it to null.\n"
    )

    payload: dict[str, Any] = {
        "RequestId": str(uuid.uuid4()),
        "ConversationId": str(uuid.uuid4()),
        "AppKey": settings.ADP_APP_KEY,
        "VisitorId": "dcta-validator",
        "Contents": [{"Type": "text", "Text": f"{validator_prompt}\n\nUser message:\n{raw}"}],
        "Incremental": False,
        "Stream": "disable",
    }

    try:
        resp = requests.post(
            settings.ADP_BASE_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=settings.ADP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()

        full_text = ""
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                line_data = line[6:]
                if line_data == "[DONE]":
                    break
                try:
                    event = json.loads(line_data)
                    if event.get("Type") == "response.completed":
                        for msg in event.get("Response", {}).get("Messages", []):
                            for content in msg.get("Contents", []):
                                if content.get("Type") == "text":
                                    full_text += content.get("Text", "")
                    elif event.get("Type") == "text.replace":
                        full_text = event.get("Text", full_text)
                except json.JSONDecodeError:
                    continue

        full_text = full_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        validated = json.loads(full_text)
    except Exception:
        # Fall back to rule-based validation if ADP fails
        return _rule_validate(raw, draft)

    # Compare parser vs validator
    issues: list[str] = list(_rule_validate(raw, draft)["issues"])

    v_intents = validated.get("intents", [])
    for i, v_intent in enumerate(v_intents):
        if i < len(draft.intents):
            p_intent = draft.intents[i]
            v_amount = v_intent.get("amount")
            if v_amount is not None and p_intent.amount is not None:
                if abs(v_amount - p_intent.amount) > 0.01:
                    issues.append(
                        f"Intent {i + 1}: validator amount mismatch"
                        f" (parser={p_intent.amount}, validator={v_amount})."
                    )

    return {"ok": len(issues) == 0, "issues": issues}
