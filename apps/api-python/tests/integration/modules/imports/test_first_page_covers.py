"""Real import/regeneration coverage for optional page-zero artwork."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.library_resource_actions import regenerate_local_metadata_covers
from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.application.local_cover_regeneration import (
    LocalCoverUnavailableError,
)
from app.modules.library.application.resource_commands import LibraryActor
from app.modules.media.infrastructure.page_image import PageImageRenderer


@pytest.fixture
def library(
    tmp_path: Path,
) -> Iterator[tuple[Session, Settings, Path, ReadableResourcePipeline]]:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir()
    bootstrap_database(engine, settings)
    try:
        with Session(engine) as db:
            db.add(
                Library(
                    id="lib",
                    name="Library",
                    root_path=str(root),
                    organization_mode="VOLUMES",
                    min_file_size_bytes=0,
                )
            )
            db.commit()
            yield db, settings, root, build_readable_resource_pipeline(db, settings)
    finally:
        engine.dispose()


def write_pages(root: Path, kind: str) -> Path:
    book = root / "Book"
    book.mkdir()
    if kind == "PDF":
        target = book / "book.pdf"
        with (
            Image.new("RGB", (120, 180), "red") as first,
            Image.new("RGB", (120, 180), "blue") as second,
        ):
            first.save(target, format="PDF", save_all=True, append_images=[second])
        return target
    target = book
    for name, color in (("1.png", "red"), ("2.png", "green"), ("10.png", "blue")):
        with Image.new("RGB", (120, 180), color) as image:
            image.save(target / name)
    return target


def scan(db: Session, pipeline: ReadableResourcePipeline) -> dict[str, str]:
    pipeline.continue_import.execute(ContinueLibraryImport("lib"))
    assert build_readable_resource_worker(pipeline).process_once() == "scan"
    return dict(
        db.execute(
            select(LibrarySourceNode.name, LibraryImportTask.id)
            .join(
                LibraryImportTask,
                LibraryImportTask.source_node_id == LibrarySourceNode.id,
            )
            .where(LibraryImportTask.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE")))
        ).all()
    )


def import_task(db: Session, pipeline: ReadableResourcePipeline, task_id: str) -> None:
    db.commit()
    assert pipeline.process_import_task.execute(task_id).outcome == "ok"
    db.expire_all()


def assert_red(content: bytes) -> None:
    with Image.open(BytesIO(content)) as image:
        red, green, blue = image.convert("RGB").getpixel((20, 20))
        assert red > 200 and green < 35 and blue < 35


@pytest.mark.parametrize(
    "order", [("1.png", "2.png", "10.png"), ("10.png", "2.png", "1.png")]
)
def test_image_cover_follows_page_order_and_survives_later_imports(
    library, monkeypatch, order
) -> None:
    db, settings, root, pipeline = library
    write_pages(root, "IMAGE_DIR")
    tasks = scan(db, pipeline)
    assert set(tasks) == {"Book"}
    rendered = []
    original = PageImageRenderer.render

    def render(self, source, page_index):
        rendered.append(source.path.name)
        return original(self, source, page_index)

    monkeypatch.setattr(PageImageRenderer, "render", render)
    # Member creation order cannot affect resource-level cover selection.
    import_task(db, pipeline, tasks["Book"])
    resource = db.scalar(select(LibraryReadableResource))
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata.cover_status == "READY"
    content = (settings.resolved_storage_root / metadata.cover_path).read_bytes()
    assert_red(content)
    assert rendered == ["1.png"]
    resource_id, book_id = resource.id, resource.book_id
    # Existing resource regeneration selects the same first page, not lexicographic order.
    regenerate_local_metadata_covers(db, settings).regenerate_resource(
        actor=LibraryActor("admin", True, True, True, ("lib",)),
        book_id=book_id,
        resource_id=resource_id,
    )
    db.expire_all()
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    assert (
        settings.resolved_storage_root / metadata.cover_path
    ).read_bytes() == content
    assert rendered[-1] == "1.png"


@pytest.mark.parametrize("kind", ["PDF", "IMAGE_DIR"])
@pytest.mark.parametrize("sidecar", ["absent", "valid", "invalid"])
def test_metadata_precedes_first_page_and_regeneration_matches(
    library, monkeypatch, kind, sidecar
) -> None:
    db, settings, root, pipeline = library
    target = write_pages(root, kind)
    expected = None
    if sidecar != "absent":
        opf = target / "metadata.opf" if target.is_dir() else target.with_suffix(".opf")
        image = opf.parent / "metadata.cover.png"
        if sidecar == "valid":
            with Image.new("RGB", (30, 45), "yellow") as cover:
                cover.save(image)
        else:
            image.write_bytes(b"\x89PNG\r\n\x1a\ninvalid")
        expected = image.read_bytes()
        opf.write_text(
            '<package><metadata><meta name="cover" content="cover"/></metadata><manifest><item id="cover" href="metadata.cover.png" media-type="image/png"/></manifest></package>'
        )
    rendered = []
    original = PageImageRenderer.render

    def render(self, source, page_index):
        rendered.append((source.path.name, page_index))
        return original(self, source, page_index)

    monkeypatch.setattr(PageImageRenderer, "render", render)
    tasks = scan(db, pipeline)
    for name in sorted(tasks, key=lambda name: (len(name), name)):
        import_task(db, pipeline, tasks[name])
    resource = db.scalar(select(LibraryReadableResource))
    resource_id, book_id = resource.id, resource.book_id
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    assert metadata.cover_path
    content = (settings.resolved_storage_root / metadata.cover_path).read_bytes()
    if sidecar == "valid":
        assert content == expected
        assert rendered == []
    else:
        assert_red(content)
        assert rendered == [("book.pdf" if kind == "PDF" else "1.png", 0)]
    regenerate_local_metadata_covers(db, settings).regenerate_resource(
        actor=LibraryActor("admin", True, True, True, ("lib",)),
        book_id=book_id,
        resource_id=resource_id,
    )
    db.expire_all()
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    assert (
        settings.resolved_storage_root / metadata.cover_path
    ).read_bytes() == content
    if sidecar == "valid":
        assert rendered == []


@pytest.mark.parametrize("kind", ["PDF", "IMAGE_DIR"])
def test_unreadable_first_page_is_optional_and_never_skips_ahead(library, kind) -> None:
    db, settings, root, pipeline = library
    target = write_pages(root, kind)
    first = target if kind == "PDF" else target / "1.png"
    first.write_bytes(b"broken")
    tasks = scan(db, pipeline)
    for name in sorted(tasks, key=lambda name: (len(name), name)):
        import_task(db, pipeline, tasks[name])
    resource = db.scalar(select(LibraryReadableResource))
    resource_id, book_id = resource.id, resource.book_id
    assert resource.import_state == "READY"
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    if kind == "IMAGE_DIR":
        assert metadata.cover_path is not None
        with Image.open(settings.resolved_storage_root / metadata.cover_path) as image:
            assert image.convert("RGB").getpixel((20, 20))[1] > 80
    else:
        assert metadata.cover_path is None
    existing = settings.resolved_storage_root / "covers" / "old.png"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"old")
    metadata.cover_path = "covers/old.png"
    metadata.cover_status = "READY"
    db.commit()
    with pytest.raises(LocalCoverUnavailableError):
        regenerate_local_metadata_covers(db, settings).regenerate_resource(
            actor=LibraryActor("admin", True, True, True, ("lib",)),
            book_id=book_id,
            resource_id=resource_id,
        )
    assert (
        db.get(LibraryReadableResourceMetadata, resource_id).cover_path
        == "covers/old.png"
    )
    assert existing.read_bytes() == b"old"


def test_image_natural_first_page_and_missing_first_regeneration(library) -> None:
    db, settings, root, pipeline = library
    target = write_pages(root, "IMAGE_DIR")
    (target / "1.png").replace(target / "2.png")
    tasks = scan(db, pipeline)
    import_task(db, pipeline, tasks["Book"])
    resource = db.scalar(select(LibraryReadableResource))
    resource_id, book_id = resource.id, resource.book_id
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    assert_red((settings.resolved_storage_root / metadata.cover_path).read_bytes())
    regenerate = regenerate_local_metadata_covers(db, settings)
    regenerate.regenerate_resource(
        actor=LibraryActor("admin", True, True, True, ("lib",)),
        book_id=book_id,
        resource_id=resource_id,
    )
    db.expire_all()
    previous = db.get(LibraryReadableResourceMetadata, resource_id).cover_path
    assert_red((settings.resolved_storage_root / previous).read_bytes())
    (target / "2.png").unlink()
    with pytest.raises(LocalCoverUnavailableError):
        regenerate.regenerate_resource(
            actor=LibraryActor("admin", True, True, True, ("lib",)),
            book_id=book_id,
            resource_id=resource_id,
        )
    assert db.get(LibraryReadableResourceMetadata, resource_id).cover_path == previous


@pytest.mark.parametrize("outcome", ["cancelled", "failed", "protected"])
def test_fallback_publication_preserves_previous_cover_on_cancel_failure_or_protection(
    library, monkeypatch, outcome
) -> None:
    from app.modules.imports.infrastructure.local_cover_publication import (
        FilesystemLocalCoverPublication,
    )
    from app.modules.library.application.metadata_ownership import protect_fields

    db, settings, root, pipeline = library
    write_pages(root, "PDF")
    tasks = scan(db, pipeline)
    task_id = tasks["book.pdf"]
    import_task(db, pipeline, task_id)
    resource_id = db.scalar(select(LibraryReadableResource.id))
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    previous = metadata.cover_path
    previous_content = (settings.resolved_storage_root / previous).read_bytes()
    previous_files = set(
        (settings.resolved_storage_root / "covers" / "resources").iterdir()
    )
    # Reprocess a genuinely changed input; unchanged successful resource tasks
    # now reuse their committed results without entering cover publication.
    pdf = root / "Book" / "book.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"\n% changed source\n")
    if outcome == "protected":
        metadata.protected_fields = protect_fields(
            metadata.protected_fields, ("cover_path",)
        )
        db.commit()

        def forbidden_render(*args, **kwargs):
            raise AssertionError("protected artwork must not render the first page")

        monkeypatch.setattr(PageImageRenderer, "render", forbidden_render)
    else:
        original_publish = FilesystemLocalCoverPublication.publish

        def publish(self, prepared):
            original_publish(self, prepared)
            if outcome == "failed":
                raise OSError("publication failure")
            db.delete(db.get(LibraryImportTask, task_id))
            db.commit()

        monkeypatch.setattr(FilesystemLocalCoverPublication, "publish", publish)
    db.commit()
    result = pipeline.process_import_task.execute(task_id)
    assert result.outcome == ("ok" if outcome == "protected" else outcome)
    db.expire_all()
    assert db.get(LibraryReadableResourceMetadata, resource_id).cover_path == previous
    assert (settings.resolved_storage_root / previous).read_bytes() == previous_content
    assert (
        set((settings.resolved_storage_root / "covers" / "resources").iterdir())
        == previous_files
    )


@pytest.mark.parametrize("retry_after_rollback", [False, True])
@pytest.mark.parametrize("kind", ["PDF"])
def test_import_phase_counts_and_finalization_rollback(
    library, monkeypatch, retry_after_rollback, kind
) -> None:
    """Count real work by phase; a failed transaction may repeat finalization."""
    from collections import Counter

    from sqlalchemy import event

    from app.models import LibraryResourceAsset
    from app.modules.imports.infrastructure.local_cover_publication import (
        FilesystemLocalCoverPublication,
    )
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemyBookResourceRepository,
    )

    db, settings, root, pipeline = library
    write_pages(root, kind)
    filenames = ("book.pdf",) if kind == "PDF" else ("1.png", "2.png", "10.png")
    file_count = len(filenames)
    process = pipeline.process_import_task
    phase = "scan"
    sql = {name: Counter() for name in ("scan", "save", "finalize", "queue_context")}
    counts = Counter()

    def executed(conn, cursor, statement, parameters, context, executemany):
        sql[phase]["driver_calls"] += 1
        sql[phase]["executemany_calls"] += int(executemany)
        # DBAPI rowcount is affected DML rows, not a SQL statement count. SELECT
        # rows are measured separately at the resource aggregation boundary.
        if cursor.rowcount >= 0:
            sql[phase]["affected_rows"] += cursor.rowcount

    def committed(connection):
        sql[phase]["connection_commit_calls"] += 1
        # SQLite SELECT-only scopes and empty Session.commit() calls need not
        # open a native transaction. Count native transactions independently.
        if connection.connection.driver_connection.in_transaction:
            sql[phase]["transaction_commits"] += 1

    original_parse = RegistryResourceAdapterExecutor.parse_file
    original_publish = FilesystemLocalCoverPublication.publish
    original_count = SqlAlchemyBookResourceRepository.count_ready_assets
    original_merge = SqlAlchemyBookResourceRepository.refresh_resource_local_metadata
    original_save = process.save_asset_result
    original_finalize = process.finalize_resource

    def parse(self, **kwargs):
        assert not db.in_transaction()
        counts["media_parses"] += 1
        return original_parse(self, **kwargs)

    def publish(self, prepared):
        assert not db.in_transaction()
        counts["cover_publications"] += 1
        original_publish(self, prepared)

    def ready_count(self, resource_id):
        result = original_count(self, resource_id)
        if phase == "finalize":
            counts["aggregate_assets"] += result
        return result

    def merge(self, resource_id):
        counts["metadata_merges"] += 1
        return original_merge(self, resource_id)

    def save(**kwargs):
        nonlocal phase
        phase = "save"
        try:
            return original_save(**kwargs)
        finally:
            phase = "queue_context"

    def finalize(**kwargs):
        nonlocal phase
        phase = "finalize"
        counts["resource_finalizations"] += 1
        try:
            original_finalize(**kwargs)
            if retry_after_rollback and counts["resource_finalizations"] == 1:
                raise RuntimeError("injected after resource finalization")
        finally:
            phase = "queue_context"

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", parse)
    monkeypatch.setattr(FilesystemLocalCoverPublication, "publish", publish)
    monkeypatch.setattr(
        SqlAlchemyBookResourceRepository, "count_ready_assets", ready_count
    )
    monkeypatch.setattr(
        SqlAlchemyBookResourceRepository, "refresh_resource_local_metadata", merge
    )
    monkeypatch.setattr(process, "save_asset_result", save)
    monkeypatch.setattr(process, "finalize_resource", finalize)
    engine = db.get_bind()
    event.listen(engine, "after_cursor_execute", executed)
    event.listen(engine, "commit", committed)
    try:
        tasks = scan(db, pipeline)
        assert len(tasks) == file_count
        phase = "queue_context"
        task_id = tasks[filenames[0]]
        if retry_after_rollback:
            worker = build_readable_resource_worker(pipeline)
            # Select the first page deterministically through the real queue.
            from datetime import UTC, datetime

            db.get(LibraryImportTask, task_id).created_at = datetime(
                2000, 1, 1, tzinfo=UTC
            )
            db.commit()
            assert worker.process_once() == "error"
            db.expire_all()
            assert db.get(LibraryImportTask, task_id).state == "FAILED"
            assert db.scalar(select(LibraryResourceAsset.id)) is None
            assert db.scalar(select(LibraryReadableResourceMetadata)) is None
            assert not list(
                (settings.resolved_storage_root / "covers" / "resources").iterdir()
            )
            pipeline.queue.requeue_failed_task(task_id)
            db.commit()
        for name in filenames:
            import_task(db, pipeline, tasks[name])
        assert set(
            db.scalars(
                select(LibraryImportTask.state).where(
                    LibraryImportTask.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE"))
                )
            )
        ) == {"SUCCEEDED"}
        metadata = db.scalar(select(LibraryReadableResourceMetadata))
        assert_red((settings.resolved_storage_root / metadata.cover_path).read_bytes())
        assert counts == {
            "media_parses": file_count + int(retry_after_rollback),
            "cover_publications": 2 if retry_after_rollback else 1,
            "resource_finalizations": file_count + int(retry_after_rollback),
            "aggregate_assets": file_count * (file_count + 1) // 2
            + int(retry_after_rollback),
            "metadata_merges": file_count + int(retry_after_rollback),
        }
        # One transaction owns save + finalize + failed outcome; neither helper
        # silently commits. These counts include attempted rows before rollback.
        assert (
            sql["save"]["connection_commit_calls"]
            == sql["finalize"]["connection_commit_calls"]
            == 0
        )
        print(
            {
                "mode": "rollback_retry" if retry_after_rollback else "normal",
                "import_asset_tasks": len(tasks) if kind == "IMAGE_DIR" else 0,
                "import_resource_tasks": len(tasks) if kind == "PDF" else 0,
                "format": kind,
                "aggregate_chapters": 0,
                "audio_aggregations": 0,
                "work": dict(counts),
                "sql_by_phase": {key: dict(value) for key, value in sql.items()},
            }
        )
    finally:
        event.remove(engine, "after_cursor_execute", executed)
        event.remove(engine, "commit", committed)


def test_unchanged_resource_reuses_committed_result_without_cover_publication(
    library, monkeypatch
) -> None:
    from app.models import LibraryResourceAsset
    from app.modules.imports.infrastructure.local_cover_publication import (
        FilesystemLocalCoverPublication,
    )
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    db, settings, root, pipeline = library
    write_pages(root, "PDF")
    tasks = scan(db, pipeline)
    task_id = tasks["book.pdf"]
    import_task(db, pipeline, task_id)
    asset = db.scalar(select(LibraryResourceAsset))
    assert asset.processed_source_version is not None
    asset_id = asset.id
    old_cover = db.scalar(select(LibraryReadableResourceMetadata)).cover_path

    def forbidden(*args, **kwargs):
        raise AssertionError("unchanged asset must not parse or publish covers")

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", forbidden)
    monkeypatch.setattr(FilesystemLocalCoverPublication, "publish", forbidden)
    monkeypatch.setattr(FilesystemLocalCoverPublication, "prepare", forbidden)
    assert scan(db, pipeline) == tasks
    assert db.get(LibraryImportTask, task_id).state == "SUCCEEDED"
    import_task(db, pipeline, task_id)
    assert db.scalar(select(LibraryResourceAsset.id)) == asset_id
    assert db.scalar(select(LibraryReadableResourceMetadata)).cover_path == old_cover
    assert (settings.resolved_storage_root / old_cover).is_file()


@pytest.mark.parametrize("interrupt_after_three", [False, True])
def test_thousand_images_batch_import_and_incremental_reuse(
    library, monkeypatch, interrupt_after_three
):
    from collections import Counter

    from sqlalchemy import event

    from app.models import LibraryResourceAsset
    from app.modules.imports.application.readable_resource.continue_import import (
        ContinueImportTask,
    )
    from app.modules.imports.infrastructure.local_cover_publication import (
        FilesystemLocalCoverPublication,
    )
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemyBookResourceRepository,
    )

    db, settings, root, pipeline = library
    folder = root / "Book"
    folder.mkdir()
    output = BytesIO()
    Image.new("RGB", (32, 32), "red").save(output, format="PNG")
    for index in range(1, 1001):
        (folder / f"{index}.png").write_bytes(output.getvalue())
    (folder / "metadata.opf").write_text(
        "<package><metadata><title>Original</title><meta name='cover' content='cover'/></metadata><manifest><item id='cover' href='1.png' media-type='image/png'/></manifest></package>"
    )
    counts = Counter()
    parsed_names = Counter()
    phase = "scan"
    sql = {key: Counter() for key in ("scan", "asset", "finish")}
    engine = db.get_bind()

    def executed(conn, cursor, statement, parameters, context, executemany):
        sql[phase]["driver_calls"] += 1
        sql[phase]["executemany_calls"] += int(executemany)
        sql[phase]["selects"] += int(statement.lstrip().upper().startswith("SELECT"))
        if cursor.rowcount >= 0:
            sql[phase]["affected_rows"] += cursor.rowcount

    def commit(conn):
        sql[phase]["connection_commits"] += 1
        sql[phase]["actual_commits"] += int(
            conn.connection.driver_connection.in_transaction
        )

    event.listen(engine, "after_cursor_execute", executed)
    event.listen(engine, "commit", commit)
    parse = RegistryResourceAdapterExecutor.parse_file
    inspect = RegistryResourceAdapterExecutor.inspect_resource_metadata
    publish = FilesystemLocalCoverPublication.publish
    apply = SqlAlchemyBookResourceRepository.apply_local_metadata

    def parse_count(self, **kwargs):
        parsed_names[kwargs["absolute_path"].name] += 1
        return parse(self, **kwargs)

    def inspect_count(self, **kwargs):
        counts["directory_metadata"] += 1
        return inspect(self, **kwargs)

    def publish_count(self, prepared):
        counts["cover_publications"] += 1
        return publish(self, prepared)

    def apply_count(self, **kwargs):
        counts["resource_merges"] += 1
        return apply(self, **kwargs)

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", parse_count)
    monkeypatch.setattr(
        RegistryResourceAdapterExecutor, "inspect_resource_metadata", inspect_count
    )
    monkeypatch.setattr(FilesystemLocalCoverPublication, "publish", publish_count)
    monkeypatch.setattr(
        SqlAlchemyBookResourceRepository, "apply_local_metadata", apply_count
    )
    original_batch = pipeline.process_import_task._save_directory_batch
    sizes = []

    def save_batch(*args):
        nonlocal phase
        phase = "asset"
        try:
            result = original_batch(*args)
            sizes.append(len(args[2]))
        finally:
            phase = "finish"
        if interrupt_after_three and len(sizes) == 3:
            raise KeyboardInterrupt()
        return result

    monkeypatch.setattr(
        pipeline.process_import_task, "_save_directory_batch", save_batch
    )
    try:
        tasks = scan(db, pipeline)
        assert list(tasks) == ["Book"]
        task_id = tasks["Book"]
        assert (
            db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_ASSET"
                )
            ).all()
            == []
        )
        phase = "finish"
        worker = build_readable_resource_worker(pipeline)
        if interrupt_after_three:
            with pytest.raises(KeyboardInterrupt):
                worker.process_once()
            assert len(db.scalars(select(LibraryResourceAsset)).all()) == 600
            # Discard the worker and its Session, as on application restart.
            db.close()
            with Session(engine) as resumed:
                restored = build_readable_resource_pipeline(resumed, settings)
                original_batch = restored.process_import_task._save_directory_batch
                monkeypatch.setattr(
                    restored.process_import_task, "_save_directory_batch", save_batch
                )
                restarted = build_readable_resource_worker(restored)
                assert restarted.startup() == 1
                restored.continue_import.execute(ContinueImportTask(task_id))
                assert restarted.process_once() == "ok"
            db.expire_all()
        else:
            assert worker.process_once() == "ok"
            assert sizes == [200] * 5
            assert sql["asset"]["actual_commits"] == 5
            assert sql["asset"]["selects"] <= 7 * 5
            assert counts == {
                "directory_metadata": 1,
                "resource_merges": 1,
                "cover_publications": 1,
            }
        assets = db.scalars(select(LibraryResourceAsset)).all()
        assert len(assets) == 1000
        assert all(
            a.role == "PAGE"
            and a.import_state == "READY"
            and a.processed_source_version
            for a in assets
        )
        assert all(a.local_metadata_candidates == "[]" for a in assets)
        assert sum(parsed_names.values()) == 1000
        ids = {a.source_node_id: a.id for a in assets}
        saved_timestamps = {a.id: a.updated_at for a in assets}
        resource = db.scalar(select(LibraryReadableResource))
        assert db.get(LibraryReadableResourceMetadata, resource.id).page_count == 1000
        from app.modules.reader.infrastructure.resource_catalog_repository import (
            SqlAlchemyReaderResourceCatalogRepository,
        )

        ordered = SqlAlchemyReaderResourceCatalogRepository(db).list_assets(resource.id)
        assert [a.title for a in ordered] == [str(i) for i in range(1, 1001)]
        assert sizes == [200] * 5
        assert sql["asset"]["actual_commits"] == 5
        print(
            {
                "mode": "interrupted_after_600" if interrupt_after_three else "normal",
                "resource_tasks": 1,
                "batches": sizes,
                "work": dict(counts),
                "parses": sum(parsed_names.values()),
                "sql": {k: dict(v) for k, v in sql.items()},
            }
        )
        if interrupt_after_three:
            return
        for index in range(1001, 1011):
            (folder / f"{index}.png").write_bytes(output.getvalue())
        parsed_names.clear()
        phase = "scan"
        scan(db, pipeline)
        phase = "finish"
        assert worker.process_once() == "ok"
        assert len(parsed_names) == 10
        assert sizes == [200] * 5 + [10]
        assert counts["cover_publications"] == 1
        assert all(
            db.get(LibraryResourceAsset, asset_id).updated_at == timestamp
            for asset_id, timestamp in saved_timestamps.items()
        )
        assert all(
            db.get(LibraryResourceAsset, asset_id).source_node_id == node_id
            for node_id, asset_id in ids.items()
        )
        parsed_names.clear()
        (folder / "metadata.opf").write_text(
            "<package><metadata><title>Changed</title><meta name='cover' content='cover'/></metadata><manifest><item id='cover' href='1.png' media-type='image/png'/></manifest></package>"
        )
        scan(db, pipeline)
        assert worker.process_once() == "ok"
        assert not parsed_names
        assert db.get(LibraryReadableResourceMetadata, resource.id).title == "Changed"
        assert counts["cover_publications"] == 1
        # Missing published artwork is repaired without reprocessing any page.
        cover = db.get(LibraryReadableResourceMetadata, resource.id).cover_path
        (settings.resolved_storage_root / cover).unlink()
        scan(db, pipeline)
        assert worker.process_once() == "ok"
        assert not parsed_names
        assert counts["cover_publications"] == 2
        metadata_row = db.get(LibraryReadableResourceMetadata, resource.id)
        metadata_row.protected_fields = '["title","cover_path"]'
        old_cover = metadata_row.cover_path
        db.commit()
        (folder / "metadata.opf").write_text(
            "<package><metadata><title>Protected change</title><meta name='cover' content='cover'/></metadata><manifest><item id='cover' href='1.png' media-type='image/png'/></manifest></package>"
        )
        scan(db, pipeline)
        assert worker.process_once() == "ok"
        assert db.get(LibraryReadableResourceMetadata, resource.id).title == "Changed"
        assert (
            db.get(LibraryReadableResourceMetadata, resource.id).cover_path == old_cover
        )
        assert counts["cover_publications"] == 2
        assert not parsed_names
        (folder / "1011.png").write_bytes(output.getvalue())

        def failed_parse(self, **kwargs):
            if kwargs["absolute_path"].name == "1011.png":
                parsed_names["1011.png"] += 1
                raise OSError("injected unreadable image")
            return parse_count(self, **kwargs)

        monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", failed_parse)
        scan(db, pipeline)
        assert worker.process_once() == "failed"
        assert parsed_names == {"1011.png": 1}
        assert db.scalar(select(LibraryReadableResource)).import_state == "READY"
        failed = db.scalar(
            select(LibraryResourceAsset).where(
                LibraryResourceAsset.import_state == "FAILED"
            )
        )
        assert failed.failure_reason == "IMAGE_FILE_UNREADABLE"
        assert failed.processed_source_version is None
        monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", parse_count)
        parsed_names.clear()
        pipeline.continue_import.execute(ContinueImportTask(task_id))
        assert worker.process_once() == "ok"
        assert parsed_names == {"1011.png": 1}
        # A changed existing image keeps its identity and updates the selected cover.
        metadata_row = db.get(LibraryReadableResourceMetadata, resource.id)
        metadata_row.protected_fields = '["title"]'
        db.commit()
        changed_id = db.scalar(
            select(LibraryResourceAsset.id)
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(LibrarySourceNode.relative_path == "Book/1.png")
        )
        before_version = db.get(
            LibraryResourceAsset, changed_id
        ).processed_source_version
        Image.new("RGB", (40, 40), "blue").save(folder / "1.png")
        parsed_names.clear()
        scan(db, pipeline)
        assert worker.process_once() == "ok"
        assert parsed_names == {"1.png": 1}
        assert (
            db.get(LibraryResourceAsset, changed_id).processed_source_version
            != before_version
        )
        assert counts["cover_publications"] == 3
    finally:
        event.remove(engine, "after_cursor_execute", executed)
        event.remove(engine, "commit", commit)


def test_image_finalization_rollback_reuses_committed_pages(library, monkeypatch):
    from app.models import LibraryResourceAsset
    from app.modules.imports.application.readable_resource.continue_import import (
        ContinueImportTask,
    )
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemyBookResourceRepository,
    )

    db, settings, root, pipeline = library
    write_pages(root, "IMAGE_DIR")
    task_id = scan(db, pipeline)["Book"]
    original = SqlAlchemyBookResourceRepository.apply_local_metadata
    calls = 0

    def fail(self, **kwargs):
        nonlocal calls
        original(self, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("injected finalization rollback")

    monkeypatch.setattr(SqlAlchemyBookResourceRepository, "apply_local_metadata", fail)
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "error"
    assets = db.scalars(select(LibraryResourceAsset)).all()
    ids = {a.id for a in assets}
    assert len(ids) == 3
    assert all(a.processed_source_version is not None for a in assets)
    assert db.scalar(select(LibraryReadableResourceMetadata)) is None
    assert not list((settings.resolved_storage_root / "covers" / "resources").iterdir())

    def forbidden(*args, **kwargs):
        raise AssertionError("committed pages must be reused")

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", forbidden)
    pipeline.continue_import.execute(ContinueImportTask(task_id))
    assert worker.process_once() == "ok"
    assert {a.id for a in db.scalars(select(LibraryResourceAsset))} == ids
    assert db.scalar(select(LibraryReadableResourceMetadata)).page_count == 3


@pytest.mark.parametrize("delete_resource", [False, True])
def test_image_cancellation_prevents_batch_writeback(
    library, monkeypatch, delete_resource
):
    from sqlalchemy import delete

    from app.models import LibraryResourceAsset
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    db, _settings, root, pipeline = library
    write_pages(root, "IMAGE_DIR")
    task_id = scan(db, pipeline)["Book"]
    resource_id = db.scalar(select(LibraryReadableResource.id))
    parse = RegistryResourceAdapterExecutor.parse_file

    def cancel(self, **kwargs):
        result = parse(self, **kwargs)
        with Session(db.get_bind()) as other:
            if delete_resource:
                other.execute(
                    delete(LibraryReadableResource).where(
                        LibraryReadableResource.id == resource_id
                    )
                )
            else:
                other.execute(
                    delete(LibraryImportTask).where(LibraryImportTask.id == task_id)
                )
            other.commit()
        return result

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", cancel)
    db.commit()
    assert pipeline.process_import_task.execute(task_id).outcome == "cancelled"
    assert db.scalars(select(LibraryResourceAsset)).all() == []
    assert db.get(LibraryImportTask, task_id) is None
    if delete_resource:
        assert db.get(LibraryReadableResource, resource_id) is None


@pytest.mark.parametrize("invalid", ["library", "directory", "outside", "suffix"])
def test_image_batch_keeps_topology_and_file_type_validation(library, invalid):
    from dataclasses import replace
    from datetime import UTC, datetime

    from app.models import LibraryResourceAsset
    from app.modules.library.public import DirectoryAssetResult, SourceNodeRelativePath

    db, _settings, root, pipeline = library
    write_pages(root, "IMAGE_DIR")
    task_id = scan(db, pipeline)["Book"]
    resource_id = db.get(LibraryImportTask, task_id).resource_id
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemyBookResourceRepository,
    )

    repository = SqlAlchemyBookResourceRepository(db)
    member = repository.load_directory_members(resource_id)[0]
    node_id = member.node.id
    if invalid == "directory":
        node_id = db.get(LibraryImportTask, task_id).source_node_id
    elif invalid in {"outside", "suffix"}:
        path = "Other.png" if invalid == "outside" else "Book/notes.txt"
        db.add(
            LibrarySourceNode(
                id="invalid-node",
                library_id="lib",
                relative_path=path,
                path_key=SourceNodeRelativePath(path).path_key,
                name=Path(path).name,
                physical_kind="REGULAR_FILE",
                observed_size_bytes=1,
                observed_mtime_ns=0,
                observed_at=datetime.now(UTC),
            )
        )
        db.commit()
        node_id = "invalid-node"
    result = DirectoryAssetResult(
        replace(member.node, id=node_id), "test-version", "page", "image/png", None
    )
    with pytest.raises(ValueError), pipeline.uow.transaction():
        repository.save_directory_assets(
            library_id="other-library" if invalid == "library" else "lib",
            resource_id=resource_id,
            results=(result,),
        )
    assert db.scalars(select(LibraryResourceAsset)).all() == []


def test_image_failed_file_summary_counts_assets_not_tasks(library, monkeypatch):
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )
    from app.modules.library.infrastructure.books import resource_import_summaries

    db, _settings, root, pipeline = library
    write_pages(root, "IMAGE_DIR")
    scan(db, pipeline)
    parse = RegistryResourceAdapterExecutor.parse_file

    def fail(self, **kwargs):
        if kwargs["absolute_path"].name != "1.png":
            raise OSError("injected file error")
        return parse(self, **kwargs)

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", fail)
    assert build_readable_resource_worker(pipeline).process_once() == "failed"
    resource = db.scalar(select(LibraryReadableResource))
    summary = resource_import_summaries(db, [resource.book_id])[resource.book_id]
    assert summary.ready == 1 and summary.failed_files == 2
    assert (
        len(
            db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE",
                    LibraryImportTask.state == "FAILED",
                )
            ).all()
        )
        == 1
    )


@pytest.mark.parametrize("tracks", [10, 20, 100])
@pytest.mark.parametrize("interrupted", [False, True])
def test_audio_resource_batches_reuse_tracks_and_finalize_once(
    library, monkeypatch, tracks, interrupted
):
    from collections import Counter

    from sqlalchemy import event

    from app.models import LibraryResourceAsset, ReadableResourceNavigationUnit
    from app.modules.imports.application.audio_types import (
        AudioChapterMetadata,
        AudioFileMetadata,
    )
    from app.modules.imports.application.readable_resource.continue_import import (
        ContinueImportTask,
    )
    from app.modules.imports.infrastructure.audio_metadata_inspector import (
        BoundedAudioMetadataInspector,
    )
    from app.modules.imports.infrastructure.local_cover_publication import (
        FilesystemLocalCoverPublication,
    )
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemyBookResourceRepository,
    )

    db, settings, root, pipeline = library
    folder = root / "Album"
    folder.mkdir()
    for index in range(1, tracks + 1):
        (folder / f"{index}.mp3").write_bytes(b"audio")
    cover = BytesIO()
    Image.new("RGB", (32, 32), "red").save(cover, format="PNG")
    parsed = Counter()
    counts = Counter()
    phase = "scan"
    sql = {name: Counter() for name in ("scan", "asset", "finish", "aggregate")}
    engine = db.get_bind()

    def executed(conn, cursor, statement, parameters, context, executemany):
        sql[phase]["driver_calls"] += 1
        sql[phase]["executemany_calls"] += int(executemany)
        if cursor.rowcount >= 0:
            sql[phase]["affected_rows"] += cursor.rowcount
        if statement.startswith('UPDATE "ReadableResourceNavigationUnit"'):
            counts["chapter_order_update_calls"] += 1
            assert phase == "aggregate"

    def committed(conn):
        sql[phase]["commit_calls"] += 1
        sql[phase]["actual_commits"] += int(
            conn.connection.driver_connection.in_transaction
        )

    event.listen(engine, "after_cursor_execute", executed)
    event.listen(engine, "commit", committed)
    batch_save = pipeline.process_import_task._save_directory_batch

    def measured_batch(*args):
        nonlocal phase
        phase = "asset"
        try:
            return batch_save(*args)
        finally:
            phase = "finish"

    monkeypatch.setattr(
        pipeline.process_import_task, "_save_directory_batch", measured_batch
    )
    broken = set()
    changed = set()
    unknown = set()

    def inspect(self, path):
        assert not db.in_transaction()
        index = int(path.stem)
        parsed[index] += 1
        if index in broken:
            raise ValueError("damaged track fixture")
        return AudioFileMetadata(
            path=path,
            title=f"Track {index}",
            album="Album",
            author="Author",
            narrator=None,
            duration_ms=None if index in unknown else 3000,
            codec="mp3",
            bitrate=128000,
            sample_rate=44100,
            channels=2,
            disc_number=1 if index in changed else 2,
            track_number=index,
            chapters=tuple(
                AudioChapterMetadata(f"{index}.{c}", (c - 1) * 1000, c * 1000)
                for c in range(1, 4)
            ),
            cover_data=cover.getvalue(),
            cover_extension=".png",
        )

    aggregate = SqlAlchemyBookResourceRepository.refresh_audio_resource_aggregates
    publish = FilesystemLocalCoverPublication.publish
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    resource_inspect = RegistryResourceAdapterExecutor.inspect_resource_metadata
    resource_merge = SqlAlchemyBookResourceRepository.apply_local_metadata

    def inspect_resource(self, **kwargs):
        counts["directory_metadata_inspections"] += 1
        return resource_inspect(self, **kwargs)

    def merge_resource(self, **kwargs):
        counts["resource_metadata_merges"] += 1
        return resource_merge(self, **kwargs)

    monkeypatch.setattr(
        RegistryResourceAdapterExecutor, "inspect_resource_metadata", inspect_resource
    )
    monkeypatch.setattr(
        SqlAlchemyBookResourceRepository, "apply_local_metadata", merge_resource
    )

    def aggregate_count(self, resource_id):
        nonlocal phase
        counts["global_audio_ordering"] += 1
        phase = "aggregate"
        try:
            return aggregate(self, resource_id)
        finally:
            phase = "finish"

    def publish_count(self, prepared):
        counts["cover_publications"] += 1
        return publish(self, prepared)

    monkeypatch.setattr(BoundedAudioMetadataInspector, "inspect", inspect)
    monkeypatch.setattr(
        SqlAlchemyBookResourceRepository,
        "refresh_audio_resource_aggregates",
        aggregate_count,
    )
    monkeypatch.setattr(FilesystemLocalCoverPublication, "publish", publish_count)
    task_id = scan(db, pipeline)["Album"]
    assert not db.scalars(
        select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_ASSET")
    ).all()
    phase = "finish"
    worker = build_readable_resource_worker(pipeline)
    if interrupted:
        save = pipeline.process_import_task._save_directory_batch

        def crash(*args):
            save(*args)
            raise KeyboardInterrupt()

        monkeypatch.setattr(
            pipeline.process_import_task, "_save_directory_batch", crash
        )
        with pytest.raises(KeyboardInterrupt):
            worker.process_once()
        assert len(db.scalars(select(LibraryResourceAsset)).all()) == tracks
        assert (
            len(db.scalars(select(ReadableResourceNavigationUnit)).all()) == tracks * 3
        )
        assert counts == {}
        engine = db.get_bind()
        db.close()
        with Session(engine) as resumed:
            restored = build_readable_resource_pipeline(resumed, settings)
            restarted = build_readable_resource_worker(restored)
            assert restarted.startup() == 1
            restored.continue_import.execute(ContinueImportTask(task_id))
            assert restarted.process_once() == "ok"
    else:
        assert worker.process_once() == "ok"
    assert parsed == {i: 1 for i in range(1, tracks + 1)}
    assert counts == {
        "global_audio_ordering": 1,
        "cover_publications": 1,
        "chapter_order_update_calls": 2,
        "directory_metadata_inspections": 1,
        "resource_metadata_merges": 1,
    }
    assert sql["asset"]["actual_commits"] == 1
    print(
        {
            "mode": "interrupted" if interrupted else "normal",
            "tracks": tracks,
            "chapters": tracks * 3,
            "resource_tasks": 1,
            "parses": sum(parsed.values()),
            "work": dict(counts),
            "sql": {key: dict(value) for key, value in sql.items()},
        }
    )
    event.remove(engine, "after_cursor_execute", executed)
    event.remove(engine, "commit", committed)
    resource = db.scalar(select(LibraryReadableResource))
    assets = db.scalars(
        select(LibraryResourceAsset).order_by(LibraryResourceAsset.sequence_index)
    ).all()
    assert len(assets) == tracks and all(a.role == "TRACK" for a in assets)
    chapters = db.scalars(
        select(ReadableResourceNavigationUnit).order_by(
            ReadableResourceNavigationUnit.sort_order
        )
    ).all()
    assert [c.title for c in chapters] == [
        f"{i}.{c}" for i in range(1, tracks + 1) for c in range(1, 4)
    ]
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert (metadata.track_count, metadata.chapter_count, metadata.duration_ms) == (
        tracks,
        tracks * 3,
        tracks * 3000,
    )
    assert (
        len(
            list(
                (settings.resolved_storage_root / "covers/resources").glob(
                    "*-candidate-*"
                )
            )
        )
        == 1
    )
    if interrupted:
        return
    import json

    from app.models import ReaderResourceProgress, User

    db.add(
        User(
            id="audio-reader",
            email="audio@example.test",
            name="Listener",
            password_hash="fixture",
        )
    )
    db.commit()
    locator = json.dumps(
        {"chapterId": chapters[0].id, "assetId": chapters[0].asset_id, "offsetMs": 250}
    )
    db.add(
        ReaderResourceProgress(
            id="audio-progress",
            user_id="audio-reader",
            resource_id=resource.id,
            reader_type="audio",
            position="250",
            extra=locator,
        )
    )
    db.commit()
    stable = {a.id: a.processed_source_version for a in assets}
    stable_chapters = {c.id for c in chapters if c.asset_id != assets[-1].id}
    changed.add(tracks)
    (folder / f"{tracks}.mp3").write_bytes(b"changed audio version")
    parsed.clear()
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert parsed == {tracks: 1}
    assert counts["global_audio_ordering"] == 2 and counts["cover_publications"] == 1
    assert all(
        db.get(ReadableResourceNavigationUnit, chapter_id) is not None
        for chapter_id in stable_chapters
    )
    assert all(
        db.get(LibraryResourceAsset, key).processed_source_version == value
        for key, value in stable.items()
        if key != assets[-1].id
    )
    ordered = db.scalars(
        select(ReadableResourceNavigationUnit).order_by(
            ReadableResourceNavigationUnit.sort_order
        )
    ).all()
    assert ordered[0].title == f"{tracks}.1"
    assert [c.sort_order for c in ordered] == list(range(tracks * 3))
    parsed.clear()
    (folder / "metadata.opf").write_text(
        "<package><metadata><title>OPF title</title></metadata></package>"
    )
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert not parsed
    assert db.get(LibraryReadableResourceMetadata, resource.id).title == "OPF title"
    Image.new("RGB", (40, 40), "blue").save(folder / "metadata.cover.png")
    (folder / "metadata.opf").write_text(
        '<package><metadata><title>OPF title</title><meta name="cover" content="cover"/></metadata><manifest><item id="cover" href="metadata.cover.png" media-type="image/png"/></manifest></package>'
    )
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert not parsed
    assert counts["cover_publications"] == 2
    # A damaged changed track loses its own chapters, never the other tracks'.
    broken.add(tracks)
    (folder / f"{tracks}.mp3").write_bytes(b"damaged audio")
    scan(db, pipeline)
    assert worker.process_once() == "failed"
    assert parsed == {tracks: 1}
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert (metadata.track_count, metadata.chapter_count, metadata.duration_ms) == (
        tracks - 1,
        (tracks - 1) * 3,
        (tracks - 1) * 3000,
    )
    assert all(
        db.get(ReadableResourceNavigationUnit, chapter_id) is not None
        for chapter_id in stable_chapters
    )
    broken.clear()
    unknown.add(tracks)
    parsed.clear()
    pipeline.continue_import.execute(ContinueImportTask(task_id))
    assert worker.process_once() == "ok"
    assert parsed == {tracks: 1}
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata.track_count == tracks and metadata.chapter_count == tracks * 3
    assert metadata.duration_ms is None
    assert db.get(ReaderResourceProgress, "audio-progress").extra == locator
    assert db.get(ReadableResourceNavigationUnit, chapters[0].id) is not None
    parsed.clear()
    (folder / f"{tracks}.mp3").unlink()
    (folder / "metadata.cover.png").unlink()
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert not parsed
    db.expire_all()
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert (metadata.track_count, metadata.chapter_count, metadata.duration_ms) == (
        tracks - 1,
        (tracks - 1) * 3,
        (tracks - 1) * 3000,
    )
    assert db.get(ReaderResourceProgress, "audio-progress").extra == locator
    assert db.get(ReadableResourceNavigationUnit, chapters[0].id) is not None
    assert counts["cover_publications"] == 3


@pytest.mark.parametrize("file_count", [200, 2000])
def test_scan_node_batches_and_unchanged_scan(library, monkeypatch, file_count):
    import os
    from collections import Counter

    from sqlalchemy import event

    from app.models import LibraryResourceAsset
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )
    from app.modules.imports.infrastructure.readable_resource.filesystem import (
        OsSourceTreeFilesystem,
    )
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemySourceNodeRepository,
    )

    db, _settings, root, pipeline = library
    folder = root / "Book"
    folder.mkdir()
    out = BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, format="PNG")
    for index in range(file_count):
        (folder / f"{index}.png").write_bytes(out.getvalue())
    stats = Counter()
    enumeration = Counter()
    batch_sizes = []
    original = SqlAlchemySourceNodeRepository.reconcile_batch

    def batch(self, **kwargs):
        batch_sizes.append(len(kwargs["entries"]))
        return original(self, **kwargs)

    original_iter = OsSourceTreeFilesystem.iter_directory_entries

    def listing(self, path):
        enumeration[path.name] += 1
        yield from original_iter(self, path)

    monkeypatch.setattr(SqlAlchemySourceNodeRepository, "reconcile_batch", batch)
    monkeypatch.setattr(OsSourceTreeFilesystem, "iter_directory_entries", listing)

    def executed(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('UPDATE "LibrarySourceNode"'):
            stats["node_update_calls"] += 1
            stats["node_update_rows"] += max(0, cursor.rowcount)
            assert executemany
        stats["driver_calls"] += 1
        stats["executemany_calls"] += int(executemany)
        stats["selects"] += int(statement.lstrip().startswith("SELECT"))
        stats["affected_rows"] += max(0, cursor.rowcount)

    def commit(conn):
        stats["commits"] += int(conn.connection.driver_connection.in_transaction)

    engine = db.get_bind()
    event.listen(engine, "after_cursor_execute", executed)
    event.listen(engine, "commit", commit)
    try:
        scan(db, pipeline)
        initial = dict(stats)
        assert batch_sizes == [1] + [200] * (file_count // 200)
        assert enumeration["Book"] == 1
        # Calls grow per business batch, not per member. Multirow DML rows
        # and actual commits are counted independently from driver invocations.
        assert stats["driver_calls"] < 80 + 16 * (file_count // 200)
        worker = build_readable_resource_worker(pipeline)
        assert worker.process_once() == "ok"
        while worker.process_once() != "idle":
            pass
        db.expire_all()
        old_nodes = {n.id: n.observed_at for n in db.scalars(select(LibrarySourceNode))}
        old_assets = {
            a.id: a.updated_at for a in db.scalars(select(LibraryResourceAsset))
        }
        old_tasks = {
            t.id: t.finished_at
            for t in db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
        }

        def forbidden(*args, **kwargs):
            raise AssertionError("unchanged scan parsed media")

        monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", forbidden)
        stats.clear()
        scan(db, pipeline)
        assert worker.process_once() == "idle"
        unchanged = dict(stats)
        db.expire_all()
        assert old_nodes == {
            n.id: n.observed_at for n in db.scalars(select(LibrarySourceNode))
        }
        assert old_assets == {
            a.id: a.updated_at for a in db.scalars(select(LibraryResourceAsset))
        }
        assert old_tasks == {
            t.id: t.finished_at
            for t in db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_RESOURCE"
                )
            )
        }
        for page in folder.glob("*.png"):
            stamp = page.stat()
            os.utime(page, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000))
        stats.clear()
        scan(db, pipeline)
        changed = dict(stats)
        assert stats["node_update_calls"] == file_count // 200
        assert stats["node_update_rows"] == file_count
        assert (
            len(
                db.scalars(
                    select(LibraryImportTask).where(
                        LibraryImportTask.kind == "IMPORT_RESOURCE",
                        LibraryImportTask.state == "QUEUED",
                    )
                ).all()
            )
            == 1
        )
        print(
            {
                "files": file_count,
                "initial_scan": initial,
                "unchanged_scan": unchanged,
                "changed_scan": changed,
            }
        )
    finally:
        event.remove(engine, "after_cursor_execute", executed)
        event.remove(engine, "commit", commit)


def test_scan_committed_batch_keeps_intent_and_blocks_incomplete_resource(
    library, monkeypatch
):
    from collections import Counter

    from sqlalchemy import event

    from app.models import LibraryResourceAsset
    from app.modules.library.infrastructure.persistence.source_tree_repository import (
        SqlAlchemySourceNodeRepository,
    )

    db, _settings, root, pipeline = library
    folder = write_pages(root, "IMAGE_DIR")
    scan(db, pipeline)
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "ok"
    while worker.process_once() != "idle":
        pass
    resource_id = db.scalar(select(LibraryReadableResource.id))
    previous = db.scalar(
        select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_RESOURCE")
    )
    phase = "interrupted_scan"
    sql = {"interrupted_scan": Counter(), "recovery": Counter()}
    engine = db.get_bind()

    def executed(conn, cursor, statement, parameters, context, executemany):
        sql[phase]["driver_calls"] += 1
        sql[phase]["executemany_calls"] += int(executemany)
        sql[phase]["affected_rows"] += max(0, cursor.rowcount)

    def committed(conn):
        sql[phase]["commits"] += int(conn.connection.driver_connection.in_transaction)

    event.listen(engine, "after_cursor_execute", executed)
    event.listen(engine, "commit", committed)
    try:
        original = SqlAlchemySourceNodeRepository.reconcile_batch
        count = 0

        def fail_after_batch(self, **kwargs):
            nonlocal count
            count += 1
            if count == 3:
                raise KeyboardInterrupt("after committed first member batch")
            return original(self, **kwargs)

        content = (folder / "1.png").read_bytes()
        for index in range(11, 411):
            (folder / f"{index}.png").write_bytes(content)
        monkeypatch.setattr(
            SqlAlchemySourceNodeRepository, "reconcile_batch", fail_after_batch
        )
        pipeline.continue_import.execute(ContinueLibraryImport("lib"))
        with pytest.raises(KeyboardInterrupt):
            worker.process_once()
        db.expire_all()
        assert db.get(LibraryImportTask, previous.id).state == "QUEUED"
        assert (
            len(
                db.scalars(
                    select(LibrarySourceNode).where(
                        LibrarySourceNode.physical_kind == "REGULAR_FILE"
                    )
                ).all()
            )
            >= 200
        )
        assert len(db.scalars(select(LibraryResourceAsset)).all()) == 3
        phase = "recovery"
        worker = build_readable_resource_worker(pipeline)
        assert worker.startup() == 1
        assert worker.process_once() == "idle"
        monkeypatch.setattr(SqlAlchemySourceNodeRepository, "reconcile_batch", original)
        pipeline.queue.enqueue(kind="SCAN_LIBRARY", library_id="lib")
        db.commit()
        scan(db, pipeline)
        assert worker.process_once() == "ok"
        assert db.scalar(select(LibraryReadableResource.id)) == resource_id
        assert len(db.scalars(select(LibraryResourceAsset)).all()) == 403
        print(
            {
                "scan_crash_after_member_batch": dict(sql["interrupted_scan"]),
                "recovery_scan_and_import": dict(sql["recovery"]),
                "final_assets": 403,
            }
        )
    finally:
        event.remove(engine, "after_cursor_execute", executed)
        event.remove(engine, "commit", committed)


def test_scan_sidecar_config_deletion_and_equal_count_member_change(
    library, monkeypatch
):
    import json

    from app.models import LibraryResourceAsset
    from app.models.organize import OrganizePolicy
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    db, _settings, root, pipeline = library
    folder = write_pages(root, "IMAGE_DIR")
    opf = folder / "metadata.opf"
    opf.write_text(
        "<package><metadata><title>Sidecar title</title><description>Sidecar description</description></metadata></package>"
    )
    scan(db, pipeline)
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "ok"
    while worker.process_once() != "idle":
        pass
    resource = db.scalar(select(LibraryReadableResource))
    original_ids = {
        a.source_node_id: a.id for a in db.scalars(select(LibraryResourceAsset))
    }
    original_parse = RegistryResourceAdapterExecutor.parse_file
    parsed = []

    def parse(self, **kwargs):
        parsed.append(kwargs["absolute_path"].name)
        return original_parse(self, **kwargs)

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", parse)
    policy = db.scalar(select(OrganizePolicy))
    if policy is None:
        policy = OrganizePolicy(id="default")
        db.add(policy)
    policy.local_metadata_priority_json = json.dumps(
        ["PATH", "SIDECAR_OPF", "EMBEDDED"]
    )
    db.commit()
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert parsed == []
    db.expire_all()
    assert db.get(LibraryReadableResourceMetadata, resource.id).title == "Book"
    opf.unlink()
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert parsed == []
    db.expire_all()
    assert db.get(LibraryReadableResourceMetadata, resource.id).description is None
    old_cover = db.get(LibraryReadableResourceMetadata, resource.id).cover_path
    # Same count, different membership; old page zero is no longer a cover candidate.
    (folder / "1.png").unlink()
    (folder / "20.png").write_bytes((folder / "2.png").read_bytes())
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    assert parsed == ["20.png"]
    db.expire_all()
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata.page_count == 3
    assert metadata.cover_path != old_cover
    for asset in db.scalars(select(LibraryResourceAsset)):
        if asset.source_node_id in original_ids:
            assert asset.id == original_ids[asset.source_node_id]
    for file in folder.glob("*.png"):
        file.unlink()
    scan(db, pipeline)
    # Current recognition rules turn an empty folder into NODE_ONLY.
    assert db.get(LibraryReadableResource, resource.id) is None
    assert not db.scalars(select(LibraryResourceAsset)).all()


def test_single_file_sidecar_refresh_does_not_parse_media(library, monkeypatch):
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    db, _settings, root, pipeline = library
    source = write_pages(root, "PDF")
    scan(db, pipeline)
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "ok"
    while worker.process_once() != "idle":
        pass

    def forbidden(*args, **kwargs):
        raise AssertionError("sidecar-only change parsed PDF")

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", forbidden)
    source.with_suffix(".opf").write_text(
        "<package><metadata><title>New PDF title</title></metadata></package>"
    )
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    db.expire_all()
    assert db.scalar(select(LibraryReadableResourceMetadata)).title == "New PDF title"
    fallback = db.scalar(select(LibraryReadableResourceMetadata)).cover_path
    cover = source.parent / "metadata.cover.png"
    Image.new("RGB", (20, 20), "green").save(cover)
    source.with_suffix(".opf").write_text(
        "<package><metadata><title>New PDF title</title><meta name='cover' content='c'/></metadata><manifest><item id='c' href='metadata.cover.png' media-type='image/png'/></manifest></package>"
    )
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    db.expire_all()
    assert db.scalar(select(LibraryReadableResourceMetadata)).cover_path != fallback
    cover.unlink()
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    db.expire_all()
    assert db.scalar(select(LibraryReadableResourceMetadata)).cover_path == fallback


def test_explicit_resource_force_preserves_ids_and_reprocesses(library, monkeypatch):
    from app.models import LibraryResourceAsset
    from app.modules.imports.application.readable_resource.continue_import import (
        ContinueImportTask,
    )
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    db, _settings, root, pipeline = library
    write_pages(root, "IMAGE_DIR")
    scan(db, pipeline)
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "ok"
    while worker.process_once() != "idle":
        pass
    original_ids = set(db.scalars(select(LibraryResourceAsset.id)))
    task = db.scalar(
        select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_RESOURCE")
    )
    parsed = []
    original_parse = RegistryResourceAdapterExecutor.parse_file

    def parse(self, **kwargs):
        parsed.append(kwargs["absolute_path"].name)
        return original_parse(self, **kwargs)

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", parse)
    pipeline.continue_import.execute(ContinueImportTask(task.id, force=True))
    assert worker.process_once() == "ok"
    assert sorted(parsed) == ["1.png", "10.png", "2.png"]
    assert set(db.scalars(select(LibraryResourceAsset.id))) == original_ids


def test_external_sidecar_cover_changes_without_media_parse(library, monkeypatch):
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )

    db, _settings, root, pipeline = library
    folder = write_pages(root, "IMAGE_DIR")
    # Existing discovery supports a sibling Book.opf and a cover under its directory.
    opf = root / "Book.opf"
    opf.write_text(
        "<package><metadata><title>External</title><meta name='cover' content='c'/></metadata><manifest><item id='c' href='Book/metadata.cover.png' media-type='image/png'/></manifest></package>"
    )
    cover = folder / "metadata.cover.png"
    cover.write_bytes((folder / "1.png").read_bytes())
    scan(db, pipeline)
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "ok"
    while worker.process_once() != "idle":
        pass
    old_cover = db.scalar(select(LibraryReadableResourceMetadata)).cover_path

    def forbidden(*args, **kwargs):
        raise AssertionError("cover-only change parsed media")

    monkeypatch.setattr(RegistryResourceAdapterExecutor, "parse_file", forbidden)
    cover.write_bytes((folder / "2.png").read_bytes())
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    db.expire_all()
    assert db.scalar(select(LibraryReadableResourceMetadata)).cover_path != old_cover
    opf.unlink()
    scan(db, pipeline)
    assert worker.process_once() == "ok"
    db.expire_all()
    assert db.scalar(select(LibraryReadableResourceMetadata)).title == "Book"
