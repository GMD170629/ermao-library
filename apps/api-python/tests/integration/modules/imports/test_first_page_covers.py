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
            .where(LibraryImportTask.kind == "IMPORT_ASSET")
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
    assert set(tasks) == set(order)
    rendered = []
    original = PageImageRenderer.render

    def render(self, source, page_index):
        rendered.append(source.path.name)
        return original(self, source, page_index)

    monkeypatch.setattr(PageImageRenderer, "render", render)
    for name in order:
        import_task(db, pipeline, tasks[name])
    resource = db.scalar(select(LibraryReadableResource))
    metadata = db.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata.cover_status == "READY"
    content = (settings.resolved_storage_root / metadata.cover_path).read_bytes()
    assert_red(content)
    assert rendered == (["1.png"] if order[0] == "1.png" else list(order))
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
    for name in ("10.png", "2.png"):
        import_task(db, pipeline, tasks[name])
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
