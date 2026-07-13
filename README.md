# VoiceOps Sentinel

VoiceOps Sentinel is a governed, multi-agent voice operations platform for high-stakes customer support. It accepts Azure Communication Services call events and bidirectional media streams, transcribes live audio with Azure Speech, retrieves approved knowledge from Azure AI Search, and coordinates specialist agents through Microsoft AutoGen and Azure OpenAI.

It is designed around a simple production rule: the model may recommend a response, but it never autonomously performs a financially consequential, account-security, or cancellation action. Those actions are held for an authenticated supervisor.

## What it demonstrates

- Azure Communication Services Call Automation integration boundary with inbound event handling and bidirectional WebSocket media streaming.
- Azure Speech adapter for real-time call audio transcription and synthesized audio return.
- Microsoft AutoGen specialist agents: knowledge, resolution, compliance, and supervisor.
- Azure AI Search retrieval for approved policy and product knowledge.
- Azure OpenAI model access through managed identity, not embedded keys.
- Entra ID JWT validation, Cosmos DB persistence, structured audit events, and explicit approval gates.
- Azure Container Apps + Key Vault + Cosmos DB + AI Search infrastructure as code (Bicep).

## Architecture

```text
PSTN / VoIP caller
        │
Azure Communication Services ── events ──► FastAPI control plane
        │                                      │
        └── bidirectional media WebSocket ─────┼── Azure Speech
                                               │
                                      Azure AI Search retrieval
                                               │
                              AutoGen specialist-agent supervisor
                                               │
                    Cosmos DB audit trail ◄────┴────► Operator approval console
```

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

Local development uses deterministic contract fixtures only so tests can run without cloud credentials. Set `VOICEOPS_ENVIRONMENT=production` only when every required Azure endpoint, Entra ID issuer/audience, and managed-identity role assignment is configured. `/readyz` reports missing production dependencies; invocation fails closed when any are absent.

## Production prerequisites

1. Deploy the Bicep resources and attach a system-assigned managed identity to Container Apps.
2. Grant the identity only the roles it needs for Azure OpenAI, Azure AI Search, Cosmos DB, and the Communication Services resource.
3. Configure Azure Communication Services to send incoming-call and call-control events to `/integrations/acs/events`.
4. Expose the secure `wss://.../media` endpoint for ACS bidirectional PCM streaming. The initial ACS media metadata maps the connection to the persisted call.
5. Configure Entra ID issuer and audience, then use operator roles `voiceops_supervisor` or `voiceops_admin` for approvals.

The repository includes a runbook, test suite, and a compact golden dataset for evaluation. It contains no deployment claim or cloud credential.
