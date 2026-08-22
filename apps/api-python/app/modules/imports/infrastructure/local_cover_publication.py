"""Validated atomic publication for covers discovered during local import."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.modules.imports.application.readable_resource.ports import PreparedLocalCover

_MAX_COVER_BYTES = 20 * 1024 * 1024
_SUFFIXES = {"GIF": ".gif", "JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class FilesystemLocalCoverPublication:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()

    def prepare(self, *, book_id: str, content: bytes) -> PreparedLocalCover:
        if not book_id or Path(book_id).name != book_id:
            raise ValueError("invalid book identifier")
        if not 0 < len(content) <= _MAX_COVER_BYTES:
            raise ValueError("local cover exceeds the supported size")
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                image.verify()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise ValueError("local cover could not be validated") from error
        suffix = _SUFFIXES.get(image_format)
        if suffix is None:
            raise ValueError("local cover is not a supported image")
        target_dir = self._storage_root / "covers"
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = target_dir / f".{book_id}.{uuid4().hex}.part"
        temporary_path.write_bytes(content)
        final_path = target_dir / f"{book_id}{suffix}"
        return PreparedLocalCover(
            temporary_path=temporary_path,
            final_path=final_path,
            stored_path=str(final_path.relative_to(self._storage_root)),
        )

    def publish(self, prepared: PreparedLocalCover) -> None:
        os.replace(prepared.temporary_path, prepared.final_path)

    def discard(self, prepared: PreparedLocalCover) -> None:
        prepared.temporary_path.unlink(missing_ok=True)


__all__ = ["FilesystemLocalCoverPublication"]
