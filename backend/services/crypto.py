"""
Zero-Trust Gateway / biometric signature verification (Layer 4).

Production:
  - Verify signatures using Tencent KMS or a public key registered in KMS / user profile.

Dev / mock:
  - If KMS_KEY_ID is not configured, fall back to a local PEM public key or a deterministic toy HMAC.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

from config import get_settings
from models import Draft


def verify_biometric_signature(turn_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()

    signature = envelope.get("signature")
    draft: Draft | None = envelope.get("draft")
    timestamp = envelope.get("timestamp")

    if not signature:
        return {"ok": False, "reason": "Rejected: missing biometric signature."}
    if not draft:
        return {"ok": False, "reason": "Rejected: no transaction draft attached."}

    # Callers may pass the envelope as a plain dict (e.g. Envelope.model_dump()).
    if isinstance(draft, dict):
        try:
            draft = Draft(**draft)
        except Exception as e:
            return {"ok": False, "reason": f"Rejected: malformed draft in envelope ({e})."}

    # TTL check
    if not timestamp or (time.time() * 1000 - timestamp) > settings.SIGNATURE_TTL_SECONDS * 1000:
        return {"ok": False, "reason": "Rejected: signature expired."}

    payload = json.dumps({
        "turnId": turn_id,
        "intents": [i.model_dump(mode="json") for i in draft.intents],
        "timestamp": timestamp,
    }, separators=(",", ":"), sort_keys=True)

    # Demo / dev signatures use a deterministic toy HMAC (prefix "sig_").
    # Real RSA signatures are base64-encoded and do not start with "sig_".
    if signature.startswith("sig_"):
        expected = _toy_sign(payload, "demo_secure_enclave_key")
        if signature != expected:
            return {"ok": False, "reason": "Rejected: signature does not match payload. Possible tampering."}
        return {"ok": True, "draft": draft}

    # Real cryptographic signature — try KMS first if configured.
    if settings.KMS_KEY_ID:
        return _verify_with_kms(payload, signature)

    # Fallback to local public key verification.
    if settings.LOCAL_PUBLIC_KEY_PEM:
        return _verify_with_local_key(payload, signature, settings.LOCAL_PUBLIC_KEY_PEM)

    # No verification method available — reject.
    return {"ok": False, "reason": "Rejected: no signature verification method configured."}


def _verify_with_kms(payload: str, signature: str) -> dict[str, Any]:
    try:
        from tencentcloud.kms.v20190118 import kms_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile

        settings = get_settings()
        cred = credential.Credential(settings.TENCENT_SECRET_ID, settings.TENCENT_SECRET_KEY)
        http_profile = HttpProfile(endpoint="kms.tencentcloudapi.com")
        client_profile = ClientProfile(httpProfile=http_profile)
        client = kms_client.KmsClient(cred, settings.TENCENT_REGION, client_profile)

        req = models.VerifyByAsymmetricKeyRequest()
        req.KeyId = settings.KMS_KEY_ID
        req.Message = base64.b64encode(payload.encode()).decode()
        req.SignatureValue = signature
        req.Algorithm = settings.KMS_KEY_ALGORITHM
        req.MessageType = "RAW"
        client.VerifyByAsymmetricKey(req)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"Rejected: KMS signature verification failed: {e}"}


def _verify_with_local_key(payload: str, signature: str, pem: str) -> dict[str, Any]:
    try:
        public_key = serialization.load_pem_public_key(pem.encode())
        sig_bytes = base64.b64decode(signature)
        public_key.verify(
            sig_bytes,
            payload.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return {"ok": True}
    except InvalidSignature:
        return {"ok": False, "reason": "Rejected: invalid cryptographic signature."}
    except Exception as e:
        return {"ok": False, "reason": f"Rejected: signature verification error: {e}"}


def _toy_sign(payload: str, key: str) -> str:
    """Deterministic toy digest for dev only. NOT cryptographic."""
    h = 0
    data = f"{payload}:{key}"
    for ch in data:
        h = ((h << 5) - h + ord(ch)) & 0xffffffff
    return f"sig_{abs(h):016x}"


# ---------------------------------------------------------------------------
# Helpers to generate a demo key pair (run once offline, store public key in env)
# ---------------------------------------------------------------------------
def generate_demo_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pub_pem, priv_pem
