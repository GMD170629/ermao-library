from __future__ import annotations

import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from appv2.modules.catalog.contracts import CoverResource, CoverStoragePort

MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_COVER_PIXELS = 40_000_000
VARIANT_BOUNDS = {
    "small": (320, 480),
    "medium": (640, 960),
    "large": (1200, 1800),
    "original": (2000, 3000),
}


class InvalidCoverImage(ValueError):
    pass


class LocalCoverStorage(CoverStoragePort):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def store(self, work_id: uuid.UUID, stream: BinaryIO) -> str:
        payload = stream.read(MAX_COVER_BYTES + 1)
        if len(payload) > MAX_COVER_BYTES:
            raise InvalidCoverImage("cover image exceeds the 20 MiB limit")
        try:
            with Image.open(BytesIO(payload)) as source:
                if source.width * source.height > MAX_COVER_PIXELS:
                    raise InvalidCoverImage("cover image exceeds the pixel limit")
                source.load()
                normalized = ImageOps.exif_transpose(source)
                if normalized.mode not in {"RGB", "RGBA"}:
                    normalized = normalized.convert(
                        "RGBA" if "transparency" in source.info else "RGB"
                    )
                target_dir = self._resolve(str(work_id))
                target_dir.mkdir(parents=True, exist_ok=True)
                for size, bounds in VARIANT_BOUNDS.items():
                    variant = normalized.copy()
                    variant.thumbnail(bounds, Image.Resampling.LANCZOS)
                    destination = target_dir / self._filename(size)
                    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
                    variant.save(temporary, format="WEBP", quality=88, method=6)
                    os.replace(temporary, destination)
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
            raise InvalidCoverImage("cover file is not a supported image") from error
        return f"{work_id}/cover.webp"

    def open(self, key: str, size: str) -> CoverResource:
        source = self._resolve(key)
        selected = source.with_name(self._filename(size))
        stat = selected.stat()
        return CoverResource(
            path=selected,
            media_type="image/webp",
            etag=f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
            last_modified=datetime.fromtimestamp(stat.st_mtime, UTC),
        )

    def delete(self, key: str) -> None:
        source = self._resolve(key)
        for size in VARIANT_BOUNDS:
            source.with_name(self._filename(size)).unlink(missing_ok=True)
        with suppress(OSError):
            source.parent.rmdir()

    def _resolve(self, key: str) -> Path:
        resolved = (self._root / key).resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError("cover key escapes the appv2 cover root")
        return resolved

    @staticmethod
    def _filename(size: str) -> str:
        normalized = size if size in VARIANT_BOUNDS else "medium"
        return "cover.webp" if normalized == "original" else f"cover-{normalized}.webp"
