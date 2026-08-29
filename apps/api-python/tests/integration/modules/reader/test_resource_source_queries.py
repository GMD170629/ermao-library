from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.library import Library
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
from app.modules.media.infrastructure.resource_repository import (
    SqlAlchemyMediaResourceRepository,
)
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import PublicationNotFoundError
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
)
from app.modules.reader.application.dto import ReaderAccessScope
from app.modules.reader.infrastructure.resource_repository import (
    SqlAlchemyReaderResourceRepository,
)

_API_ROOT = Path(__file__).resolve().parents[4]
_READER_ROOT = _API_ROOT / "app" / "modules" / "reader"
_SOURCE_REPOSITORY = (
    _API_ROOT
    / "app"
    / "modules"
    / "library"
    / "infrastructure"
    / "publication_source.py"
)
_AUDIOBOOK_SUPPORT_TEST = _API_ROOT / "tests" / "test_audiobook_support.py"
_ADMIN_PUBLICATION = PublicationAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    library_ids=(),
)
_ADMIN_READER = ReaderAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    library_ids=(),
)


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _source_node(
    *,
    node_id: str,
    path: str,
    physical_kind: str,
    size_bytes: int | None,
    mtime_ms: int,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key=_path_key(path),
        name=Path(path).name or node_id,
        physical_kind=physical_kind,
        observed_size_bytes=size_bytes if physical_kind != "DIRECTORY" else None,
        observed_mtime_ns=mtime_ms * 1_000_000,
        observed_at=datetime.now(UTC),
    )


def _seed_catalog(
    db: Session,
    *,
    book_id: str,
    resource_id: str,
    title: str,
    fmt: str,
    assets: tuple[tuple[str, str, str, str | None, int], ...],
) -> LibraryReadableResource:
    """Create a complete Book -> Resource -> Asset graph for repository tests."""

    first_asset_id, _first_path, _first_role, _first_mime, _first_order = assets[0]
    book_node = _source_node(
        node_id=f"{book_id}-node",
        path=f"{book_id}/",
        physical_kind="DIRECTORY",
        size_bytes=None,
        mtime_ms=1,
    )
    file_nodes = [
        _source_node(
            node_id=f"{asset_id}-node",
            path=path,
            physical_kind="REGULAR_FILE",
            size_bytes=Path(path).stat().st_size if Path(path).is_file() else 4,
            mtime_ms=(
                int(Path(path).stat().st_mtime * 1000) if Path(path).is_file() else 1
            ),
        )
        for asset_id, path, _role, _mime, _order in assets
    ]
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book_id,
        title=title,
        normalized_title=title.lower(),
        author="作者",
        normalized_author="作者",
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id="test-library",
        book_id=book_id,
        source_node_id=file_nodes[0].id,
        adapter_id=fmt.lower(),
        adapter_version="1",
        format=fmt,
        enablement_state="ENABLED",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource_id,
        title=title,
    )
    asset_rows = [
        LibraryResourceAsset(
            id=asset_id,
            library_id="test-library",
            resource_id=resource_id,
            source_node_id=node.id,
            source_node_physical_kind="REGULAR_FILE",
            role=role,
            import_state="READY",
            sequence_index=sort_order,
            sort_key=str(sort_order),
        )
        for (asset_id, _path, role, _mime, sort_order), node in zip(
            assets, file_nodes, strict=True
        )
    ]
    asset_metadata = [
        LibraryResourceAssetMetadata(asset_id=asset_id, mime_type=mime_type)
        for asset_id, _path, _role, mime_type, _sort_order in assets
    ]
    db.add_all([book_node, *file_nodes])
    db.flush()
    db.add(book)
    db.flush()
    db.add(book_metadata)
    db.flush()
    db.add(resource)
    db.flush()
    db.add(resource_metadata)
    db.flush()
    db.add_all(asset_rows)
    db.flush()
    db.add_all(asset_metadata)
    db.commit()
    assert first_asset_id == asset_rows[0].id
    return resource


def test_reader_production_code_does_not_use_media_version_contract() -> None:
    forbidden = (
        "LibraryMediaVersion",
        "ReaderMediaVersionDto",
        "mediaVersion",
        "mediaCompleted",
    )
    violations = [
        f"{path.relative_to(_API_ROOT)}:{token}"
        for path in _READER_ROOT.rglob("*.py")
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert violations == []


def test_reader_source_lookup_joins_book_and_resource() -> None:
    source = _SOURCE_REPOSITORY.read_text(encoding="utf-8")
    assert "LibraryMediaVersion" not in source
    context_source = inspect.getsource(SqlAlchemyReaderResourceRepository._get_context)
    assert "LibraryReadableResource.book_id == LibraryBook.id" in context_source
    assert "LibraryReadableResource.id == resource_id" in context_source


def test_audiobook_support_tests_do_not_reference_removed_file_hashes() -> None:
    source = _AUDIOBOOK_SUPPORT_TEST.read_text(encoding="utf-8")
    assert "fingerprint" not in source
    assert "`fingerprint`" not in source
    assert "`hashStatus`" not in source
    assert "`fullHash`" not in source
    assert "hash_status" not in source
    assert "full_hash" not in source


@pytest.mark.parametrize(
    ("fmt", "mime", "path_name"),
    [
        ("EPUB", "application/epub+zip", "book.epub"),
        ("PDF", "application/pdf", "book.pdf"),
        ("CBZ", "application/vnd.comicbook+zip", "book.cbz"),
        ("AZW3", "application/x-mobipocket-ebook", "book.azw3"),
    ],
)
def test_reader_resolves_book_and_source_through_resource_graph(
    db_session: Session,
    tmp_path: Path,
    fmt: str,
    mime: str,
    path_name: str,
) -> None:
    source_path = tmp_path / path_name
    source_path.write_bytes(b"src")
    suffix = fmt.lower()
    resource = _seed_catalog(
        db_session,
        book_id=f"book-{suffix}",
        resource_id=f"resource-{suffix}",
        title=f"{fmt} 资源",
        fmt=fmt,
        assets=((f"asset-{suffix}", str(source_path), "PRIMARY", mime, 0),),
    )

    context = SqlAlchemyReaderResourceRepository(db_session).get_context(resource.id)
    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        resource_id=resource.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert context is not None
    assert context.book.id == f"book-{suffix}"
    assert context.resource.id == resource.id
    assert context.resource.book_id == f"book-{suffix}"
    assert source is not None
    assert source.resource_id == resource.id
    assert source.asset_id == f"asset-{suffix}"
    assert source.path == str(source_path)
    assert source.source_format == fmt.lower()


@pytest.mark.parametrize(
    ("fmt", "role", "stored_mime", "path_name", "expected_mime"),
    [
        ("EPUB", "PRIMARY", None, "book.epub", "application/epub+zip"),
        (
            "AZW3",
            "PRIMARY",
            "application/octet-stream",
            "book.azw3",
            "application/vnd.amazon.ebook",
        ),
        ("CBR", "PRIMARY", None, "book.cbr", "application/vnd.comicbook-rar"),
        ("IMAGE_DIR", "PAGE", None, "page-001.png", "image/png"),
    ],
)
def test_reader_and_media_resolve_the_same_canonical_asset_mime(
    db_session: Session,
    tmp_path: Path,
    fmt: str,
    role: str,
    stored_mime: str | None,
    path_name: str,
    expected_mime: str,
) -> None:
    source_path = tmp_path / path_name
    source_path.write_bytes(b"original")
    suffix = fmt.lower()
    resource = _seed_catalog(
        db_session,
        book_id=f"book-mime-{suffix}",
        resource_id=f"resource-mime-{suffix}",
        title=f"{fmt} MIME",
        fmt=fmt,
        assets=((f"asset-mime-{suffix}", str(source_path), role, stored_mime, 0),),
    )

    reader_asset = SqlAlchemyReaderResourceRepository(db_session).list_assets(
        resource.id
    )[0]
    media_asset = SqlAlchemyMediaResourceRepository(db_session).get_asset(
        f"asset-mime-{suffix}"
    )

    assert reader_asset.mime_type == expected_mime
    assert media_asset is not None
    assert media_asset.mime_type == expected_mime


@pytest.mark.parametrize(
    ("filename", "expected_format", "expected_mime"),
    [
        ("book.mobi", "MOBI", "application/x-mobipocket-ebook"),
        ("book.azw", "AZW", "application/vnd.amazon.ebook"),
        ("book.azw3", "AZW3", "application/vnd.amazon.ebook"),
        ("book.prc", "PRC", "application/x-mobipocket-ebook"),
    ],
)
def test_mobi_family_catalog_uses_persisted_exact_reader_source_format(
    db_session: Session,
    tmp_path: Path,
    filename: str,
    expected_format: str,
    expected_mime: str,
) -> None:
    source_path = tmp_path / filename
    source_path.write_bytes(b"original")
    resource = _seed_catalog(
        db_session,
        book_id=f"book-{expected_format.lower()}",
        resource_id=f"resource-{expected_format.lower()}",
        title=expected_format,
        fmt=expected_format,
        assets=(
            (f"asset-{expected_format.lower()}", str(source_path), "PRIMARY", None, 0),
        ),
    )

    repository = SqlAlchemyReaderResourceRepository(db_session)
    context = repository.get_context(resource.id)
    assets = repository.list_assets(resource.id)
    publication_source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        resource_id=resource.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert context is not None
    assert context.resource.format == expected_format
    assert context.resource.source_format == expected_format
    assert assets[0].mime_type == expected_mime
    assert publication_source is not None
    assert publication_source.source_format == expected_format.lower()


def test_audiobook_lists_every_track_in_natural_path_order(
    db_session: Session,
    tmp_path: Path,
) -> None:
    first = tmp_path / "z-last-name.mp3"
    second = tmp_path / "a-first-name.mp3"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    resource = _seed_catalog(
        db_session,
        book_id="book-audio",
        resource_id="resource-audio",
        title="有声书",
        fmt="AUDIO",
        assets=(
            ("asset-audio-1", str(first), "TRACK", "audio/mpeg", 0),
            ("asset-audio-2", str(second), "TRACK", "audio/mpeg", 1),
        ),
    )

    repository = SqlAlchemyReaderResourceRepository(db_session)
    context = repository.get_context(resource.id)
    assets = repository.list_assets(resource.id)
    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        resource_id=resource.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert context is not None
    assert context.book.id == "book-audio"
    assert [asset.id for asset in assets] == ["asset-audio-2", "asset-audio-1"]
    assert [asset.sort_order for asset in assets] == [0, 1]
    assert source is not None
    assert source.asset_id == "asset-audio-1"
    assert source.path == str(first)


def test_reader_source_lookup_uses_resource_without_legacy_version_layer(
    db_session: Session,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "orphan.epub"
    source_path.write_bytes(b"epub")
    resource = _seed_catalog(
        db_session,
        book_id="book-orphan",
        resource_id="resource-orphan",
        title="无版本资源",
        fmt="EPUB",
        assets=(
            ("asset-orphan", str(source_path), "PRIMARY", "application/epub+zip", 0),
        ),
    )

    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        resource_id=resource.id,
        access_scope=_ADMIN_PUBLICATION,
    )
    repository = SqlAlchemyReaderResourceRepository(db_session)
    context = repository.get_context(resource.id)
    assets = repository.list_assets(resource.id)
    visible = repository.list_visible_resources_for_book("book-orphan", _ADMIN_READER)

    assert context is not None
    assert context.resource.id == resource.id
    assert source is not None
    assert source.path == str(source_path)
    assert [asset.id for asset in assets] == ["asset-orphan"]
    assert [item.id for item in visible] == [resource.id]


def test_reader_source_resolves_relative_path_against_library_root(
    db_session: Session,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "relative.epub"
    source_path.write_bytes(b"epub")
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(tmp_path)
    resource = _seed_catalog(
        db_session,
        book_id="book-relative",
        resource_id="resource-relative",
        title="相对路径资源",
        fmt="EPUB",
        assets=(
            ("asset-relative", source_path.name, "PRIMARY", "application/epub+zip", 0),
        ),
    )

    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        resource_id=resource.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert source is not None
    assert source.path == source_path.name
    assert source.library_root == str(tmp_path)
    assert (
        resolve_publication_source(source.path, Path(source.library_root))
        == source_path
    )


def test_missing_source_file_keeps_unavailable_error(
    db_session: Session,
    test_settings: Settings,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "gone.epub"
    resource = _seed_catalog(
        db_session,
        book_id="book-missing",
        resource_id="resource-missing",
        title="缺失源文件",
        fmt="EPUB",
        assets=(("asset-missing", str(missing), "PRIMARY", "application/epub+zip", 0),),
    )
    source = SqlAlchemyPublicationSourceRepository(db_session).find_source(
        resource_id=resource.id,
        access_scope=_ADMIN_PUBLICATION,
    )

    assert source is not None
    with pytest.raises(PublicationNotFoundError) as missing_error:
        resolve_publication_source(source.path, test_settings.resolved_storage_root)
    assert isinstance(missing_error.value.__cause__, FileNotFoundError)
    assert missing_error.value.code == "PUBLICATION_NOT_FOUND"
    assert (
        SqlAlchemyReaderResourceRepository(db_session)
        .list_visible_resources_for_book("book-missing", _ADMIN_READER)[0]
        .id
        == resource.id
    )
