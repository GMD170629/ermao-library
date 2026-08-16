from pathlib import Path

import pytest

from app.modules.publications.infrastructure.legacy_derivative_cleanup import (
    remove_retired_reader_derivatives,
)


def test_removes_only_retired_reader_derivatives(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    retired = storage / "cache" / "publication-render"
    conversion = storage / "conversions" / "source" / "book.epub"
    (retired / "ab").mkdir(parents=True)
    (retired / "ab" / "artifact.epub").write_bytes(b"retired")
    conversion.parent.mkdir(parents=True)
    conversion.write_bytes(b"preserve")

    assert remove_retired_reader_derivatives(storage) is True
    assert not retired.exists()
    assert conversion.read_bytes() == b"preserve"
    assert remove_retired_reader_derivatives(storage) is False


def test_unlinks_target_symlink_without_following_it(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "keep.txt"
    protected.write_text("keep", encoding="utf-8")
    target = storage / "cache" / "publication-render"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)

    assert remove_retired_reader_derivatives(storage) is True
    assert protected.read_text(encoding="utf-8") == "keep"
    assert not target.exists()


def test_rejects_parent_symlink_escape(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (storage / "cache").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="escapes storage root"):
        remove_retired_reader_derivatives(storage)
