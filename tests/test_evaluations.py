import json
from pathlib import Path

import pytest

from app.config import Settings
from app.models import Principal, StartCallRequest, UtteranceRequest
from app.service import VoiceOpsService


@pytest.mark.asyncio
async def test_golden_voice_safety_dataset():
    service = VoiceOpsService(settings=Settings.from_environment())
    operator = Principal(subject="evaluation-runner", roles={"voiceops_operator"})
    dataset = Path("evaluations/golden_dataset.jsonl").read_text().splitlines()
    for line in dataset:
        scenario = json.loads(line)
        call = await service.start_call(StartCallRequest(caller_reference=scenario["id"]), operator)
        result = await service.ingest_utterance(call.id, UtteranceRequest(text=scenario["utterance"]), operator)
        assessment = result.latest_assessment
        assert assessment is not None
        if "expected_intent" in scenario:
            assert assessment.intent == scenario["expected_intent"]
        assert assessment.risk.value == scenario["expected_risk"]
        assert assessment.requires_human_approval is scenario["expected_approval"]
        output = " ".join(turn.text for turn in result.transcript)
        if "must_contain" in scenario:
            assert scenario["must_contain"].lower() in output.lower()
        if "must_not_contain" in scenario:
            assert scenario["must_not_contain"] not in output
