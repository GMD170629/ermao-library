"""Validate local artwork against the source-node publication format and limit."""

from io import BytesIO

from PIL import Image, UnidentifiedImageError


def valid_local_cover(content: bytes | None) -> bytes | None:
    if not content or len(content) > 10 * 1024 * 1024:
        return None
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                return None
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    return content
