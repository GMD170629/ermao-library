from __future__ import annotations

from dataclasses import replace

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
)
from app.modules.media.application.page_index import (
    ReadOnlyResourcePageIndex,
    ResourcePageIndexProjection,
    ResourcePageSource,
    comic_manifest_policy_failure,
)


def _page_source(
    source_id: str,
    path: str,
    *,
    legacy_sort_order: int,
) -> ResourcePageSource:
    return ResourcePageSource(
        id=source_id,
        path=path,
        title=path.rsplit("/", 1)[-1],
        mime_type="image/jpeg",
        source_root="/library",
        role="PAGE",
        import_state="READY",
        size_bytes=1,
        sort_order=legacy_sort_order,
        mtime_ms=1,
        sort_key=path,
    )


def test_image_directory_page_index_uses_natural_relative_path_order() -> None:
    projection = ResourcePageIndexProjection(
        resource_id="comic-1",
        resource_index=None,
        persisted_pages=(),
        sources=(
            _page_source("page-10", "chapter/page10.jpg", legacy_sort_order=0),
            _page_source("page-2", "chapter/page2.jpg", legacy_sort_order=99),
            _page_source("page-1", "chapter/page1.jpg", legacy_sort_order=50),
        ),
    )

    resolved = ReadOnlyResourcePageIndex().execute(projection)

    assert [page.asset_id for page in resolved.pages] == [
        "page-1",
        "page-2",
        "page-10",
    ]
    assert [page.sort_order for page in resolved.pages] == [0, 1, 2]
    assert resolved.revision.startswith("sha256:")
    assert len(resolved.revision) == 71


def test_page_index_revision_is_stable_and_changes_with_asset_version() -> None:
    source = _page_source("page-1", "page1.jpg", legacy_sort_order=0)
    projection = ResourcePageIndexProjection(
        resource_id="comic-1",
        resource_index=None,
        persisted_pages=(),
        sources=(source,),
    )

    first = ReadOnlyResourcePageIndex().execute(projection)
    repeated = ReadOnlyResourcePageIndex().execute(projection)
    changed = ReadOnlyResourcePageIndex().execute(
        replace(projection, sources=(replace(source, mtime_ms=2),))
    )

    assert repeated.revision == first.revision
    assert changed.revision != first.revision


def test_manifest_policy_uses_generated_page_and_size_budgets() -> None:
    page_failure = comic_manifest_policy_failure(
        page_count=reader_safety_budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT) + 1
    )
    size_failure = comic_manifest_policy_failure(
        page_count=1,
        serialized_size_bytes=reader_safety_budget(
            ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES
        )
        + 1,
    )

    assert page_failure is not None
    assert page_failure.rule_id == ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT.value
    assert size_failure is not None
    assert size_failure.rule_id == ReaderSafetyRuleId.COMIC_MANIFEST_MAX_BYTES.value
