import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import Settings
from app.modules.backup.application.operations import BackupOperationError
from app.modules.backup.infrastructure.archive import backup_path, upload_backup
from app.modules.backup.infrastructure.inspection import inspect_backup


def test_upload_preserves_bytes_and_assigns_atomic_collision_indices(tmp_path):
    settings = Settings(storage_root=str(tmp_path))
    payload = b"stored without compatibility gating"
    with ThreadPoolExecutor(max_workers=6) as executor:
        paths = list(
            executor.map(
                lambda _: upload_backup(settings, "备份.zip", io.BytesIO(payload)),
                range(6),
            )
        )
    assert {path.name for path in paths} == {
        "备份.zip",
        *(f"备份（{i}）.zip" for i in range(1, 6)),
    }
    assert all(path.read_bytes() == payload for path in paths)
    assert (
        upload_backup(settings, "备份（1）.zip", io.BytesIO(payload)).name
        == "备份（1）（1）.zip"
    )
    backup_path(settings, "备份（2）").unlink()
    assert (
        upload_backup(settings, "备份.zip", io.BytesIO(payload)).name == "备份（2）.zip"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "../bad.zip",
        "a/b.zip",
        "a\\b.zip",
        "C:bad.zip",
        ".hidden.zip",
        "CON.zip",
        "bad.txt",
    ],
)
def test_upload_rejects_unsafe_names(tmp_path, filename):
    with pytest.raises(BackupOperationError):
        upload_backup(
            Settings(storage_root=str(tmp_path)), filename, io.BytesIO(b"data")
        )
    assert not list(tmp_path.rglob("*.zip"))


def test_interrupted_upload_removes_partial_file(tmp_path):
    class BrokenStream(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("interrupted upload")
            return super().read(size)

    with pytest.raises(OSError, match="interrupted"):
        upload_backup(
            Settings(storage_root=str(tmp_path)), "backup.zip", BrokenStream(b"partial")
        )
    assert list((tmp_path / "backups").iterdir()) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, None),
        ({"version": 4}, "BACKUP_FORMAT_MISMATCH"),
        ({"databaseRevision": "older"}, "BACKUP_DATABASE_MISMATCH"),
        ({"app": "another-app"}, "BACKUP_APP_MISMATCH"),
        ({"databaseRevision": None}, "BACKUP_METADATA_INVALID"),
    ],
)
def test_compatibility_reports_the_exact_difference(tmp_path, changes, expected):
    metadata = {
        "app": "ermao-books",
        "version": 5,
        "databaseRevision": "current",
        **changes,
    }
    path = tmp_path / "backup.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("metadata.json", json.dumps(metadata))
        archive.writestr("database-export.json", "{}")
    check = inspect_backup(path, "current").compatibility
    assert (check.problem.code if check.problem else None) == expected
    if expected:
        assert check.status != "compatible"
        assert check.problem.message and check.problem.message_en
    else:
        assert check.status == "compatible"


def test_missing_member_and_corrupt_zip_are_distinct(tmp_path):
    path = tmp_path / "backup.zip"
    path.write_bytes(b"broken")
    assert (
        inspect_backup(path, "current").compatibility.problem.code
        == "BACKUP_ZIP_INVALID"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("metadata.json", "{}")
    check = inspect_backup(path, "current").compatibility
    assert check.problem.code == "BACKUP_MEMBER_INVALID"
    assert check.problem.params["member"] == "database-export.json"
