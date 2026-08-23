from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.publications.domain.model import PublicationCorruptError
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)


def test_publication_source_rejects_symlink_escape(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside = tmp_path / "outside.epub"
    outside.write_bytes(b"secret")
    link = library_root / "book.epub"
    link.symlink_to(outside)

    with pytest.raises(PublicationCorruptError, match="escapes its library"):
        resolve_publication_source("book.epub", library_root)


def test_publication_source_rejects_absolute_path_outside_root(
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside = tmp_path / "outside.epub"
    outside.write_bytes(b"secret")

    with pytest.raises(PublicationCorruptError, match="escapes its library"):
        resolve_publication_source(str(outside), library_root)


def test_library_root_does_not_fallback_to_storage_root_when_missing(
    tmp_path: Path,
) -> None:
    missing_library = tmp_path / "missing-library"
    storage_root = tmp_path / "storage"

    assert select_publication_source_root(str(missing_library), storage_root) == (
        missing_library
    )
