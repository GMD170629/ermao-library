from __future__ import annotations

import hashlib
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
    LibraryResourceAssetNavigation,
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
from app.modules.publications.infrastructure.uow import (
    SqlAlchemyPublicationNavigationLookupUnitOfWork,
    SqlAlchemyPublicationNavigationUnitOfWork,
)


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode()).hexdigest()}"


def _seed_resource(
    db_session: Session,
    source_path: Path,
) -> tuple[LibraryReadableResource, LibraryResourceAsset]:
    relative_path = str(source_path)
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
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=source_path.name,
        physical_kind="REGULAR_FILE",
        observed_size_bytes=1,
        observed_mtime_ns=1_000_000,
        observed_at=datetime.now(UTC),
    )
    book = LibraryBook(
        id="navigation-book",
        library_id="test-library",
        source_node_id=book_node.id,
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
    db_session.add_all([book_node, source_node])
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book.id,
            title="Publication Navigation",
            normalized_title="publication navigation",
            author="作者",
            normalized_author="作者",
        )
    )
    db_session.add(resource)
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(resource_id=resource.id, title="卷册")
    )
    db_session.add(asset)
    db_session.flush()
    db_session.add(
        LibraryResourceAssetMetadata(
            asset_id=asset.id,
            mime_type="application/epub+zip",
        )
    )
    db_session.commit()
    return resource, asset


def _publication(
    toc: tuple[PublicationTocEntry, ...],
    *,
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
            parser="test-parser",
            normalization="test-normalization",
        ),
        reading_order=(
            PublicationLink("Text/one.xhtml", "application/xhtml+xml"),
            PublicationLink("Text/two.xhtml", "application/xhtml+xml"),
        ),
        resources=(),
        toc=toc,
    )


class _Adapter:
    def __init__(
        self,
        publication: NormalizedPublication,
        error: Exception | None = None,
    ) -> None:
        self.publication = publication
        self.error = error
        self.open_count = 0

    def open(self, source: PublicationSource) -> NormalizedPublication:
        self.open_count += 1
        if self.error is not None:
            raise self.error
        return self.publication

    def read_resource(self, source: PublicationSource, href: str):
        raise AssertionError("navigation generation must not read content resources")


def _ensure(db_session: Session, adapter: _Adapter) -> EnsurePublicationNavigation:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
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


def test_first_access_generates_and_same_asset_uses_marker(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, asset = _seed_resource(db_session, tmp_path / "book.epub")
    adapter = _Adapter(
        _publication(
            (
                PublicationTocEntry(
                    href="Text/one.xhtml",
                    title="第一章",
                    children=(
                        PublicationTocEntry(href="Text/two.xhtml", title="第二章"),
                    ),
                ),
            )
        )
    )
    ensure = _ensure(db_session, adapter)

    generated = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    cached = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert generated.outcome is EnsurePublicationNavigationOutcome.GENERATED
    assert cached.outcome is EnsurePublicationNavigationOutcome.CACHED
    assert cached.asset_id == asset.id
    assert cached.chapter_count == 2
    assert adapter.open_count == 1
    db_session.expire_all()
    marker = db_session.get(LibraryResourceAssetNavigation, asset.id)
    assert marker is not None
    assert marker.chapter_count == 2
    chapters = db_session.scalars(
        select(ReadableResourceNavigationUnit)
        .where(ReadableResourceNavigationUnit.resource_id == resource.id)
        .order_by(ReadableResourceNavigationUnit.sort_order)
    ).all()
    assert [(chapter.title, chapter.asset_id) for chapter in chapters] == [
        ("第一章", asset.id),
        ("第二章", asset.id),
    ]


def test_empty_toc_is_successfully_cached(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, asset = _seed_resource(db_session, tmp_path / "empty.epub")
    adapter = _Adapter(_publication(()))
    ensure = _ensure(db_session, adapter)

    generated = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    cached = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert generated.chapter_count == 0
    assert cached.outcome is EnsurePublicationNavigationOutcome.CACHED
    assert adapter.open_count == 1
    assert db_session.get(LibraryResourceAssetNavigation, asset.id).chapter_count == 0


def test_same_asset_ignores_revision_fields(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, _asset = _seed_resource(db_session, tmp_path / "same.epub")
    adapter = _Adapter(
        _publication(
            (PublicationTocEntry(href="Text/one.xhtml", title="第一章"),),
            source_size_bytes=1,
            source_mtime_ms=1,
        )
    )
    ensure = _ensure(db_session, adapter)
    ensure.execute(resource_id=resource.id, access_scope=_ADMIN)
    adapter.publication = _publication(
        (PublicationTocEntry(href="Text/two.xhtml", title="不同章节"),),
        source_size_bytes=999,
        source_mtime_ms=999,
    )

    result = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert result.outcome is EnsurePublicationNavigationOutcome.CACHED
    assert adapter.open_count == 1


@pytest.mark.parametrize(
    "error",
    [PublicationCorruptError("broken"), PublicationUnsupportedError("unsupported")],
)
def test_parse_failure_does_not_publish_success_marker(
    db_session: Session,
    tmp_path: Path,
    error: Exception,
) -> None:
    resource, asset = _seed_resource(db_session, tmp_path / "broken.epub")
    adapter = _Adapter(_publication(()), error)

    with pytest.raises(type(error)):
        _ensure(db_session, adapter).execute(
            resource_id=resource.id, access_scope=_ADMIN
        )

    db_session.expire_all()
    assert db_session.get(LibraryResourceAssetNavigation, asset.id) is None
    assert (
        db_session.get(LibraryReadableResourceMetadata, resource.id).chapter_count
        is None
    )


def test_asset_replacement_regenerates_for_new_asset(
    db_session: Session,
    tmp_path: Path,
) -> None:
    resource, old_asset = _seed_resource(db_session, tmp_path / "replace.epub")
    adapter = _Adapter(
        _publication((PublicationTocEntry(href="Text/one.xhtml", title="旧目录"),))
    )
    ensure = _ensure(db_session, adapter)
    ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    source_node_id = old_asset.source_node_id
    db_session.delete(old_asset)
    db_session.flush()
    new_asset = LibraryResourceAsset(
        id="navigation-asset-v2",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=source_node_id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
        sequence_index=0,
        sort_key="0",
    )
    db_session.add(new_asset)
    db_session.flush()
    db_session.add(
        LibraryResourceAssetMetadata(
            asset_id=new_asset.id,
            mime_type="application/epub+zip",
        )
    )
    db_session.commit()
    adapter.publication = _publication(
        (PublicationTocEntry(href="Text/two.xhtml", title="新目录"),)
    )

    result = ensure.execute(resource_id=resource.id, access_scope=_ADMIN)

    assert result.outcome is EnsurePublicationNavigationOutcome.GENERATED
    assert result.asset_id == new_asset.id
    assert adapter.open_count == 2
    db_session.expire_all()
    assert db_session.get(LibraryResourceAssetNavigation, old_asset.id) is None
    assert db_session.get(LibraryResourceAssetNavigation, new_asset.id) is not None
