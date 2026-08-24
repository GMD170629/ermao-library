"""SQLite repository invariants for ADR 0018 SourceNode / Book / Resource / Asset."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.publication_metadata import PublicationMetadata
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library
from app.modules.library.application.source_tree_ports import (
    AdapterIdentity,
    ObservedSourceEntry,
)
from app.modules.library.domain.readable_resource_anchors import (
    ReadableResourceAnchorViolationCode,
    ReadableResourceTopologyError,
)
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    AssetRole,
)
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    SourceNodeTopologyError,
    SourceNodeViolationCode,
)
from app.modules.library.infrastructure.persistence.source_tree_repository import (
    SqlAlchemyBookResourceRepository,
    SqlAlchemySourceNodeRepository,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime(2024, 7, 1, tzinfo=UTC)


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _add_library(
    db: Session,
    tmp_path: Path,
    library_id: str = "lib-1",
    *,
    organization_mode: str = "FLAT",
) -> None:
    db.add(
        Library(
            id=library_id,
            name=library_id,
            root_path=str(tmp_path / library_id),
            organization_mode=organization_mode,
        )
    )


def _entry(
    relative_path: str,
    kind: SourceNodePhysicalKind,
    *,
    size: int | None = 1,
) -> ObservedSourceEntry:
    path = SourceNodeRelativePath(relative_path)
    return ObservedSourceEntry(
        relative_path=path,
        physical_kind=kind,
        observed_size_bytes=None if kind is SourceNodePhysicalKind.DIRECTORY else size,
        observed_mtime_ns=1,
        observed_at=_now(),
    )


def _adapter() -> AdapterIdentity:
    return AdapterIdentity(
        adapter_id="epub",
        adapter_version="1",
        format_label="EPUB",
    )


def test_insert_root_and_direct_child_succeed(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            root, created = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("Series", SourceNodePhysicalKind.DIRECTORY),
            )
            assert created is True
            child, created_child = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=root.id,
                entry=_entry("Series/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            assert created_child is True
            assert child.parent_id == root.id
            db.commit()
    finally:
        engine.dispose()


def test_insert_rejects_missing_parent_and_rolls_back(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            with pytest.raises(SourceNodeTopologyError) as caught:
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=None,
                    entry=_entry("Series/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
                )
            assert caught.value.code is SourceNodeViolationCode.PARENT_PATH_MISMATCH
            db.rollback()
            assert db.scalar(select(LibrarySourceNode)) is None
    finally:
        engine.dispose()


def test_insert_rejects_wrong_parent_path_and_non_directory(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            file_node, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("file.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            other_dir, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("Other", SourceNodePhysicalKind.DIRECTORY),
            )
            with pytest.raises(SourceNodeTopologyError) as wrong:
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=other_dir.id,
                    entry=_entry("Series/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
                )
            assert wrong.value.code is SourceNodeViolationCode.PARENT_PATH_MISMATCH
            with pytest.raises(SourceNodeTopologyError) as nondir:
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=file_node.id,
                    entry=_entry(
                        "file.epub/nested.epub",
                        SourceNodePhysicalKind.REGULAR_FILE,
                    ),
                )
            assert nondir.value.code is SourceNodeViolationCode.PARENT_NOT_DIRECTORY
    finally:
        engine.dispose()


def test_insert_rejects_cross_library_parent(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path, "lib-1")
            _add_library(db, tmp_path, "lib-2")
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            parent, _ = nodes.insert_if_absent(
                library_id="lib-2",
                parent_id=None,
                entry=_entry("Series", SourceNodePhysicalKind.DIRECTORY),
            )
            with pytest.raises(SourceNodeTopologyError) as caught:
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=parent.id,
                    entry=_entry("Series/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
                )
            assert caught.value.code is SourceNodeViolationCode.CROSS_LIBRARY_PARENT
    finally:
        engine.dispose()


def test_insert_idempotent_and_path_key_collision(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            first, created = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("a.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            again, created_again = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("a.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            assert created is True and created_again is False
            assert again.id == first.id

            # Forge a colliding pathKey with a different relativePath via ORM.
            forged = LibrarySourceNode(
                id="forged",
                library_id="lib-1",
                parent_id=None,
                parent_physical_kind=None,
                relative_path="forged-visible.epub",
                path_key=_path_key("collision-target.epub"),
                name="forged-visible.epub",
                physical_kind="REGULAR_FILE",
                observed_size_bytes=1,
                observed_mtime_ns=1,
                observed_at=_now(),
            )
            db.add(forged)
            db.flush()
            with pytest.raises(SourceNodeTopologyError) as caught:
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=None,
                    entry=_entry(
                        "collision-target.epub",
                        SourceNodePhysicalKind.REGULAR_FILE,
                    ),
                )
            assert caught.value.code is SourceNodeViolationCode.PATH_KEY_COLLISION
    finally:
        engine.dispose()


def test_insert_missing_parent_id_raises_parent_not_found(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            with pytest.raises(SourceNodeTopologyError) as caught:
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id="missing-parent",
                    entry=_entry("Series/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
                )
            assert caught.value.code is SourceNodeViolationCode.PARENT_NOT_FOUND
    finally:
        engine.dispose()


def test_book_and_resource_library_and_anchor_scope(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path, "lib-1")
            _add_library(db, tmp_path, "lib-2")
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            books = SqlAlchemyBookResourceRepository(db)
            directory, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("book", SourceNodePhysicalKind.DIRECTORY),
            )
            child, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=directory.id,
                entry=_entry("book/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            sibling_dir, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("book-other", SourceNodePhysicalKind.DIRECTORY),
            )
            sibling, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=sibling_dir.id,
                entry=_entry("book-other/a.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            foreign, _ = nodes.insert_if_absent(
                library_id="lib-2",
                parent_id=None,
                entry=_entry("x.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            file_root, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("solo.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )

            with pytest.raises(ReadableResourceTopologyError) as cross:
                books.ensure_book(
                    library_id="lib-1",
                    source_node_id=foreign.id,
                    title="X",
                )
            assert cross.value.code is ReadableResourceAnchorViolationCode.CROSS_LIBRARY

            book_id = books.ensure_book(
                library_id="lib-1", source_node_id=directory.id, title="Book"
            )
            assert (
                books.ensure_book(
                    library_id="lib-1", source_node_id=directory.id, title="Book"
                )
                == book_id
            )

            resource = books.create_pending_resource(
                library_id="lib-1",
                book_id=book_id,
                source_node_id=child.id,
                adapter=_adapter(),
            )
            again = books.create_pending_resource(
                library_id="lib-1",
                book_id=book_id,
                source_node_id=child.id,
                adapter=_adapter(),
            )
            assert again.id == resource.id

            with pytest.raises(ReadableResourceTopologyError) as prefix:
                books.create_pending_resource(
                    library_id="lib-1",
                    book_id=book_id,
                    source_node_id=sibling.id,
                    adapter=_adapter(),
                )
            assert (
                prefix.value.code
                is ReadableResourceAnchorViolationCode.RESOURCE_OUT_OF_BOOK_SCOPE
            )

            file_book = books.ensure_book(
                library_id="lib-1", source_node_id=file_root.id, title="Solo"
            )
            with pytest.raises(ReadableResourceTopologyError) as file_scope:
                books.create_pending_resource(
                    library_id="lib-1",
                    book_id=file_book,
                    source_node_id=sibling.id,
                    adapter=_adapter(),
                )
            assert (
                file_scope.value.code
                is ReadableResourceAnchorViolationCode.RESOURCE_OUT_OF_BOOK_SCOPE
            )

            # Same SourceNode cannot anchor a second Resource under another Book.
            other_book = books.ensure_book(
                library_id="lib-1",
                source_node_id=sibling.id,
                title="Other",
            )
            with pytest.raises(ReadableResourceTopologyError) as dup:
                books.create_pending_resource(
                    library_id="lib-1",
                    book_id=other_book,
                    source_node_id=child.id,
                    adapter=_adapter(),
                )
            assert (
                dup.value.code
                is ReadableResourceAnchorViolationCode.RESOURCE_ALREADY_ANCHORED
            )
    finally:
        engine.dispose()


def test_local_metadata_projects_to_flat_book_with_same_source_anchor(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            books = SqlAlchemyBookResourceRepository(db)
            source, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("solo.epub", SourceNodePhysicalKind.REGULAR_FILE),
            )
            book_id = books.ensure_book(
                library_id="lib-1", source_node_id=source.id, title="solo"
            )
            resource = books.create_pending_resource(
                library_id="lib-1",
                book_id=book_id,
                source_node_id=source.id,
                adapter=_adapter(),
            )

            books.apply_local_metadata(
                resource_id=resource.id,
                metadata=PublicationMetadata(
                    title="Embedded Title",
                    authors=("Author One", "Author Two"),
                    description="Description",
                    series_name="Series",
                    series_index=2.0,
                    language="zh-CN",
                    publisher="Publisher",
                    identifier="book-id",
                ),
                cover_path="covers/solo.jpg",
            )

            book_metadata = db.get(LibraryBookMetadata, book_id)
            assert book_metadata is not None
            assert book_metadata.title == "Embedded Title"
            assert book_metadata.normalized_title == "embedded title"
            assert book_metadata.author == "Author One / Author Two"
            assert book_metadata.normalized_author == "author one / author two"
            assert book_metadata.description == "Description"
            assert book_metadata.series_name == "Series"
            assert book_metadata.series_index == 2.0
            assert book_metadata.metadata_quality > 0
            assert book_metadata.cover_path == "covers/solo.jpg"
            assert book_metadata.cover_status == "READY"

            resource_metadata = db.get(LibraryReadableResourceMetadata, resource.id)
            assert resource_metadata is not None
            assert resource_metadata.title == "Embedded Title"
            assert resource_metadata.description == "Description"
            assert resource_metadata.language == "zh-CN"
            assert resource_metadata.publisher == "Publisher"
            assert resource_metadata.identifier == "book-id"
            assert resource_metadata.cover_path == "covers/solo.jpg"
            assert resource_metadata.cover_status == "READY"

            books.clear_local_cover(
                resource_id=resource.id,
                expected_path="covers/stale.jpg",
            )
            assert book_metadata.cover_path == "covers/solo.jpg"
            assert resource_metadata.cover_path == "covers/solo.jpg"

            books.clear_local_cover(
                resource_id=resource.id,
                expected_path="covers/solo.jpg",
            )
            assert book_metadata.cover_path is None
            assert book_metadata.cover_status == "FAILED"
            assert resource_metadata.cover_path is None
            assert resource_metadata.cover_status == "FAILED"
    finally:
        engine.dispose()


@pytest.mark.parametrize("import_order", ((0, 1), (1, 0)))
def test_descendant_resource_metadata_never_overwrites_volume_book(
    tmp_path: Path,
    import_order: tuple[int, int],
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path, organization_mode="VOLUMES")
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            books = SqlAlchemyBookResourceRepository(db)
            directory, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("Series", SourceNodePhysicalKind.DIRECTORY),
            )
            children = [
                nodes.insert_if_absent(
                    library_id="lib-1",
                    parent_id=directory.id,
                    entry=_entry(
                        f"Series/{index}.epub",
                        SourceNodePhysicalKind.REGULAR_FILE,
                    ),
                )[0]
                for index in (1, 2)
            ]
            book_id = books.ensure_book(
                library_id="lib-1", source_node_id=directory.id, title="Series"
            )
            book_metadata = db.get(LibraryBookMetadata, book_id)
            assert book_metadata is not None
            book_metadata.author = "Curated Author"
            book_metadata.normalized_author = "curated author"
            book_metadata.description = "Curated Description"
            book_metadata.series_name = "Curated Series"
            book_metadata.series_index = 9.0
            book_metadata.metadata_quality = 91
            book_metadata.cover_path = "covers/curated.jpg"
            book_metadata.cover_status = "READY"

            resources = [
                books.create_pending_resource(
                    library_id="lib-1",
                    book_id=book_id,
                    source_node_id=child.id,
                    adapter=_adapter(),
                )
                for child in children
            ]
            publications = [
                PublicationMetadata(
                    title="Embedded One",
                    volume_title="Volume One",
                    authors=("File Author One",),
                    description="File Description One",
                    series_name="File Series One",
                    series_index=1.0,
                    language="en",
                ),
                PublicationMetadata(
                    title="Embedded Two",
                    volume_title="Volume Two",
                    authors=("File Author Two",),
                    description="File Description Two",
                    series_name="File Series Two",
                    series_index=2.0,
                    language="zh-CN",
                ),
            ]
            for index in import_order:
                books.apply_local_metadata(
                    resource_id=resources[index].id,
                    metadata=publications[index],
                    cover_path=f"covers/child-{index + 1}.jpg",
                )

            assert book_metadata.title == "Series"
            assert book_metadata.normalized_title == "series"
            assert book_metadata.author == "Curated Author"
            assert book_metadata.normalized_author == "curated author"
            assert book_metadata.description == "Curated Description"
            assert book_metadata.series_name == "Curated Series"
            assert book_metadata.series_index == 9.0
            assert book_metadata.metadata_quality == 91
            assert book_metadata.cover_path == "covers/curated.jpg"
            assert book_metadata.cover_status == "READY"

            first_metadata = db.get(LibraryReadableResourceMetadata, resources[0].id)
            second_metadata = db.get(LibraryReadableResourceMetadata, resources[1].id)
            assert first_metadata is not None
            assert first_metadata.title == "Volume One"
            assert first_metadata.description == "File Description One"
            assert first_metadata.language == "en"
            assert first_metadata.cover_path == "covers/child-1.jpg"
            assert second_metadata is not None
            assert second_metadata.title == "Volume Two"
            assert second_metadata.description == "File Description Two"
            assert second_metadata.language == "zh-CN"
            assert second_metadata.cover_path == "covers/child-2.jpg"

            books.clear_local_cover(
                resource_id=resources[0].id,
                expected_path="covers/child-1.jpg",
            )
            assert first_metadata.cover_path is None
            assert first_metadata.cover_status == "FAILED"
            assert book_metadata.cover_path == "covers/curated.jpg"
            assert book_metadata.cover_status == "READY"
    finally:
        engine.dispose()


def test_asset_scope_ready_count_and_multi_resource_share(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.commit()
            nodes = SqlAlchemySourceNodeRepository(db)
            books = SqlAlchemyBookResourceRepository(db)
            album, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("album", SourceNodePhysicalKind.DIRECTORY),
            )
            track, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=album.id,
                entry=_entry("album/a.mp3", SourceNodePhysicalKind.REGULAR_FILE),
            )
            outside, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("other.mp3", SourceNodePhysicalKind.REGULAR_FILE),
            )
            directory_symlink, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=None,
                entry=_entry("link", SourceNodePhysicalKind.SYMLINK, size=1),
            )

            book_id = books.ensure_book(
                library_id="lib-1", source_node_id=album.id, title="Album"
            )
            dir_resource = books.create_pending_resource(
                library_id="lib-1",
                book_id=book_id,
                source_node_id=album.id,
                adapter=AdapterIdentity(
                    adapter_id="audiobook-directory",
                    adapter_version="1",
                    format_label="AUDIOBOOK_DIR",
                ),
            )
            file_book = books.ensure_book(
                library_id="lib-1", source_node_id=outside.id, title="Outside"
            )
            file_resource = books.create_pending_resource(
                library_id="lib-1",
                book_id=file_book,
                source_node_id=outside.id,
                adapter=_adapter(),
            )

            asset_id = books.upsert_asset(
                library_id="lib-1",
                resource_id=dir_resource.id,
                source_node_id=track.id,
                role=AssetRole.TRACK,
                import_state=AssetImportState.READY,
                sequence_index=1,
                sort_key="a.mp3",
                failure_reason=None,
            )
            reused = books.upsert_asset(
                library_id="lib-1",
                resource_id=dir_resource.id,
                source_node_id=track.id,
                role=AssetRole.TRACK,
                import_state=AssetImportState.READY,
                sequence_index=1,
                sort_key="a.mp3",
                failure_reason=None,
            )
            assert reused == asset_id

            # Same SourceNode may be referenced by another covering Resource.
            covering_book = books.ensure_book(
                library_id="lib-1",
                source_node_id=track.id,
                title="Track Book",
            )
            covering = books.create_pending_resource(
                library_id="lib-1",
                book_id=covering_book,
                source_node_id=track.id,
                adapter=_adapter(),
            )
            shared = books.upsert_asset(
                library_id="lib-1",
                resource_id=covering.id,
                source_node_id=track.id,
                role=AssetRole.PRIMARY,
                import_state=AssetImportState.READY,
                sequence_index=None,
                sort_key="a.mp3",
                failure_reason=None,
            )
            assert shared != asset_id

            with pytest.raises(ReadableResourceTopologyError) as out_of_scope:
                books.upsert_asset(
                    library_id="lib-1",
                    resource_id=dir_resource.id,
                    source_node_id=outside.id,
                    role=AssetRole.TRACK,
                    import_state=AssetImportState.READY,
                    sequence_index=None,
                    sort_key="x",
                    failure_reason=None,
                )
            assert (
                out_of_scope.value.code
                is ReadableResourceAnchorViolationCode.ASSET_OUT_OF_RESOURCE_SCOPE
            )

            with pytest.raises(ReadableResourceTopologyError) as file_only:
                books.upsert_asset(
                    library_id="lib-1",
                    resource_id=file_resource.id,
                    source_node_id=track.id,
                    role=AssetRole.PRIMARY,
                    import_state=AssetImportState.READY,
                    sequence_index=None,
                    sort_key="x",
                    failure_reason=None,
                )
            assert (
                file_only.value.code
                is ReadableResourceAnchorViolationCode.ASSET_OUT_OF_RESOURCE_SCOPE
            )

            with pytest.raises(ReadableResourceTopologyError) as not_file:
                books.upsert_asset(
                    library_id="lib-1",
                    resource_id=dir_resource.id,
                    source_node_id=directory_symlink.id,
                    role=AssetRole.TRACK,
                    import_state=AssetImportState.READY,
                    sequence_index=None,
                    sort_key="x",
                    failure_reason=None,
                )
            assert (
                not_file.value.code
                is ReadableResourceAnchorViolationCode.ASSET_SOURCE_NOT_REGULAR_FILE
            )

            books.upsert_asset(
                library_id="lib-1",
                resource_id=dir_resource.id,
                source_node_id=track.id,
                role=AssetRole.TRACK,
                import_state=AssetImportState.FAILED,
                sequence_index=1,
                sort_key="a.mp3",
                failure_reason="PARSE_FAILED",
            )
            # Add a second READY asset via another descendant.
            track2, _ = nodes.insert_if_absent(
                library_id="lib-1",
                parent_id=album.id,
                entry=_entry("album/b.mp3", SourceNodePhysicalKind.REGULAR_FILE),
            )
            books.upsert_asset(
                library_id="lib-1",
                resource_id=dir_resource.id,
                source_node_id=track2.id,
                role=AssetRole.TRACK,
                import_state=AssetImportState.READY,
                sequence_index=2,
                sort_key="b.mp3",
                failure_reason=None,
            )
            assert books.count_ready_assets(dir_resource.id) == 1
    finally:
        engine.dispose()


def test_schema_uniques_and_metadata_cascade(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            node = LibrarySourceNode(
                id="n1",
                library_id="lib-1",
                parent_id=None,
                relative_path="a.epub",
                path_key=_path_key("a.epub"),
                name="a.epub",
                physical_kind="REGULAR_FILE",
                observed_size_bytes=1,
                observed_mtime_ns=0,
                observed_at=_now(),
            )
            db.add(node)
            db.flush()
            db.add(LibrarySourceNodeMetadata(source_node_id="n1", title="A"))
            db.flush()
            db.add(LibraryBook(id="b1", library_id="lib-1", source_node_id="n1"))
            db.flush()
            db.add(LibraryBookMetadata(book_id="b1", title="A", normalized_title="a"))
            db.flush()
            db.add(
                LibraryReadableResource(
                    id="r1",
                    library_id="lib-1",
                    book_id="b1",
                    source_node_id="n1",
                    adapter_id="epub",
                    adapter_version="1",
                    format="EPUB",
                    enablement_state="ENABLED",
                    import_state="READY",
                )
            )
            db.flush()
            db.add(LibraryReadableResourceMetadata(resource_id="r1", title="A"))
            db.flush()
            db.add(
                LibraryResourceAsset(
                    id="a1",
                    library_id="lib-1",
                    resource_id="r1",
                    source_node_id="n1",
                    source_node_physical_kind="REGULAR_FILE",
                    role="PRIMARY",
                    import_state="READY",
                )
            )
            db.flush()
            db.add(LibraryResourceAssetMetadata(asset_id="a1"))
            db.commit()

            with pytest.raises(IntegrityError):
                db.add(LibraryBook(id="b2", library_id="lib-1", source_node_id="n1"))
                db.flush()
            db.rollback()

            with pytest.raises(IntegrityError):
                db.add(
                    LibraryReadableResource(
                        id="r2",
                        library_id="lib-1",
                        book_id="b1",
                        source_node_id="n1",
                        adapter_id="epub",
                        adapter_version="1",
                        format="EPUB",
                        enablement_state="ENABLED",
                        import_state="PENDING",
                    )
                )
                db.flush()
            db.rollback()

            with pytest.raises(IntegrityError):
                db.add(
                    LibraryResourceAsset(
                        id="a2",
                        library_id="lib-1",
                        resource_id="r1",
                        source_node_id="n1",
                        source_node_physical_kind="REGULAR_FILE",
                        role="PRIMARY",
                        import_state="READY",
                    )
                )
                db.flush()
            db.rollback()

            db.delete(db.get(LibrarySourceNode, "n1"))
            db.commit()
            assert db.get(LibrarySourceNodeMetadata, "n1") is None
            assert db.get(LibraryBook, "b1") is None
            assert db.get(LibraryBookMetadata, "b1") is None
            assert db.get(LibraryReadableResource, "r1") is None
            assert db.get(LibraryReadableResourceMetadata, "r1") is None
            assert db.get(LibraryResourceAsset, "a1") is None
            assert db.get(LibraryResourceAssetMetadata, "a1") is None
    finally:
        engine.dispose()
