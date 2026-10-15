"""
Layer 5: Ledger execution.

In production this calls the real DBS payment API using credentials that are
available ONLY to the gateway executor. The conversational agent never has
access to these credentials.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from config import get_settings
from models import Draft, Intent


def execute_transactions(draft: Draft) -> dict[str, Any]:
    settings = get_settings()
    results: list[dict[str, Any]] = []

    for intent in draft.intents:
        result = _execute_intent(intent, settings.DBS_PAYMENT_API_URL, settings.DBS_PAYMENT_API_KEY)
        results.append(result)

    return {
        "results": results,
        "timestamp": int(time.time() * 1000),
    }


def _dest_attr(destination: Any, name: str) -> str:
    """Read a field from a destination that may be a Pydantic model or a dict."""
    if isinstance(destination, dict):
        value = destination.get(name)
    else:
        value = getattr(destination, name, None)
    return str(value) if value is not None else ""


def _execute_intent(intent: Intent, api_url: str, api_key: str) -> dict[str, Any]:
    if intent.type == "transfer" and intent.amount and intent.destination:
        dest_id = _dest_attr(intent.destination, "id") or _dest_attr(intent.destination, "symbol") or "X"
        ref = f"REF-{int(time.time() * 1000)}-{dest_id[:4]}"

        # If a real DBS API URL is configured, call it.
        if api_url and not api_url.startswith("https://mock"):
            try:
                return _call_dbs_transfer(intent, api_url, api_key)
            except Exception as e:
                return {"type": "transfer", "status": "failed", "error": str(e)}

        return {
            "type": "transfer",
            "status": "completed",
            "amount": intent.amount,
            "currency": intent.currency,
            "from": intent.sourceAccount.type if intent.sourceAccount else "Unknown",
            "to": _dest_attr(intent.destination, "name") or intent.destinationName,
            "reference": ref,
        }

    if intent.type == "invest" and intent.destination:
        ref = f"ORD-{int(time.time() * 1000)}"
        return {
            "type": "invest",
            "status": "completed",
            "amount": intent.amount,
            "currency": intent.currency,
            "from": intent.sourceAccount.type if intent.sourceAccount else "Unknown",
            "to": _dest_attr(intent.destination, "name") or intent.destinationName,
            "reference": ref,
        }

    return {"type": "unknown", "status": "ignored", "note": "No executable intent"}


def _call_dbs_transfer(intent: Intent, api_url: str, api_key: str) -> dict[str, Any]:
    """Example real DBS payment API call. Adjust payload shape to DBS docs."""
    payload = {
        "sourceAccountId": intent.sourceAccount.id if intent.sourceAccount else None,
        "destination": (
            intent.destination.model_dump(mode="json")
            if hasattr(intent.destination, "model_dump")
            else intent.destination
        ),
        "amount": intent.amount,
        "currency": intent.currency,
        "reference": f"DBSDCTA-{int(time.time() * 1000)}",
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{api_url.rstrip('/')}/transfers", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
