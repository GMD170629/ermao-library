"""Filesystem and HTTP adapter for atomic Library cover publication."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.modules.library.application.cover_publication import (
    PreparedCoverPublication,
)

_MAX_COVER_BYTES = 8 * 1024 * 1024
_IMAGE_SUFFIXES = {
    "GIF": ".gif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


class RemoteCoverPublication:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    def prepare(self, *, work_id: str, cover_url: str) -> PreparedCoverPublication:
        if not cover_url.startswith(("http://", "https://")):
            raise ValueError("Remote cover URL must use HTTP or HTTPS")
        if not work_id or Path(work_id).name != work_id:
            raise ValueError("Invalid work identifier")
        request = UrlRequest(
            cover_url,
            headers={
                "Accept": "image/*,*/*",
                "User-Agent": "Shuku Starship Python",
                "Referer": "https://book.douban.com/",
            },
        )
        target_dir = self._storage_root / "covers"
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = target_dir / f".{work_id}.{uuid4().hex}.part"
        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read(_MAX_COVER_BYTES + 1)
            if not payload or len(payload) > _MAX_COVER_BYTES:
                raise ValueError("Remote cover exceeds the supported size")
            temporary_path.write_bytes(payload)
            with Image.open(temporary_path) as image:
                image_format = str(image.format or "").upper()
                image.verify()
            suffix = _IMAGE_SUFFIXES.get(image_format)
            if suffix is None:
                raise ValueError("Remote cover is not a supported image")
        except (
            OSError,
            UnidentifiedImageError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            temporary_path.unlink(missing_ok=True)
            raise ValueError("Remote cover could not be validated") from exc
        final_path = target_dir / f"{work_id}{suffix}"
        return PreparedCoverPublication(
            work_id=work_id,
            temporary_path=temporary_path,
            final_path=final_path,
            stored_path=str(final_path.relative_to(self._storage_root)),
        )

    def publish(self, prepared: PreparedCoverPublication) -> None:
        os.replace(prepared.temporary_path, prepared.final_path)

    def discard(self, prepared: PreparedCoverPublication) -> None:
        prepared.temporary_path.unlink(missing_ok=True)


__all__ = ["RemoteCoverPublication"]
