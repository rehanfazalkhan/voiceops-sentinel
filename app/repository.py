from __future__ import annotations

from abc import ABC, abstractmethod

from .config import Settings
from .models import VoiceCall


class CallRepository(ABC):
    @abstractmethod
    def save(self, call: VoiceCall) -> None: ...

    @abstractmethod
    def get(self, call_id: str) -> VoiceCall | None: ...

    @abstractmethod
    def find_by_acs_connection(self, connection_id: str) -> VoiceCall | None: ...

    @abstractmethod
    def recent(self) -> list[VoiceCall]: ...


class InMemoryCallRepository(CallRepository):
    def __init__(self) -> None:
        self.calls: dict[str, VoiceCall] = {}

    def save(self, call: VoiceCall) -> None:
        self.calls[call.id] = call.model_copy(deep=True)

    def get(self, call_id: str) -> VoiceCall | None:
        call = self.calls.get(call_id)
        return call.model_copy(deep=True) if call else None

    def find_by_acs_connection(self, connection_id: str) -> VoiceCall | None:
        for call in self.calls.values():
            if call.acs_call_connection_id == connection_id:
                return call.model_copy(deep=True)
        return None

    def recent(self) -> list[VoiceCall]:
        return sorted((call.model_copy(deep=True) for call in self.calls.values()), key=lambda call: call.updated_at, reverse=True)


class CosmosCallRepository(CallRepository):
    """Cosmos repository used only after production readiness has been satisfied."""

    def __init__(self, settings: Settings) -> None:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        self.container = CosmosClient(settings.cosmos_endpoint, credential=DefaultAzureCredential()).get_database_client(
            settings.cosmos_database
        ).get_container_client(settings.cosmos_container)

    def save(self, call: VoiceCall) -> None:
        self.container.upsert_item(call.model_dump(mode="json"))

    def get(self, call_id: str) -> VoiceCall | None:
        try:
            item = self.container.read_item(item=call_id, partition_key=call_id)
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                return None
            raise
        return VoiceCall.model_validate(item)

    def find_by_acs_connection(self, connection_id: str) -> VoiceCall | None:
        query = "SELECT TOP 1 * FROM c WHERE c.acs_call_connection_id = @connection_id"
        items = list(
            self.container.query_items(
                query=query,
                parameters=[{"name": "@connection_id", "value": connection_id}],
                enable_cross_partition_query=True,
            )
        )
        return VoiceCall.model_validate(items[0]) if items else None

    def recent(self) -> list[VoiceCall]:
        query = "SELECT TOP 50 * FROM c ORDER BY c.updated_at DESC"
        return [VoiceCall.model_validate(item) for item in self.container.query_items(query=query, enable_cross_partition_query=True)]


def build_repository(settings: Settings) -> CallRepository:
    return CosmosCallRepository(settings) if settings.is_production else InMemoryCallRepository()
