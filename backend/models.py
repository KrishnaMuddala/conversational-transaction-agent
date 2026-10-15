"""
Pydantic schemas for the DBS DCTA API.
These match the JSON contract used by the Gadget prototype.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared entities
# ---------------------------------------------------------------------------
class Account(BaseModel):
    id: str
    type: str
    balance: float = 0.0
    currency: str = "SGD"


class Payee(BaseModel):
    id: str
    name: str
    bank: str
    account: str


class Asset(BaseModel):
    symbol: str
    name: str


class Intent(BaseModel):
    type: Literal["transfer", "invest", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    amount: float | None = None
    amountDisplay: str | None = None
    currency: str = "SGD"
    sourceAccount: Account | None = None
    destinationName: str | None = None
    destination: Payee | Asset | None = None
    destinationCandidates: list[Payee | Asset] = Field(default_factory=list)
    isRelativeAmount: bool = False
    note: str = ""


class Ambiguity(BaseModel):
    intentIndex: int
    field: Literal["payee_disambiguation", "amount_resolution", "account_selection"]
    question: str
    options: list[Any] = Field(default_factory=list)


class Draft(BaseModel):
    rawTranscript: str
    intents: list[Intent]
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    signature: str | None = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class IntentRequest(BaseModel):
    rawTranscript: str
    mode: Literal["text", "voice"] = "text"


class Resolution(BaseModel):
    field: str
    intentIndex: int
    value: Any


class ResolveRequest(BaseModel):
    turnId: str
    resolutions: list[Resolution]


class BiometricEnvelope(BaseModel):
    draft: Draft
    timestamp: int
    signature: str


class ConfirmRequest(BaseModel):
    turnId: str
    envelope: BiometricEnvelope


class AuditQuery(BaseModel):
    turnId: str | None = None
    limit: int = 100


class IntentResponse(BaseModel):
    type: Literal["draft", "clarify", "frozen", "blocked", "chat", "error"]
    turnId: str
    message: str
    rawTranscript: str | None = None
    draft: Draft | None = None
    ambiguities: list[Ambiguity] | None = None
    validation: dict[str, Any] | None = None


class ConfirmResponse(BaseModel):
    type: Literal["confirmed", "rejected", "error"]
    turnId: str
    message: str
    execution: dict[str, Any] | None = None
    auditHash: str | None = None


class AuditEvent(BaseModel):
    ts: int
    turnId: str
    event: str
    payload: Any | None = None


# ---------------------------------------------------------------------------
# ASR
# ---------------------------------------------------------------------------
class ASRResponse(BaseModel):
    transcript: str
    confidence: float | None = None
