"""End-to-end coverage for comic archive import and Reader delivery."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import User
from app.models.library import Library, ReadableResourceNavigationUnit
from app.models.organize import OrganizePolicy
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
)
from app.modules.imports.infrastructure.readable_resource import adapter_registry
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
)
from tests.support.import_fixtures import write_epub_metadata_fixture

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_cbz(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("001.png", _ONE_PIXEL_PNG)
        archive.writestr("002.png", _ONE_PIXEL_PNG)


def _other_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1), color="red").save(output, format="PNG")
    return output.getvalue()


def _write_image_directory(path: Path) -> None:
    path.mkdir()
    (path / "page10.png").write_bytes(_ONE_PIXEL_PNG)
    (path / "page2.png").write_bytes(_ONE_PIXEL_PNG)


def _drain_worker(pipeline) -> None:
    worker = build_readable_resource_worker(pipeline)
    for _ in range(20):
        if worker.process_once() == "idle":
            return
    raise AssertionError("comic import worker did not become idle")


def _login(client: TestClient, db_session: Session) -> None:
    user = User(
        id="comic-pipeline-user",
        email="comic-pipeline@example.com",
        name="Comic Pipeline",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("source_format", ["cbz", "zip"])
def test_scan_import_comic_archive_is_readable_end_to_end(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    tmp_path: Path,
    source_format: str,
) -> None:
    library = db_session.get(Library, "test-library")
    assert library is not None
    root = tmp_path / "comic-library"
    root.mkdir()
    library.root_path = str(root)
    db_session.commit()
    source = root / f"sample.{source_format}"
    _write_cbz(source)
    if source_format == "zip":
        with ZipFile(source, "a") as archive:
            archive.writestr("README.txt", "Text attachment, not a comic page.")
    original = source.read_bytes()

    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    db_session.expire_all()

    resource = db_session.scalar(select(LibraryReadableResource))
    assert resource is not None
    assert resource.adapter_id == "comic-archive"
    assert resource.format == source_format.upper()
    assert resource.import_state == "READY"
    resource_metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert resource_metadata is not None and resource_metadata.page_count == 2
    assert db_session.scalar(select(LibraryBook)) is not None
    asset = db_session.scalar(select(LibraryResourceAsset))
    assert asset is not None
    assert asset.import_state == "READY"
    task = db_session.scalar(
        select(LibraryImportTask).where(
            LibraryImportTask.kind == "IMPORT_BOOK"
        )
    )
    assert task is not None
    assert task.state == "SUCCEEDED"
    assert db_session.scalar(
        select(func.count()).select_from(ReadableResourceNavigationUnit).where(
            ReadableResourceNavigationUnit.resource_id == resource.id
        )
    ) == 0

    _login(client, db_session)
    book = db_session.scalar(select(LibraryBook))
    assert book is not None
    book_response = client.get(f"/api/books/{book.id}")
    assert book_response.status_code == 200, book_response.text
    book_resource = book_response.json()["data"]["book"]["resources"][0]
    assert book_resource["format"] == source_format.upper()
    assert book_resource["readerType"] == "comic"
    bootstrap_response = client.get(f"/api/reader/v5/resources/{resource.id}/bootstrap")
    assert bootstrap_response.status_code == 200, bootstrap_response.text
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["readerType"] == "comic"
    assert bootstrap["sourceFormat"] == source_format
    assert bootstrap["publication"]["kind"] == "comic"

    manifest_response = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/manifest"
    )
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()["data"]
    assert manifest["schemaVersion"] == 2
    assert manifest["kind"] == "comic"
    assert manifest["sourceFormat"] == source_format
    assert len(manifest["readingOrder"]) == 2
    assert manifest["revision"].startswith("sha256:")

    stale_response = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/pages/0",
        params={"revision": "sha256:" + "0" * 64},
    )
    assert stale_response.status_code == 412
    assert stale_response.json()["error"]["code"] == "COMIC_RESOURCE_CHANGED"
    page_response = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/pages/0",
        params={"revision": manifest["revision"]},
    )
    assert page_response.status_code == 200, page_response.text
    assert page_response.headers["x-comic-revision"] == manifest["revision"]
    assert page_response.headers["content-type"].startswith("image/")
    assert page_response.content
    assert source.read_bytes() == original

    for index in range(2):
        db_session.add(ReadableResourceNavigationUnit(
            id=f"legacy-page-{index}",
            resource_id=resource.id,
            asset_id=asset.id,
            unit_type="page",
            title=f"Page {index + 1}",
            href=f"00{index + 1}.png",
            media_type="image/png",
            sort_order=index,
            metadata_json="{}",
        ))
    db_session.commit()
    legacy_manifest = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/manifest"
    )
    assert legacy_manifest.status_code == 200
    assert len(legacy_manifest.json()["data"]["readingOrder"]) == 2

    with ZipFile(source, "a") as archive:
        archive.writestr("updated.txt", "source changed")
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    db_session.expire_all()
    assert db_session.scalar(
        select(func.count()).select_from(ReadableResourceNavigationUnit).where(
            ReadableResourceNavigationUnit.resource_id == resource.id
        )
    ) == 0
    changed_manifest = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/manifest"
    )
    assert changed_manifest.status_code == 200
    assert changed_manifest.json()["data"]["revision"] != manifest["revision"]


def test_comic_sidecar_cover_skips_archive_image_then_recovers_when_removed(
    db_session: Session,
    test_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = db_session.get(Library, "test-library")
    assert library is not None
    root = tmp_path / "sidecar-comic-library"
    root.mkdir()
    library.root_path = str(root)
    db_session.commit()
    source = root / "sample.cbz"
    _write_cbz(source)
    sidecar_cover = _other_png()
    (root / "cover.png").write_bytes(sidecar_cover)
    sidecar = source.with_suffix(".opf")
    sidecar_text = (
        '<package xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<metadata><dc:title>Comic</dc:title><meta name="cover" content="cover"/>'
        '</metadata><manifest><item id="cover" href="cover.png" '
        'media-type="image/png"/></manifest></package>'
    )
    sidecar.write_text(sidecar_text)
    inspected_cover_modes: list[bool] = []
    original_inspect = adapter_registry.inspect_comic_archive

    def inspect(*args, **kwargs):
        inspected_cover_modes.append(kwargs.get("include_cover", True))
        return original_inspect(*args, **kwargs)

    monkeypatch.setattr(adapter_registry, "inspect_comic_archive", inspect)
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    resource = db_session.scalar(select(LibraryReadableResource))
    assert resource is not None
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None and metadata.cover_path is not None
    first_path = metadata.cover_path
    assert inspected_cover_modes == [False]
    assert (test_settings.resolved_storage_root / first_path).read_bytes() == sidecar_cover

    sidecar.unlink()
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None and metadata.cover_path is not None
    assert metadata.cover_path != first_path
    assert (test_settings.resolved_storage_root / metadata.cover_path).read_bytes() == _ONE_PIXEL_PNG
    assert (test_settings.resolved_storage_root / first_path).read_bytes() == sidecar_cover
    assert True in inspected_cover_modes
    assert len(list((test_settings.resolved_storage_root / "covers" / "resources").glob(
        f"{resource.book_id}-*"
    ))) == 2

    policy = db_session.get(OrganizePolicy, "default")
    if policy is None:
        policy = OrganizePolicy(id="default")
        db_session.add(policy)
    policy.local_metadata_priority_json = '["EMBEDDED","SIDECAR_OPF","PATH"]'
    db_session.commit()
    sidecar.write_text(sidecar_text)
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None and metadata.cover_path != first_path

    policy = db_session.get(OrganizePolicy, "default")
    assert policy is not None
    policy.local_metadata_priority_json = '["SIDECAR_OPF","EMBEDDED","PATH"]'
    db_session.commit()
    sidecar.write_text(sidecar_text + " ")
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None and metadata.cover_path == first_path


@pytest.mark.parametrize("organization_mode", ["FLAT", "VOLUMES"])
def test_scan_import_image_directory_reuses_comic_manifest_without_download(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    tmp_path: Path,
    organization_mode: str,
) -> None:
    library = db_session.get(Library, "test-library")
    assert library is not None
    root = tmp_path / "image-library"
    root.mkdir()
    library.root_path = str(root)
    library.organization_mode = organization_mode
    db_session.commit()
    _write_image_directory(root / "图片目录 Images [01]")

    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    pipeline.continue_import.execute(ContinueLibraryImport("test-library"))
    _drain_worker(pipeline)
    db_session.expire_all()
    resource = db_session.scalar(
        select(LibraryReadableResource).where(
            LibraryReadableResource.format == "IMAGE_DIR"
        )
    )
    assert resource is not None
    page_assets = db_session.scalars(
        select(LibraryResourceAsset).where(
            LibraryResourceAsset.resource_id == resource.id,
            LibraryResourceAsset.role == "PAGE",
        )
    ).all()
    assert len(page_assets) == 2

    _login(client, db_session)
    book_response = client.get(f"/api/books/{resource.book_id}")
    assert book_response.status_code == 200, book_response.text
    book = book_response.json()["data"]["book"]
    assert book["title"] == "图片目录 Images"
    assert book["resources"][0]["title"] == "图片目录 Images [01]"
    assert {asset["title"] for asset in book["resources"][0]["assets"]} == {
        "page2",
        "page10",
    }
    bootstrap_response = client.get(f"/api/reader/v5/resources/{resource.id}/bootstrap")
    assert bootstrap_response.status_code == 200, bootstrap_response.text
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["readerType"] == "comic"
    assert bootstrap["sourceFormat"] == "image_dir"
    assert set(bootstrap["publication"]) == {
        "kind",
        "manifestUrl",
        "positionsUrl",
        "pageUrlTemplate",
        "imageVariants",
    }

    manifest_response = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/manifest"
    )
    assert manifest_response.status_code == 200, manifest_response.text
    manifest = manifest_response.json()["data"]
    assert manifest["schemaVersion"] == 2
    assert manifest["sourceFormat"] == "image_dir"
    assert [page["title"] for page in manifest["readingOrder"]] == [
        "page2.png",
        "page10.png",
    ]

    page_response = client.get(
        f"/api/reader/v5/resources/{resource.id}/comic/pages/0",
        params={"revision": manifest["revision"]},
    )
    assert page_response.status_code == 200, page_response.text
    assert page_response.headers["content-type"].startswith("image/")
    assert page_response.content


def test_mixed_book_resources_scan_worker_and_reader_bootstrap(
    client: TestClient, db_session: Session, test_settings: Settings, tmp_path: Path
) -> None:
    import wave

    from PIL import Image

    from app.models import LibraryBookMetadata

    library = db_session.get(Library, "test-library")
    root = tmp_path / "mixed-library"
    work = root / "Work"
    audio = work / "Audio"
    audio.mkdir(parents=True)
    for name in ("1.wav", "2.wav"):
        with wave.open(str(audio / name), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 800)
    _write_image_directory(work / "Pages")
    with Image.new("RGB", (32, 32), "red") as page:
        page.save(work / "single.pdf", format="PDF")
    (work / "story.txt").write_text("第一章\n\n这是一个真实的文本阅读样例。\n" * 20)
    write_epub_metadata_fixture(work / "story.epub", "Story", "Author")
    library.root_path = str(root)
    library.organization_mode = "VOLUMES"
    db_session.commit()
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    pipeline.continue_import.execute(ContinueLibraryImport(library.id))
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "scan"
    book = db_session.scalar(select(LibraryBook))
    resources = db_session.scalars(select(LibraryReadableResource)).all()
    assert len(resources) == 5 and {r.book_id for r in resources} == {book.id}
    assert not db_session.scalars(
        select(LibraryImportTask).where(LibraryImportTask.kind == "IDENTIFY_BOOK")
    ).all()
    assert worker.process_once() == "book"
    assert worker.process_once() == "idle"
    db_session.expire_all()
    assert db_session.get(LibraryBookMetadata, book.id).metadata_state == "COMPLETED"
    assert all(r.import_state == "READY" for r in resources)
    assert len(db_session.scalars(select(LibraryResourceAsset)).all()) == 7
    _login(client, db_session)
    response = client.get(f"/api/books/{book.id}")
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["book"]["resources"]) == 5
    expected = {
        "IMAGE_DIR": "comic",
        "AUDIOBOOK_DIR": "audio",
        "PDF": "pdf",
        "TXT": "reflowable",
        "EPUB": "reflowable",
    }
    for resource in resources:
        response = client.get(f"/api/reader/v5/resources/{resource.id}/bootstrap")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["readerType"] == expected[resource.format]
        assert data["assets"]
        assert len(data["availableResources"]) == 5
        for asset in data["assets"]:
            content = client.get(asset["url"])
            assert content.status_code == 200, content.text
            assert content.content
        if resource.format == "IMAGE_DIR":
            manifest = client.get(data["publication"]["manifestUrl"])
            assert manifest.status_code == 200, manifest.text
            assert len(manifest.json()["data"]["readingOrder"]) == 2
