"""TXT encoding regressions through real filesystem events and HTTP uploads."""

from __future__ import annotations

import json
from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.library_scan_runtime import LibraryScanCoordinator
from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.auth import create_session, hash_password
from app.core.config import Settings
from app.models import (
    Library,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    User,
)
from app.modules.imports.domain.library_scan_schedule import LibraryScanSettings
from app.modules.imports.infrastructure.library_scan_settings import (
    SqlAlchemyLibraryScanSettingsRepository,
)


def _drain(db: Session, settings: Settings) -> None:
    worker = build_readable_resource_worker(build_readable_resource_pipeline(db, settings))
    for _ in range(20):
        if worker.process_once() == "idle":
            return
    pytest.fail("TXT import did not finish within its expected work scope")


def _assert_ready(db: Session, source: Path, content: bytes) -> LibraryResourceAsset:
    db.expire_all()
    resource = db.scalar(select(LibraryReadableResource))
    asset = db.scalar(select(LibraryResourceAsset))
    assert resource is not None and asset is not None
    assert resource.import_state == asset.import_state == "READY"
    assert source.read_bytes() == content
    assert any(
        item["source"] == "EMBEDDED" and item["metadata"]["language"] == "zh-CN"
        for item in json.loads(asset.local_metadata_candidates)
    )
    assert all(task.state == "SUCCEEDED" for task in db.scalars(select(LibraryImportTask)))
    return asset


def test_txt_real_watcher_imports_created_and_modified_chinese_source(
    db_session: Session, test_settings: Settings, tmp_path: Path,
) -> None:
    root = tmp_path / "watched"
    root.mkdir()
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(root)
    library.min_file_size_bytes = 0
    SqlAlchemyLibraryScanSettingsRepository(db_session).save(
        LibraryScanSettings(watch_enabled=True, interval_minutes=0)
    )
    db_session.commit()
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    coordinator = LibraryScanCoordinator(
        session=db_session, request_scan=pipeline.request_library_scan,
        uow=pipeline.uow,
    )
    source = root / "中文小说.txt"
    asset_id = None
    try:
        coordinator.tick()
        for text, encoding in (
            ("第一章\n有效中文正文\x00内容。第二段正文内容结束。", "gbk"),
            ("第一章\n修改后的有效中文正文�内容。第二段正文内容结束。", "gb18030"),
        ):
            previous = set(db_session.scalars(select(LibraryImportTask.id)))
            content = text.encode(encoding)
            source.write_bytes(content)
            deadline = monotonic() + 20
            while monotonic() < deadline:
                coordinator.tick()
                current = set(db_session.scalars(select(LibraryImportTask.id)))
                if current - previous:
                    break
                sleep(0.05)
            else:
                pytest.fail("Real filesystem event did not enqueue a TXT import")
            _drain(db_session, test_settings)
            asset = _assert_ready(db_session, source, content)
            if asset_id is not None:
                assert asset.id == asset_id
            asset_id = asset.id
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("encoding", ["gbk", "gb18030", "utf-8", "utf-8-sig", "utf-16"])
def test_txt_http_upload_download_and_reimport_preserve_chinese_bytes(
    client: TestClient, db_session: Session, test_settings: Settings,
    tmp_path: Path, encoding: str,
) -> None:
    root = tmp_path / "uploads"
    root.mkdir()
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(root)
    library.min_file_size_bytes = 0
    owner = User(
        id="txt-upload-owner", email="txt-upload@example.com", name="TXT tester",
        role="admin", password_hash=hash_password("test-password-123"),
    )
    db_session.add(owner)
    db_session.flush()
    _, token = create_session(db_session, owner.id)
    db_session.commit()
    client.cookies.set("shuku_session", token)
    marker = "�" if encoding == "gb18030" else "\x00"
    content = f"第一章\n有效中文正文{marker}内容。第二段正文内容结束。".encode(encoding)
    response = client.post(
        "/api/books/import", headers={"Origin": "http://testserver"},
        data={"targetPath": str(root)},
        files={"file": ("中文小说.txt", content, "text/plain")},
    )
    assert response.status_code == 202, response.text
    assert response.json()["data"]["saved"] == 1
    _drain(db_session, test_settings)
    asset = _assert_ready(db_session, root / "中文小说.txt", content)
    downloaded = client.get(f"/api/assets/{asset.id}")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == content
    task = db_session.scalar(select(LibraryImportTask).where(LibraryImportTask.kind == "IMPORT_BOOK"))
    assert task is not None
    retry = client.post(
        f"/api/library-import-tasks/{task.id}/reimport",
        headers={"Origin": "http://testserver"},
    )
    assert retry.status_code == 202, retry.text
    _drain(db_session, test_settings)
    assert _assert_ready(db_session, root / "中文小说.txt", content).id == asset.id
