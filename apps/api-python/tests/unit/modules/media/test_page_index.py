from __future__ import annotations

import os
from dataclasses import replace
from zipfile import ZipFile

from app.modules.media.application.page_index import (
    ReadOnlyResourcePageIndex,
    ResourcePageIndexProjection,
    ResourcePageSource,
)
from app.modules.media.infrastructure.page_index import FilesystemComicArchivePageReader


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


def test_archive_pages_are_resolved_on_demand_and_invalidated_by_source_change(
    tmp_path,
) -> None:
    archive = tmp_path / "comic.cbz"
    with ZipFile(archive, "w") as output:
        output.writestr("page10.jpg", b"ten")
        output.writestr("page2.jpg", b"two")
    source = replace(
        _page_source("asset-1", archive.name, legacy_sort_order=0),
        role="PRIMARY",
        source_root=str(tmp_path),
    )
    projection = ResourcePageIndexProjection(
        resource_id="comic-1",
        resource_index=None,
        persisted_pages=(),
        sources=(source,),
        resource_format="CBZ",
    )
    resolver = ReadOnlyResourcePageIndex(FilesystemComicArchivePageReader())
    first = resolver.execute(projection)
    repeated = resolver.execute(projection)
    assert [page.href for page in first.pages] == ["page2.jpg", "page10.jpg"]
    assert first.revision == repeated.revision
    assert [page.id for page in first.pages] == [page.id for page in repeated.pages]

    # Existing indexes may omit pages filtered by older parser quotas.
    incomplete = replace(projection, persisted_pages=first.pages[:1])
    recovered = resolver.execute(incomplete)
    assert recovered.pages == first.pages

    original_mtime = archive.stat().st_mtime_ns
    with ZipFile(archive, "w") as output:
        output.writestr("new.jpg", b"new page")
    os.utime(archive, ns=(original_mtime, original_mtime))
    changed = resolver.execute(projection)
    assert [page.href for page in changed.pages] == ["new.jpg"]
    assert changed.revision != first.revision


def test_image_directory_index_retains_pages_above_former_count_limit() -> None:
    projection = ResourcePageIndexProjection(
        resource_id="comic-1", resource_index=None, persisted_pages=(),
        sources=tuple(_page_source(str(index), f"{index}.jpg", legacy_sort_order=index) for index in range(10_001)),
    )
    resolved = ReadOnlyResourcePageIndex().execute(projection)
    assert len(resolved.pages) == 10_001
