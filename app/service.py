from __future__ import annotations

from .agents import VoiceOrchestrator, build_orchestrator
from .config import Settings
from .knowledge import KnowledgeBase, build_knowledge_base
from .models import CallStatus, Principal, StartCallRequest, TranscriptTurn, UtteranceRequest, VoiceCall, now
from .policy import PolicyViolation, assert_approval_allowed, assess_risk, redact_sensitive_text
from .repository import CallRepository, build_repository
from .telemetry import audit


class VoiceOpsService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: CallRepository | None = None,
        knowledge: KnowledgeBase | None = None,
        orchestrator: VoiceOrchestrator | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.repository = repository or build_repository(self.settings)
        self.knowledge = knowledge or build_knowledge_base(self.settings)
        self.orchestrator = orchestrator or build_orchestrator(self.settings)

    async def start_call(self, request: StartCallRequest, principal: Principal, acs_call_connection_id: str | None = None) -> VoiceCall:
        if self.settings.is_production:
            self.settings.assert_production_ready()
        call = VoiceCall(
            channel=request.channel,
            caller_reference=request.caller_reference,
            locale=request.locale,
            acs_call_connection_id=acs_call_connection_id,
        )
        call.audit_events.append(audit("call_opened", call.id, actor=principal.subject, channel=request.channel))
        self.repository.save(call)
        if request.initial_utterance:
            return await self.ingest_utterance(call.id, UtteranceRequest(text=request.initial_utterance), principal)
        return call

    async def ingest_utterance(self, call_id: str, request: UtteranceRequest, principal: Principal) -> VoiceCall:
        if self.settings.is_production:
            self.settings.assert_production_ready()
        call = self.repository.get(call_id)
        if not call:
            raise KeyError(call_id)
        if call.status in {CallStatus.ENDED, CallStatus.RESOLVED}:
            raise PolicyViolation("This call is no longer accepting utterances.")
        risk, must_approve, reason = assess_risk(request.text)
        sanitized_text, redacted = redact_sensitive_text(request.text)
        citations = await self.knowledge.search(sanitized_text)
        assessment = await self.orchestrator.assess(sanitized_text, citations)
        if must_approve:
            assessment.risk = risk
            assessment.requires_human_approval = True
            assessment.escalation_reason = reason
        call.transcript.append(TranscriptTurn(at=now(), speaker="caller", text=sanitized_text, redacted=redacted))
        call.transcript.append(TranscriptTurn(at=now(), speaker="agent", text=assessment.spoken_response))
        call.latest_assessment = assessment
        call.status = CallStatus.REQUIRES_APPROVAL if assessment.requires_human_approval else CallStatus.ACTIVE
        call.updated_at = now()
        call.audit_events.append(
            audit(
                "utterance_assessed",
                call.id,
                actor=principal.subject,
                source=request.source,
                risk=assessment.risk,
                approval_required=assessment.requires_human_approval,
                redacted=redacted,
            )
        )
        self.repository.save(call)
        return call

    def approve_recommendation(self, call_id: str, principal: Principal) -> VoiceCall:
        assert_approval_allowed(principal.roles)
        call = self.repository.get(call_id)
        if not call:
            raise KeyError(call_id)
        if call.status != CallStatus.REQUIRES_APPROVAL or not call.latest_assessment:
            raise PolicyViolation("This call has no pending recommendation to approve.")
        call.approved_by = principal.subject
        call.status = CallStatus.RESOLVED
        call.updated_at = now()
        call.audit_events.append(audit("recommendation_approved", call.id, actor=principal.subject, action=call.latest_assessment.recommended_action))
        self.repository.save(call)
        return call

    def end_call(self, call_id: str, principal: Principal) -> VoiceCall:
        call = self.repository.get(call_id)
        if not call:
            raise KeyError(call_id)
        call.status = CallStatus.ENDED
        call.updated_at = now()
        call.audit_events.append(audit("call_ended", call.id, actor=principal.subject))
        self.repository.save(call)
        return call
