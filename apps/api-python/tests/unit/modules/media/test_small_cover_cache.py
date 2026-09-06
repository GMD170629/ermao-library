from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import pytest
from fastapi import Request
from PIL import Image

from app.core.config import Settings
from app.modules.media.infrastructure import http_streaming


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/books/book-1/cover",
            "headers": [],
            "query_string": b"size=small",
        }
    )


def _source_and_settings(tmp_path: Path) -> tuple[Path, Settings]:
    source = tmp_path / "cover.png"
    Image.new("RGB", (64, 96), color=(201, 92, 48)).save(source, format="PNG")
    settings = Settings(
        session_secret="test-secret", storage_root=str(tmp_path / "storage")
    )
    return source, settings


def _synchronize_concurrent_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    conversion_barrier = Barrier(2)
    original_converter = http_streaming._small_cover_webp_bytes

    def synchronized_converter(path: Path) -> bytes | None:
        conversion_barrier.wait(timeout=5)
        return original_converter(path)

    monkeypatch.setattr(
        http_streaming, "_small_cover_webp_bytes", synchronized_converter
    )


def _request_concurrently(source: Path, settings: Settings) -> list[bytes]:
    original_source = source.read_bytes()
    def request_cover() -> bytes:
        response = http_streaming.small_cover_response(
            source, _request(), "user-1", settings
        )
        assert response is not None
        assert response.status_code == 200
        return response.body

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: request_cover(), range(2)))
    assert source.read_bytes() == original_source
    return responses


def _assert_one_complete_cover_cache(settings: Settings) -> None:
    cache_root = settings.resolved_storage_root / "cache" / "covers"
    cache_files = list(cache_root.rglob("*.webp"))
    assert len(cache_files) == 1
    with Image.open(cache_files[0]) as cached:
        cached.verify()
    assert not list(cache_root.rglob("*.tmp"))


def _windows_replace_error(target_path: str | Path, winerror: int) -> PermissionError:
    error = PermissionError(13, "access denied", str(target_path))
    # Preserve the Windows adapter's normalized error fact on every test host.
    error.winerror = winerror
    return error


def test_small_cover_cache_concurrent_requests_publish_without_replace_injection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, settings = _source_and_settings(tmp_path)
    _synchronize_concurrent_conversion(monkeypatch)

    responses = _request_concurrently(source, settings)

    assert responses[0] == responses[1]
    _assert_one_complete_cover_cache(settings)


@pytest.mark.parametrize("winerror", [5, 32])
def test_small_cover_cache_retries_transient_windows_replace_errors_from_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, winerror: int
) -> None:
    source, settings = _source_and_settings(tmp_path)
    _synchronize_concurrent_conversion(monkeypatch)

    replace_lock = Lock()
    replace_attempts = 0
    temporary_names: set[str] = set()
    original_replace = http_streaming.os.replace

    def transient_windows_lock(
        source_path: str | Path, target_path: str | Path
    ) -> None:
        nonlocal replace_attempts
        with replace_lock:
            replace_attempts += 1
            attempt = replace_attempts
            temporary_names.add(Path(source_path).name)
        if attempt <= 2:
            raise _windows_replace_error(target_path, winerror)
        original_replace(source_path, target_path)

    monkeypatch.setattr(http_streaming.os, "replace", transient_windows_lock)

    responses = _request_concurrently(source, settings)

    assert responses[0] == responses[1]
    assert replace_attempts >= 3
    assert len(temporary_names) == 2
    _assert_one_complete_cover_cache(settings)


def test_small_cover_cache_permanent_windows_replace_failure_preserves_cache_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "storage" / "cache" / "covers" / "aa" / "cover.webp"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-cache")
    errors: list[PermissionError] = []
    replace_attempts = 0

    def permanent_windows_lock(
        _source_path: str | Path, target_path: str | Path
    ) -> None:
        nonlocal replace_attempts
        replace_attempts += 1
        error = _windows_replace_error(target_path, 32)
        errors.append(error)
        raise error

    monkeypatch.setattr(http_streaming.os, "replace", permanent_windows_lock)

    with pytest.raises(PermissionError) as raised:
        http_streaming._write_cache_bytes(target, b"new-cache")

    assert raised.value is errors[-1]
    assert raised.value.winerror == 32
    assert replace_attempts == 1 + len(
        http_streaming._CACHE_REPLACE_RETRY_DELAYS_SECONDS
    )
    assert target.read_bytes() == b"old-cache"
    assert not list(target.parent.glob("*.tmp"))


def test_small_cover_cache_errno_five_without_winerror_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "storage" / "cache" / "covers" / "aa" / "cover.webp"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-cache")
    replace_attempts = 0

    def posix_errno_five(_source_path: str | Path, _target_path: str | Path) -> None:
        nonlocal replace_attempts
        replace_attempts += 1
        raise PermissionError(5, "I/O error")

    monkeypatch.setattr(http_streaming.os, "replace", posix_errno_five)

    with pytest.raises(PermissionError) as raised:
        http_streaming._write_cache_bytes(target, b"new-cache")

    assert raised.value.errno == 5
    assert getattr(raised.value, "winerror", None) is None
    assert replace_attempts == 1
    assert target.read_bytes() == b"old-cache"
    assert not list(target.parent.glob("*.tmp"))
