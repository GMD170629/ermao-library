from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from appv2.modules.catalog.contracts import CatalogFile
from appv2.modules.ingestion.infrastructure.files import MonitorFileDiscovery
from appv2.modules.operations.contracts import BackupView
from appv2.modules.operations.infrastructure.backup import PgBackupExecutor
from appv2.modules.reading.infrastructure.resources import LocalReaderResources
from appv2.platform.auth import PasswordHasher, new_session_token, token_digest
from appv2.platform.config import Settings
from appv2.platform.filesystem import StorageLayout
from appv2.platform.http.models import CamelModel
from appv2.platform.http.ranges import InvalidRange, parse_range_header


class ExampleModel(CamelModel):
    page_size: int
    trace_id: str


def test_http_models_emit_camel_case() -> None:
    model = ExampleModel(page_size=24, trace_id="abc")
    assert model.model_dump(by_alias=True) == {"pageSize": 24, "traceId": "abc"}


@pytest.mark.parametrize(
    ("raw", "start", "end"),
    [
        ("bytes=0-99", 0, 99),
        ("bytes=100-", 100, None),
        ("bytes=-500", None, 500),
    ],
)
def test_parse_single_byte_ranges(raw: str, start: int | None, end: int | None) -> None:
    parsed = parse_range_header(raw)
    assert parsed is not None
    assert (parsed.start, parsed.end) == (start, end)


@pytest.mark.parametrize(
    "raw",
    ["items=0-1", "bytes=2-1", "bytes=1-2,4-5", "bytes=-", "bytes=bad-2"],
)
def test_reject_invalid_ranges(raw: str) -> None:
    with pytest.raises(InvalidRange):
        parse_range_header(raw)


def test_password_hashes_are_salted_and_verified() -> None:
    hasher = PasswordHasher()
    first = hasher.hash("correct horse battery staple")
    second = hasher.hash("correct horse battery staple")
    assert first != second
    assert hasher.verify("correct horse battery staple", first)
    assert not hasher.verify("wrong password", first)


def test_session_digest_is_keyed_and_stable() -> None:
    token = new_session_token()
    assert token_digest(token, "first") == token_digest(token, "first")
    assert token_digest(token, "first") != token_digest(token, "second")


def test_settings_reject_sqlite(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr(f"sqlite:///{tmp_path / 'legacy.db'}"),
            storage_root=tmp_path,
        )


def test_storage_layout_never_uses_legacy_database_directory(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path / "v2")
    layout.ensure()
    assert {path.name for path in layout.root.iterdir()} == {
        "backups",
        "control",
        "conversions",
        "covers",
        "logs",
        "secrets",
        "temp",
    }
    assert not (tmp_path / "database").exists()
    with pytest.raises(ValueError):
        layout.resolve_inside(tmp_path / "outside")


def test_monitor_tree_is_bounded_and_lists_directories(tmp_path: Path) -> None:
    monitor = tmp_path / "monitor"
    (monitor / "Series" / "Book").mkdir(parents=True)
    discovery = MonitorFileDiscovery(monitor)

    root, configured = discovery.tree()
    assert configured == str(monitor.resolve())
    assert root.path == str(monitor.resolve())
    assert [child.name for child in root.children] == ["Series"]

    series, _ = discovery.tree(str(monitor / "Series"))
    assert [child.name for child in series.children] == ["Book"]
    with pytest.raises(ValueError):
        discovery.tree(str(tmp_path))


def test_cbz_pages_are_naturally_sorted_and_streamed(tmp_path: Path) -> None:
    archive = tmp_path / "comic.cbz"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("chapter/page10.jpg", b"page-ten")
        target.writestr("chapter/page2.png", b"page-two")
        target.writestr("__MACOSX/ignored.jpg", b"ignored")
        target.writestr("notes.txt", b"ignored")
    catalog_file = CatalogFile(
        id=uuid.uuid4(),
        edition_id=uuid.uuid4(),
        storage_path=str(archive),
        original_name=archive.name,
        media_type="application/vnd.comicbook+zip",
        size_bytes=archive.stat().st_size,
        checksum="abc123",
    )
    resources = LocalReaderResources(allowed_roots=(tmp_path,), streams_per_user=2)

    pages = resources.comic_pages(catalog_file)
    assert [page.title for page in pages] == ["page2.png", "page10.jpg"]
    stream = resources.open_comic_page(catalog_file, page_index=1, stream_key="reader")
    assert stream.media_type == "image/png"
    assert b"".join(stream.body) == b"page-two"
    with pytest.raises(ValueError):
        resources.open_comic_page(catalog_file, page_index=3, stream_key="reader")


def test_completed_backup_archive_can_be_streamed(tmp_path: Path) -> None:
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"postgres-custom-backup")
    now = datetime.now(UTC)
    backup = BackupView(
        id=uuid.uuid4(),
        status="completed",
        archive_name=archive.name,
        app_version="0.4.0",
        postgres_major=18,
        alembic_revision="0001_appv2_initial",
        checksum="checksum",
        size_bytes=archive.stat().st_size,
        error_detail=None,
        created_at=now,
        updated_at=now,
    )
    executor = PgBackupExecutor(
        database_url="postgresql+psycopg://unused",
        backups_root=tmp_path,
    )

    opened = executor.open(backup)
    assert opened.filename == archive.name
    assert b"".join(opened.body) == archive.read_bytes()
