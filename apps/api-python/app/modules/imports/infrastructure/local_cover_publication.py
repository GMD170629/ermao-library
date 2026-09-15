"""Validated atomic publication for covers discovered during local import."""

from __future__ import annotations

import hashlib
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

    def exists(self, stored_path: str) -> bool:
        target = (self._storage_root / stored_path).resolve()
        return target.is_relative_to(self._storage_root) and target.is_file()

    def prepare(self, *, resource_id: str, content: bytes) -> PreparedLocalCover:
        if not resource_id or Path(resource_id).name != resource_id:
            raise ValueError("invalid resource identifier")
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
        target_dir = self._storage_root / "covers" / "resources"
        target_dir.mkdir(parents=True, exist_ok=True)
        publication_id = uuid4().hex
        temporary_path = target_dir / f".{resource_id}.{publication_id}.part"
        temporary_path.write_bytes(content)
        final_path = target_dir / f"{resource_id}.{publication_id}{suffix}"
        return PreparedLocalCover(
            temporary_path=temporary_path,
            final_path=final_path,
            stored_path=final_path.relative_to(self._storage_root).as_posix(),
        )

    def retain_audio_candidate(self, *, resource_id: str, content: bytes) -> str:
        # This is a durable parser candidate, not the user-visible cover. Identical
        # album artwork shares one file; batches retain paths rather than bytes.
        if not resource_id or Path(resource_id).name != resource_id:
            raise ValueError("invalid resource identifier")
        if not 0 < len(content) <= _MAX_COVER_BYTES:
            raise ValueError("local cover exceeds the supported size")
        digest = hashlib.sha256(content).hexdigest()
        target = (
            self._storage_root
            / "covers"
            / "resources"
            / f"{resource_id}-candidate-{digest}"
        )
        if target.is_file():
            return target.relative_to(self._storage_root).as_posix()
        prepared = self.prepare(resource_id=resource_id, content=content)
        os.replace(prepared.temporary_path, target)
        return target.relative_to(self._storage_root).as_posix()

    def read_candidate(self, stored_path: str) -> bytes | None:
        target = (self._storage_root / stored_path).resolve()
        if not target.is_relative_to(self._storage_root):
            return None
        try:
            if target.stat().st_size > _MAX_COVER_BYTES:
                return None
            return target.read_bytes()
        except OSError:
            return None

    def matches(self, stored_path: str | None, content: bytes) -> bool:
        if stored_path is None:
            return False
        target = (self._storage_root / stored_path).resolve()
        if not target.is_relative_to(self._storage_root):
            return False
        try:
            return (
                target.stat().st_size == len(content) and target.read_bytes() == content
            )
        except OSError:
            return False

    def publish(self, prepared: PreparedLocalCover) -> None:
        os.replace(prepared.temporary_path, prepared.final_path)

    def discard(self, prepared: PreparedLocalCover) -> None:
        prepared.temporary_path.unlink(missing_ok=True)
        prepared.final_path.unlink(missing_ok=True)


__all__ = ["FilesystemLocalCoverPublication"]
