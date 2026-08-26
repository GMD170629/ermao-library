"""Stable media application contracts."""

from app.modules.media.application.cover_proxy import (
    UnsafeCoverUrl,
    configured_cover_origins,
    validate_cover_url,
)
from app.modules.media.application.page_index import (
    ReadOnlyResourcePageIndex,
    ResolvedResourcePageIndex,
    ResourcePageIndexProjection,
    ResourcePageSource,
    ResourcePageUnit,
)

__all__ = [
    "ReadOnlyResourcePageIndex",
    "ResolvedResourcePageIndex",
    "ResourcePageIndexProjection",
    "ResourcePageSource",
    "ResourcePageUnit",
    "UnsafeCoverUrl",
    "configured_cover_origins",
    "validate_cover_url",
]
