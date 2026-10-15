"""
Tests for the Tencent Cloud ADP parser transport and response decoding.

These stub out `requests.post` so the ADP v2 request contract and the reply
decoding are covered without a published ADP application.
Run with: pytest backend/tests
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from models import Draft
from services import parser as parser_mod


DRAFT_JSON = {
    "intents": [
        {
            "type": "transfer",
            "confidence": 0.95,
            "amount": 500,
            "currency": "SGD",
            "destinationName": "Mom",
            "note": "",
        }
    ],
    "ambiguities": [],
}


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        # requests would report ISO-8859-1 for text/event-stream; the parser
        # must not rely on this.
        self.encoding = "ISO-8859-1"

    @property
    def ok(self) -> bool:
        return self.status_code < 400


def _stub_post(monkeypatch, body: str, status_code: int = 200) -> list[dict]:
    """Replace requests.post and record the payloads it receives."""
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(body, status_code)

    monkeypatch.setitem(sys.modules, "requests", type("m", (), {"post": staticmethod(fake_post)}))
    return calls


ADP_V1_URL = "https://wss.lke.tencentcloud.com/v1/qbot/chat/sse"
ADP_V2_URL = "https://wss.lke.cloud.tencent.com/adp/v2/chat"


@pytest.fixture
def adp_enabled(monkeypatch):
    """Live ADP parsing against the international console's v1 endpoint."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ADP_APP_KEY", "test-app-key", raising=False)
    monkeypatch.setattr(settings, "USE_MOCK_PARSER", False, raising=False)
    monkeypatch.setattr(settings, "ADP_BASE_URL", ADP_V1_URL, raising=False)


@pytest.fixture
def adp_v2(monkeypatch):
    """Live ADP parsing against the China console's v2 endpoint."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ADP_APP_KEY", "test-app-key", raising=False)
    monkeypatch.setattr(settings, "USE_MOCK_PARSER", False, raising=False)
    monkeypatch.setattr(settings, "ADP_BASE_URL", ADP_V2_URL, raising=False)


def test_request_matches_adp_v2_contract(adp_v2, monkeypatch):
    calls = _stub_post(monkeypatch, json.dumps(DRAFT_JSON))
    parser_mod._adp_parse("Transfer $500 to mom")

    assert len(calls) == 1
    payload = calls[0]["json"]

    # Documented v2 fields only: no UserId / SystemRole / ModelName.
    assert "VisitorId" in payload
    assert "UserId" not in payload
    assert "SystemRole" not in payload
    assert "ModelName" not in payload
    assert payload["AppKey"] == "test-app-key"
    assert payload["Stream"] == "disable"
    assert payload["EnableMultiIntent"] is True

    # RequestId / ConversationId must match ^[a-zA-Z0-9_-]{32,64}$
    for field in ("RequestId", "ConversationId"):
        value = payload[field]
        assert 32 <= len(value) <= 64
        assert all(c.isalnum() or c in "-_" for c in value)

    # The parser contract must travel with the transcript.
    sent = payload["Contents"][0]["Text"]
    assert parser_mod.PARSER_SYSTEM_PROMPT in sent
    assert "Transfer $500 to mom" in sent


def test_parses_single_json_object_body(adp_v2, monkeypatch):
    _stub_post(monkeypatch, json.dumps(DRAFT_JSON))
    draft = parser_mod._adp_parse("Transfer $500 to mom")

    assert len(draft.intents) == 1
    assert draft.intents[0].type == "transfer"
    assert draft.intents[0].amount == 500
    # rawTranscript is injected, not requested from the model.
    assert draft.rawTranscript == "Transfer $500 to mom"


def test_parses_sse_completed_event(adp_v2, monkeypatch):
    body = "\n".join([
        "event: message",
        'data: {"Type":"response.completed","Response":{"Messages":[{"Contents":'
        f'[{{"Type":"text","Text":{json.dumps(json.dumps(DRAFT_JSON))}}}]}}]}}}}',
        "",
        "event: done",
        "data: [DONE]",
    ])
    _stub_post(monkeypatch, body)
    draft = parser_mod._adp_parse("Transfer $500 to mom")

    assert draft.intents[0].amount == 500


def test_parses_sse_plain_text_deltas(adp_v2, monkeypatch):
    body = "data: " + json.dumps(json.dumps(DRAFT_JSON)) + "\n\ndata: [DONE]\n"
    _stub_post(monkeypatch, body)
    draft = parser_mod._adp_parse("Transfer $500 to mom")

    assert draft.intents[0].amount == 500


def test_reply_text_probe_shapes():
    assert parser_mod._adp_event_text({"Text": "hello"}) == "hello"
    assert parser_mod._adp_event_text({"Answer": "hi"}) == "hi"
    assert parser_mod._adp_event_text({"trace_id": "abc"}) is None
    # A bare JSON string is a plain-text delta, not a structured event.
    assert parser_mod._adp_event_text("partial answer") == "partial answer"
    assert parser_mod._adp_event_text("") is None
    assert parser_mod._adp_event_text(None) is None


def test_loads_json_object_tolerates_fences_and_prose():
    fenced = '```json\n{"intents": [], "ambiguities": []}\n```'
    assert parser_mod._loads_json_object(fenced) == {"intents": [], "ambiguities": []}

    prose = 'Here is the draft:\n{"intents": [], "ambiguities": []}\nHope that helps.'
    assert parser_mod._loads_json_object(prose) == {"intents": [], "ambiguities": []}


def test_loads_json_object_without_json_raises():
    with pytest.raises(ValueError):
        parser_mod._loads_json_object("I could not parse that request.")


def test_http_error_surfaces_status_and_body(adp_v2, monkeypatch):
    _stub_post(monkeypatch, '{"error":"app not published"}', status_code=403)
    with pytest.raises(RuntimeError, match="ADP HTTP 403"):
        parser_mod._adp_parse("Transfer $500 to mom")


def test_missing_app_key_fails_fast(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ADP_APP_KEY", "", raising=False)
    with pytest.raises(RuntimeError, match="ADP_APP_KEY is not set"):
        parser_mod._adp_parse("Transfer $500 to mom")


def test_empty_answer_surfaces_body(adp_v2, monkeypatch):
    _stub_post(monkeypatch, "data: [DONE]\n")
    with pytest.raises(RuntimeError, match="no answer text"):
        parser_mod._adp_parse("Transfer $500 to mom")


def test_adp_error_event_is_surfaced_not_parsed_as_draft(adp_v2, monkeypatch):
    """ADP reports auth/service failures as an SSE error event, not an HTTP error.

    The Chinese message below is deliberate: it mirrors the real 4505004 response
    ("application key is invalid") and confirms the parser surfaces the server's
    text verbatim rather than re-encoding it.
    """
    body = (
        'event: error\n'
        'data: {"Type":"error","Error":{"Code":4505004,'
        '"Message":"应用密钥无效","TraceId":"abc123"}}\n\n'
    )
    _stub_post(monkeypatch, body)
    with pytest.raises(RuntimeError) as exc:
        parser_mod._adp_parse("Transfer $500 to mom")

    message = str(exc.value)
    assert "ADP rejected the request" in message
    assert "4505004" in message
    assert "应用密钥无效" in message
    assert "abc123" in message


def test_non_ascii_answer_is_not_mojibake(adp_v2, monkeypatch):
    """Regression: requests decodes text/event-stream as ISO-8859-1 by default.

    Do not translate this fixture to ASCII — an all-ASCII payload decodes
    identically under either encoding, so the test would stop detecting the bug.
    """
    draft = dict(DRAFT_JSON)
    draft["intents"] = [dict(DRAFT_JSON["intents"][0], note="转给妈妈，金额五百新元")]
    body = "data: " + json.dumps(json.dumps(draft, ensure_ascii=False)) + "\n\ndata: [DONE]\n"
    _stub_post(monkeypatch, body)

    parsed = parser_mod._adp_parse("Transfer $500 to mom")
    assert parsed.intents[0].note == "转给妈妈，金额五百新元"


# ---------------------------------------------------------------------------
# v1 (international console) contract
# ---------------------------------------------------------------------------

V1_ECHO = {
    "type": "reply",
    "payload": {
        "content": "Transfer $500 to mom",
        "is_evil": False,
        "is_final": True,
        "is_from_self": True,
        "is_llm_generated": False,
        "reply_method": 0,
        "session_id": "sse_session1",
    },
}


def _v1_reply(content, *, llm=True, evil=False, method=18):
    return {
        "type": "reply",
        "payload": {
            "content": content,
            "is_evil": evil,
            "is_final": True,
            "is_from_self": False,
            "is_llm_generated": llm,
            "reply_method": method,
            "session_id": "sse_session1",
        },
    }


def _v1_sse(*events):
    """Frame v1 events the way the endpoint streams them."""
    return "".join(f"event:{e.get('type')}\ndata: {json.dumps(e)}\n\n" for e in events)


def test_request_matches_adp_v1_contract(adp_enabled, monkeypatch):
    calls = _stub_post(monkeypatch, _v1_sse(_v1_reply(json.dumps(DRAFT_JSON))))
    parser_mod._adp_parse("Transfer $500 to mom")

    assert len(calls) == 1
    payload = calls[0]["json"]

    # v1 field names only; none of the v2 spellings.
    assert payload["bot_app_key"] == "test-app-key"
    assert payload["stream"] == "disable"
    assert payload["search_network"] == "disable"
    for absent in ("AppKey", "ConversationId", "Contents", "VisitorId", "EnableMultiIntent"):
        assert absent not in payload

    # system_role is ignored by agent-mode applications, so the contract must
    # travel in content instead.
    assert "system_role" not in payload
    assert parser_mod.PARSER_SYSTEM_PROMPT in payload["content"]
    assert "Transfer $500 to mom" in payload["content"]

    # session_id / request_id must match ^[a-zA-Z0-9_-]{2,64}$
    for field in ("request_id", "session_id"):
        value = payload[field]
        assert 2 <= len(value) <= 64
        assert all(c.isalnum() or c in "-_" for c in value)


def test_v1_user_message_echo_is_not_parsed_as_the_answer(adp_enabled, monkeypatch):
    """v1 echoes the user's own message before the model's reply.

    Parsing the echo would hand the raw transcript to the JSON extractor.
    """
    _stub_post(monkeypatch, _v1_sse(V1_ECHO, _v1_reply(json.dumps(DRAFT_JSON))))
    parsed = parser_mod._adp_parse("Transfer $500 to mom")

    assert len(parsed.intents) == 1
    assert parsed.intents[0].amount == 500
    assert parsed.rawTranscript == "Transfer $500 to mom"


def test_v1_last_reply_wins_when_not_incremental(adp_enabled, monkeypatch):
    """`incremental: false` resends the full answer, so the last reply is final."""
    partial = {"intents": DRAFT_JSON["intents"]}
    _stub_post(monkeypatch, _v1_sse(_v1_reply(json.dumps(partial)), _v1_reply(json.dumps(DRAFT_JSON))))
    parsed = parser_mod._adp_parse("Transfer $500 to mom")

    assert parsed.intents[0].amount == 500


def test_v1_array_framed_event_is_decoded(adp_enabled, monkeypatch):
    """The docs show some events streamed as ["reply", {...}] rather than {...}."""
    body = 'event:reply\ndata: ["reply", ' + json.dumps(_v1_reply(json.dumps(DRAFT_JSON))) + ']\n\n'
    _stub_post(monkeypatch, body)
    parsed = parser_mod._adp_parse("Transfer $500 to mom")

    assert parsed.intents[0].amount == 500


def test_v1_multiline_event_does_not_hide_the_reply(adp_enabled, monkeypatch):
    """Regression: v1 streams payloads that span several physical lines.

    A line-oriented reader rejects the truncated JSON and can miss the reply
    that follows it.
    """
    body = (
        'event:thought\ndata: {"type":"thought","payload":{"content":"step one\n'
        'step two\nstep three"}}\n\n'
        + _v1_sse(_v1_reply(json.dumps(DRAFT_JSON)))
    )
    _stub_post(monkeypatch, body)
    parsed = parser_mod._adp_parse("Transfer $500 to mom")

    assert parsed.intents[0].amount == 500


def test_v1_error_event_carries_an_actionable_hint(adp_enabled, monkeypatch):
    body = _v1_sse({"type": "error", "error": {"code": 4505004, "message": "APPKEY is invalid"}})
    _stub_post(monkeypatch, body)

    with pytest.raises(RuntimeError) as exc:
        parser_mod._adp_parse("Transfer $500 to mom")

    message = str(exc.value)
    assert "4505004" in message
    assert "AppKey is invalid" in message
    # The hint must name the endpoint/console mismatch, which is the real cause.
    assert "console" in message


def test_v1_missing_application_is_reported_clearly(adp_enabled, monkeypatch):
    body = _v1_sse({"type": "error", "error": {"code": 460004, "message": "application does not exist"}})
    _stub_post(monkeypatch, body)

    with pytest.raises(RuntimeError) as exc:
        parser_mod._adp_parse("Transfer $500 to mom")

    assert "460004" in str(exc.value)


def test_v1_sensitive_content_is_rejected(adp_enabled, monkeypatch):
    """is_evil means sensitive-content filtering stopped the message."""
    body = _v1_sse(_v1_reply("", evil=True))
    _stub_post(monkeypatch, body)

    with pytest.raises(RuntimeError) as exc:
        parser_mod._adp_parse("Transfer $500 to mom")

    assert "sensitive" in str(exc.value).lower()


def test_v1_non_ascii_note_survives_decoding(adp_enabled, monkeypatch):
    """Do not translate this fixture — ASCII decodes identically either way."""
    draft = dict(DRAFT_JSON)
    draft["intents"] = [dict(DRAFT_JSON["intents"][0], note="转给妈妈，金额五百新元")]
    _stub_post(monkeypatch, _v1_sse(_v1_reply(json.dumps(draft, ensure_ascii=False))))

    parsed = parser_mod._adp_parse("Transfer $500 to mom")
    assert parsed.intents[0].note == "转给妈妈，金额五百新元"


V2_BODY = json.dumps({
    "Response": {"Messages": [{"Contents": [{"Type": "text", "Text": json.dumps(DRAFT_JSON)}]}]}
})


def test_wire_format_follows_configured_endpoint(monkeypatch):
    """The endpoint selects the schema; keys are not portable between consoles."""
    for url, expected, absent, body in (
        (ADP_V1_URL, "bot_app_key", "AppKey", _v1_sse(_v1_reply(json.dumps(DRAFT_JSON)))),
        (ADP_V2_URL, "AppKey", "bot_app_key", V2_BODY),
    ):
        settings = get_settings()
        monkeypatch.setattr(settings, "ADP_APP_KEY", "test-app-key", raising=False)
        monkeypatch.setattr(settings, "USE_MOCK_PARSER", False, raising=False)
        monkeypatch.setattr(settings, "ADP_BASE_URL", url, raising=False)

        calls = _stub_post(monkeypatch, body)
        parser_mod._adp_parse("Transfer $500 to mom")

        assert expected in calls[0]["json"]
        assert absent not in calls[0]["json"]


def test_missing_app_key_fails_before_any_request(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ADP_APP_KEY", "", raising=False)
    monkeypatch.setattr(settings, "USE_MOCK_PARSER", False, raising=False)

    calls = _stub_post(monkeypatch, _v1_sse(_v1_reply(json.dumps(DRAFT_JSON))))
    with pytest.raises(RuntimeError) as exc:
        parser_mod._adp_parse("Transfer $500 to mom")

    assert "ADP_APP_KEY" in str(exc.value)
    assert calls == []


# ---------------------------------------------------------------------------
# Model-drift resilience
# ---------------------------------------------------------------------------

def test_null_balance_inside_source_account_is_repaired():
    """The model emits "balance": null, which Account rejects outright."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"][0]["sourceAccount"] = {
        "id": "acc_savings", "type": "savings", "balance": None, "currency": None,
    }

    parser_mod._normalize_draft_payload(data)

    account = data["intents"][0]["sourceAccount"]
    assert account["balance"] == 0.0
    assert account["currency"] == "SGD"
    # Must now survive validation.
    Draft(**{**data, "rawTranscript": "x"})


def test_source_account_without_identity_is_dropped():
    """An Account needs id and type; a fragment is worse than no account."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"][0]["sourceAccount"] = {"balance": 100.0}

    parser_mod._normalize_draft_payload(data)

    assert data["intents"][0]["sourceAccount"] is None
    Draft(**{**data, "rawTranscript": "x"})


def test_partial_destination_entity_is_discarded():
    """A Payee missing bank/account cannot be shown to the user."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"][0]["destination"] = {"id": "p1", "name": "Mom"}
    data["intents"][0]["destinationCandidates"] = [
        {"symbol": "NVDA", "name": "NVIDIA"},
        {"id": "p2", "name": "Incomplete"},
        "not-an-object",
    ]

    parser_mod._normalize_draft_payload(data)

    # The valid Asset survives; the malformed entries do not.
    assert data["intents"][0]["destination"] is None
    assert len(data["intents"][0]["destinationCandidates"]) == 1
    assert data["intents"][0]["destinationCandidates"][0]["symbol"] == "NVDA"
    Draft(**{**data, "rawTranscript": "x"})


def test_registry_backfill_resolves_payee_and_ambiguity():
    """ADP supplies semantics; the registry supplies canonical ids."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [
        {"type": "transfer", "confidence": 0.5, "amount": 500, "destinationName": "Mom"},
        # "John" alone matches two saved payees.
        {"type": "transfer", "confidence": 0.9, "amount": 100, "destinationName": "John"},
    ]
    parser_mod._normalize_draft_payload(data)
    data.setdefault("rawTranscript", "Send $500 to mom and $100 to John")
    draft = Draft(**data)

    parser_mod._backfill_from_registry(draft, data["rawTranscript"])

    assert draft.intents[0].destination.id == "payee_mom"
    assert draft.intents[0].sourceAccount.id == "acc_savings"

    assert draft.intents[1].destination is None
    assert [a.field for a in draft.ambiguities] == ["payee_disambiguation"]
    assert draft.ambiguities[0].intentIndex == 1
    assert len(draft.ambiguities[0].options) == 2


def test_registry_backfill_resolves_instrument_from_transcript():
    """A ticker in the transcript is enough to identify the instrument."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{"type": "invest", "confidence": 0.8, "amount": 2000}]
    parser_mod._normalize_draft_payload(data)
    data["rawTranscript"] = "Buy $2000 of NVDA"
    draft = Draft(**data)

    parser_mod._backfill_from_registry(draft, data["rawTranscript"])

    assert draft.intents[0].destination.symbol == "NVDA"


def test_registry_backfill_computes_relative_amount():
    """'the rest' resolves against the registry balance, not a model guess."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{"type": "transfer", "confidence": 0.9, "amount": None,
                        "destinationName": "Mom"}]
    parser_mod._normalize_draft_payload(data)
    data["rawTranscript"] = "Send everything left in savings to mom"
    draft = Draft(**data)

    parser_mod._backfill_from_registry(draft, data["rawTranscript"])

    intent = draft.intents[0]
    assert intent.isRelativeAmount is True
    assert intent.amount == 4820.50  # KNOWN_ACCOUNTS["savings"].balance
    assert intent.amountDisplay == "$4,820.50"


def test_stale_ambiguities_are_dropped_once_resolved():
    """A question the draft can already answer must not block confirmation."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{"type": "transfer", "confidence": 0.9, "amount": None,
                        "destinationName": "Mom"}]
    data["ambiguities"] = [
        {"intentIndex": 0, "field": "amount_resolution", "question": "How much?"},
        {"intentIndex": 0, "field": "payee_disambiguation", "question": "Which Mom?"},
    ]
    parser_mod._normalize_draft_payload(data)
    data["rawTranscript"] = "Send everything left in savings to mom"
    draft = Draft(**data)

    parser_mod._backfill_from_registry(draft, data["rawTranscript"])

    assert draft.intents[0].amount == 4820.50
    assert draft.intents[0].destination.id == "payee_mom"
    # Both were answered deterministically, so neither question survives.
    assert draft.ambiguities == []


def test_unresolved_ambiguity_is_kept():
    """Reconciliation must not silence a genuine question."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{"type": "transfer", "confidence": 0.5, "amount": 100,
                        "destinationName": "nobody"}]
    data["ambiguities"] = [
        {"intentIndex": 0, "field": "payee_disambiguation", "question": "Who?"},
    ]
    parser_mod._normalize_draft_payload(data)
    data["rawTranscript"] = "Send $100 to nobody"
    draft = Draft(**data)

    parser_mod._backfill_from_registry(draft, data["rawTranscript"])

    assert [a.field for a in draft.ambiguities] == ["payee_disambiguation"]


def test_out_of_range_ambiguity_index_is_discarded():
    data = json.loads(json.dumps(DRAFT_JSON))
    data["ambiguities"] = [{"intentIndex": 7, "field": "amount_resolution", "question": "?"}]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="x")

    parser_mod._backfill_from_registry(draft, "x")

    assert draft.ambiguities == []


def test_hallucinated_payee_is_replaced_by_the_canonical_one():
    """The model invents payee ids; only registry ids may reach the draft."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{
        "type": "transfer", "confidence": 0.9, "amount": 500, "destinationName": "Mom",
        "destination": {"id": "***2201", "name": "Mom", "bank": "OCBC", "account": "***2201"},
    }]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="Transfer $500 to mom")

    parser_mod._backfill_from_registry(draft, "Transfer $500 to mom")

    payee = draft.intents[0].destination
    assert payee.id == "payee_mom"
    assert payee.bank == "DBS"
    assert draft.intents[0].destinationCandidates[0].id == "payee_mom"


def test_hallucinated_instrument_is_replaced_by_the_canonical_one():
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{
        "type": "invest", "confidence": 0.9, "amount": 2000, "destinationName": "NVDA",
        "destination": {"symbol": "NVDA", "name": "Some Other Company"},
    }]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="Buy $2000 of NVDA")

    parser_mod._backfill_from_registry(draft, "Buy $2000 of NVDA")

    assert draft.intents[0].destination.symbol == "NVDA"
    assert draft.intents[0].destination.name == "NVIDIA Corp."


def test_unverifiable_payee_is_dropped_and_questioned():
    """A payee absent from the registry must not reach confirmation as-is."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{
        "type": "transfer", "confidence": 0.7, "amount": 500, "destinationName": "Zack",
        "destination": {"id": "p_zack", "name": "Zack", "bank": "DBS", "account": "***0000"},
    }]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="Send $500 to Zack")

    parser_mod._backfill_from_registry(draft, "Send $500 to Zack")

    assert draft.intents[0].destination is None
    assert draft.ambiguities[0].field == "payee_disambiguation"


def test_exact_full_payee_name_beats_the_ambiguous_first_word():
    """"John Tan" is unambiguous, so it must not raise a John Tan/John Lim choice."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{
        "type": "transfer", "confidence": 0.8, "amount": 100, "destinationName": "John Tan",
    }]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="Send $100 to John Tan")

    parser_mod._backfill_from_registry(draft, "Send $100 to John Tan")

    assert draft.intents[0].destination.id == "payee_john_tan"
    assert draft.ambiguities == []


def test_model_supplied_vague_payee_question_is_reworded():
    """A model question with no options must not dead-end the user.

    The live model sometimes pre-populates its own `payee_disambiguation`
    ("Which payee do you mean?") with an empty `options` list. The registry
    knows the name is unknown, so the question has to say that instead of
    offering a choice that does not exist.
    """
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{
        "type": "transfer", "confidence": 0.5, "amount": 80, "destinationName": "Zi Wei",
    }]
    data["ambiguities"] = [{
        "intentIndex": 0, "field": "payee_disambiguation",
        "question": "Which payee do you mean?", "options": [],
    }]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="pay $80 to Zi Wei for tutoring")

    parser_mod._backfill_from_registry(draft, "pay $80 to Zi Wei for tutoring")

    assert len(draft.ambiguities) == 1
    question = draft.ambiguities[0].question
    assert question != "Which payee do you mean?"
    assert "Zi Wei" in question
    assert "not among your saved payees" in question


def test_model_supplied_payee_question_keeps_real_options():
    """A model question that already lists candidates must be left alone."""
    data = json.loads(json.dumps(DRAFT_JSON))
    data["intents"] = [{
        "type": "transfer", "confidence": 0.5, "amount": 100, "destinationName": "John",
    }]
    data["ambiguities"] = [{
        "intentIndex": 0, "field": "payee_disambiguation",
        "question": "Which John?",
        "options": [{"id": "payee_john_tan", "name": "John Tan"}],
    }]
    parser_mod._normalize_draft_payload(data)
    draft = Draft(**data, rawTranscript="Send $100 to John")

    parser_mod._backfill_from_registry(draft, "Send $100 to John")

    assert draft.ambiguities[0].question == "Which John?"


def test_json_wrapped_in_prose_is_salvaged(adp_enabled, monkeypatch):
    """A conversational answer that still contains the object must be usable."""
    draft = json.loads(json.dumps(DRAFT_JSON))
    answer = (
        "Sure! Here is the parsed draft:\n"
        + json.dumps(draft)
        + "\nLet me know if you would like to change anything."
    )
    _stub_post(monkeypatch, _v1_sse(_v1_reply(answer)))

    parsed = parser_mod._adp_parse("Transfer $500 to mom")
    assert parsed.intents[0].amount == 500


def test_answer_without_the_contract_still_fails_loudly(adp_enabled, monkeypatch):
    """Salvage must not invent a draft out of a pure conversational reply."""
    answer = "I can help with that. Who would you like to send the money to?"
    _stub_post(monkeypatch, _v1_sse(_v1_reply(answer)))

    with pytest.raises(RuntimeError) as exc:
        parser_mod._adp_parse("Transfer $500 to mom")

    assert "No JSON object found" in str(exc.value)
