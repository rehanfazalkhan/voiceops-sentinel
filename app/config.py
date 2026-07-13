from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    public_base_url: str
    azure_openai_endpoint: str | None
    azure_openai_deployment: str | None
    azure_openai_model: str | None
    azure_openai_api_version: str | None
    search_endpoint: str | None
    search_index: str | None
    search_semantic_config: str | None
    cosmos_endpoint: str | None
    cosmos_database: str
    cosmos_container: str
    communication_endpoint: str | None
    communication_callback_url: str | None
    media_websocket_url: str | None
    speech_endpoint: str | None
    speech_region: str | None
    entra_issuer: str | None
    entra_audience: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        get = os.getenv
        return cls(
            environment=get("VOICEOPS_ENVIRONMENT", "development").lower(),
            public_base_url=get("VOICEOPS_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            azure_openai_endpoint=get("AZURE_OPENAI_ENDPOINT"),
            azure_openai_deployment=get("AZURE_OPENAI_DEPLOYMENT"),
            azure_openai_model=get("AZURE_OPENAI_MODEL"),
            azure_openai_api_version=get("AZURE_OPENAI_API_VERSION"),
            search_endpoint=get("AZURE_AI_SEARCH_ENDPOINT"),
            search_index=get("AZURE_AI_SEARCH_INDEX"),
            search_semantic_config=get("AZURE_AI_SEARCH_SEMANTIC_CONFIG"),
            cosmos_endpoint=get("AZURE_COSMOS_ENDPOINT"),
            cosmos_database=get("AZURE_COSMOS_DATABASE", "voiceops"),
            cosmos_container=get("AZURE_COSMOS_CONTAINER", "calls"),
            communication_endpoint=get("AZURE_COMMUNICATION_ENDPOINT"),
            communication_callback_url=get("AZURE_COMMUNICATION_CALLBACK_URL"),
            media_websocket_url=get("AZURE_MEDIA_WEBSOCKET_URL"),
            speech_endpoint=get("AZURE_SPEECH_ENDPOINT"),
            speech_region=get("AZURE_SPEECH_REGION"),
            entra_issuer=get("ENTRA_ISSUER"),
            entra_audience=get("ENTRA_AUDIENCE"),
        )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_gaps(self) -> list[str]:
        required = {
            "AZURE_OPENAI_ENDPOINT": self.azure_openai_endpoint,
            "AZURE_OPENAI_DEPLOYMENT": self.azure_openai_deployment,
            "AZURE_OPENAI_MODEL": self.azure_openai_model,
            "AZURE_OPENAI_API_VERSION": self.azure_openai_api_version,
            "AZURE_AI_SEARCH_ENDPOINT": self.search_endpoint,
            "AZURE_AI_SEARCH_INDEX": self.search_index,
            "AZURE_COSMOS_ENDPOINT": self.cosmos_endpoint,
            "AZURE_COMMUNICATION_ENDPOINT": self.communication_endpoint,
            "AZURE_COMMUNICATION_CALLBACK_URL": self.communication_callback_url,
            "AZURE_MEDIA_WEBSOCKET_URL": self.media_websocket_url,
            "AZURE_SPEECH_ENDPOINT": self.speech_endpoint,
            "AZURE_SPEECH_REGION": self.speech_region,
            "ENTRA_ISSUER": self.entra_issuer,
            "ENTRA_AUDIENCE": self.entra_audience,
        }
        return [name for name, value in required.items() if not value]

    def assert_production_ready(self) -> None:
        gaps = self.production_gaps()
        if gaps:
            raise RuntimeError(f"Production configuration incomplete: {', '.join(gaps)}")
