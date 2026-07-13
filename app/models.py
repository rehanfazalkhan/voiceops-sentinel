from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class CallStatus(str, Enum):
    ACTIVE = "active"
    REQUIRES_APPROVAL = "requires_approval"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    ENDED = "ended"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class Principal(BaseModel):
    subject: str
    roles: set[str] = Field(default_factory=set)


class StartCallRequest(BaseModel):
    channel: Literal["web", "pstn", "voip"] = "web"
    caller_reference: str = Field(min_length=3, max_length=80)
    locale: str = "en-US"
    initial_utterance: str | None = Field(default=None, max_length=4000)


class UtteranceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    source: Literal["operator", "transcription"] = "operator"


class KnowledgeCitation(BaseModel):
    title: str
    source_id: str
    excerpt: str


class AgentAssessment(BaseModel):
    intent: str
    risk: RiskLevel
    spoken_response: str = Field(min_length=1, max_length=1200)
    supervisor_summary: str = Field(min_length=1, max_length=1600)
    recommended_action: str
    requires_human_approval: bool
    escalation_reason: str | None = None
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    agent_trace: list[dict[str, object]] = Field(default_factory=list)


class TranscriptTurn(BaseModel):
    at: datetime
    speaker: Literal["caller", "agent", "operator"]
    text: str
    redacted: bool = False


class VoiceCall(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CallStatus = CallStatus.ACTIVE
    channel: str
    caller_reference: str
    locale: str
    acs_call_connection_id: str | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    latest_assessment: AgentAssessment | None = None
    approved_by: str | None = None
    audit_events: list[dict[str, object]] = Field(default_factory=list)


def now() -> datetime:
    return datetime.now(timezone.utc)
