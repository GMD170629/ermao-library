"""Idempotent removal of legacy bundled default-cover copies under storage.

Older versions persisted ``default-book-cover-v1.png`` into metadata, which let
OPF writeback copy that asset into durable storage per Book. The metadata rows
are reset by migration ``0017_reset_default_cover_paths``; this task removes the
files those rows already produced. It runs once, guarded by a system setting so
storage is not rescanned on every startup.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.bootstrap.system import get_setting, upsert_setting
from app.core.config import Settings
from app.core.exception_diagnostics import record_exception
from app.modules.system.application.commands import SystemWriteTransaction

LOGGER = logging.getLogger(__name__)

_CLEANUP_MARKER_KEY = "defaultCoverResidueCleanup"
_CLEANUP_MARKER_VALUE = "1"
_COVERS_DIRECTORY = "covers"
_LEGACY_DEFAULT_COVER_SHA256 = frozenset(
    {"6f8de37700323fb6e81e4c3323c39e32c35f6d8b1ab54fed91622c0382a43649"}
)


def cleanup_default_cover_residue(db: Session, settings: Settings) -> int:
    """Delete storage copies of the bundled fallback cover exactly once."""

    if get_setting(db, _CLEANUP_MARKER_KEY) == _CLEANUP_MARKER_VALUE:
        return 0
    removed = _remove_legacy_default_covers(settings.resolved_storage_root)
    with SystemWriteTransaction(db):
        upsert_setting(db, _CLEANUP_MARKER_KEY, _CLEANUP_MARKER_VALUE)
    LOGGER.info("default_cover_cleanup removed=%d", removed)
    return removed


def _remove_legacy_default_covers(storage_root: Path) -> int:
    covers_root = storage_root / _COVERS_DIRECTORY
    if not covers_root.is_dir():
        return 0
    removed = 0
    for path in covers_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if _is_default_cover_copy(path):
                path.unlink()
                removed += 1
        except OSError as error:
            record_exception(LOGGER, "default_cover_cleanup.failed", error, context={"step": "remove_cover_residue"})
    return removed


def _is_default_cover_copy(path: Path) -> bool:
    if path.name.startswith("default-book-cover-"):
        return True
    return _sha256(path) in _LEGACY_DEFAULT_COVER_SHA256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["cleanup_default_cover_residue"]
