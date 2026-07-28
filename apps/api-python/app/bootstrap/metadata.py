"""Metadata capability composition root."""

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

__all__ = [
    "METADATA_SOURCE_KIND",
    "ensure_metadata_sources",
    "get_provider_source",
    "list_enabled_provider_ids",
    "list_metadata_sources",
    "source_to_dict",
]
