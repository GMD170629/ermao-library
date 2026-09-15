"""End-to-end coverage for comic archive import and Reader delivery."""

from __future__ import annotations

import base64
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import User
from app.models.library import Library
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
)

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_cbz(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("001.png", _ONE_PIXEL_PNG)
        archive.writestr("002.png", _ONE_PIXEL_PNG)


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
    assert db_session.scalar(select(LibraryBook)) is not None
    asset = db_session.scalar(select(LibraryResourceAsset))
    assert asset is not None
    assert asset.import_state == "READY"
    task = db_session.scalar(
        select(LibraryImportTask).where(
            LibraryImportTask.kind.in_(("IMPORT_ASSET", "IMPORT_RESOURCE"))
        )
    )
    assert task is not None
    assert task.state == "SUCCEEDED"

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
    library.root_path = str(root)
    library.organization_mode = "VOLUMES"
    db_session.commit()
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    pipeline.continue_import.execute(ContinueLibraryImport(library.id))
    worker = build_readable_resource_worker(pipeline)
    assert worker.process_once() == "scan"
    book = db_session.scalar(select(LibraryBook))
    resources = db_session.scalars(select(LibraryReadableResource)).all()
    assert len(resources) == 4 and {r.book_id for r in resources} == {book.id}
    assert not db_session.scalars(
        select(LibraryImportTask).where(LibraryImportTask.kind == "IDENTIFY_BOOK")
    ).all()
    for _ in resources:
        assert worker.process_once() == "ok"
    assert worker.process_once() == "identified"
    assert worker.process_once() == "idle"
    db_session.expire_all()
    assert db_session.get(LibraryBookMetadata, book.id).metadata_state == "COMPLETED"
    assert all(r.import_state == "READY" for r in resources)
    assert len(db_session.scalars(select(LibraryResourceAsset)).all()) == 6
    _login(client, db_session)
    response = client.get(f"/api/books/{book.id}")
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["book"]["resources"]) == 4
    expected = {
        "IMAGE_DIR": "comic",
        "AUDIOBOOK_DIR": "audio",
        "PDF": "pdf",
        "TXT": "reflowable",
    }
    for resource in resources:
        response = client.get(f"/api/reader/v5/resources/{resource.id}/bootstrap")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["readerType"] == expected[resource.format]
        assert data["assets"]
        assert len(data["availableResources"]) == 4
        for asset in data["assets"]:
            content = client.get(asset["url"])
            assert content.status_code == 200, content.text
            assert content.content
        if resource.format == "IMAGE_DIR":
            manifest = client.get(data["publication"]["manifestUrl"])
            assert manifest.status_code == 200, manifest.text
            assert len(manifest.json()["data"]["readingOrder"]) == 2
