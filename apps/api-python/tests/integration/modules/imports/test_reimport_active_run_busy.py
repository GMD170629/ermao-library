"""ACTIVE_RUN_BUSY must short-circuit before FS I/O or Run creation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library
from app.modules.imports.application.readable_resource.ports import (
    SourceTreeFilesystemPort,
)
from app.modules.imports.domain.import_run_policies import ImportRunState
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportRun,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResource,
)


class RaisingFilesystem(SourceTreeFilesystemPort):
    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        raise AssertionError("FS must not be touched when ACTIVE_RUN_BUSY")

    def iter_directory_entries(self, absolute_directory: Path):
        raise AssertionError("FS must not be touched when ACTIVE_RUN_BUSY")
        yield from ()  # pragma: no cover

    def probe_directory(self, **kwargs: object):
        raise AssertionError("probe must not run when ACTIVE_RUN_BUSY")

    def path_is_readable_directory(self, path: Path) -> bool:
        raise AssertionError("FS must not be touched when ACTIVE_RUN_BUSY")


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def test_reimport_active_run_busy_no_fs_no_run(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    root = tmp_path / "books"
    root.mkdir()
    (root / "Novel.txt").write_text("hello\n", encoding="utf-8")
    try:
        with Session(engine) as db:
            db.add(
                Library(
                    id="lib-1",
                    name="Lib",
                    root_path=str(root),
                    organization_mode="FLAT",
                    min_file_size_bytes=0,
                )
            )
            db.commit()

        with Session(engine) as db:
            pipeline = build_readable_resource_pipeline(db)
            pipeline.scan_library_source_tree.execute("lib-1")
            resource = db.scalar(select(LibraryReadableResource).limit(1))
            assert resource is not None
            assert resource.active_import_run_id is not None
            active = resource.active_import_run_id
            source_node_id = resource.source_node_id
            runs_before = db.scalars(select(LibraryImportRun)).all()
            assert len(runs_before) == 1

            pipeline.reimport_source_node._filesystem = RaisingFilesystem()  # noqa: SLF001
            result = pipeline.reimport_source_node.execute(source_node_id)
            assert result.ok is False
            assert result.code == "ACTIVE_RUN_BUSY"
            assert result.run_id is None

            db.refresh(resource)
            assert resource.active_import_run_id == active
            runs_after = db.scalars(select(LibraryImportRun)).all()
            assert len(runs_after) == 1
            assert runs_after[0].id == active
            assert runs_after[0].state == ImportRunState.RUNNING.value
    finally:
        engine.dispose()
