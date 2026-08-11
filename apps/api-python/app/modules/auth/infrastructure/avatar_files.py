"""Validated, recoverable filesystem publication for account avatars."""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from secrets import token_hex

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = 512
ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}


@dataclass(frozen=True)
class PreparedAvatarPublication:
    """A same-directory staged avatar whose final path is not referenced yet."""

    temporary_path: Path
    published_path: Path

    def publish(self) -> None:
        """Atomically publish the validated file under its unique final name."""

        os.replace(self.temporary_path, self.published_path)

    def discard(self) -> None:
        """Remove staged or published files that are not referenced by the database."""

        self.temporary_path.unlink(missing_ok=True)
        self.published_path.unlink(missing_ok=True)


def _normalized_avatar(data: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in ALLOWED_AVATAR_FORMATS:
                raise ValueError("不支持的头像格式")
            if probe.width * probe.height > MAX_AVATAR_PIXELS:
                raise ValueError("头像像素尺寸过大")
            probe.verify()
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise ValueError("头像像素尺寸过大")
            normalized = ImageOps.exif_transpose(source).convert("RGB")
            return ImageOps.fit(
                normalized,
                (AVATAR_SIZE, AVATAR_SIZE),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("头像文件不是有效的图片") from exc


def prepare_avatar_publication(
    data: bytes,
    *,
    target_directory: Path,
) -> PreparedAvatarPublication:
    """Normalize, write, and verify an avatar before any database write begins."""

    target_directory.mkdir(parents=True, exist_ok=True)
    version = token_hex(12)
    published_path = target_directory / f"avatar-{version}.webp"
    temporary_path = target_directory / f".avatar-{version}.webp.part"
    publication = PreparedAvatarPublication(
        temporary_path=temporary_path,
        published_path=published_path,
    )
    processed = _normalized_avatar(data)
    try:
        processed.save(temporary_path, format="WEBP", quality=88, method=6)
        with Image.open(temporary_path) as verification:
            verification.verify()
        with Image.open(temporary_path) as verification:
            if verification.format != "WEBP" or verification.size != (
                AVATAR_SIZE,
                AVATAR_SIZE,
            ):
                raise ValueError("头像文件写入校验失败")
    except Exception:
        publication.discard()
        raise
    finally:
        processed.close()
    return publication


__all__ = [
    "AVATAR_SIZE",
    "PreparedAvatarPublication",
    "prepare_avatar_publication",
]
