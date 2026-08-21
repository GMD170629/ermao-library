"""SQLite integration: ADR 0018 SourceNode delete / mode switch / relocate."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
)
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
    LibrarySourceNodeMetadata,
)


def _path_key(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return f"v1:{digest}"


def _now() -> datetime:
    return datetime(2024, 6, 1, tzinfo=UTC)


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _add_library(
    db: Session,
    root: Path,
    *,
    library_id: str = "lib-1",
    organization_mode: str = "FLAT",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    db.add(
        Library(
            id=library_id,
            name="Lib",
            root_path=str(root.resolve()),
            organization_mode=organization_mode,
            min_file_size_bytes=0,
        )
    )


def _node(
    *,
    node_id: str,
    relative_path: str,
    physical_kind: str,
    parent_id: str | None = None,
    library_id: str = "lib-1",
    size: int | None = 1,
) -> LibrarySourceNode:
    name = relative_path.rsplit("/", 1)[-1]
    parent_kind = None if parent_id is None else "DIRECTORY"
    return LibrarySourceNode(
        id=node_id,
        library_id=library_id,
        parent_id=parent_id,
        parent_physical_kind=parent_kind,
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=name,
        physical_kind=physical_kind,
        observed_size_bytes=None if physical_kind == "DIRECTORY" else size,
        observed_mtime_ns=1,
        observed_at=_now(),
    )


class StubOkAdapter(ResourceAdapterExecutorPort):
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
    ) -> FileParseResult:
        return FileParseResult(
            ok=True,
            adapter=adapter,
            resource_title=absolute_path.stem,
            asset=ParsedAssetPayload(
                title=absolute_path.stem,
                role=role,
                sequence_index=None,
                sort_key=absolute_path.name,
                mime_type=None,
                duration_ms=None,
                failure_reason=None,
                technical=AssetTechnicalMetadata(),
            ),
            error_code=None,
            error_summary=None,
        )


def _seed_full_target_topology(db: Session, root: Path) -> dict[str, str]:
    """Seed SourceNodes/Books/Resources/Assets/metadata and mixed tasks."""
    (root / "album").mkdir(parents=True, exist_ok=True)
    (root / "album" / "track.mp3").write_bytes(b"audio")
    (root / "outer.epub").write_bytes(b"epub")
    (root / "shared.mp3").write_bytes(b"audio")

    album = _node(
        node_id="node-album",
        relative_path="album",
        physical_kind="DIRECTORY",
        size=None,
    )
    track = _node(
        node_id="node-track",
        relative_path="album/track.mp3",
        physical_kind="REGULAR_FILE",
        parent_id="node-album",
    )
    outer = _node(
        node_id="node-outer",
        relative_path="outer.epub",
        physical_kind="REGULAR_FILE",
    )
    shared = _node(
        node_id="node-shared",
        relative_path="shared.mp3",
        physical_kind="REGULAR_FILE",
    )
    db.add_all([album, track, outer, shared])
    db.flush()
    db.add_all(
        [
            LibrarySourceNodeMetadata(source_node_id="node-album", title="Album"),
            LibrarySourceNodeMetadata(source_node_id="node-track", title="Track"),
            LibrarySourceNodeInterpretation(
                source_node_id="node-album",
                result="RESOURCE",
                source="AUTO",
                adapter_id="audiobook-directory",
                adapter_version="1",
                reason_code="UNIQUE_ADAPTER",
            ),
            LibrarySourceNodeInterpretation(
                source_node_id="node-outer",
                result="RESOURCE",
                source="AUTO",
                adapter_id="epub",
                adapter_version="1",
                reason_code="UNIQUE_ADAPTER",
            ),
        ]
    )
    db.add_all(
        [
            LibraryBook(
                id="book-album", library_id="lib-1", source_node_id="node-album"
            ),
            LibraryBook(
                id="book-outer", library_id="lib-1", source_node_id="node-outer"
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            LibraryBookMetadata(
                book_id="book-album",
                title="Album Book",
                normalized_title="album book",
            ),
            LibraryBookMetadata(
                book_id="book-outer",
                title="Outer Book",
                normalized_title="outer book",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            LibraryReadableResource(
                id="res-album",
                library_id="lib-1",
                book_id="book-album",
                source_node_id="node-album",
                adapter_id="audiobook-directory",
                adapter_version="1",
                media_kind="AUDIO",
                format="AUDIOBOOK_DIR",
                enablement_state="ENABLED",
                import_state="READY",
            ),
            LibraryReadableResource(
                id="res-outer",
                library_id="lib-1",
                book_id="book-outer",
                source_node_id="node-outer",
                adapter_id="epub",
                adapter_version="1",
                media_kind="TEXT",
                format="EPUB",
                enablement_state="ENABLED",
                import_state="READY",
            ),
        ]
    )
    db.add_all(
        [
            LibraryReadableResourceMetadata(
                resource_id="res-album", title="Album Resource"
            ),
            LibraryReadableResourceMetadata(
                resource_id="res-outer", title="Outer Resource"
            ),
        ]
    )
    # Album owns track; outer also references shared as TRACK-like sibling asset.
    db.add_all(
        [
            LibraryResourceAsset(
                id="asset-track",
                library_id="lib-1",
                resource_id="res-album",
                source_node_id="node-track",
                source_node_physical_kind="REGULAR_FILE",
                role="TRACK",
                import_state="READY",
            ),
            LibraryResourceAsset(
                id="asset-outer-primary",
                library_id="lib-1",
                resource_id="res-outer",
                source_node_id="node-outer",
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            ),
            LibraryResourceAsset(
                id="asset-outer-shared",
                library_id="lib-1",
                resource_id="res-outer",
                source_node_id="node-shared",
                source_node_physical_kind="REGULAR_FILE",
                role="SUPPLEMENT",
                import_state="READY",
            ),
        ]
    )
    db.flush()
    db.add(LibraryResourceAssetMetadata(asset_id="asset-track"))
    db.add_all(
        [
            LibraryImportTask(
                id="task-scan",
                kind="SCAN_LIBRARY",
                library_id="lib-1",
                state="QUEUED",
            ),
            LibraryImportTask(
                id="task-continue",
                kind="CONTINUE_SOURCE",
                library_id="lib-1",
                source_node_id="node-album",
                state="QUEUED",
            ),
            LibraryImportTask(
                id="task-import-track",
                kind="IMPORT_ASSET",
                library_id="lib-1",
                resource_id="res-album",
                source_node_id="node-track",
                role="TRACK",
                state="SUCCEEDED",
            ),
            LibraryImportTask(
                id="task-import-outer",
                kind="IMPORT_ASSET",
                library_id="lib-1",
                resource_id="res-outer",
                source_node_id="node-outer",
                role="PRIMARY",
                state="SUCCEEDED",
            ),
        ]
    )
    db.flush()
    return {
        "album": "node-album",
        "track": "node-track",
        "outer": "node-outer",
        "shared": "node-shared",
        "res_album": "res-album",
        "res_outer": "res-outer",
    }


def test_organization_mode_switch_clears_target_topology_and_queues_fresh_scan(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            _seed_full_target_topology(db, root)
            db.commit()
            pipeline = build_readable_resource_pipeline(db)
            result = pipeline.change_library_organization_mode.execute(
                "lib-1", "VOLUMES"
            )
            assert result.ok is True
            db.commit()

            library = db.get(Library, "lib-1")
            assert library is not None
            assert library.organization_mode == "VOLUMES"
            assert db.scalar(select(func.count()).select_from(LibrarySourceNode)) == 0
            assert db.scalar(select(func.count()).select_from(LibraryBook)) == 0
            assert (
                db.scalar(select(func.count()).select_from(LibraryReadableResource))
                == 0
            )
            assert (
                db.scalar(select(func.count()).select_from(LibraryResourceAsset)) == 0
            )
            assert (
                db.scalar(select(func.count()).select_from(LibrarySourceNodeMetadata))
                == 0
            )
            assert db.scalar(select(func.count()).select_from(LibraryBookMetadata)) == 0
            tasks = db.scalars(select(LibraryImportTask)).all()
            assert len(tasks) == 1
            task = tasks[0]
            assert task.kind == "SCAN_LIBRARY"
            assert task.state == "QUEUED"
            assert task.library_id == "lib-1"
            assert task.resource_id is None
            assert task.source_node_id is None
            assert task.role is None
            assert task.id != "task-scan"

            # Second switch must still leave exactly one fresh SCAN_LIBRARY.
            result2 = pipeline.change_library_organization_mode.execute("lib-1", "FLAT")
            assert result2.ok is True
            db.commit()
            tasks2 = db.scalars(select(LibraryImportTask)).all()
            assert len(tasks2) == 1
            assert tasks2[0].kind == "SCAN_LIBRARY"
            assert tasks2[0].state == "QUEUED"
            assert tasks2[0].id != task.id
            library2 = db.get(Library, "lib-1")
            assert library2 is not None
            assert library2.organization_mode == "FLAT"
    finally:
        engine.dispose()


def test_illegal_organization_mode_has_no_side_effects(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            ids = _seed_full_target_topology(db, root)
            db.commit()
            pipeline = build_readable_resource_pipeline(db)
            result = pipeline.change_library_organization_mode.execute(
                "lib-1", "AUDIOBOOK"
            )
            assert result.ok is False
            assert result.code == "UNSUPPORTED_MODE"
            db.expire_all()
            library = db.get(Library, "lib-1")
            assert library is not None
            assert library.organization_mode == "FLAT"
            assert db.get(LibrarySourceNode, ids["album"]) is not None
            assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 4
    finally:
        engine.dispose()


def test_delete_subtree_cleans_cross_resource_assets_and_keeps_ready_survivor(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            # Outer resource READY via own primary + shared supplement.
            # Shared file lives under album subtree for this delete scenario.
            (root / "album").mkdir(parents=True, exist_ok=True)
            (root / "album" / "track.mp3").write_bytes(b"a")
            (root / "album" / "shared.mp3").write_bytes(b"a")
            (root / "outer.epub").write_bytes(b"e")

            album = _node(
                node_id="node-album",
                relative_path="album",
                physical_kind="DIRECTORY",
                size=None,
            )
            track = _node(
                node_id="node-track",
                relative_path="album/track.mp3",
                physical_kind="REGULAR_FILE",
                parent_id="node-album",
            )
            shared = _node(
                node_id="node-shared",
                relative_path="album/shared.mp3",
                physical_kind="REGULAR_FILE",
                parent_id="node-album",
            )
            outer = _node(
                node_id="node-outer",
                relative_path="outer.epub",
                physical_kind="REGULAR_FILE",
            )
            db.add_all([album, track, shared, outer])
            db.add(LibrarySourceNodeMetadata(source_node_id="node-track", title="T"))
            db.add(
                LibraryBook(
                    id="book-album", library_id="lib-1", source_node_id="node-album"
                )
            )
            db.add(
                LibraryBook(
                    id="book-outer", library_id="lib-1", source_node_id="node-outer"
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res-album",
                    library_id="lib-1",
                    book_id="book-album",
                    source_node_id="node-album",
                    adapter_id="audiobook-directory",
                    adapter_version="1",
                    media_kind="AUDIO",
                    format="AUDIOBOOK_DIR",
                    enablement_state="ENABLED",
                    import_state="READY",
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res-outer",
                    library_id="lib-1",
                    book_id="book-outer",
                    source_node_id="node-outer",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="TEXT",
                    format="EPUB",
                    enablement_state="ENABLED",
                    import_state="READY",
                )
            )
            db.add_all(
                [
                    LibraryResourceAsset(
                        id="asset-track",
                        library_id="lib-1",
                        resource_id="res-album",
                        source_node_id="node-track",
                        source_node_physical_kind="REGULAR_FILE",
                        role="TRACK",
                        import_state="READY",
                    ),
                    LibraryResourceAsset(
                        id="asset-outer-primary",
                        library_id="lib-1",
                        resource_id="res-outer",
                        source_node_id="node-outer",
                        source_node_physical_kind="REGULAR_FILE",
                        role="PRIMARY",
                        import_state="READY",
                    ),
                    LibraryResourceAsset(
                        id="asset-outer-shared",
                        library_id="lib-1",
                        resource_id="res-outer",
                        source_node_id="node-shared",
                        source_node_physical_kind="REGULAR_FILE",
                        role="SUPPLEMENT",
                        import_state="READY",
                    ),
                ]
            )
            db.add(
                LibraryImportTask(
                    id="task-import-shared",
                    kind="IMPORT_ASSET",
                    library_id="lib-1",
                    resource_id="res-outer",
                    source_node_id="node-shared",
                    role="SUPPLEMENT",
                    state="SUCCEEDED",
                )
            )
            db.add(
                LibraryImportTask(
                    id="task-continue-album",
                    kind="CONTINUE_SOURCE",
                    library_id="lib-1",
                    source_node_id="node-album",
                    state="QUEUED",
                )
            )
            db.commit()

            pipeline = build_readable_resource_pipeline(db)
            result = pipeline.delete_source_node.execute("node-album")
            assert result.ok is True
            db.commit()

            assert db.get(LibrarySourceNode, "node-album") is None
            assert db.get(LibrarySourceNode, "node-track") is None
            assert db.get(LibrarySourceNode, "node-shared") is None
            assert db.get(LibrarySourceNodeMetadata, "node-track") is None
            assert db.get(LibraryBook, "book-album") is None
            assert db.get(LibraryReadableResource, "res-album") is None
            assert db.get(LibraryResourceAsset, "asset-track") is None
            assert db.get(LibraryResourceAsset, "asset-outer-shared") is None
            assert db.get(LibraryImportTask, "task-import-shared") is None
            assert db.get(LibraryImportTask, "task-continue-album") is None

            survivor = db.get(LibraryReadableResource, "res-outer")
            assert survivor is not None
            assert survivor.import_state == "READY"
            assert db.get(LibraryResourceAsset, "asset-outer-primary") is not None
            assert db.get(LibrarySourceNode, "node-outer") is not None
    finally:
        engine.dispose()


def test_delete_subtree_marks_survivor_failed_without_ready_assets(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            (root / "album").mkdir(parents=True, exist_ok=True)
            (root / "album" / "only.mp3").write_bytes(b"a")
            (root / "outer.epub").write_bytes(b"e")

            album = _node(
                node_id="node-album",
                relative_path="album",
                physical_kind="DIRECTORY",
                size=None,
            )
            only = _node(
                node_id="node-only",
                relative_path="album/only.mp3",
                physical_kind="REGULAR_FILE",
                parent_id="node-album",
            )
            outer = _node(
                node_id="node-outer",
                relative_path="outer.epub",
                physical_kind="REGULAR_FILE",
            )
            db.add_all([album, only, outer])
            db.add(
                LibraryBook(
                    id="book-outer", library_id="lib-1", source_node_id="node-outer"
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res-outer",
                    library_id="lib-1",
                    book_id="book-outer",
                    source_node_id="node-outer",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="TEXT",
                    format="EPUB",
                    enablement_state="ENABLED",
                    import_state="READY",
                )
            )
            # Outer resource's only READY asset points into the deleted subtree.
            db.add(
                LibraryResourceAsset(
                    id="asset-only",
                    library_id="lib-1",
                    resource_id="res-outer",
                    source_node_id="node-only",
                    source_node_physical_kind="REGULAR_FILE",
                    role="SUPPLEMENT",
                    import_state="READY",
                )
            )
            db.commit()

            pipeline = build_readable_resource_pipeline(db)
            assert pipeline.delete_source_node.execute("node-album").ok is True
            db.commit()
            survivor = db.get(LibraryReadableResource, "res-outer")
            assert survivor is not None
            assert survivor.import_state == "FAILED"
            assert db.get(LibraryResourceAsset, "asset-only") is None
    finally:
        engine.dispose()


def test_delete_then_continue_import_rediscovers_with_new_source_node_id(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            db.commit()
            (root / "novel.epub").write_bytes(b"epub")

            from dataclasses import replace

            from app.modules.imports.application.readable_resource.process_import_task import (
                ProcessReadableResourceImportTask,
            )
            from app.modules.imports.infrastructure.readable_resource.support import (
                InMemorySidecarWriteback,
                StructuredPipelineLog,
            )
            from app.modules.library.infrastructure.persistence.source_tree_repository import (
                SqlAlchemyBookResourceRepository,
                SqlAlchemyLibraryConfigAdapter,
                SqlAlchemySourceNodeRepository,
            )

            base = build_readable_resource_pipeline(db)
            process = ProcessReadableResourceImportTask(
                libraries=SqlAlchemyLibraryConfigAdapter(db),
                filesystem=base.filesystem,
                source_nodes=SqlAlchemySourceNodeRepository(db),
                books_resources=SqlAlchemyBookResourceRepository(db),
                adapters=StubOkAdapter(),
                queue=base.queue,
                uow=base.uow,
                clock=base.clock,
                log=StructuredPipelineLog(),
                sidecar=InMemorySidecarWriteback(),
            )
            pipeline = replace(base, process_import_task=process)

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            for _ in range(50):
                if worker.process_once() == "idle":
                    break
            db.commit()
            first = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "novel.epub"
                )
            )
            assert first is not None
            old_id = first.id
            assert (root / "novel.epub").exists()

            assert pipeline.delete_source_node.execute(old_id).ok is True
            db.commit()
            assert (
                db.scalar(
                    select(LibrarySourceNode).where(
                        LibrarySourceNode.relative_path == "novel.epub"
                    )
                )
                is None
            )

            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            for _ in range(50):
                if worker.process_once() == "idle":
                    break
            db.commit()
            second = db.scalar(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.relative_path == "novel.epub"
                )
            )
            assert second is not None
            assert second.id != old_id
            assert second.relative_path == "novel.epub"
            assert second.path_key == _path_key("novel.epub")
    finally:
        engine.dispose()


def test_relocate_library_root_preserves_source_tree_identity(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    new_root = tmp_path / "relocated"
    try:
        with Session(engine) as db:
            _add_library(db, root)
            ids = _seed_full_target_topology(db, root)
            db.commit()
            new_root.mkdir(parents=True, exist_ok=True)
            # Keep relative layout available under the new root (no auto-scan).
            (new_root / "album").mkdir(parents=True, exist_ok=True)
            (new_root / "album" / "track.mp3").write_bytes(b"audio")
            (new_root / "outer.epub").write_bytes(b"epub")
            (new_root / "shared.mp3").write_bytes(b"audio")

            before_nodes = {
                row.id: (row.relative_path, row.path_key)
                for row in db.scalars(select(LibrarySourceNode)).all()
            }
            before_tasks = {
                row.id: (row.kind, row.state, row.source_node_id, row.resource_id)
                for row in db.scalars(select(LibraryImportTask)).all()
            }
            before_books = {row.id for row in db.scalars(select(LibraryBook)).all()}
            before_resources = {
                row.id for row in db.scalars(select(LibraryReadableResource)).all()
            }
            before_assets = {
                row.id for row in db.scalars(select(LibraryResourceAsset)).all()
            }

            pipeline = build_readable_resource_pipeline(db)
            result = pipeline.relocate_library_root.execute("lib-1", new_root)
            assert result.ok is True
            db.commit()

            library = db.get(Library, "lib-1")
            assert library is not None
            assert Path(library.root_path).resolve() == new_root.resolve()
            after_nodes = {
                row.id: (row.relative_path, row.path_key)
                for row in db.scalars(select(LibrarySourceNode)).all()
            }
            assert after_nodes == before_nodes
            assert {
                row.id: (row.kind, row.state, row.source_node_id, row.resource_id)
                for row in db.scalars(select(LibraryImportTask)).all()
            } == before_tasks
            assert {
                row.id for row in db.scalars(select(LibraryBook)).all()
            } == before_books
            assert {
                row.id for row in db.scalars(select(LibraryReadableResource)).all()
            } == before_resources
            assert {
                row.id for row in db.scalars(select(LibraryResourceAsset)).all()
            } == before_assets
            # No additional SCAN_LIBRARY beyond the seeded one.
            assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 4
            assert ids["album"] in after_nodes
    finally:
        engine.dispose()


def test_relocate_unreadable_or_conflicting_root_has_no_side_effects(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    other = tmp_path / "other"
    missing = tmp_path / "missing-root"
    try:
        with Session(engine) as db:
            _add_library(db, root, library_id="lib-1")
            _add_library(db, other, library_id="lib-2")
            ids = _seed_full_target_topology(db, root)
            db.commit()
            original = db.get(Library, "lib-1")
            assert original is not None
            original_root = original.root_path
            pipeline = build_readable_resource_pipeline(db)

            unread = pipeline.relocate_library_root.execute("lib-1", missing)
            assert unread.ok is False
            assert unread.code == "ROOT_NOT_READABLE"
            db.expire_all()
            library = db.get(Library, "lib-1")
            assert library is not None
            assert library.root_path == original_root
            assert db.get(LibrarySourceNode, ids["album"]) is not None

            conflict = pipeline.relocate_library_root.execute("lib-1", other)
            assert conflict.ok is False
            assert conflict.code == "ROOT_CONFLICT"
            db.expire_all()
            library2 = db.get(Library, "lib-1")
            assert library2 is not None
            assert library2.root_path == original_root
            assert db.scalar(select(func.count()).select_from(LibraryImportTask)) == 4
    finally:
        engine.dispose()
