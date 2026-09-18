from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services import default_cover_cleanup


def _write(path: Path, content: bytes = b"cover") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_cleanup_removes_named_and_duplicate_default_covers_once(
    db_session: Session,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    covers = test_settings.resolved_storage_root / "covers"
    legacy = _write(covers / "default-book-cover-v1.png")
    nested_default = _write(covers / "resources" / "default-book-cover-v9.webp")
    real = _write(covers / "resources" / "real.jpg")
    duplicate_bytes = b"identical-to-legacy-asset"
    duplicate = _write(covers / "source-nodes" / "copy.jpg", duplicate_bytes)
    monkeypatch.setattr(
        default_cover_cleanup,
        "_LEGACY_DEFAULT_COVER_SHA256",
        frozenset({hashlib.sha256(duplicate_bytes).hexdigest()}),
    )

    removed = default_cover_cleanup.cleanup_default_cover_residue(
        db_session, test_settings
    )

    assert removed == 3
    assert not legacy.exists()
    assert not nested_default.exists()
    assert not duplicate.exists()
    assert real.exists()

    later = _write(covers / "default-book-cover-v1.png")
    assert (
        default_cover_cleanup.cleanup_default_cover_residue(db_session, test_settings)
        == 0
    )
    assert later.exists()


def test_cleanup_without_storage_marks_done(
    db_session: Session, test_settings: Settings
) -> None:
    assert (
        default_cover_cleanup.cleanup_default_cover_residue(db_session, test_settings)
        == 0
    )
