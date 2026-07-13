from __future__ import annotations

from abc import ABC, abstractmethod

from .config import Settings
from .models import KnowledgeCitation


class KnowledgeBase(ABC):
    @abstractmethod
    async def search(self, query: str) -> list[KnowledgeCitation]: ...


class DevelopmentKnowledgeBase(KnowledgeBase):
    async def search(self, query: str) -> list[KnowledgeCitation]:
        query = query.lower()
        if any(term in query for term in ("refund", "charge", "payment", "cancel")):
            return [
                KnowledgeCitation(
                    title="Customer-impact action policy",
                    source_id="POL-104",
                    excerpt="Refunds, cancellations, and disputed charges require a verified supervisor approval before execution.",
                )
            ]
        return [
            KnowledgeCitation(
                title="Support interaction standard",
                source_id="SUP-201",
                excerpt="Confirm the request, provide approved information, and escalate account-impacting changes to a verified operator.",
            )
        ]


class AzureAISearchKnowledgeBase(KnowledgeBase):
    def __init__(self, settings: Settings) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.search.documents import SearchClient

        self.client = SearchClient(endpoint=settings.search_endpoint, index_name=settings.search_index, credential=DefaultAzureCredential())
        self.semantic_config = settings.search_semantic_config

    async def search(self, query: str) -> list[KnowledgeCitation]:
        results = self.client.search(
            search_text=query,
            query_type="semantic",
            semantic_configuration_name=self.semantic_config,
            top=4,
            select=["id", "title", "content"],
        )
        return [
            KnowledgeCitation(
                title=result.get("title", "Approved knowledge"),
                source_id=result.get("id", "unknown"),
                excerpt=result.get("content", "")[:600],
            )
            for result in results
        ]


def build_knowledge_base(settings: Settings) -> KnowledgeBase:
    return AzureAISearchKnowledgeBase(settings) if settings.is_production else DevelopmentKnowledgeBase()
