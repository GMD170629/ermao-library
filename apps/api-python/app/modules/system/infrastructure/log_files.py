"""Daily JSONL storage. No database connection is needed to write diagnostics."""

from __future__ import annotations

import heapq
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import SpooledTemporaryFile
from time import monotonic, sleep
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.config import get_settings
from app.core.exception_diagnostics import emergency_diagnostic
from app.core.time import to_timestamp_ms
from app.db.file_lock import try_file_lock, unlock_file
from app.infrastructure.atomic_files import write_atomic_bytes
from app.modules.system.domain.events import (
    DEFAULT_RETENTION_DAYS,
    LOG_LEVELS,
    validate_log_retention_days,
)

_root: Path | None = None
_writing: ContextVar[bool] = ContextVar("writing_log_file", default=False)


def configure_log_directory(storage_root: Path) -> None:
    global _root
    _root = storage_root / "logs"


def log_directory() -> Path:
    return _root or get_settings().resolved_storage_root / "logs"


def log_settings() -> dict[str, Any]:
    path = log_directory() / "settings.json"
    if not path.is_file():
        return {"retentionDays": DEFAULT_RETENTION_DAYS, "minimumLevel": "error"}
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_log_retention_days(value["retentionDays"])
    if value["minimumLevel"] not in LOG_LEVELS:
        raise ValueError("invalid-log-level")
    return value


def save_log_settings(retention_days: int, minimum_level: str) -> int:
    validate_log_retention_days(retention_days)
    if minimum_level not in LOG_LEVELS:
        raise ValueError("invalid-log-level")
    write_atomic_bytes(log_directory() / "settings.json", json.dumps({
        "retentionDays": retention_days, "minimumLevel": minimum_level,
    }).encode("utf-8"))
    return prune_log_files()


@contextmanager
def log_file_lock() -> Iterator[None]:
    root = log_directory()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".api.lock").open("a+b") as handle:
        deadline = monotonic() + 2
        while not try_file_lock(handle, exclusive=True):
            if monotonic() >= deadline:
                raise TimeoutError("Daily log file lock timed out")
            sleep(0.005)
        try:
            yield
        finally:
            unlock_file(handle)


def _daily_files() -> list[Path]:
    root = log_directory()
    return sorted(
        (path for runtime in ("api", "web") for path in (root / runtime).glob("????-??-??.jsonl")
         if path.is_file() and not path.is_symlink()),
        key=lambda path: (path.name, str(path.parent)), reverse=True,
    )


def retained_log_files(*, today: date | None = None) -> list[Path]:
    cutoff = (today or datetime.now().astimezone().date()) - timedelta(days=log_settings()["retentionDays"] - 1)
    return [path for path in _daily_files() if path.stem >= cutoff.isoformat()]


def prune_log_files(*, today: date | None = None) -> int:
    cutoff = (today or datetime.now().astimezone().date()) - timedelta(days=log_settings()["retentionDays"] - 1)
    deleted = 0
    with log_file_lock():
        for path in _daily_files():
            if path.stem < cutoff.isoformat():
                path.unlink(missing_ok=True)
                deleted += 1
    return deleted


def append_log_event(event: dict[str, Any]) -> bool:
    """Isolate all outlet failures, preserving the operation's result."""
    if _writing.get():
        return False
    token = _writing.set(True)
    try:
        settings = log_settings()
        if LOG_LEVELS.index(event["level"]) < LOG_LEVELS.index(settings["minimumLevel"]):
            return False
        now = datetime.now().astimezone()
        path = log_directory() / "api" / f"{now.date().isoformat()}.jsonl"
        if not path.exists():
            prune_log_files(today=now.date())
        # One serialized physical line retains all embedded newlines and Unicode.
        data = (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        with log_file_lock():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as stream:
                stream.write(data)
        return True
    except Exception as error:  # noqa: BLE001 - never recurse into the failed outlet
        emergency_diagnostic("system.log_file_write_failed", error)
        # Preserve the original complete record even when its file cannot be written.
        emergency_diagnostic("system.log_file_original", RuntimeError(json.dumps(event, ensure_ascii=False, default=str)))
        return False
    finally:
        _writing.reset(token)


def _reverse_lines(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        remainder = b""
        while position:
            size = min(position, 64 * 1024)
            position -= size
            stream.seek(position)
            chunks = (stream.read(size) + remainder).split(b"\n")
            remainder = chunks[0]
            yield from (line for line in reversed(chunks[1:]) if line)
        if remainder:
            yield remainder


def read_log_events() -> Iterator[dict[str, Any]]:
    def read_file(path: Path) -> Iterator[dict[str, Any]]:
        try:
            for line in _reverse_lines(path):
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise TypeError("Daily log record must be a JSON object")
                    yield event
                except (TypeError, ValueError, UnicodeError) as error:
                    emergency_diagnostic("system.log_line_read_failed", error)
        except FileNotFoundError as error:  # Rotation/clear may remove a listed file.
            emergency_diagnostic("system.log_file_removed_during_read", error)
    yield from heapq.merge(
        *(read_file(path) for path in retained_log_files()),
        key=lambda event: to_timestamp_ms(event.get("createdAt")) or 0, reverse=True,
    )


def log_size_bytes() -> int:
    return sum(path.stat().st_size for path in retained_log_files())


def export_log_files() -> Iterator[bytes]:
    """Archive retained files verbatim, spilling large archives to temporary disk."""
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as stream:
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive, log_file_lock():
            for path in retained_log_files():
                archive.write(path, arcname=f"{path.parent.name}/{path.name}")
        stream.seek(0)
        while chunk := stream.read(64 * 1024):
            yield chunk


def clear_log_files() -> int:
    with log_file_lock():
        count = sum(1 for _ in read_log_events())
        for path in _daily_files():
            path.unlink(missing_ok=True)
        return count
