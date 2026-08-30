"""Read-only comic page-index contracts and orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
    reader_safety_rule,
)
from app.core.natural_sort import natural_sort_key


@dataclass(frozen=True)
class ResourcePageUnit:
    id: str
    resource_id: str
    asset_id: str | None
    unit_type: str
    title: str
    href: str
    media_type: str | None
    sort_order: int
    width: int | None
    height: int | None
    size: int | None
    metadata_json: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ResourcePageSource:
    id: str
    path: str
    title: str
    mime_type: str | None
    source_root: str
    role: str
    import_state: str
    size_bytes: int
    sort_order: int
    mtime_ms: int
    sort_key: str | None


@dataclass(frozen=True)
class ResourcePageIndexProjection:
    """Database projection captured before any archive file is inspected."""

    resource_id: str
    resource_index: float | None
    persisted_pages: tuple[ResourcePageUnit, ...]
    sources: tuple[ResourcePageSource, ...]

    def comic_source(self) -> ResourcePageSource | None:
        return next(
            (source for source in self.sources if source.role == "PRIMARY"), None
        )


@dataclass(frozen=True)
class ResolvedResourcePageIndex:
    """Page data resolved without changing database state."""

    pages: tuple[ResourcePageUnit, ...]
    sources: tuple[ResourcePageSource, ...]
    revision: str

    def page(self, page_index: int) -> ResourcePageUnit | None:
        return next(
            (page for page in self.pages if page.sort_order == page_index),
            None,
        )

    def source_for(self, asset_id: str | None) -> ResourcePageSource | None:
        if asset_id is None:
            return None
        return next((source for source in self.sources if source.id == asset_id), None)


@dataclass(frozen=True, slots=True)
class ComicManifestPolicyFailure:
    rule_id: str
    error_code: str


def comic_manifest_policy_failure(
    *,
    page_count: int,
    serialized_size_bytes: int | None = None,
) -> ComicManifestPolicyFailure | None:
    """Evaluate manifest facts against the generated Reader safety policy."""

    if page_count > reader_safety_budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT):
        rule_id = ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT
    elif (
        serialized_size_bytes is not None
        and serialized_size_bytes
        > reader_safety_budget(ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES)
    ):
        rule_id = ReaderSafetyRuleId.COMIC_MANIFEST_MAX_BYTES
    else:
        return None
    rule = reader_safety_rule(rule_id)
    if rule.error_code is None:
        raise RuntimeError(f"generated Reader safety rule {rule_id.value} has no error")
    return ComicManifestPolicyFailure(
        rule_id=rule.id.value,
        error_code=rule.error_code.value,
    )


class ReadOnlyResourcePageIndex:
    """Resolve only the persisted page index prepared before API startup."""

    def execute(
        self,
        projection: ResourcePageIndexProjection,
    ) -> ResolvedResourcePageIndex:
        if projection.persisted_pages:
            pages = projection.persisted_pages
        else:
            page_sources = sorted(
                (source for source in projection.sources if source.role == "PAGE"),
                key=lambda source: (
                    natural_sort_key(source.sort_key or source.title),
                    source.id,
                ),
            )
            pages = tuple(
                ResourcePageUnit(
                    id=source.id,
                    resource_id=projection.resource_id,
                    asset_id=source.id,
                    unit_type="page",
                    title=source.title,
                    href=source.path,
                    media_type=source.mime_type,
                    sort_order=index,
                    width=None,
                    height=None,
                    size=source.size_bytes,
                    metadata_json="{}",
                    created_at=None,
                    updated_at=None,
                )
                for index, source in enumerate(page_sources)
            )
        return ResolvedResourcePageIndex(
            pages=pages,
            sources=projection.sources,
            revision=_page_index_revision(
                resource_id=projection.resource_id,
                pages=pages,
                sources=projection.sources,
            ),
        )


def _page_index_revision(
    *,
    resource_id: str,
    pages: tuple[ResourcePageUnit, ...],
    sources: tuple[ResourcePageSource, ...],
) -> str:
    """Return the strong identity for one immutable comic page session."""

    payload = {
        "schemaVersion": 2,
        "resourceId": resource_id,
        "sources": [
            {
                "id": source.id,
                "role": source.role,
                "sizeBytes": source.size_bytes,
                "mtimeMs": source.mtime_ms,
            }
            for source in sources
        ],
        "pages": [
            {
                "id": page.id,
                "assetId": page.asset_id,
                "href": page.href,
                "mediaType": page.media_type,
                "size": page.size,
                "sortOrder": page.sort_order,
            }
            for page in pages
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


__all__ = [
    "ComicManifestPolicyFailure",
    "ReadOnlyResourcePageIndex",
    "ResolvedResourcePageIndex",
    "ResourcePageIndexProjection",
    "ResourcePageSource",
    "ResourcePageUnit",
    "comic_manifest_policy_failure",
]
