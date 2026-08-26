from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ReadableResourceNavigationUnit
from app.modules.library.infrastructure.publication_navigation import (
    SqlAlchemyLibraryNavigationProjection,
)
from app.modules.library.infrastructure.publication_source import (
    SqlAlchemyPublicationSourceRepository,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
    EnsurePublicationNavigationOutcome,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationRevision,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.domain.navigation import (
    CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
    PublicationParserProfile,
)
from app.modules.publications.infrastructure.models import PublicationNavigationCache
from app.modules.publications.infrastructure.navigation_cache import (
    ConfiguredPublicationParserProfiles,
)
from app.modules.publications.infrastructure.uow import (
    SqlAlchemyPublicationNavigationLookupUnitOfWork,
    SqlAlchemyPublicationNavigationUnitOfWork,
)


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _seed_resource(
    db_session: Session,
    source_path: Path,
    *,
    observed_mtime_ns: int = 1_000_000,
) -> tuple[LibraryReadableResource, LibraryResourceAsset]:
    path = str(source_path)
    book_node = LibrarySourceNode(
        id="navigation-book-node",
        library_id="test-library",
        relative_path="navigation-book/",
        path_key=_path_key("navigation-book/"),
        name="navigation-book",
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=1_000_000,
        observed_at=datetime.now(UTC),
    )
    source_node = LibrarySourceNode(
        id="navigation-source-node",
        library_id="test-library",
        relative_path=path,
        path_key=_path_key(path),
        name=source_path.name,
        physical_kind="REGULAR_FILE",
        observed_size_bytes=1,
        observed_mtime_ns=observed_mtime_ns,
        observed_at=datetime.now(UTC),
    )
    book = LibraryBook(
        id="navigation-book",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book.id,
        title="Publication Navigation",
        normalized_title="publication navigation",
        author="作者",
        normalized_author="作者",
    )
    resource = LibraryReadableResource(
        id="navigation-resource",
        library_id="test-library",
        book_id=book.id,
        source_node_id=source_node.id,
        adapter_id="epub",
        adapter_version="1",
        format="EPUB",
        enablement_state="ENABLED",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource.id,
        title="卷册",
    )
    asset = LibraryResourceAsset(
        id="navigation-asset",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=source_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
        sequence_index=0,
        sort_key="0",
    )
    asset_metadata = LibraryResourceAssetMetadata(
        asset_id=asset.id,
        mime_type="application/epub+zip",
    )
    db_session.add_all([book_node, source_node])
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add(book_metadata)
    db_session.flush()
    db_session.add(resource)
    db_session.flush()
    db_session.add(resource_metadata)
    db_session.flush()
    db_session.add(asset)
    db_session.flush()
    db_session.add(asset_metadata)
    db_session.commit()
    return resource, asset


def _publication(
    *,
    toc: tuple[PublicationTocEntry, ...],
    source_size_bytes: int = 1,
    source_mtime_ms: int = 1,
) -> NormalizedPublication:
    return NormalizedPublication(
        identifier="urn:test:publication-navigation",
        title="卷册",
        author="作者",
        language="zh-CN",
        reading_progression="ltr",
        revision=PublicationRevision(
            source_size_bytes=source_size_bytes,
            source_mtime_ms=source_mtime_ms,
            parser="epub-package:test",
            normalization="epub-normalization:test",
        ),
        reading_order=(
            PublicationLink("Text/one.xhtml", "application/xhtml+xml"),
            PublicationLink("Text/two.xhtml", "application/xhtml+xml"),
        ),
        resources=(),
        toc=toc,
    )


class _Adapter:
    def __init__(self, publication: NormalizedPublication) -> None:
        self.publication = publication
        self.open_count = 0
        self.raise_corrupt = False

    def open(self, source: PublicationSource) -> NormalizedPublication:
        self.open_count += 1
        if self.raise_corrupt:
            raise PublicationCorruptError("broken")
        return self.publication

    def read_resource(self, source: PublicationSource, href: str):
        raise AssertionError("navigation generation must not read a resource")


def _ensure(
    db_session: Session,
    adapter: _Adapter,
) -> EnsurePublicationNavigation:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    profile = PublicationParserProfile(
        parser=adapter.publication.revision.parser,
        normalization=adapter.publication.revision.normalization,
    )
    return EnsurePublicationNavigation(
        lookup_unit_of_work_factory=lambda: (
            SqlAlchemyPublicationNavigationLookupUnitOfWork(
                factory,
                SqlAlchemyPublicationSourceRepository,
                SqlAlchemyLibraryNavigationProjection,
            )
        ),
        publication_adapter=adapter,
        profile_resolver=ConfiguredPublicationParserProfiles({"epub": profile}),
        unit_of_work_factory=lambda: SqlAlchemyPublicationNavigationUnitOfWork(
            factory,
            SqlAlchemyLibraryNavigationProjection,
        ),
    )


_ADMIN = PublicationAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    library_ids=(),
)


def test_manifest_generation_ignores_source_revision_differences(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "changed.epub")
    adapter = _Adapter(
        _publication(
            toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),),
            source_size_bytes=77,
            source_mtime_ms=99,
        )
    )

    result = _ensure(db_session, adapter).open_and_ensure(
        resource_id=resource.id,
        access_scope=_ADMIN,
    )

    assert result.navigation.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert result.publication is adapter.publication
    db_session.expire_all()
    cache = db_session.get(PublicationNavigationCache, resource.id)
    assert cache is not None
    assert cache.source_size_bytes == 77
    assert cache.source_mtime_ms == 99


def test_first_access_replaces_legacy_chapters_and_second_access_hits_cache(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, asset = _seed_resource(db_session, tmp_path / "book.epub")
    db_session.add_all(
        [
            ReadableResourceNavigationUnit(
                id="legacy-chapter",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="chapter",
                title="旧目录",
                href="old.xhtml",
                sort_order=4,
                metadata_json="{}",
            ),
            ReadableResourceNavigationUnit(
                id="preserved-page",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="page",
                title="Page 1",
                href="page-1",
                sort_order=0,
                metadata_json="{}",
            ),
        ]
    )
    db_session.commit()
    adapter = _Adapter(
        _publication(
            toc=(
                PublicationTocEntry(
                    href="Text/one.xhtml#one",
                    title="第一部",
                    children=(
                        PublicationTocEntry(
                            href="Text/two.xhtml#two",
                            title="第二章",
                        ),
                    ),
                ),
            )
        )
    )
    ensure = _ensure(db_session, adapter)

    first = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    second = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert first.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert second.outcome == EnsurePublicationNavigationOutcome.CACHED
    assert adapter.open_count == 1
    db_session.expire_all()
    chapters = db_session.scalars(
        select(ReadableResourceNavigationUnit)
        .where(ReadableResourceNavigationUnit.unit_type == "chapter")
        .order_by(ReadableResourceNavigationUnit.sort_order)
    ).all()
    assert [chapter.title for chapter in chapters] == ["第一部", "第二章"]
    assert [chapter.sort_order for chapter in chapters] == [0, 1]
    assert db_session.get(ReadableResourceNavigationUnit, "legacy-chapter") is None
    assert db_session.get(ReadableResourceNavigationUnit, "preserved-page") is not None
    metadata = [json.loads(chapter.metadata_json) for chapter in chapters]
    assert [item["level"] for item in metadata] == [0, 1]
    assert [item["path"] for item in metadata] == [[0], [0, 0]]
    assert [item["readingOrderPosition"] for item in metadata] == [1, 2]
    assert all(item["exactNavigation"] is True for item in metadata)
    assert all(item["hrefBase"] == "publication-root" for item in metadata)
    assert all(
        item["navigationKey"] == chapter.id for item, chapter in zip(metadata, chapters)
    )
    cache = db_session.get(PublicationNavigationCache, resource.id)
    assert cache is not None
    assert cache.asset_id == asset.id
    assert cache.source_size_bytes == 1
    assert cache.source_mtime_ms == 1
    assert cache.chapter_count == 2
    assert cache.projection_version == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
    resource_metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert resource_metadata is not None
    assert resource_metadata.chapter_count == 2


def test_stale_projection_version_regenerates_without_a_source_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "projection.epub")
    adapter = _Adapter(
        _publication(toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),))
    )
    ensure = _ensure(db_session, adapter)
    ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    cache = db_session.get(PublicationNavigationCache, resource.id)
    assert cache is not None
    cache.projection_version = CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION - 1
    db_session.commit()

    regenerated = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert regenerated.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert adapter.open_count == 2
    db_session.expire_all()
    refreshed = db_session.get(PublicationNavigationCache, resource.id)
    assert refreshed is not None
    assert (
        refreshed.projection_version
        == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
    )


def test_successful_empty_toc_is_cached_without_reparsing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "empty.epub")
    adapter = _Adapter(_publication(toc=()))
    ensure = _ensure(db_session, adapter)

    first = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    second = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert first.chapter_count == 0
    assert second.outcome == EnsurePublicationNavigationOutcome.CACHED
    assert second.chapter_count == 0
    assert adapter.open_count == 1
    db_session.expire_all()
    cache = db_session.get(PublicationNavigationCache, resource.id)
    assert cache is not None
    assert cache.chapter_count == 0
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    assert metadata.chapter_count == 0


def test_open_and_ensure_reuses_its_single_parse_on_miss_and_hit(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "manifest.epub")
    publication = _publication(
        toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),)
    )
    adapter = _Adapter(publication)
    ensure = _ensure(db_session, adapter)

    generated = ensure.open_and_ensure(resource_id=resource.id, access_scope=_ADMIN)
    cached = ensure.open_and_ensure(resource_id=resource.id, access_scope=_ADMIN)

    assert generated.publication is publication
    assert generated.navigation.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert cached.publication is publication
    assert cached.navigation.outcome == EnsurePublicationNavigationOutcome.CACHED
    assert adapter.open_count == 2


def test_cache_mismatch_is_invalidated_before_parse_failure(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, asset = _seed_resource(db_session, tmp_path / "broken.epub")
    db_session.add(
        ReadableResourceNavigationUnit(
            id="stale-chapter",
            resource_id=resource.id,
            asset_id=asset.id,
            unit_type="chapter",
            title="过期章节",
            href="stale.xhtml",
            sort_order=0,
            metadata_json="{}",
        )
    )
    db_session.commit()
    adapter = _Adapter(_publication(toc=()))
    adapter.raise_corrupt = True

    with pytest.raises(PublicationCorruptError):
        _ensure(db_session, adapter).execute(
            resource_id=resource.id, access_scope=_ADMIN
        )

    db_session.expire_all()
    assert db_session.get(ReadableResourceNavigationUnit, "stale-chapter") is None
    assert db_session.get(PublicationNavigationCache, resource.id) is None
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    assert metadata.chapter_count is None


def test_manifest_parse_failure_invalidates_a_matching_cache_before_reraising(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "later-broken.epub")
    adapter = _Adapter(
        _publication(toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),))
    )
    ensure = _ensure(db_session, adapter)
    ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    adapter.raise_corrupt = True

    with pytest.raises(PublicationCorruptError):
        ensure.open_and_ensure(resource_id=resource.id, access_scope=_ADMIN)

    db_session.expire_all()
    assert db_session.scalars(select(ReadableResourceNavigationUnit)).all() == []
    assert db_session.get(PublicationNavigationCache, resource.id) is None
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    assert metadata.chapter_count is None


def test_source_revision_change_during_parse_does_not_block_navigation(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "changing.epub")
    publication = _publication(
        toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),)
    )
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    class _ChangingAdapter(_Adapter):
        def open(self, publication_source: PublicationSource) -> NormalizedPublication:
            opened = super().open(publication_source)
            with factory.begin() as mutation:
                current = mutation.get(LibrarySourceNode, "navigation-source-node")
                assert current is not None
                current.observed_mtime_ns = 2_000_000
            return opened

    result = _ensure(db_session, _ChangingAdapter(publication)).execute(
        resource_id=resource.id,
        access_scope=_ADMIN,
    )

    assert result.outcome == EnsurePublicationNavigationOutcome.GENERATED
    db_session.expire_all()
    chapters = db_session.scalars(select(ReadableResourceNavigationUnit)).all()
    assert [chapter.title for chapter in chapters] == ["第一章"]
    assert db_session.get(PublicationNavigationCache, resource.id) is not None
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    assert metadata.chapter_count == 1


def test_selected_asset_change_regenerates_navigation_for_the_new_asset(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _source = _seed_resource(db_session, tmp_path / "first.epub")
    adapter = _Adapter(
        _publication(toc=(PublicationTocEntry(href="Text/one.xhtml", title="旧章"),))
    )
    ensure = _ensure(db_session, adapter)
    first = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    replacement_path = str(tmp_path / "replacement.epub")
    replacement_node = LibrarySourceNode(
        id="replacement-navigation-node",
        library_id="test-library",
        relative_path=replacement_path,
        path_key=_path_key(replacement_path),
        name="replacement.epub",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=2,
        observed_mtime_ns=2_000_000,
        observed_at=datetime.now(UTC),
    )
    replacement = LibraryResourceAsset(
        id="replacement-navigation-asset",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=replacement_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
        sequence_index=-1,
        sort_key="-1",
    )
    db_session.add_all([replacement_node, replacement])
    db_session.commit()
    adapter.publication = _publication(
        toc=(PublicationTocEntry(href="Text/two.xhtml", title="新章"),),
        source_size_bytes=2,
        source_mtime_ms=2,
    )

    regenerated = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert first.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert regenerated.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert adapter.open_count == 2
    db_session.expire_all()
    chapters = db_session.scalars(
        select(ReadableResourceNavigationUnit).where(
            ReadableResourceNavigationUnit.resource_id == resource.id,
            ReadableResourceNavigationUnit.unit_type == "chapter",
        )
    ).all()
    assert [(chapter.title, chapter.asset_id) for chapter in chapters] == [
        ("新章", replacement.id)
    ]
    cache = db_session.get(PublicationNavigationCache, resource.id)
    assert cache is not None
    assert cache.asset_id == replacement.id
    assert cache.source_size_bytes == replacement_node.observed_size_bytes
    assert cache.source_mtime_ms == 2


def test_unsupported_format_never_invalidates_non_publication_units(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, asset = _seed_resource(db_session, tmp_path / "comic.cbz")
    resource.format = "CBZ"
    asset_metadata = db_session.get(LibraryResourceAssetMetadata, asset.id)
    assert asset_metadata is not None
    asset_metadata.mime_type = "application/vnd.comicbook+zip"
    db_session.add_all(
        [
            ReadableResourceNavigationUnit(
                id="comic-chapter-shaped-unit",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="chapter",
                title="Archive metadata",
                href="metadata",
                sort_order=0,
                metadata_json="{}",
            ),
            ReadableResourceNavigationUnit(
                id="comic-page",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="page",
                title="Page 1",
                href="page-1",
                sort_order=0,
                metadata_json="{}",
            ),
        ]
    )
    resource_metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert resource_metadata is not None
    resource_metadata.chapter_count = 9
    db_session.commit()
    adapter = _Adapter(_publication(toc=()))
    ensure = _ensure(db_session, adapter)

    result = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert result.outcome == EnsurePublicationNavigationOutcome.UNSUPPORTED
    with pytest.raises(PublicationUnsupportedError):
        ensure.open_and_ensure(resource_id=resource.id, access_scope=_ADMIN)
    assert adapter.open_count == 0
    db_session.expire_all()
    assert (
        db_session.get(ReadableResourceNavigationUnit, "comic-chapter-shaped-unit")
        is not None
    )
    assert db_session.get(ReadableResourceNavigationUnit, "comic-page") is not None
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    assert metadata.chapter_count == 9
