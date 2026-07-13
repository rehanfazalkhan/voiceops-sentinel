# VoiceOps Sentinel production readiness

## Deployment gate

Do not set `VOICEOPS_ENVIRONMENT=production` until `/readyz` returns `ready`. The service intentionally refuses model, search, ACS, and persistence invocations when required configuration is missing.

Deploy the Container App and then set the public callback and media URLs to the deployed HTTPS/WSS host. Configure an Azure Communication Services phone number and Event Grid subscription to send incoming-call events to `/integrations/acs/events`.

## Identity and least privilege

The Container App uses its system-assigned managed identity. Grant it data-plane access, scoped to the named resources:

- Azure OpenAI: `Cognitive Services OpenAI User`.
- Azure AI Search: `Search Index Data Reader`.
- Cosmos DB: a Cosmos SQL data-plane role permitting read, query, and upsert only in the `voiceops/calls` container.
- Key Vault: `Key Vault Secrets User` only if a service requires an externally held secret.

Disable local Cosmos authentication after confirming the managed identity is assigned. Do not place Azure keys or telephony credentials in source control or Container App environment variables.

## Telephony and media controls

1. Restrict ACS callbacks to the intended public endpoint; validate Event Grid subscription validation before enabling traffic.
2. Terminate TLS at the Container App ingress and require WSS for `/media`.
3. ACS streams PCM 24 kHz mono media. The runtime only treats confirmed transcription events as text; raw audio bytes are never sent directly to an LLM.
4. Use Azure Speech synthesis to create the outbound PCM response. Configure call recording only after legal review, consent wording, retention, and deletion paths are approved.

## Model and approval controls

- Azure AI Search is the only knowledge source. Index approved documents with source IDs, title, owner, effective date, and expiry date.
- The AutoGen supervisor must produce contract-valid JSON. Invalid model output fails the request instead of being silently improvised.
- Payment-card patterns, credentials, cancellation, financial changes, fraud, and disputes always trigger an approval hold. The model cannot release the hold.
- Only Entra principals with `voiceops_supervisor` or `voiceops_admin` may approve a recommendation. Approval records include the actor and recommended action.

## Operational checks

- Run the golden evaluation dataset against the deployed deployment before any policy or model change.
- Alert on failed readiness, ACS callback errors, response contract failures, approval-hold volume, and Speech synthesis failures.
- Run a quarterly access review for managed identity role assignments and Entra operator roles.
- Rotate any exception-only secrets through Key Vault and test call failover and media reconnection paths.
