from pathlib import Path
from unittest.mock import Mock

import pytest

from app.modules.system.application.storage import CATEGORIES, StorageManagement
from app.modules.system.infrastructure.storage import FileSystemStorage


def put(root: Path, name: str, size: int) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_metadata_only_classification_and_selective_refresh(tmp_path, monkeypatch):
    paths = {
        "runtime/app.py": "program",
        "dependencies/python": "program",
        "database/shuku.sqlite3-wal": "database",
        "covers/a.jpg": "images",
        "profiles/u/a.jpg": "images",
        "books/b/r/a/cover.jpg": "images",
        "cache/resource-previews/ab/a.webp": "cache",
        "cache/unknown": "cache",
        "logs/api/a.jsonl": "logs",
        "backups/a.zip": "backups",
        "update-tmp/prepare.lock": "updates",
        "automation-uploads/a.part": "uploads",
        "secrets/a": "other",
    }
    expected = dict.fromkeys(CATEGORIES, 0)
    for index, (name, category) in enumerate(paths.items(), 1):
        put(tmp_path, name, index)
        expected[category] += index
    monkeypatch.setattr(
        Path, "read_bytes", Mock(side_effect=AssertionError("must not read content"))
    )
    usage = FileSystemStorage(tmp_path).usage()
    assert usage.sizes == expected
    assert FileSystemStorage(tmp_path).usage("cache").sizes == {
        "cache": expected["cache"]
    }
    assert FileSystemStorage(tmp_path).usage("other").sizes == {
        "other": expected["other"]
    }


def test_missing_directory_during_walk_is_tolerated(tmp_path, monkeypatch):
    from app.modules.system.infrastructure import storage

    put(tmp_path, "logs/api/a.jsonl", 9)
    scan = storage.os.scandir

    def disappear(path):
        if Path(path).name == "api":
            raise FileNotFoundError(path)
        return scan(path)

    monkeypatch.setattr(storage.os, "scandir", disappear)
    assert FileSystemStorage(tmp_path).usage().sizes["logs"] == 0


def test_clear_checks_authority_and_refreshes_only_changed_category(tmp_path):
    target = put(tmp_path, "logs/api/a.jsonl", 9)
    put(tmp_path, "database/shuku.sqlite3", 50)
    use_case = StorageManagement(FileSystemStorage(tmp_path))
    with pytest.raises(PermissionError):
        use_case.clear("logs", authorized=False)
    with pytest.raises(ValueError):
        use_case.clear("database", authorized=True)
    assert target.exists()
    assert use_case.clear("logs", authorized=True).sizes == {"logs": 0}
    assert (tmp_path / "database/shuku.sqlite3").stat().st_size == 50


@pytest.mark.parametrize(
    ("category", "directory"),
    [
        ("cache", "cache"),
        ("logs", "logs"),
        ("backups", "backups"),
        ("updates", "update-tmp/prepared"),
        ("uploads", "automation-uploads"),
    ],
)
def test_clear_deletes_whole_target_and_is_repeatable(tmp_path, category, directory):
    put(tmp_path, f"{directory}/nested/file", 5)
    database = put(tmp_path, "database/shuku.sqlite3", 9)
    control = put(tmp_path, "update-tmp/launcher.lock", 1)
    files = FileSystemStorage(tmp_path)
    files.clear(category)
    files.clear(category)
    assert not (tmp_path / directory).exists()
    assert database.exists() and control.exists()
