from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.modules.imports.infrastructure.local_cover_publication import (
    FilesystemLocalCoverPublication,
)


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 3), color=(10, 20, 30)).save(output, format="PNG")
    return output.getvalue()


def test_local_cover_is_validated_and_atomically_published(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)

    prepared = publication.prepare(resource_id="resource-1", content=_png())
    publication.publish(prepared)

    assert prepared.stored_path.startswith("covers/resources/resource-1-")
    assert prepared.stored_path.endswith(".png")
    assert prepared.final_path.is_file()
    assert not prepared.temporary_path.exists()


def test_discard_removes_prepared_cover(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    prepared = publication.prepare(resource_id="resource-1", content=_png())

    publication.discard(prepared)

    assert not prepared.temporary_path.exists()
    assert not prepared.final_path.exists()


def test_same_book_and_bytes_reuse_published_cover(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    previous = publication.prepare(resource_id="resource-1", content=_png())
    publication.publish(previous)
    replacement = publication.prepare(resource_id="resource-1", content=_png())
    publication.publish(replacement)
    publication.discard(replacement)
    assert replacement.reused
    assert replacement.stored_path == previous.stored_path
    assert previous.final_path.read_bytes() == _png()
    assert len(list((tmp_path / "covers" / "resources").iterdir())) == 1


def test_different_books_keep_separate_covers(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    first = publication.prepare(resource_id="book-1", content=_png())
    second = publication.prepare(resource_id="book-2", content=_png())
    publication.publish(first)
    publication.publish(second)
    assert first.stored_path != second.stored_path


def test_discard_after_publication_does_not_remove_shared_content(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    prepared = publication.prepare(resource_id="book-1", content=_png())
    publication.publish(prepared)
    publication.discard(prepared)
    assert prepared.final_path.read_bytes() == _png()


def test_same_size_corrupt_cover_is_not_reused(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    prepared = publication.prepare(resource_id="book-1", content=_png())
    publication.publish(prepared)
    prepared.final_path.write_bytes(b"x" * len(_png()))

    with pytest.raises(ValueError, match="unexpected content"):
        publication.prepare(resource_id="book-1", content=_png())
