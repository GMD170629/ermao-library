from __future__ import annotations

import errno
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import sessionmaker

from app.modules.media.application.resource_preview import ResourcePreviewAccessScope
from app.modules.media.infrastructure import resource_preview_cache as cache_module
from app.modules.media.infrastructure.page_image import PageImageSource
from app.modules.media.infrastructure.resource_preview import (
    FilesystemResourcePreview,
    ResourcePreviewRenderCoordinator,
)
from app.modules.media.infrastructure.resource_preview_cache import (
    PREVIEW_CACHE_TTL_SECONDS,
    ResourcePreviewCache,
)
from app.services import log_maintenance

NOW = 1_800_000_000.0
DIGEST = "ab" + "1" * 62


def cache_file(storage: Path, *, digest: str = DIGEST, age: float = 0) -> Path:
    path = storage / "cache" / "resource-previews" / digest[:2] / f"{digest}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"preview")
    os.utime(path, (NOW - age, NOW - age))
    return path


def test_cache_hit_does_not_extend_seven_day_expiration(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    cache = ResourcePreviewCache(tmp_path)
    assert cache.read(DIGEST) is None
    cache.publish(DIGEST, b"rendered preview")
    path = tmp_path / "cache" / "resource-previews" / "ab" / f"{DIGEST}.webp"
    os.utime(path, (NOW - PREVIEW_CACHE_TTL_SECONDS + 1,) * 2)
    assert cache.read(DIGEST) == b"rendered preview"
    assert path.stat().st_mtime == NOW - PREVIEW_CACHE_TTL_SECONDS + 1
    monkeypatch.setattr(cache_module, "time", lambda: NOW + 1)
    assert cache.read(DIGEST) is None
    # Re-rendering replaces the expired artifact atomically at the same identity.
    cache.publish(DIGEST, b"new preview")
    assert path.read_bytes() == b"new preview"
    assert len(list(path.parent.iterdir())) == 1


def test_prune_deletes_unvisited_expired_previews_and_abandoned_temp_files(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    expired = cache_file(tmp_path, age=PREVIEW_CACHE_TTL_SECONDS)
    fresh = cache_file(
        tmp_path, digest="cd" + "2" * 62, age=PREVIEW_CACHE_TTL_SECONDS - 1
    )
    temporary = expired.with_name(f".{expired.name}.abandoned.tmp")
    temporary.write_bytes(b"partial preview")
    os.utime(temporary, (NOW - PREVIEW_CACHE_TTL_SECONDS,) * 2)
    source = tmp_path / "original.webp"
    source.write_bytes(b"user media")
    unrelated = expired.parent / "cover.webp"
    unrelated.write_bytes(b"not a preview cache key")
    os.utime(unrelated, (NOW - PREVIEW_CACHE_TTL_SECONDS * 2,) * 2)

    assert ResourcePreviewCache(tmp_path).prune() == 2
    assert not expired.exists()
    assert not temporary.exists()
    assert fresh.read_bytes() == b"preview"
    assert source.read_bytes() == b"user media"
    assert unrelated.read_bytes() == b"not a preview cache key"


def test_resource_preview_reuses_fresh_and_regenerates_expired_cache(
    tmp_path, monkeypatch, test_settings
):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    original = tmp_path / "original.pdf"
    original.write_bytes(b"original media")
    preview = FilesystemResourcePreview(
        Mock(), test_settings, ResourcePreviewRenderCoordinator()
    )
    monkeypatch.setattr(
        preview, "_source", lambda *args: PageImageSource("PDF", original, None)
    )
    render = Mock(side_effect=[b"first preview", b"regenerated preview"])
    monkeypatch.setattr(preview._renderer, "render", render)
    scope = ResourcePreviewAccessScope(is_admin=True, library_ids=())
    assert (
        preview.load(scope=scope, resource_id="resource", page_index=0).content
        == b"first preview"
    )
    cached = next(
        (test_settings.resolved_storage_root / "cache/resource-previews").glob(
            "*/*.webp"
        )
    )
    os.utime(cached, (NOW - PREVIEW_CACHE_TTL_SECONDS + 1,) * 2)
    assert (
        preview.load(scope=scope, resource_id="resource", page_index=0).content
        == b"first preview"
    )
    os.utime(cached, (NOW - PREVIEW_CACHE_TTL_SECONDS,) * 2)
    assert (
        preview.load(scope=scope, resource_id="resource", page_index=0).content
        == b"regenerated preview"
    )
    assert render.call_count == 2
    assert original.read_bytes() == b"original media"


@pytest.mark.parametrize("link_at", ["cache", "resource-previews", "shard", "file"])
def test_cache_never_follows_links_to_source_files(tmp_path, monkeypatch, link_at):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    storage = tmp_path / "storage"
    outside = tmp_path / "originals"
    source = cache_file(outside, age=PREVIEW_CACHE_TTL_SECONDS * 2)
    target = {
        "cache": outside / "cache",
        "resource-previews": outside / "cache" / "resource-previews",
        "shard": source.parent,
        "file": source,
    }[link_at]
    link = {
        "cache": storage / "cache",
        "resource-previews": storage / "cache" / "resource-previews",
        "shard": storage / "cache" / "resource-previews" / "ab",
        "file": storage / "cache" / "resource-previews" / "ab" / source.name,
    }[link_at]
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=link_at != "file")

    cache = ResourcePreviewCache(storage)
    assert cache.read(DIGEST) is None
    assert cache.prune() == 0
    cache.publish(DIGEST, b"generated preview")
    assert source.read_bytes() == b"preview"
    assert source.stat().st_mtime == NOW - PREVIEW_CACHE_TTL_SECONDS * 2


def test_prune_failure_records_cause_and_continues_other_entries(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    blocked = cache_file(tmp_path, age=PREVIEW_CACHE_TTL_SECONDS)
    removable = cache_file(
        tmp_path, digest="ab" + "2" * 62, age=PREVIEW_CACHE_TTL_SECONDS
    )
    unlink = Path.unlink

    def fail_one(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one)
    assert ResourcePreviewCache(tmp_path).prune() == 1
    assert blocked.exists()
    assert not removable.exists()
    assert "PermissionError" in caplog.text
    assert "Traceback (most recent call last):" in caplog.text
    assert f"[Errno {errno.EACCES}]" in caplog.text
    assert str(blocked) in caplog.text


def test_prune_accepts_empty_cache_and_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    cache = ResourcePreviewCache(tmp_path)
    assert cache.prune() == 0
    path = cache_file(tmp_path, age=PREVIEW_CACHE_TTL_SECONDS)
    assert cache.prune(cancelled=lambda: True) == 0
    assert path.exists()


def test_maintenance_failure_does_not_block_other_maintenance(
    monkeypatch, db_session, test_settings, caplog
):
    monotonic_now = [NOW]
    monkeypatch.setattr(log_maintenance, "monotonic", lambda: monotonic_now[0])
    worker = log_maintenance.SystemEventMaintenanceWorker(
        sessionmaker(bind=db_session.get_bind()), settings=test_settings
    )
    prune = Mock(side_effect=RuntimeError("cache maintenance bug"))
    monkeypatch.setattr(worker._preview_cache, "prune", prune)
    events = Mock(return_value={"deleted": 0})
    sessions = Mock(return_value=0)
    monkeypatch.setattr(log_maintenance, "maintain_system_events", events)
    monkeypatch.setattr(
        log_maintenance, "delete_expired_or_disabled_sessions", sessions
    )

    result = worker.run_once()
    events.assert_called_once()
    sessions.assert_called_once()
    assert result["expiredResourcePreviewsDeleted"] == 0
    assert "RuntimeError" in caplog.text
    assert "prune_resource_previews" in caplog.text

    monotonic_now[0] += 15 * 60
    assert worker.run_once()["expiredResourcePreviewsDeleted"] == 0
    assert prune.call_count == 1
    assert events.call_count == sessions.call_count == 2
    monotonic_now[0] = NOW + 24 * 60 * 60
    assert worker.run_once()["expiredResourcePreviewsDeleted"] == 0
    assert prune.call_count == 2
    assert events.call_count == sessions.call_count == 3


def test_existing_maintenance_lifecycle_prunes_daily_and_keeps_log_interval(
    tmp_path, monkeypatch, test_settings
):
    monkeypatch.setattr(cache_module, "time", lambda: NOW)
    monotonic_now = [NOW]
    monkeypatch.setattr(log_maintenance, "monotonic", lambda: monotonic_now[0])
    expired = cache_file(
        test_settings.resolved_storage_root, age=PREVIEW_CACHE_TTL_SECONDS
    )
    worker = log_maintenance.SystemEventMaintenanceWorker(
        Mock(), settings=test_settings
    )
    monkeypatch.setattr(worker, "_recover_startup_maintenance", lambda: None)
    events = Mock(return_value={"deleted": 0})
    sessions = Mock(return_value=0)
    monkeypatch.setattr(log_maintenance, "maintain_system_events", events)
    monkeypatch.setattr(
        log_maintenance, "delete_expired_or_disabled_sessions", sessions
    )
    worker._db_factory = Mock(
        return_value=Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
    )
    prune = Mock(wraps=worker._preview_cache.prune)
    monkeypatch.setattr(worker._preview_cache, "prune", prune)
    waits = []

    def advance_maintenance_clock(timeout):
        waits.append(timeout)
        assert timeout == 15 * 60
        if len(waits) == 1:
            assert not expired.exists()
            cache_file(
                test_settings.resolved_storage_root, age=PREVIEW_CACHE_TTL_SECONDS
            )
        elif len(waits) <= 96:
            assert expired.exists()
        else:
            assert not expired.exists()
            return True
        monotonic_now[0] += timeout
        return False

    monkeypatch.setattr(worker._stop, "wait", advance_maintenance_clock)
    worker._run()
    assert prune.call_count == 2  # Startup and 24 hours later.
    assert events.call_count == sessions.call_count == 96
    assert len(waits) == 97
