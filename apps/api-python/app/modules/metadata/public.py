"""Public metadata capability contracts used during composition."""

from app.modules.metadata.domain.providers import (
    BUILTIN_MANIFESTS,
    ProviderConfigField,
    ProviderManifest,
)
from app.modules.metadata.infrastructure.sources import (
    METADATA_SOURCE_KIND,
    ensure_metadata_sources,
)

__all__ = [
    "BUILTIN_MANIFESTS",
    "METADATA_SOURCE_KIND",
    "ProviderConfigField",
    "ProviderManifest",
    "ensure_metadata_sources",
]
