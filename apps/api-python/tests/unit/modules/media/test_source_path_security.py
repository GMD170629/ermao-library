from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request

from app.core.config import Settings
from app.modules.media.infrastructure.http_streaming import (
    send_file,
    stored_path,
)


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/assets/test-asset",
            "headers": [],
            "query_string": b"",
        }
    )


def _settings(storage_root: Path) -> Settings:
    return Settings(session_secret="test-secret", storage_root=str(storage_root))


def test_source_path_is_contained_after_symlink_resolution(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    safe_file = library_root / "book.epub"
    safe_file.write_bytes(b"safe")
    secret = outside_root / "secret.epub"
    secret.write_bytes(b"secret")
    escape = library_root / "escape.epub"
    escape.symlink_to(secret)
    settings = _settings(tmp_path / "storage")

    assert stored_path("book.epub", settings, (library_root,)) == safe_file.resolve()
    assert stored_path("escape.epub", settings, (library_root,)) is None
    assert stored_path(str(secret), settings, (library_root,)) is None


def test_streaming_rejects_a_symlink_replaced_after_resolution(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        return
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    safe_file = library_root / "book.epub"
    safe_file.write_bytes(b"safe")
    secret = outside_root / "secret.epub"
    secret.write_bytes(b"secret")
    resolved = stored_path(
        "book.epub", _settings(tmp_path / "storage"), (library_root,)
    )
    assert resolved == safe_file.resolve()
    safe_file.unlink()
    safe_file.symlink_to(secret)

    response = send_file(resolved, _request(), "user-1", asset_id="asset-1")

    assert response.status_code == 404


def test_normal_source_file_and_range_still_resolve(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    source = library_root / "book.epub"
    source.write_bytes(b"0123456789")
    settings = _settings(tmp_path / "storage")
    resolved = stored_path("book.epub", settings, (library_root,))

    assert resolved == source.resolve()
    response = send_file(
        resolved,
        Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/assets/test-asset",
                "headers": [(b"range", b"bytes=2-5")],
                "query_string": b"",
            }
        ),
        "user-1",
        asset_id="asset-1",
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-5/10"
