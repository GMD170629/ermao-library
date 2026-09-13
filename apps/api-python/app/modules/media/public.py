"""Stable media application contracts."""

from app.modules.media.application.cover_identity import CoverUrlResolver
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
    comic_manifest_policy_failure,
)

__all__ = [
    "CoverUrlResolver",
    "ReadOnlyResourcePageIndex",
    "ResolvedResourcePageIndex",
    "ResourcePageIndexProjection",
    "ResourcePageSource",
    "ResourcePageUnit",
    "UnsafeCoverUrl",
    "comic_manifest_policy_failure",
    "configured_cover_origins",
    "validate_cover_url",
]
