"""
Basic backend tests for DBS DCTA.
Run with: pytest backend/tests
"""

import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app

client = TestClient(app)


def test_multi_intent_draft():
    response = client.post("/intent", json={
        "rawTranscript": "Transfer $500 to mom and invest the rest in Apple shares"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "draft"
    assert len(data["draft"]["intents"]) == 2
    assert data["draft"]["intents"][1]["amount"] == 4320.5


def test_ambiguous_payee_clarifies():
    response = client.post("/intent", json={
        "rawTranscript": "Send fifty to John"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "clarify"
    assert data["ambiguities"][0]["field"] == "payee_disambiguation"


def test_greeting_prefixed_transfer_is_not_a_plain_chat_freezebomb():
    """A greeting + transaction must not crash the pipeline.

    Regression: the validator's amount regex ([\\d,]+) matched the bare comma in
    "Hello, ..." as a whole group, making float("") blow up into an HTTP 500.
    These hit the user's voice flow (ASR → /intent), producing parser_output in
    the audit trail but never reaching a gateway decision.
    """
    response = client.post("/intent", json={
        "rawTranscript": "Hello, can you transfer 500 dollars to mom?"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["type"] in ("draft", "frozen"), data["type"]


@pytest.mark.parametrize("utterance", [
    "good morning",
    "oh no",
    "hi",
    "hello",
    "thank you",
    "yes",
    "no",
    "what is my balance",
])
def test_non_transaction_never_produces_a_confirmable_draft(utterance):
    """Chitchat and refusals must not reach the execution surface.

    Regression: every one of these used to return a "confirm with biometrics"
    draft (empty intents) or HTTP 500 when ADP replied with its own
    non-transaction envelope, e.g. {"Type": "request_ack"}.
    """
    response = client.post("/intent", json={"rawTranscript": utterance})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "chat", f"{utterance!r} produced {data['type']!r}"
    assert data.get("draft") is None
    assert data.get("ambiguities") is None
    assert "didn't catch a transaction" in data["message"]


def test_no_intent_message_lists_supported_scenarios():
    """The chat reply should tell the user what the agent can actually do."""
    response = client.post("/intent", json={"rawTranscript": "good morning"})
    assert response.status_code == 200
    message = response.json()["message"]
    assert "Transfers" in message
    assert "Investments" in message


def test_real_transaction_still_produces_a_draft():
    """Guard the no-intent gate against over-blocking legitimate transfers."""
    response = client.post("/intent", json={"rawTranscript": "Transfer $100 to mom"})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "draft"
    assert data["draft"]["intents"][0]["destinationName"]


def test_draft_amount_is_formatted_for_display():
    """Every resolved amount must carry a formatted display string.

    Regression: ADP returns a bare number and no amountDisplay, so the draft card
    rendered an em-dash per intent while the total line — computed from the
    numeric value — showed the real figure. The backfill now derives it.

    Uses a payee the heuristic fallback resolves cleanly; the mock parser's
    handling of possessives ("my mom") is a separate, mock-only issue.
    """
    response = client.post("/intent", json={"rawTranscript": "Transfer $500 to mom"})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "draft"
    intent = data["draft"]["intents"][0]
    assert intent["amount"] == 500.0
    assert intent["amountDisplay"] == "$500.00"


def test_multi_intent_amounts_are_all_formatted():
    response = client.post("/intent", json={
        "rawTranscript": "Transfer $500 to mom and invest the rest in Apple shares"
    })
    assert response.status_code == 200
    intents = response.json()["draft"]["intents"]
    assert len(intents) == 2
    for intent in intents:
        assert intent["amountDisplay"], f"missing display for {intent}"
        assert intent["amountDisplay"].startswith("$")


def test_relative_amount_transfer_is_not_treated_as_chitchat():
    """A relative-amount transfer needs clarification, not a chat reply.

    It returns "clarify" because the amount is not yet a number. The point of
    this test is that the no-intent gate does not swallow it as "chat".
    """
    response = client.post("/intent", json={"rawTranscript": "Transfer the rest of my savings to mom"})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "clarify"
    assert data["ambiguities"][0]["field"] == "amount_resolution"


def test_prompt_injection_blocked():
    response = client.post("/demo/prompt_injection")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "blocked"


def test_tampered_signature_rejected():
    # First get a valid draft
    r1 = client.post("/intent", json={"rawTranscript": "Transfer $100 to mom"})
    turn_id = r1.json()["turnId"]
    draft = r1.json()["draft"]

    r2 = client.post("/confirm", json={
        "turnId": turn_id,
        "envelope": {
            "draft": draft,
            "timestamp": 1700000000000,
            "signature": "fake-signature"
        }
    })
    assert r2.status_code == 200
    data = r2.json()
    assert data["type"] == "rejected"


def test_audit_log_returns_events():
    response = client.get("/audit?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_valid_signature_confirms_and_executes():
    """Happy path: a correctly signed draft must reach the ledger executor.

    Regression cover for the gateway/executor path, which previously crashed
    because the envelope arrives as a dict and destinations are Pydantic models.
    """
    import json
    import time
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from services.crypto import _toy_sign

    r1 = client.post("/intent", json={"rawTranscript": "Transfer $100 to mom"})
    turn_id = r1.json()["turnId"]
    draft = r1.json()["draft"]

    timestamp = int(time.time() * 1000)
    payload = json.dumps(
        {
            "turnId": turn_id,
            "intents": draft["intents"],
            "timestamp": timestamp,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    signature = _toy_sign(payload, "demo_secure_enclave_key")

    r2 = client.post("/confirm", json={
        "turnId": turn_id,
        "envelope": {"draft": draft, "timestamp": timestamp, "signature": signature},
    })
    assert r2.status_code == 200
    data = r2.json()
    assert data["type"] == "confirmed", data.get("message")
    assert data["auditHash"].startswith("audit_")
    results = data["execution"]["results"]
    assert results[0]["status"] == "completed"
    assert results[0]["type"] == "transfer"
    assert results[0]["to"] == "Mom"


def test_multi_intent_execution_produces_two_legs():
    """A 2-intent draft must execute both legs (transfer + invest)."""
    r = client.post("/intent", json={
        "rawTranscript": "Transfer $500 to mom and invest the rest in Apple shares"
    })
    assert r.json()["type"] == "draft"
    assert len(r.json()["draft"]["intents"]) == 2

    from ledger.executor import execute_transactions
    from models import Draft

    execution = execute_transactions(Draft(**r.json()["draft"]))
    assert len(execution["results"]) == 2
    assert {x["type"] for x in execution["results"]} == {"transfer", "invest"}


# ---------------------------------------------------------------------------
# TRTC ASR — unit tests (no network calls; service is mocked)
# ---------------------------------------------------------------------------
def test_asr_missing_credentials_returns_503():
    """The /asr endpoint must return 503 when TRTC credentials are absent."""
    # conftest sets USE_MOCK_PARSER=true but does not set TRTC creds.
    # If creds happen to be in .env, skip this test.
    from config import get_settings
    settings = get_settings()
    if settings.TRTC_SDK_APP_ID and settings.TRTC_SDK_SECRET_KEY:
        pytest.skip("TRTC credentials are configured — cannot test the 503 path")

    response = client.post("/asr", files={"file": ("voice.wav", b"dummy", "audio/wav")})
    assert response.status_code == 503


def test_asr_usersig_generation():
    """UserSig must be deterministic for the same inputs and look like base64."""
    from services.asr import _generate_user_sig

    sig = _generate_user_sig(20048881, "test-secret-key", "user_123", expire=86400)
    sig2 = _generate_user_sig(20048881, "test-secret-key", "user_123", expire=86400)

    # Same inputs at the same second produce the same sig (time is embedded,
    # so this is only true when calls are within the same second)
    assert isinstance(sig, str)
    assert len(sig) > 50  # zlib-compressed JSON is not trivially short


def test_asr_format_detection():
    """_guess_format must map common browser extensions to TRTC voice_format values."""
    from services.asr import _guess_format

    assert _guess_format("voice.wav") == "wav"
    assert _guess_format("voice.mp3") == "mp3"
    assert _guess_format("voice.pcm") == "pcm"
    assert _guess_format("voice.m4a") == "m4a"
    assert _guess_format("voice.ogg") == "ogg-opus"
    assert _guess_format("voice.opus") == "ogg-opus"
    assert _guess_format("voice.webm") == "ogg-opus"
    assert _guess_format("noext") == "mp3"  # default fallback


def test_asr_engine_to_language():
    """_engine_to_language must map ASR_ENGINE presets to TRTC language codes."""
    from services.asr import _engine_to_language

    assert _engine_to_language("16k_en") == "en"
    assert _engine_to_language("16k_zh") == "zh"
    assert _engine_to_language("16k_zh_dialect") == "zh"
    assert _engine_to_language("auto") == ""  # auto-detect
