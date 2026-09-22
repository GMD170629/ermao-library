"""Read-only identity for an object's own cover, using the delivery path boundary."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import quote

from app.core.config import Settings
from app.core.exception_diagnostics import record_exception
from app.modules.media.infrastructure.http_streaming import stored_path
from app.services.default_cover import is_default_cover_path


def versioned_cover_url(
    endpoint: str,
    cover_path: str | None,
    settings: Settings,
    *,
    size: str | None = None,
) -> str:
    if not cover_path or is_default_cover_path(cover_path):
        return ""
    path = stored_path(cover_path, settings)
    if path is None:
        return ""
    try:
        if not path.is_file():
            return ""
        info = path.stat()
    except OSError as error:
        record_exception(logging.getLogger(__name__), "modules.media.infrastructure.cover_identity.versioned_cover_url.failed", error,
                         context={"step": "versioned_cover_url"})
        return ""
    if info.st_size <= 0:
        return ""
    identity = f"{cover_path}|{info.st_size}|{info.st_mtime_ns}|{info.st_ctime_ns}"
    revision = hashlib.sha256(identity.encode()).hexdigest()[:32]
    query = f"v={revision}"
    if size is not None:
        query += f"&size={quote(size, safe='')}"
    return f"{endpoint}?{query}"
