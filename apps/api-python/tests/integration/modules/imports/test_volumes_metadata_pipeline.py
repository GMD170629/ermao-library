"""Real VOLUMES import coverage for Book/Resource metadata ownership."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from sqlalchemy import select
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
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 3), color=color).save(output, format="PNG")
    return output.getvalue()


def _write_epub(
    path: Path,
    *,
    title: str,
    author: str,
    cover: bytes,
) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/>'
            "</rootfiles></container>",
        )
        archive.writestr(
            "OPS/book.opf",
            f"""<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
            <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
            <meta name="cover" content="cover-image"/></metadata>
            <manifest><item id="cover-image" href="cover.png"
            media-type="image/png"/></manifest></package>""",
        )
        archive.writestr("OPS/cover.png", cover)


@pytest.mark.parametrize(
    "import_order",
    (("01.epub", "02.epub"), ("02.epub", "01.epub")),
)
def test_real_volumes_import_keeps_book_stable_and_resource_covers_distinct(
    tmp_path: Path,
    import_order: tuple[str, str],
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    series = root / "Series"
    series.mkdir(parents=True)
    covers = {
        "01.epub": _png((220, 20, 20)),
        "02.epub": _png((20, 20, 220)),
    }
    _write_epub(
        series / "01.epub",
        title="Embedded One",
        author="File Author One",
        cover=covers["01.epub"],
    )
    _write_epub(
        series / "02.epub",
        title="Embedded Two",
        author="File Author Two",
        cover=covers["02.epub"],
    )
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.add(
                Library(
                    id="lib-1",
                    name="Volumes",
                    root_path=str(root),
                    organization_mode="VOLUMES",
                    min_file_size_bytes=0,
                )
            )
            db.commit()
            pipeline = build_readable_resource_pipeline(db, settings)
            pipeline.continue_import.execute(ContinueLibraryImport("lib-1"))
            worker = build_readable_resource_worker(pipeline)
            assert worker.process_once() == "scan"

            tasks = db.execute(
                select(LibraryImportTask, LibrarySourceNode.name)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryImportTask.source_node_id,
                )
                .where(LibraryImportTask.kind == "IMPORT_ASSET")
            ).all()
            tasks_by_name = {name: task for task, name in tasks}
            assert set(tasks_by_name) == {"01.epub", "02.epub"}
            for name in import_order:
                task = tasks_by_name[name]
                task.state = "RUNNING"
                db.commit()
                assert pipeline.process_import_task.execute(task.id).outcome == "ok"

            book = db.scalar(select(LibraryBook))
            assert book is not None
            book_anchor = db.get(LibrarySourceNode, book.source_node_id)
            assert book_anchor is not None
            assert book_anchor.relative_path == "Series"
            book_metadata = db.get(LibraryBookMetadata, book.id)
            assert book_metadata is not None
            assert book_metadata.title == "Series"
            assert book_metadata.author is None
            assert book_metadata.series_name is None
            assert book_metadata.metadata_quality == 0
            assert book_metadata.cover_path is None

            resources = db.execute(
                select(
                    LibraryReadableResource,
                    LibraryReadableResourceMetadata,
                    LibrarySourceNode.name,
                )
                .join(
                    LibraryReadableResourceMetadata,
                    LibraryReadableResourceMetadata.resource_id
                    == LibraryReadableResource.id,
                )
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryReadableResource.source_node_id,
                )
            ).all()
            by_name = {
                name: (resource, metadata) for resource, metadata, name in resources
            }
            assert set(by_name) == {"01.epub", "02.epub"}
            assert by_name["01.epub"][1].title == "Embedded One"
            assert by_name["02.epub"][1].title == "Embedded Two"

            stored_paths = {
                name: metadata.cover_path
                for name, (_resource, metadata) in by_name.items()
            }
            assert stored_paths["01.epub"] != stored_paths["02.epub"]
            for name, stored_path in stored_paths.items():
                assert stored_path is not None
                assert stored_path.startswith("covers/resources/")
                assert (
                    settings.resolved_storage_root / stored_path
                ).read_bytes() == covers[name]
            assert all(task.state == "SUCCEEDED" for task in tasks_by_name.values())
    finally:
        engine.dispose()
