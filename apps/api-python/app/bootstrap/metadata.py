"""Metadata capability composition root."""

from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS
from app.modules.metadata.infrastructure.automatic_rate_limiter import (
    AutomaticMetadataRequestRateLimiter,
)
from app.modules.metadata.infrastructure.providers import (
    get_provider_source,
    list_enabled_provider_ids,
    list_metadata_sources,
    source_to_dict,
)
from app.modules.metadata.infrastructure.sources import (
    METADATA_SOURCE_KIND,
    ensure_metadata_sources,
)


def build_automatic_metadata_request_gate() -> AutomaticMetadataRequestRateLimiter:
    return AutomaticMetadataRequestRateLimiter(BUILTIN_MANIFESTS)


__all__ = [
    "METADATA_SOURCE_KIND",
    "build_automatic_metadata_request_gate",
    "ensure_metadata_sources",
    "get_provider_source",
    "list_enabled_provider_ids",
    "list_metadata_sources",
    "source_to_dict",
]
