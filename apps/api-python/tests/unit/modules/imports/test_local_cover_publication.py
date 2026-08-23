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

    assert prepared.stored_path == "covers/resources/resource-1.png"
    assert prepared.final_path.is_file()
    assert not prepared.temporary_path.exists()


def test_discard_removes_prepared_cover(tmp_path: Path) -> None:
    publication = FilesystemLocalCoverPublication(tmp_path)
    prepared = publication.prepare(resource_id="resource-1", content=_png())

    publication.discard(prepared)

    assert not prepared.temporary_path.exists()
    assert not prepared.final_path.exists()
