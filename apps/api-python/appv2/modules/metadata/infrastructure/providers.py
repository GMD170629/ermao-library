from __future__ import annotations

from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    ProviderRegistry,
    ProviderView,
)


class ConfiguredProviderRegistry(ProviderRegistry):
    """Registry boundary for provider adapters.

    Providers are deliberately opt-in. Unknown provider slugs produce no candidates
    instead of allowing arbitrary code or URLs from configuration.
    """

    def search_all(self, query: str, providers: list[ProviderView]) -> list[MetadataCandidate]:
        del query
        if any(provider.enabled and provider.slug == "manual" for provider in providers):
            return []
        return []
