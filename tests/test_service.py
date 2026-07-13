from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.models import CallStatus, Principal, StartCallRequest, UtteranceRequest
from app.service import VoiceOpsService


@pytest.mark.asyncio
async def test_payment_card_is_redacted_and_held_for_approval():
    service = VoiceOpsService(settings=Settings.from_environment())
    operator = Principal(subject="operator-1", roles={"voiceops_operator"})
    call = await service.start_call(StartCallRequest(caller_reference="case-204"), operator)
    updated = await service.ingest_utterance(
        call.id,
        UtteranceRequest(text="My card number is 4111 1111 1111 1111. Please charge it."),
        operator,
    )
    assert updated.status == CallStatus.REQUIRES_APPROVAL
    assert updated.latest_assessment and updated.latest_assessment.requires_human_approval
    assert "4111" not in updated.transcript[0].text
    assert updated.transcript[0].redacted is True


@pytest.mark.asyncio
async def test_supervisor_can_approve_high_impact_recommendation():
    service = VoiceOpsService(settings=Settings.from_environment())
    call = await service.start_call(StartCallRequest(caller_reference="case-501"), Principal(subject="operator", roles=set()))
    await service.ingest_utterance(call.id, UtteranceRequest(text="Please cancel my plan."), Principal(subject="operator", roles=set()))
    approved = service.approve_recommendation(call.id, Principal(subject="supervisor-7", roles={"voiceops_supervisor"}))
    assert approved.status == CallStatus.RESOLVED
    assert approved.approved_by == "supervisor-7"


@pytest.mark.asyncio
async def test_general_support_stays_active_with_specialist_trace():
    service = VoiceOpsService(settings=Settings.from_environment())
    call = await service.start_call(StartCallRequest(caller_reference="case-819"), Principal(subject="operator", roles=set()))
    updated = await service.ingest_utterance(call.id, UtteranceRequest(text="What are your support hours?"), Principal(subject="operator", roles=set()))
    assert updated.status == CallStatus.ACTIVE
    assert updated.latest_assessment and updated.latest_assessment.intent == "general_support"
    assert len(updated.latest_assessment.agent_trace) == 4


def test_api_creates_case_and_enforces_development_supervisor_role():
    from app.main import app

    client = TestClient(app)
    created = client.post("/api/calls", json={"channel": "web", "caller_reference": "console-11"})
    assert created.status_code == 201
    call_id = created.json()["id"]
    assessed = client.post(f"/api/calls/{call_id}/utterances", json={"text": "I need a refund."})
    assert assessed.status_code == 200
    assert assessed.json()["status"] == "requires_approval"
    approved = client.post(f"/api/calls/{call_id}/approve", headers={"X-VoiceOps-Development-Role": "voiceops_supervisor"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "resolved"
