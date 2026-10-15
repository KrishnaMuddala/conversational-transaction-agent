"""
Shared construction helpers for the eval runner.

These delegate to the backend's own services so the confirm envelope is
byte-identical to what crypto.verify_biometric_signature expects in the
toy-sign fallback (payload key order, separators, sort_keys, timestamp units).

Toy signing is only possible when neither KMS_KEY_ID nor LOCAL_PUBLIC_KEY_PEM
is configured; the production paths must be signed on the device.
"""

from __future__ import annotations

import json

from config import get_settings
from services.crypto import _toy_sign


def toy_sign_available() -> bool:
    s = get_settings()
    return not (s.KMS_KEY_ID or s.LOCAL_PUBLIC_KEY_PEM)


def compute_confirm_payload(turn_id: str, draft: dict, timestamp_ms: int) -> str:
    """Same canonical string crypto.py verifies against."""
    return json.dumps({
        "turnId": turn_id,
        "intents": [i for i in draft.get("intents", [])],
        "timestamp": timestamp_ms,
    }, separators=(",", ":"), sort_keys=True)


def build_confirm_envelope(draft: dict, timestamp_ms: int, payload: str) -> dict:
    """Envelope: draft + signed timestamp, keyed for /confirm."""
    return {
        "draft": draft,
        "timestamp": timestamp_ms,
        "signature": _toy_sign(payload, "demo_secure_enclave_key"),
    }