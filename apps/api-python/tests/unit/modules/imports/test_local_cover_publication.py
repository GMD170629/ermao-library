from __future__ import annotations

from io import BytesIO
from pathlib import Path

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

    assert prepared.stored_path.startswith("covers/resources/resource-1.")
    assert prepared.stored_path.endswith(".png")
    assert prepared.final_path.is_file()
    assert not prepared.temporary_path.exists()


def test_discard_removes_prepared_cover(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    prepared = publication.prepare(resource_id="resource-1", content=_png())

    publication.discard(prepared)

    assert not prepared.temporary_path.exists()
    assert not prepared.final_path.exists()


def test_discard_new_published_version_preserves_previous_cover(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    previous = publication.prepare(resource_id="resource-1", content=_png())
    publication.publish(previous)
    replacement = publication.prepare(resource_id="resource-1", content=_png())
    publication.publish(replacement)
    publication.discard(replacement)
    assert previous.final_path.read_bytes() == _png()
    assert not replacement.final_path.exists()
