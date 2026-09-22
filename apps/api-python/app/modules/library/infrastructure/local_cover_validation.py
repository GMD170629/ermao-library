"""Validate local artwork against the source-node publication format and limit."""

import logging
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.core.exception_diagnostics import record_exception


def valid_local_cover(content: bytes | None) -> bytes | None:
    if not content or len(content) > 10 * 1024 * 1024:
        return None
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                return None
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        record_exception(logging.getLogger(__name__), "modules.library.infrastructure.local_cover_validation.valid_local_cover.failed", error,
                         context={"step": "valid_local_cover"})
        return None
    return content
