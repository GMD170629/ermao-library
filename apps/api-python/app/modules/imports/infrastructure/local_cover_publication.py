"""Validated atomic publication for covers discovered during local import."""

from __future__ import annotations

import hashlib
import logging
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.core.exception_diagnostics import record_exception
from app.modules.imports.application.readable_resource.ports import PreparedLocalCover

_MAX_COVER_BYTES = 20 * 1024 * 1024
_SUFFIXES = {"GIF": ".gif", "JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def validated_cover_suffix(content: bytes) -> str:
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
    return suffix


class FilesystemLocalCoverPublication:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()

    def exists(self, stored_path: str) -> bool:
        target = (self._storage_root / stored_path).resolve()
        return target.is_relative_to(self._storage_root) and target.is_file()

    def validates(self, content: bytes) -> bool:
        try:
            validated_cover_suffix(content)
        except ValueError:
            return False
        return True

    def prepare(self, *, resource_id: str, content: bytes) -> PreparedLocalCover:
        if not resource_id or Path(resource_id).name != resource_id:
            raise ValueError("invalid resource identifier")
        suffix = validated_cover_suffix(content)
        target_dir = self._storage_root / "covers" / "resources"
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(content).hexdigest()
        final_path = target_dir / f"{resource_id}-{digest}{suffix}"
        stored_path = final_path.relative_to(self._storage_root).as_posix()
        if final_path.is_symlink():
            raise ValueError("local cover digest path is a symbolic link")
        if final_path.is_file():
            if (
                final_path.stat().st_size != len(content)
                or hashlib.sha256(final_path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("local cover digest path has unexpected content")
            return PreparedLocalCover(final_path, final_path, stored_path, reused=True)
        publication_id = uuid4().hex
        temporary_path = target_dir / f".{resource_id}.{publication_id}.part"
        temporary_path.write_bytes(content)
        return PreparedLocalCover(
            temporary_path=temporary_path,
            final_path=final_path,
            stored_path=stored_path,
        )

    def retain_audio_candidate(self, *, resource_id: str, content: bytes) -> str:
        # This is a durable parser candidate, not the user-visible cover. Identical
        # album artwork shares one file; batches retain paths rather than bytes.
        if not resource_id or Path(resource_id).name != resource_id:
            raise ValueError("invalid resource identifier")
        if not 0 < len(content) <= _MAX_COVER_BYTES:
            raise ValueError("local cover exceeds the supported size")
        prepared = self.prepare(resource_id=resource_id, content=content)
        self.publish(prepared)
        return prepared.stored_path

    def read_candidate(self, stored_path: str) -> bytes | None:
        target = (self._storage_root / stored_path).resolve()
        if not target.is_relative_to(self._storage_root):
            return None
        try:
            if target.stat().st_size > _MAX_COVER_BYTES:
                return None
            return target.read_bytes()
        except OSError as error:
            record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.local_cover_publication.read_candidate.failed", error,
                             context={"step": "read_candidate"})
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
        except OSError as error:
            record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.local_cover_publication.matches.failed", error,
                             context={"step": "matches"})
            return False

    def publish(self, prepared: PreparedLocalCover) -> None:
        if prepared.reused:
            return
        try:
            # A shared content path must never replace a file another task uses.
            os.link(prepared.temporary_path, prepared.final_path)
        except FileExistsError:
            if (
                prepared.final_path.is_symlink()
                or prepared.final_path.stat().st_size
                != prepared.temporary_path.stat().st_size
                or hashlib.sha256(prepared.final_path.read_bytes()).digest()
                != hashlib.sha256(prepared.temporary_path.read_bytes()).digest()
            ):
                raise ValueError("local cover digest path has unexpected content")
        finally:
            prepared.temporary_path.unlink(missing_ok=True)

    def discard(self, prepared: PreparedLocalCover) -> None:
        if not prepared.reused:
            prepared.temporary_path.unlink(missing_ok=True)
        # Published content-addressed files can be shared by committed records.


__all__ = ["FilesystemLocalCoverPublication"]
