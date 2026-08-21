"""Exact relative-path anchor scope rules for Book / Resource / Asset.

ADR 0018 requires Book, ReadableResource, and ResourceAsset anchors to stay
inside the owning Library and within the declared path scope. Comparisons use
the original ``SourceNodeRelativePath`` spelling and ``/`` segment boundaries—
never case folding, Unicode normalization, or unsafe string prefixes.
"""

from __future__ import annotations

from enum import Enum

from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)


class ReadableResourceAnchorViolationCode(str, Enum):
    SOURCE_NODE_NOT_FOUND = "SOURCE_NODE_NOT_FOUND"
    BOOK_NOT_FOUND = "BOOK_NOT_FOUND"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CROSS_LIBRARY = "CROSS_LIBRARY"
    RESOURCE_OUT_OF_BOOK_SCOPE = "RESOURCE_OUT_OF_BOOK_SCOPE"
    RESOURCE_ALREADY_ANCHORED = "RESOURCE_ALREADY_ANCHORED"
    ASSET_SOURCE_NOT_REGULAR_FILE = "ASSET_SOURCE_NOT_REGULAR_FILE"
    ASSET_OUT_OF_RESOURCE_SCOPE = "ASSET_OUT_OF_RESOURCE_SCOPE"


class ReadableResourceTopologyError(Exception):
    """Stable repository-boundary rejection for Book/Resource/Asset topology."""

    def __init__(
        self,
        code: ReadableResourceAnchorViolationCode,
        *,
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code.value if detail is None else f"{code.value}:{detail}")


def is_same_or_descendant_path(
    *,
    ancestor: SourceNodeRelativePath,
    candidate: SourceNodeRelativePath,
) -> bool:
    """True when candidate is ancestor or a ``/``-bounded descendant."""

    if ancestor.value == candidate.value:
        return True
    return candidate.value.startswith(ancestor.value + "/")


def is_strict_descendant_path(
    *,
    ancestor: SourceNodeRelativePath,
    candidate: SourceNodeRelativePath,
) -> bool:
    """True when candidate is a ``/``-bounded descendant (not the same node)."""

    return candidate.value.startswith(ancestor.value + "/")


def is_resource_anchor_within_book_scope(
    *,
    book_anchor: SourceNodeRelativePath,
    book_anchor_kind: SourceNodePhysicalKind,
    resource_anchor: SourceNodeRelativePath,
) -> bool:
    """Resource anchor equals the Book anchor, or lies under a directory Book."""

    if book_anchor.value == resource_anchor.value:
        return True
    if book_anchor_kind is not SourceNodePhysicalKind.DIRECTORY:
        return False
    return is_strict_descendant_path(
        ancestor=book_anchor, candidate=resource_anchor
    )


def is_asset_path_within_resource_scope(
    *,
    resource_anchor: SourceNodeRelativePath,
    resource_anchor_kind: SourceNodePhysicalKind,
    asset_path: SourceNodeRelativePath,
) -> bool:
    """File Resource may only own itself; directory Resource owns descendants."""

    if resource_anchor_kind is SourceNodePhysicalKind.REGULAR_FILE:
        return asset_path.value == resource_anchor.value
    if resource_anchor_kind is SourceNodePhysicalKind.DIRECTORY:
        return is_strict_descendant_path(
            ancestor=resource_anchor, candidate=asset_path
        )
    return False
