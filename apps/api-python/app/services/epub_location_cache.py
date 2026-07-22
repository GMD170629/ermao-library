from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Literal, TypedDict

from app.core.config import Settings


EPUB_LOCATION_CACHE_VERSION = 2
EPUB_LOCATION_BREAK = 1200
EPUB_LOCATION_LEASE_SECONDS = 300
EPUB_LOCATION_MAX_BYTES = 64 * 1024 * 1024


class EpubLocationCacheResult(TypedDict, total=False):
    status: Literal["ready", "missing", "generating", "claimed"]
    serialized: str
    leaseToken: str
    leaseExpiresAt: int
    retryAfterMs: int


def _cache_key(content_fingerprint: str, break_size: int, cache_version: int) -> str:
    raw = f"v{cache_version}:{content_fingerprint}:{break_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_root(settings: Settings) -> Path:
    return settings.resolved_storage_root / "reader-indexes" / "epub-locations"


def _paths(settings: Settings, content_fingerprint: str, break_size: int, cache_version: int) -> tuple[Path, Path]:
    key = _cache_key(content_fingerprint, break_size, cache_version)
    root = _cache_root(settings) / f"v{cache_version}"
    return root / f"{key}.json", root / f"{key}.lease"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _valid_serialized_locations(serialized: str) -> bool:
    encoded = serialized.encode("utf-8")
    if not encoded or len(encoded) > EPUB_LOCATION_MAX_BYTES:
        return False
    try:
        locations = json.loads(serialized)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(locations, list)
        and bool(locations)
        and all(isinstance(item, str) and item.startswith("epubcfi(") for item in locations)
    )


def _ready_result(cache_path: Path, content_fingerprint: str, break_size: int, cache_version: int) -> EpubLocationCacheResult | None:
    record = _read_json(cache_path)
    if not record:
        return None
    serialized = record.get("serialized")
    if (
        record.get("contentFingerprint") != content_fingerprint
        or record.get("breakSize") != break_size
        or record.get("cacheVersion") != cache_version
        or not isinstance(serialized, str)
        or not _valid_serialized_locations(serialized)
    ):
        return None
    return {"status": "ready", "serialized": serialized}


def claim_epub_locations(
    settings: Settings,
    content_fingerprint: str,
    break_size: int,
    cache_version: int,
) -> EpubLocationCacheResult:
    cache_path, lease_path = _paths(settings, content_fingerprint, break_size, cache_version)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ready = _ready_result(cache_path, content_fingerprint, break_size, cache_version)
    if ready:
        return ready

    now = int(time.time())
    lease = _read_json(lease_path)
    expires_at = int((lease or {}).get("leaseExpiresAt") or 0)
    if expires_at > now:
        return {"status": "generating", "leaseExpiresAt": expires_at, "retryAfterMs": 1000}
    if lease_path.exists():
        try:
            lease_path.unlink()
        except FileNotFoundError:
            pass

    lease_token = uuid.uuid4().hex
    expires_at = now + EPUB_LOCATION_LEASE_SECONDS
    payload = json.dumps(
        {"leaseToken": lease_token, "leaseExpiresAt": expires_at},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        descriptor = os.open(lease_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        lease = _read_json(lease_path) or {}
        return {
            "status": "generating",
            "leaseExpiresAt": int(lease.get("leaseExpiresAt") or expires_at),
            "retryAfterMs": 1000,
        }
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    return {"status": "claimed", "leaseToken": lease_token, "leaseExpiresAt": expires_at}


def save_epub_locations(
    settings: Settings,
    content_fingerprint: str,
    break_size: int,
    cache_version: int,
    lease_token: str,
    serialized: str,
) -> EpubLocationCacheResult:
    if not _valid_serialized_locations(serialized):
        raise ValueError("INVALID_EPUB_LOCATIONS")
    cache_path, lease_path = _paths(settings, content_fingerprint, break_size, cache_version)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ready = _ready_result(cache_path, content_fingerprint, break_size, cache_version)
    if ready:
        return ready
    lease = _read_json(lease_path)
    if not lease or lease.get("leaseToken") != lease_token:
        raise PermissionError("EPUB_LOCATION_LEASE_MISMATCH")

    record = json.dumps(
        {
            "contentFingerprint": content_fingerprint,
            "breakSize": break_size,
            "cacheVersion": cache_version,
            "serialized": serialized,
            "savedAt": int(time.time()),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{cache_path.stem}.", suffix=".tmp", dir=cache_path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(record)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, cache_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    try:
        lease_path.unlink()
    except FileNotFoundError:
        pass
    return {"status": "ready", "serialized": serialized}
