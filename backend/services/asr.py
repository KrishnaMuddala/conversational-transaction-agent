"""
TRTC ASR integration via the v3 sentence-recognition HTTP API.

Replaces the legacy Tencent Cloud ASR SDK (SentenceRecognition) which
requires service activation that is not available on all accounts.
TRTC ASR v3 uses SDKAppID + SDKSecretKey (UserSig) and the endpoint
https://asr-intl.cloud-rtc.com/v3/transcribe — no separate service
activation is required.

Audio limits: <= 60 s duration, <= 3 MB file size.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
import zlib

import httpx

from config import get_settings


# ---------------------------------------------------------------------------
# UserSig generation — TLSSigAPIv2 (HMAC-SHA256 + zlib + URL-safe base64)
# Reference: https://github.com/Tencent-RTC/tls-sig-api-v2-python
# ---------------------------------------------------------------------------
def _base64_encode_url(data: bytes) -> str:
    """URL-safe base64: replace + → *, / → -, = → _."""
    b64 = base64.b64encode(data).decode("utf-8")
    return b64.replace("+", "*").replace("/", "-").replace("=", "_")


def _generate_user_sig(
    sdk_app_id: int, secret_key: str, identifier: str, expire: int = 86400
) -> str:
    """
    Generate a TRTC UserSig using the TLSSigAPIv2 algorithm.

    Steps:
      1. Build a signature string:
         TLS.identifier:<id>\\nTLS.sdkappid:<app>\\nTLS.time:<ts>\\nTLS.expire:<exp>\\n
      2. HMAC-SHA256 with SDKSecretKey, base64-encode the digest.
      3. Assemble a JSON dict with version, identifier, sdkappid, expire, time, sig.
      4. JSON-serialize, zlib-compress, URL-safe base64-encode.
    """
    curr_time = int(time.time())

    raw_to_sign = (
        f"TLS.identifier:{identifier}\n"
        f"TLS.sdkappid:{sdk_app_id}\n"
        f"TLS.time:{curr_time}\n"
        f"TLS.expire:{expire}\n"
    )

    sig_digest = hmac.new(
        secret_key.encode("utf-8"),
        raw_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = base64.b64encode(sig_digest).decode("utf-8")

    payload = {
        "TLS.ver": "2.0",
        "TLS.identifier": str(identifier),
        "TLS.sdkappid": int(sdk_app_id),
        "TLS.expire": int(expire),
        "TLS.time": int(curr_time),
        "TLS.sig": sig_b64,
    }

    raw_json = json.dumps(payload)
    compressed = zlib.compress(raw_json.encode("utf-8"))
    return _base64_encode_url(compressed)


# ---------------------------------------------------------------------------
# TRTC ASR v3 — sentence recognition (one-shot HTTP)
# ---------------------------------------------------------------------------
def transcribe_audio(audio_bytes: bytes, filename: str = "voice.mp3") -> dict:
    """
    Submit audio to TRTC ASR v3 sentence-recognition API.

    Args:
        audio_bytes: Raw audio file bytes (mp3, wav, pcm, m4a, ogg).
        filename:    Original filename — used to infer the audio format.

    Returns:
        {"transcript": str, "confidence": float | None}
    """
    settings = get_settings()

    if not settings.TRTC_SDK_APP_ID or not settings.TRTC_SDK_SECRET_KEY:
        raise RuntimeError(
            "TRTC ASR credentials not configured "
            "(TRTC_SDK_APP_ID / TRTC_SDK_SECRET_KEY)."
        )

    # Generate a per-request identifier + UserSig
    request_id = str(uuid.uuid4())
    user_sig = _generate_user_sig(
        settings.TRTC_SDK_APP_ID,
        settings.TRTC_SDK_SECRET_KEY,
        identifier=request_id,
    )

    voice_format = _guess_format(filename)
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    params: dict = {
        "engine_model_type": "bigmodel",
        "source_type": 1,  # 1 = local data (base64)
        "voice_format": voice_format,
        "data": audio_b64,
        "data_len": len(audio_bytes),
        "language": _engine_to_language(settings.ASR_ENGINE),
        "filter_punc": 0,
        "convert_num_mode": 1,
        "word_info": 1,
    }

    # PCM format requires a sample rate hint (only 8000 is documented, but
    # 16000 works for 16-bit PCM from the browser).
    if voice_format == "pcm":
        params["input_sample_rate"] = 16000

    body = {
        "auth": {
            "sdkappid": str(settings.TRTC_SDK_APP_ID),
            "usersig": user_sig,
            "request_id": request_id,
        },
        "params": params,
    }

    try:
        resp = httpx.post(
            settings.TRTC_ASR_ENDPOINT,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
    except httpx.RequestError as e:
        raise RuntimeError(f"TRTC ASR request failed: {e}")

    # TRTC ASR returns HTTP 200 even on auth errors — must check body code.
    try:
        resp_data = resp.json()
    except Exception:
        raise RuntimeError(
            f"TRTC ASR returned non-JSON (HTTP {resp.status_code}): "
            f"{resp.text[:200]}"
        )

    code = resp_data.get("code", -1)
    if code != 0:
        raise RuntimeError(
            f"TRTC ASR error (code={code}): {resp_data.get('message', 'unknown')}"
        )

    return {
        "transcript": resp_data.get("result", "") or "",
        "confidence": None,  # TRTC v3 does not return a confidence score
    }


def _guess_format(filename: str) -> str:
    """Map file extension to TRTC ASR voice_format value."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp3"
    fmt_map = {
        "mp3": "mp3",
        "wav": "wav",
        "pcm": "pcm",
        "m4a": "m4a",
        "ogg": "ogg-opus",
        "opus": "ogg-opus",
        # WebM/Opus from browser MediaRecorder — TRTC ASR accepts ogg-opus
        # for Opus audio in an OGG container. Browser MediaRecorder produces
        # Opus in a WebM container, which TRTC ASR accepts as ogg-opus.
        "webm": "ogg-opus",
    }
    return fmt_map.get(ext, "mp3")


def _engine_to_language(engine: str) -> str:
    """
    Map the legacy ASR_ENGINE setting to a TRTC ASR language code.
    TRTC uses ISO 639-1 codes: zh, en, yue, ja, ko, etc.
    """
    engine_lower = engine.lower()
    if "en" in engine_lower:
        return "en"
    if "zh" in engine_lower:
        return "zh"
    return ""  # empty = auto-detect
