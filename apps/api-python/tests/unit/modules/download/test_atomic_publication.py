from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import download_executor


class _DownloadResponse(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.headers = {"content-disposition": 'attachment; filename="book.epub"'}

    def geturl(self) -> str:
        return "https://example.invalid/book.epub"


def _task(tmp_path: Path) -> dict[str, object]:
    return {
        "id": "download-1",
        "displayName": "Book",
        "savePath": str(tmp_path),
        "remoteRef": {"downloadUrl": "https://example.invalid/book.epub"},
    }


def test_http_download_publishes_only_after_complete_temp_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        download_executor,
        "urlopen",
        lambda *_args, **_kwargs: _DownloadResponse(b"complete-book"),
    )
    real_replace = os.replace
    observed_temporary: list[Path] = []

    def replace(source: str | Path, target: str | Path) -> None:
        source_path = Path(source)
        target_path = Path(target)
        assert source_path.name.endswith(".part")
        assert source_path.read_bytes() == b"complete-book"
        assert not target_path.exists()
        observed_temporary.append(source_path)
        real_replace(source_path, target_path)

    monkeypatch.setattr(download_executor.os, "replace", replace)

    published = download_executor.execute_http_download(
        Settings(storage_root=str(tmp_path / "storage")),
        _task(tmp_path),
    )

    assert published.read_bytes() == b"complete-book"
    assert observed_temporary
    assert list(tmp_path.glob("*.part")) == []


def test_text_receipt_publish_failure_leaves_no_final_or_part_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr(download_executor.os, "replace", fail_replace)

    with pytest.raises(OSError, match="publish failed"):
        download_executor.execute_blackhole(
            Settings(storage_root=str(tmp_path / "storage")),
            _task(tmp_path),
        )

    assert list(tmp_path.iterdir()) == []
