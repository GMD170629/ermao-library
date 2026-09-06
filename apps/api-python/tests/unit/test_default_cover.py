from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import pytest

from app.core.config import Settings
from app.infrastructure import atomic_files
from app.services import default_cover


def _windows_replace_error(target_path: str | Path, winerror: int) -> PermissionError:
    error = PermissionError(13, "access denied", str(target_path))
    # Preserve the Windows adapter's normalized error fact on every test host.
    error.winerror = winerror
    return error


@pytest.mark.parametrize("winerror", [5, 32])
def test_default_cover_new_root_concurrent_publish_retries_and_preserves_asset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, winerror: int
) -> None:
    settings = Settings(
        session_secret="test-secret", storage_root=str(tmp_path / "new-root")
    )
    asset_path = default_cover.DEFAULT_COVER_ASSET_PATH
    asset_before = asset_path.read_bytes()
    asset_hash = hashlib.sha256(asset_before).hexdigest()

    replace_lock = Lock()
    replace_barrier = Barrier(2)
    replace_attempts = 0
    temporary_names: set[str] = set()
    original_replace = atomic_files.os.replace

    def transient_windows_lock(
        source_path: str | Path, target_path: str | Path
    ) -> None:
        nonlocal replace_attempts
        with replace_lock:
            replace_attempts += 1
            attempt = replace_attempts
            temporary_names.add(Path(source_path).name)
        if attempt <= 2:
            replace_barrier.wait(timeout=5)
            raise _windows_replace_error(target_path, winerror)
        original_replace(source_path, target_path)

    monkeypatch.setattr(atomic_files.os, "replace", transient_windows_lock)

    with ThreadPoolExecutor(max_workers=2) as executor:
        returned_paths = list(
            executor.map(
                lambda _index: default_cover.ensure_default_cover(settings), range(2)
            )
        )

    target = default_cover.default_cover_path(settings)
    assert returned_paths == [str(default_cover.DEFAULT_COVER_RELATIVE_PATH)] * 2
    assert target.read_bytes() == asset_before
    assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == asset_hash
    assert (
        4
        <= replace_attempts
        <= 2 * (1 + len(atomic_files._ATOMIC_REPLACE_RETRY_DELAYS_SECONDS))
    )
    assert len(temporary_names) == 2
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))
