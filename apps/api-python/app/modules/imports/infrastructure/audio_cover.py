"""Filesystem and image adapter for audiobook cover publication."""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.modules.imports.application.audio_types import AudioFileMetadata

MAX_AUDIO_COVER_BYTES = 20 * 1024 * 1024
MAX_AUDIO_COVER_PIXELS = 40_000_000
_AUDIO_COVER_FORMATS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def validated_audio_cover(data: bytes) -> tuple[bytes, str] | None:
    if not data or len(data) > MAX_AUDIO_COVER_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            if image_format not in _AUDIO_COVER_FORMATS or width <= 0 or height <= 0:
                return None
            if width * height > MAX_AUDIO_COVER_PIXELS:
                return None
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    return data, _AUDIO_COVER_FORMATS[image_format]


def publish_audio_cover(
    storage_root: Path,
    work_id: str,
    media_version_id: str,
    metadata_items: tuple[AudioFileMetadata, ...],
    *,
    bundle_root: Path | None = None,
) -> str | None:
    selected = next((item for item in metadata_items if item.cover_data), None)
    if selected and selected.cover_data:
        validated = validated_audio_cover(selected.cover_data)
        if validated:
            return _write_cover(
                storage_root, work_id, media_version_id, validated[0], validated[1]
            )

    source_root = bundle_root or metadata_items[0].path.parent
    cover_names = ("folder", "poster", "cover", "default", "front", "封面")
    priorities = {name: index for index, name in enumerate(cover_names)}
    candidates = [
        item
        for item in source_root.iterdir()
        if item.is_file()
        and item.suffix.lower() in {*_IMAGE_EXTENSIONS, ".tbn"}
        and (
            item.stem.casefold() in priorities
            or re.search(r"^(?:cover|folder|front|封面)", item.stem, re.IGNORECASE)
        )
    ]
    for source in sorted(
        candidates,
        key=lambda item: (
            priorities.get(item.stem.casefold(), len(cover_names)),
            item.name.casefold(),
        ),
    ):
        try:
            if source.stat().st_size > MAX_AUDIO_COVER_BYTES:
                continue
            validated = validated_audio_cover(source.read_bytes())
        except OSError:
            continue
        if validated:
            return _write_cover(
                storage_root, work_id, media_version_id, validated[0], validated[1]
            )
    return None


def _write_cover(
    storage_root: Path,
    work_id: str,
    media_version_id: str,
    data: bytes,
    extension: str,
) -> str:
    target = storage_root / "books" / work_id / media_version_id / f"cover{extension}"
    temporary = target.with_suffix(f"{target.suffix}.part")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)
