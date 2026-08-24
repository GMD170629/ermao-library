from __future__ import annotations

from app.modules.media.application.page_index import (
    ReadOnlyResourcePageIndex,
    ResourcePageIndexProjection,
    ResourcePageSource,
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
