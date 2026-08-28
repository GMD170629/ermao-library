"""HTTP file streaming, range responses, and comic/cover delivery helpers."""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
import os
import re
import stat as stat_module
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from time import monotonic, time_ns
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings, get_settings
from app.infrastructure.comic_archives import ComicArchiveError, open_comic_archive
from app.schemas.responses import fail

logger = logging.getLogger(__name__)
_active_file_streams_by_user: dict[str, int] = {}
_active_file_streams_lock = threading.Lock()
STREAMS_PER_USER_LIMIT: int | None = None
SLOW_REQUEST_LOG_THRESHOLD_MS = 1500
COMIC_PAGE_DATA_SAVER_VARIANT = "data-saver"
COMIC_PAGE_ORIGINAL_VARIANT = "original"
COMIC_PAGE_DATA_SAVER_MEDIA_TYPE = "image/webp"
COMIC_PAGE_DATA_SAVER_QUALITY = 75
COMIC_PAGE_DATA_SAVER_METHOD = 4
COMIC_PAGE_DATA_SAVER_MAX_EDGE = 2048
COMIC_PAGE_DATA_SAVER_CACHE_VERSION = 4
SMALL_COVER_MAX_BYTES = 50 * 1024
SMALL_COVER_MAX_DIMENSION = 600
SMALL_COVER_MEDIA_TYPE = "image/webp"
SMALL_COVER_CACHE_VERSION = 1
SMALL_COVER_QUALITIES = (82, 74, 66, 58, 50, 42, 34, 26, 18, 10)
PSE_PAGE_CACHE_VERSION = 1
PSE_PAGE_JPEG_QUALITY = 88


def _revalidate_regular_file(path: Path | None) -> Path | None:
    """Reject paths that became symlinks after the initial root check."""

    if path is None:
        return None
    try:
        candidate = path.expanduser()
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if resolved != candidate or not resolved.is_file():
        return None
    return resolved


def _read_regular_file(
    path: Path | None,
) -> tuple[Path, os.stat_result, bytes] | None:
    """Read a regular file through a descriptor after symlink revalidation."""

    resolved = _revalidate_regular_file(path)
    if resolved is None:
        return None
    open_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    open_flags |= getattr(os, "O_NOFOLLOW", 0)
    handle = None
    descriptor: int | None = None
    try:
        descriptor = os.open(resolved, open_flags)
        handle = os.fdopen(descriptor, "rb")
        descriptor = None
        stat_result = os.fstat(handle.fileno())
        if not stat_module.S_ISREG(stat_result.st_mode):
            return None
        return resolved, stat_result, handle.read()
    except OSError:
        return None
    finally:
        if handle is not None:
            handle.close()
        elif descriptor is not None:
            os.close(descriptor)


def _stored_path(
    path_value: str | None,
    settings: Settings,
    allowed_source_roots: Iterable[Path] = (),
) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        storage = settings.resolved_storage_root.expanduser().resolve()
        source_roots = tuple(
            source_root.expanduser().resolve() for source_root in allowed_source_roots
        )
    except OSError:
        return None

    # Relative source-node paths belong to their owning Library root. Only
    # managed-storage paths (covers, caches, etc.) fall back to STORAGE_ROOT.
    # Absolute paths are never trusted on their own: they must still be inside
    # one of the configured roots after resolving symlinks.
    candidates = (
        tuple(root / path for root in source_roots)
        if not path.is_absolute() and source_roots
        else (path if path.is_absolute() else storage / path,)
    )
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        roots = source_roots if source_roots else (storage,)
        if any(resolved == root or root in resolved.parents for root in roots):
            return resolved
    return None


def _parse_byte_range(
    header: str | None, size: int
) -> tuple[str, tuple[int, int] | None]:
    if not header:
        return "none", None
    match = re.match(r"^bytes=(\d*)-(\d*)$", header.strip())
    if not match:
        return "invalid", None
    raw_start, raw_end = match.groups()
    if not raw_start and not raw_end:
        return "invalid", None
    if size <= 0:
        return "unsatisfiable", None
    if not raw_start:
        try:
            suffix_length = int(raw_end)
        except ValueError:
            return "unsatisfiable", None
        if suffix_length <= 0:
            return "unsatisfiable", None
        return "range", (max(0, size - suffix_length), size - 1)
    try:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    except ValueError:
        return "unsatisfiable", None
    if start < 0 or end < start or start >= size:
        return "unsatisfiable", None
    return "range", (start, min(end, size - 1))


def _weak_etag(size: int, mtime_ms: int, extra: str = "") -> str:
    suffix = f"-{extra.encode('utf-8').hex()}" if extra else ""
    return f'W/"{size:x}-{mtime_ms:x}{suffix}"'


def _not_modified(request: Request, etag: str, last_modified: str) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        tags = [tag.strip() for tag in if_none_match.split(",")]
        return "*" in tags or etag in tags
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        try:
            since = parsedate_to_datetime(if_modified_since)
            modified = parsedate_to_datetime(last_modified)
            return modified <= since
        except (TypeError, ValueError):
            return False
    return False


def _should_use_range(request: Request, etag: str, last_modified: str) -> bool:
    if_range = request.headers.get("if-range")
    if not if_range:
        return True
    if if_range.startswith("W/"):
        # RFC 9110 requires strong comparison for an entity-tag in If-Range.
        return False
    if if_range.startswith('"'):
        return not etag.startswith("W/") and if_range == etag
    try:
        if_range_date = parsedate_to_datetime(if_range)
        modified = parsedate_to_datetime(last_modified)
        return modified <= if_range_date
    except (TypeError, ValueError):
        return False


def _response_headers(
    size: int,
    mtime: float,
    media_type: str,
    name: str,
    extra: str = "",
    *,
    as_attachment: bool = False,
) -> dict[str, str]:
    modified = datetime.fromtimestamp(mtime, UTC).replace(microsecond=0)
    disposition = "attachment" if as_attachment else "inline"
    return {
        "Accept-Ranges": "bytes",
        "Content-Type": media_type,
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "private, max-age=86400"
        if media_type.lower().startswith("image/")
        else "private, max-age=60",
        "Vary": "Cookie",
        "ETag": _weak_etag(size, int(mtime * 1000), extra),
        "Last-Modified": format_datetime(modified, usegmt=True),
    }


def _bytes_response(
    data: bytes,
    request: Request,
    media_type: str,
    name: str,
    mtime: float | None = None,
    extra: str = "",
) -> Response:
    started_at = monotonic()
    size = len(data)
    user_id = str(getattr(request.state, "user_id", "") or "")
    cache_identity = f"{extra}|user:{user_id}" if user_id else extra
    effective_mtime = mtime if mtime is not None else datetime.now(UTC).timestamp()
    headers = _response_headers(size, effective_mtime, media_type, name, cache_identity)
    if not request.headers.get("range") and _not_modified(
        request, headers["ETag"], headers["Last-Modified"]
    ):
        return Response(status_code=304, headers=headers)
    range_header = request.headers.get("range")
    byte_range = None
    if range_header and _should_use_range(
        request, headers["ETag"], headers["Last-Modified"]
    ):
        kind, parsed = _parse_byte_range(range_header, size)
        if kind == "invalid":
            response = fail("Range 请求格式不正确", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        if kind == "unsatisfiable":
            response = fail("Range 超出文件大小", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        byte_range = parsed
    if byte_range:
        start, end = byte_range
        body = data[start : end + 1]
        headers["Content-Length"] = str(len(body))
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        _log_slow_file_request(
            request,
            "bytes",
            "memory",
            request.headers.get("range"),
            len(body),
            206,
            started_at,
        )
        return Response(
            content=body, status_code=206, headers=headers, media_type=media_type
        )
    headers["Content-Length"] = str(size)
    _log_slow_file_request(
        request, "bytes", "memory", request.headers.get("range"), size, 200, started_at
    )
    return Response(content=data, headers=headers, media_type=media_type)


def _base_media_type(media_type: str | None) -> str:
    return (media_type or "").split(";", 1)[0].strip().lower()


def _comic_page_image_variant(request: Request) -> str:
    value = (
        (
            request.query_params.get("imageVariant")
            or request.query_params.get("image_variant")
            or ""
        )
        .strip()
        .lower()
    )
    return (
        COMIC_PAGE_DATA_SAVER_VARIANT
        if value
        in {COMIC_PAGE_DATA_SAVER_VARIANT, "saver", "compressed", "webp", "avif"}
        else COMIC_PAGE_ORIGINAL_VARIANT
    )


def _is_comic_page_image(media_type: str | None) -> bool:
    return _base_media_type(media_type).startswith("image/")


def _comic_page_cache_path(settings: Settings, cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return (
        settings.resolved_storage_root
        / "cache"
        / "comic-pages"
        / digest[:2]
        / f"{digest}.avif"
    )


def _pse_page_cache_path(settings: Settings, cache_key: str, media_type: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    extension = {"image/png": ".png", "image/gif": ".gif"}.get(media_type, ".jpg")
    return (
        settings.resolved_storage_root
        / "cache"
        / "opds-pse"
        / digest[:2]
        / f"{digest}{extension}"
    )


def _pse_image_bytes(
    data: bytes, max_width: int | None, media_type: str
) -> bytes | None:
    if media_type == "image/gif" and max_width is None:
        return data
    try:
        with Image.open(io.BytesIO(data)) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            prepared = ImageOps.exif_transpose(source)
            if max_width is not None and prepared.width > max_width:
                height = max(1, round(prepared.height * max_width / prepared.width))
                prepared = prepared.resize(
                    (max_width, height), Image.Resampling.LANCZOS
                )
            if media_type == "image/png":
                output = io.BytesIO()
                prepared.save(output, format="PNG", optimize=True)
                return output.getvalue()
            if _image_has_alpha(prepared):
                rgba = prepared.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                prepared = background
            elif prepared.mode != "RGB":
                prepared = prepared.convert("RGB")
            output = io.BytesIO()
            prepared.save(
                output,
                format="JPEG",
                quality=PSE_PAGE_JPEG_QUALITY,
                optimize=True,
            )
            return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        logger.debug("failed to create OPDS PSE JPEG page: %s", exc)
        return None


def _pse_image_response_unlimited(
    *,
    source: bytes,
    request: Request,
    user_id: str,
    settings: Settings,
    cache_key: str,
    source_mtime: float,
    name: str,
    max_width: int | None,
    media_type: str,
) -> Response:
    cache_path = _pse_page_cache_path(settings, cache_key, media_type)
    data = cache_path.read_bytes() if cache_path.is_file() else None
    if data is None:
        data = _pse_image_bytes(source, max_width, media_type)
        if data is None:
            return fail("页面无法转换", status_code=415, code="PSE_PAGE_UNSUPPORTED")
        _write_cache_bytes(cache_path, data)
    request.state.user_id = user_id
    if request.method == "HEAD":
        headers = _response_headers(
            len(data),
            source_mtime,
            media_type,
            str(Path(name or "page").with_suffix(cache_path.suffix)),
            extra=hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24],
        )
        headers["Content-Length"] = str(len(data))
        headers["X-OPDS-PSE-Width"] = str(max_width or "original")
        return Response(status_code=200, headers=headers, media_type=media_type)
    response = _bytes_response(
        data,
        request,
        media_type,
        str(Path(name or "page").with_suffix(cache_path.suffix)),
        mtime=source_mtime,
        extra=hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24],
    )
    response.headers["X-OPDS-PSE-Width"] = str(max_width or "original")
    return response


def _pse_image_response(
    *,
    source: bytes,
    request: Request,
    user_id: str,
    settings: Settings,
    cache_key: str,
    source_mtime: float,
    name: str,
    max_width: int | None,
    media_type: str,
) -> Response:
    release = _acquire_file_stream_slot(user_id)
    if release is None:
        return _file_stream_limit_response()
    try:
        return _pse_image_response_unlimited(
            source=source,
            request=request,
            user_id=user_id,
            settings=settings,
            cache_key=cache_key,
            source_mtime=source_mtime,
            name=name,
            max_width=max_width,
            media_type=media_type,
        )
    finally:
        release()


def _write_cache_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{time_ns()}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _small_cover_cache_key(path: Path, stat: os.stat_result) -> str:
    return (
        f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"small-cover-v{SMALL_COVER_CACHE_VERSION}:"
        f"max-{SMALL_COVER_MAX_DIMENSION}:bytes-{SMALL_COVER_MAX_BYTES}"
    )


def _small_cover_cache_path(settings: Settings, cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return (
        settings.resolved_storage_root
        / "cache"
        / "covers"
        / digest[:2]
        / f"{digest}.webp"
    )


def _image_has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )


def _image_for_webp(image: Image.Image) -> Image.Image:
    if image.mode in {"RGB", "RGBA"}:
        return image
    return image.convert("RGBA" if _image_has_alpha(image) else "RGB")


def _small_cover_webp_bytes(path: Path) -> bytes | None:
    payload = _read_regular_file(path)
    if payload is None:
        return None
    _resolved, _stat_result, content = payload
    try:
        with Image.open(io.BytesIO(content)) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            prepared = _image_for_webp(ImageOps.exif_transpose(source))
            prepared.thumbnail(
                (SMALL_COVER_MAX_DIMENSION, SMALL_COVER_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            while True:
                for quality in SMALL_COVER_QUALITIES:
                    output = io.BytesIO()
                    prepared.save(output, format="WEBP", quality=quality, method=6)
                    data = output.getvalue()
                    if len(data) <= SMALL_COVER_MAX_BYTES:
                        return data
                width, height = prepared.size
                next_size = (
                    max(1, int(width * 0.85)),
                    max(1, int(height * 0.85)),
                )
                if next_size == prepared.size:
                    return None
                prepared = prepared.resize(next_size, Image.Resampling.LANCZOS)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        logger.debug("failed to create small cover image path=%s error=%s", path, exc)
        return None


def _small_cover_response(
    path: Path, request: Request, user_id: str, settings: Settings
) -> Response | None:
    resolved_path = _revalidate_regular_file(path)
    if resolved_path is None:
        return None
    path = resolved_path
    stat = path.stat()
    cache_key = _small_cover_cache_key(path, stat)
    cache_path = _small_cover_cache_path(settings, cache_key)
    data = cache_path.read_bytes() if cache_path.is_file() else None
    if data is None or len(data) > SMALL_COVER_MAX_BYTES:
        data = _small_cover_webp_bytes(path)
        if data is None:
            return None
        _write_cache_bytes(cache_path, data)
    request.state.user_id = user_id
    cache_identity = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    return _bytes_response(
        data,
        request,
        SMALL_COVER_MEDIA_TYPE,
        str(path.with_suffix(".webp").name),
        mtime=stat.st_mtime,
        extra=f"small-cover-{cache_identity}",
    )


def _comic_page_webp_image(image: Image.Image) -> Image.Image:
    prepared = ImageOps.exif_transpose(image)
    prepared.thumbnail(
        (COMIC_PAGE_DATA_SAVER_MAX_EDGE, COMIC_PAGE_DATA_SAVER_MAX_EDGE),
        Image.Resampling.LANCZOS,
    )
    return prepared.convert("RGBA" if _image_has_alpha(prepared) else "RGB")


def _comic_page_webp_bytes(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if getattr(source, "is_animated", False):
                return None
            image = _comic_page_webp_image(source)
            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=COMIC_PAGE_DATA_SAVER_QUALITY,
                method=COMIC_PAGE_DATA_SAVER_METHOD,
                lossless=_image_has_alpha(image),
            )
            optimized = output.getvalue()
            return optimized if len(optimized) < len(data) else None
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        logger.debug("skipping comic page data-saver image variant: %s", exc)
        return None


def _webp_page_name(name: str) -> str:
    return str(Path(name or "page").with_suffix(".webp"))


def _comic_page_webp_response(
    data: bytes,
    request: Request,
    name: str,
    source_mtime: float,
    source_size: int,
    cache_extra: str,
) -> Response:
    variant_extra = hashlib.sha256(cache_extra.encode("utf-8")).hexdigest()[:24]
    response = _bytes_response(
        data,
        request,
        COMIC_PAGE_DATA_SAVER_MEDIA_TYPE,
        _webp_page_name(name),
        mtime=source_mtime,
        extra=f"comic-webp-v{COMIC_PAGE_DATA_SAVER_CACHE_VERSION}-{variant_extra}",
    )
    response.headers["X-Comic-Image-Variant"] = COMIC_PAGE_DATA_SAVER_VARIANT
    response.headers["X-Comic-Image-Quality"] = (
        f"webp;q={COMIC_PAGE_DATA_SAVER_QUALITY};"
        f"max-edge={COMIC_PAGE_DATA_SAVER_MAX_EDGE}"
    )
    if source_size > 0:
        response.headers["X-Comic-Image-Compression-Ratio"] = (
            f"{len(data) / source_size:.3f}"
        )
    return response


def _file_stream_limit_response() -> Response:
    return fail("同时文件流请求过多，请稍后重试", status_code=429)


def _acquire_file_stream_slot(user_id: str):
    limit = STREAMS_PER_USER_LIMIT
    if limit is None:
        limit = get_settings().file_streams_per_user_limit
    if limit <= 0:
        return lambda: None
    with _active_file_streams_lock:
        current = _active_file_streams_by_user.get(user_id, 0)
        if current >= limit:
            return None
        _active_file_streams_by_user[user_id] = current + 1

    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        with _active_file_streams_lock:
            next_count = max(0, _active_file_streams_by_user.get(user_id, 1) - 1)
            if next_count == 0:
                _active_file_streams_by_user.pop(user_id, None)
            else:
                _active_file_streams_by_user[user_id] = next_count

    return release


def _log_slow_file_request(
    request: Request,
    route: str,
    asset_id: str,
    range_header: str | None,
    bytes_sent: int,
    status_code: int,
    started_at: float,
) -> None:
    threshold_ms = SLOW_REQUEST_LOG_THRESHOLD_MS
    duration_ms = int((monotonic() - started_at) * 1000)
    if duration_ms < threshold_ms:
        return
    logger.warning(
        "[slow-file-request] route=%s userId=%s assetId=%s range=%s bytes=%s status=%s durationMs=%s",
        route,
        getattr(request.state, "user_id", "unknown"),
        asset_id,
        range_header,
        bytes_sent,
        status_code,
        duration_ms,
    )


def _file_response(
    path: Path | None,
    request: Request,
    user_id: str,
    media_type: str | None = None,
    name: str | None = None,
    missing_message: str = "文件不存在",
    route: str = "file",
    asset_id: str | None = None,
    *,
    as_attachment: bool = False,
) -> Response:
    path = _revalidate_regular_file(path)
    if path is None:
        return fail(missing_message, status_code=404)
    request.state.user_id = user_id
    handle = None
    if request.method == "HEAD":
        try:
            stat = path.stat()
        except OSError:
            return fail(missing_message, status_code=404)
    else:
        # Resolve-and-check happens before this function. Open the already
        # checked path without following a final symlink and stream this file
        # descriptor, so a replacement symlink cannot redirect the response
        # between validation and the first read.
        open_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        open_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, open_flags)
            handle = os.fdopen(descriptor, "rb")
            stat = os.fstat(handle.fileno())
        except OSError:
            if handle is not None:
                handle.close()
            return fail(missing_message, status_code=404)
        if not stat_module.S_ISREG(stat.st_mode):
            handle.close()
            return fail(missing_message, status_code=404)
    resolved_media_type = (
        media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    headers = _response_headers(
        stat.st_size,
        stat.st_mtime,
        resolved_media_type,
        name or path.name,
        extra=f"user:{user_id}",
        as_attachment=as_attachment,
    )
    version = f"{stat.st_size}:{int(stat.st_mtime * 1000)}"
    headers["X-Asset-Version"] = version
    expected_version = request.headers.get("x-asset-version")
    if expected_version is not None and expected_version != version:
        if handle is not None:
            handle.close()
        return fail(
            "Asset version changed", status_code=412, code="ASSET_VERSION_CHANGED"
        )
    if not request.headers.get("range") and _not_modified(
        request, headers["ETag"], headers["Last-Modified"]
    ):
        if handle is not None:
            handle.close()
        return Response(status_code=304, headers=headers)
    byte_range = None
    range_header = request.headers.get("range")
    if range_header and _should_use_range(
        request, headers["ETag"], headers["Last-Modified"]
    ):
        kind, parsed = _parse_byte_range(range_header, stat.st_size)
        if kind == "invalid":
            if handle is not None:
                handle.close()
            response = fail(
                "Range 请求格式不正确",
                status_code=416,
                code="RANGE_INVALID",
            )
            response.headers["Content-Range"] = f"bytes */{stat.st_size}"
            return response
        if kind == "unsatisfiable":
            if handle is not None:
                handle.close()
            response = fail(
                "Range 超出文件大小",
                status_code=416,
                code="RANGE_NOT_SATISFIABLE",
            )
            response.headers["Content-Range"] = f"bytes */{stat.st_size}"
            return response
        byte_range = parsed

    # Metadata probes from HTMLAudioElement and proxies frequently use HEAD.
    # Return exactly the GET headers/status without consuming a stream slot or
    # opening a multi-gigabyte audio file.
    if request.method == "HEAD":
        if byte_range:
            start, end = byte_range
            headers["Content-Length"] = str(end - start + 1)
            headers["Content-Range"] = f"bytes {start}-{end}/{stat.st_size}"
            return Response(
                status_code=206, headers=headers, media_type=resolved_media_type
            )
        headers["Content-Length"] = str(stat.st_size)
        return Response(
            status_code=200, headers=headers, media_type=resolved_media_type
        )

    def iterator(
        release,
        started_at: float,
        status_code: int,
        bytes_sent: int,
        start: int = 0,
        end: int | None = None,
    ):
        try:
            remaining = None if end is None else end - start + 1
            assert handle is not None
            handle.seek(start)
            while True:
                chunk_size = (
                    1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
                )
                if chunk_size <= 0:
                    break
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk
        finally:
            if handle is not None:
                handle.close()
            release()
            _log_slow_file_request(
                request,
                route,
                asset_id or str(path),
                range_header,
                bytes_sent,
                status_code,
                started_at,
            )

    release = _acquire_file_stream_slot(user_id)
    if release is None:
        if handle is not None:
            handle.close()
        return _file_stream_limit_response()
    started_at = monotonic()
    if byte_range:
        start, end = byte_range
        bytes_sent = end - start + 1
        headers["Content-Length"] = str(bytes_sent)
        headers["Content-Range"] = f"bytes {start}-{end}/{stat.st_size}"
        return StreamingResponse(
            iterator(release, started_at, 206, bytes_sent, start, end),
            status_code=206,
            headers=headers,
            media_type=resolved_media_type,
        )
    headers["Content-Length"] = str(stat.st_size)
    return StreamingResponse(
        iterator(release, started_at, 200, stat.st_size),
        headers=headers,
        media_type=resolved_media_type,
    )


def _send_file(
    path: Path | None,
    request: Request,
    user_id: str,
    media_type: str | None = None,
    name: str | None = None,
    route: str = "file",
    asset_id: str | None = None,
    *,
    as_attachment: bool = False,
) -> Response:
    return _file_response(
        path,
        request,
        user_id=user_id,
        media_type=media_type,
        name=name,
        route=route,
        asset_id=asset_id,
        as_attachment=as_attachment,
    )


def _send_zip_entry(
    archive_path: Path | None,
    entry_name: str | None,
    request: Request,
    user_id: str,
    media_type: str | None = None,
    route: str = "zip-entry",
    asset_id: str | None = None,
) -> Response:
    archive_path = _revalidate_regular_file(archive_path)
    if archive_path is None or not entry_name:
        return fail("页面不存在", status_code=404)
    archive = None
    try:
        archive = open_comic_archive(archive_path)
        info = archive.getinfo(entry_name)
    except (KeyError, OSError, ComicArchiveError):
        if archive is not None:
            archive.close()
        return fail("页面不存在", status_code=404)
    request.state.user_id = user_id
    resolved_media_type = (
        media_type or mimetypes.guess_type(entry_name)[0] or "application/octet-stream"
    )
    size = int(info.file_size)
    headers = _response_headers(
        size,
        archive_path.stat().st_mtime,
        resolved_media_type,
        Path(entry_name).name,
        extra=f"{entry_name}|user:{user_id}",
    )
    if not request.headers.get("range") and _not_modified(
        request, headers["ETag"], headers["Last-Modified"]
    ):
        archive.close()
        return Response(status_code=304, headers=headers)
    byte_range = None
    range_header = request.headers.get("range")
    if range_header and _should_use_range(
        request, headers["ETag"], headers["Last-Modified"]
    ):
        kind, parsed = _parse_byte_range(range_header, size)
        if kind == "invalid":
            archive.close()
            response = fail("Range 请求格式不正确", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        if kind == "unsatisfiable":
            archive.close()
            response = fail("Range 超出文件大小", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        byte_range = parsed

    def iterator(
        release,
        started_at: float,
        status_code: int,
        bytes_sent: int,
        start: int = 0,
        end: int | None = None,
    ):
        try:
            with archive, archive.open(entry_name, "r") as handle:
                remaining_skip = start
                while remaining_skip > 0:
                    skipped = handle.read(min(1024 * 1024, remaining_skip))
                    if not skipped:
                        return
                    remaining_skip -= len(skipped)
                remaining = None if end is None else end - start + 1
                while True:
                    chunk_size = (
                        1024 * 1024
                        if remaining is None
                        else min(1024 * 1024, remaining)
                    )
                    if chunk_size <= 0:
                        break
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    if remaining is not None:
                        remaining -= len(chunk)
                    yield chunk
        finally:
            release()
            _log_slow_file_request(
                request,
                route,
                asset_id or entry_name,
                range_header,
                bytes_sent,
                status_code,
                started_at,
            )

    release = _acquire_file_stream_slot(user_id)
    if release is None:
        archive.close()
        return _file_stream_limit_response()
    started_at = monotonic()
    if byte_range:
        start, end = byte_range
        bytes_sent = end - start + 1
        headers["Content-Length"] = str(bytes_sent)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(
            iterator(release, started_at, 206, bytes_sent, start, end),
            status_code=206,
            headers=headers,
            media_type=resolved_media_type,
        )
    headers["Content-Length"] = str(size)
    return StreamingResponse(
        iterator(release, started_at, 200, size),
        headers=headers,
        media_type=resolved_media_type,
    )


def _with_comic_page_variant_header(response: Response, variant: str) -> Response:
    response.headers["X-Comic-Image-Variant"] = variant
    return response


def _send_original_comic_page_file(
    path: Path | None,
    request: Request,
    user_id: str,
    media_type: str | None = None,
    route: str = "volume-page",
    asset_id: str | None = None,
) -> Response:
    return _with_comic_page_variant_header(
        _send_file(
            path,
            request,
            user_id,
            media_type=media_type,
            route=route,
            asset_id=asset_id,
        ),
        COMIC_PAGE_ORIGINAL_VARIANT,
    )


def _send_original_comic_page_zip_entry(
    archive_path: Path | None,
    entry_name: str | None,
    request: Request,
    user_id: str,
    media_type: str | None = None,
    route: str = "volume-page-zip",
    asset_id: str | None = None,
) -> Response:
    return _with_comic_page_variant_header(
        _send_zip_entry(
            archive_path,
            entry_name,
            request,
            user_id,
            media_type=media_type,
            route=route,
            asset_id=asset_id,
        ),
        COMIC_PAGE_ORIGINAL_VARIANT,
    )


def _send_comic_page_file(
    path: Path | None,
    request: Request,
    user_id: str,
    settings: Settings,
    media_type: str | None = None,
    route: str = "volume-page",
    asset_id: str | None = None,
) -> Response:
    variant = _comic_page_image_variant(request)
    path = _revalidate_regular_file(path)
    if path is None:
        return fail("文件不存在", status_code=404)
    resolved_media_type = (
        media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    if variant != COMIC_PAGE_DATA_SAVER_VARIANT or not _is_comic_page_image(
        resolved_media_type
    ):
        return _send_original_comic_page_file(
            path,
            request,
            user_id,
            media_type=resolved_media_type,
            route=route,
            asset_id=asset_id,
        )

    request.state.user_id = user_id
    stat = path.stat()
    cache_key = (
        f"file:{path}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"comic-webp-v{COMIC_PAGE_DATA_SAVER_CACHE_VERSION}:"
        f"q-{COMIC_PAGE_DATA_SAVER_QUALITY}:"
        f"edge-{COMIC_PAGE_DATA_SAVER_MAX_EDGE}"
    )
    cache_path = _comic_page_cache_path(settings, cache_key)
    if cache_path.exists() and cache_path.is_file():
        return _comic_page_webp_response(
            cache_path.read_bytes(),
            request,
            path.name,
            stat.st_mtime,
            stat.st_size,
            cache_key,
        )
    payload = _read_regular_file(path)
    if payload is None:
        return fail("文件不存在", status_code=404)
    _resolved, _source_stat, source = payload
    optimized = _comic_page_webp_bytes(source)
    if optimized is None:
        return _send_original_comic_page_file(
            path,
            request,
            user_id,
            media_type=resolved_media_type,
            route=route,
            asset_id=asset_id,
        )
    _write_cache_bytes(cache_path, optimized)
    return _comic_page_webp_response(
        optimized, request, path.name, stat.st_mtime, len(source), cache_key
    )


def _send_comic_page_zip_entry(
    archive_path: Path | None,
    entry_name: str | None,
    request: Request,
    user_id: str,
    settings: Settings,
    media_type: str | None = None,
    route: str = "volume-page-zip",
    asset_id: str | None = None,
) -> Response:
    variant = _comic_page_image_variant(request)
    archive_path = _revalidate_regular_file(archive_path)
    if archive_path is None or not entry_name:
        return fail("页面不存在", status_code=404)
    if variant != COMIC_PAGE_DATA_SAVER_VARIANT:
        return _send_original_comic_page_zip_entry(
            archive_path,
            entry_name,
            request,
            user_id,
            media_type=media_type,
            route=route,
            asset_id=asset_id,
        )

    try:
        with open_comic_archive(archive_path) as archive:
            info = archive.getinfo(entry_name)
            resolved_media_type = (
                media_type
                or mimetypes.guess_type(entry_name)[0]
                or "application/octet-stream"
            )
            if not _is_comic_page_image(resolved_media_type):
                return _send_original_comic_page_zip_entry(
                    archive_path,
                    entry_name,
                    request,
                    user_id,
                    media_type=resolved_media_type,
                    route=route,
                    asset_id=asset_id,
                )
            archive_stat = archive_path.stat()
            cache_key = (
                f"zip:{archive_path}:{archive_stat.st_size}:{archive_stat.st_mtime_ns}:"
                f"{entry_name}:{info.file_size}:{info.checksum}:"
                f"comic-webp-v{COMIC_PAGE_DATA_SAVER_CACHE_VERSION}:"
                f"q-{COMIC_PAGE_DATA_SAVER_QUALITY}:"
                f"edge-{COMIC_PAGE_DATA_SAVER_MAX_EDGE}"
            )
            cache_path = _comic_page_cache_path(settings, cache_key)
            if cache_path.exists() and cache_path.is_file():
                return _comic_page_webp_response(
                    cache_path.read_bytes(),
                    request,
                    Path(entry_name).name,
                    archive_stat.st_mtime,
                    info.file_size,
                    cache_key,
                )
            source = archive.read(entry_name)
    except (KeyError, OSError, ComicArchiveError):
        return fail("页面不存在", status_code=404)

    optimized = _comic_page_webp_bytes(source)
    if optimized is None:
        return _send_original_comic_page_zip_entry(
            archive_path,
            entry_name,
            request,
            user_id,
            media_type=resolved_media_type,
            route=route,
            asset_id=asset_id,
        )
    _write_cache_bytes(cache_path, optimized)
    return _comic_page_webp_response(
        optimized,
        request,
        Path(entry_name).name,
        archive_stat.st_mtime,
        len(source),
        cache_key,
    )


def stored_path(
    path_value: str | None,
    settings: Settings,
    allowed_source_roots: Iterable[Path] = (),
) -> Path | None:
    return _stored_path(
        path_value,
        settings,
        allowed_source_roots,
    )


def send_file(
    path: Path | None,
    request: Request,
    user_id: str,
    media_type: str | None = None,
    name: str | None = None,
    route: str = "file",
    asset_id: str | None = None,
    *,
    as_attachment: bool = False,
) -> Response:
    return _send_file(
        path,
        request,
        user_id,
        media_type=media_type,
        name=name,
        route=route,
        asset_id=asset_id,
        as_attachment=as_attachment,
    )


def small_cover_response(
    path: Path, request: Request, user_id: str, settings: Settings
) -> Response | None:
    return _small_cover_response(path, request, user_id, settings)


def send_comic_page_file(
    path: Path | None,
    request: Request,
    user_id: str,
    settings: Settings,
    media_type: str | None = None,
    route: str = "volume-page",
    asset_id: str | None = None,
) -> Response:
    return _send_comic_page_file(
        path,
        request,
        user_id,
        settings,
        media_type=media_type,
        route=route,
        asset_id=asset_id,
    )


def send_comic_page_zip_entry(
    archive_path: Path | None,
    entry_name: str | None,
    request: Request,
    user_id: str,
    settings: Settings,
    media_type: str | None = None,
    route: str = "volume-page-zip",
    asset_id: str | None = None,
) -> Response:
    return _send_comic_page_zip_entry(
        archive_path,
        entry_name,
        request,
        user_id,
        settings,
        media_type=media_type,
        route=route,
        asset_id=asset_id,
    )


def send_pse_page_file(
    path: Path | None,
    request: Request,
    user_id: str,
    settings: Settings,
    *,
    max_width: int | None,
    asset_id: str,
    output_media_type: str = "image/jpeg",
) -> Response:
    path = _revalidate_regular_file(path)
    if path is None:
        return fail("页面不存在", status_code=404, code="PAGE_NOT_FOUND")
    payload = _read_regular_file(path)
    if payload is None:
        return fail("页面不存在", status_code=404, code="PAGE_NOT_FOUND")
    _resolved, stat, source = payload
    cache_key = (
        f"file:{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"pse-v{PSE_PAGE_CACHE_VERSION}:{output_media_type}:w-{max_width or 'original'}:"
        f"q-{PSE_PAGE_JPEG_QUALITY}"
    )
    return _pse_image_response(
        source=source,
        request=request,
        user_id=user_id,
        settings=settings,
        cache_key=cache_key,
        source_mtime=stat.st_mtime,
        name=path.name,
        max_width=max_width,
        media_type=output_media_type,
    )


def send_pse_page_zip_entry(
    archive_path: Path | None,
    entry_name: str | None,
    request: Request,
    user_id: str,
    settings: Settings,
    *,
    max_width: int | None,
    asset_id: str,
    output_media_type: str = "image/jpeg",
) -> Response:
    archive_path = _revalidate_regular_file(archive_path)
    if archive_path is None or not entry_name:
        return fail("页面不存在", status_code=404, code="PAGE_NOT_FOUND")
    try:
        with open_comic_archive(archive_path) as archive:
            info = archive.getinfo(entry_name)
            source = archive.read(entry_name)
        stat = archive_path.stat()
    except (KeyError, OSError, ComicArchiveError):
        return fail("页面不存在", status_code=404, code="PAGE_NOT_FOUND")
    cache_key = (
        f"zip:{archive_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"{entry_name}:{info.file_size}:{info.checksum}:"
        f"pse-v{PSE_PAGE_CACHE_VERSION}:{output_media_type}:w-{max_width or 'original'}:"
        f"q-{PSE_PAGE_JPEG_QUALITY}"
    )
    return _pse_image_response(
        source=source,
        request=request,
        user_id=user_id,
        settings=settings,
        cache_key=cache_key,
        source_mtime=stat.st_mtime,
        name=Path(entry_name).name,
        max_width=max_width,
        media_type=output_media_type,
    )
