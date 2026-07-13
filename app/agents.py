from __future__ import annotations

import json
from abc import ABC, abstractmethod

from .config import Settings
from .models import AgentAssessment, KnowledgeCitation, RiskLevel
from .policy import assess_risk


class VoiceOrchestrator(ABC):
    @abstractmethod
    async def assess(self, utterance: str, citations: list[KnowledgeCitation]) -> AgentAssessment: ...


class DevelopmentVoiceOrchestrator(VoiceOrchestrator):
    """Deterministic contract implementation used only for local development and tests."""

    async def assess(self, utterance: str, citations: list[KnowledgeCitation]) -> AgentAssessment:
        lowered = utterance.lower()
        risk, approval_required, reason = assess_risk(utterance)
        if any(term in lowered for term in ("refund", "charge", "payment", "invoice", "billing")):
            intent = "billing_support"
            response = "I can document the billing concern and explain the approved next step. A verified supervisor must authorize any account or financial change."
            action = "Collect the minimum case details and queue a supervisor review."
        elif any(term in lowered for term in ("password", "login", "account", "access")):
            intent = "account_access"
            response = "I cannot accept or reset credentials over this channel. I can route you to the verified account recovery process."
            action = "Route to verified account recovery; do not request secrets."
        elif any(term in lowered for term in ("cancel", "close", "plan")):
            intent = "cancellation_or_plan_change"
            response = "I can capture the request and explain the next steps. A verified supervisor must review account changes before they are completed."
            action = "Queue a supervisor-reviewed retention or cancellation workflow."
        else:
            intent = "general_support"
            response = "I can help with that. Based on the approved guidance, I will provide the relevant information and keep the interaction on this call."
            action = "Provide approved knowledge and confirm whether the caller needs further help."
        return AgentAssessment(
            intent=intent,
            risk=risk,
            spoken_response=response,
            supervisor_summary=f"Classified as {intent}; {reason or 'no high-impact action detected.'}",
            recommended_action=action,
            requires_human_approval=approval_required,
            escalation_reason=reason,
            citations=citations,
            agent_trace=[
                {"agent": "knowledge_specialist", "status": "completed", "source_count": len(citations)},
                {"agent": "resolution_specialist", "status": "completed", "intent": intent},
                {"agent": "compliance_specialist", "status": "completed", "risk": risk},
                {"agent": "supervisor", "status": "completed", "approval_required": approval_required},
            ],
        )


class AutoGenVoiceOrchestrator(VoiceOrchestrator):
    """Production AutoGen coordinator backed by an Entra-authenticated Azure OpenAI deployment."""

    def __init__(self, settings: Settings) -> None:
        from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        self.client = AzureOpenAIChatCompletionClient(
            azure_deployment=settings.azure_openai_deployment,
            model=settings.azure_openai_model,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
        )

    async def _run_agent(self, name: str, system_message: str, task: str) -> str:
        from autogen_agentchat.agents import AssistantAgent

        agent = AssistantAgent(name=name, model_client=self.client, system_message=system_message)
        result = await agent.run(task=task)
        for message in reversed(result.messages):
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content
        raise RuntimeError(f"{name} produced no text response")

    async def assess(self, utterance: str, citations: list[KnowledgeCitation]) -> AgentAssessment:
        sources = [citation.model_dump() for citation in citations]
        evidence = json.dumps(sources, ensure_ascii=False)
        knowledge = await self._run_agent(
            "knowledge_specialist",
            "You are the knowledge specialist. Use only the supplied approved sources. Never invent policy or promise an account action. Summarize the applicable guidance in concise JSON.",
            f"Caller utterance: {utterance}\nApproved sources: {evidence}",
        )
        resolution = await self._run_agent(
            "resolution_specialist",
            "You are a voice support resolution specialist. Propose a helpful, spoken response. Never request passwords, one-time codes, CVV, or payment-card numbers. Never state that a financial or account change is complete.",
            f"Caller utterance: {utterance}\nKnowledge assessment: {knowledge}",
        )
        compliance = await self._run_agent(
            "compliance_specialist",
            "You are a strict conversation compliance specialist. Identify sensitive data, financial impact, cancellation, fraud, or authentication risk. State whether a human approval gate is required.",
            f"Caller utterance: {utterance}\nProposed resolution: {resolution}",
        )
        supervisor_prompt = {
            "caller_utterance": utterance,
            "knowledge_specialist": knowledge,
            "resolution_specialist": resolution,
            "compliance_specialist": compliance,
            "approved_citations": sources,
            "required_schema": {
                "intent": "string",
                "risk": "low|moderate|high",
                "spoken_response": "string, 1200 chars max",
                "supervisor_summary": "string",
                "recommended_action": "string",
                "requires_human_approval": "boolean",
                "escalation_reason": "string or null",
            },
        }
        raw = await self._run_agent(
            "voiceops_supervisor",
            "You supervise a governed multi-agent voice operation. Return exactly one JSON object that matches required_schema. Apply the strictest specialist recommendation. A card number, secret, cancellation, refund, fraud claim, disputed charge, or account change requires human approval. Do not fabricate citations.",
            json.dumps(supervisor_prompt, ensure_ascii=False),
        )
        try:
            parsed = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
            assessment = AgentAssessment.model_validate({**parsed, "citations": sources})
        except (json.JSONDecodeError, ValueError) as error:
            raise RuntimeError("AutoGen supervisor output did not satisfy the VoiceOps response contract.") from error
        deterministic_risk, deterministic_gate, deterministic_reason = assess_risk(utterance)
        if deterministic_gate:
            assessment.risk = RiskLevel.HIGH
            assessment.requires_human_approval = True
            assessment.escalation_reason = deterministic_reason
        assessment.agent_trace = [
            {"agent": "knowledge_specialist", "status": "completed", "source_count": len(citations)},
            {"agent": "resolution_specialist", "status": "completed"},
            {"agent": "compliance_specialist", "status": "completed"},
            {"agent": "voiceops_supervisor", "status": "completed", "approval_required": assessment.requires_human_approval},
        ]
        return assessment


def build_orchestrator(settings: Settings) -> VoiceOrchestrator:
    return AutoGenVoiceOrchestrator(settings) if settings.is_production else DevelopmentVoiceOrchestrator()
