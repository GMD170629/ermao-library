"""Media file, cover, and page HTTP surface."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from http.client import HTTPMessage, HTTPResponse
from pathlib import Path
from typing import Annotated, Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as UrlRequest

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.media import media_page_index, media_resource_query, media_streaming
from app.bootstrap.system import list_settings
from app.contracts.http_errors import (
    BasicNotFoundError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.authorization import (
    can_access_file,
    can_access_volume,
    can_access_work,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.media.application.cover_proxy import (
    UnsafeCoverUrl,
    configured_cover_origins,
    validate_cover_url,
)
from app.modules.media.presentation.schemas import (
    MediaFileResponse,
    MediaImageResponse,
    VolumePagesPayload,
    VolumePagesResponse,
)
from app.schemas.responses import fail
from app.services.default_cover import ensure_default_cover, is_default_cover_path

router = APIRouter(tags=["media"], route_class=TypedContractRoute)
logger = logging.getLogger(__name__)
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]

_METADATA_PROVIDER_BASE_URL_KEYS = (
    "metadata.douban.baseUrl",
    "metadata.bangumi.baseUrl",
)


class _SafeCoverRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_origins: frozenset[tuple[str, str, int | None]]) -> None:
        super().__init__()
        self._allowed_origins = allowed_origins

    def redirect_request(
        self,
        req: UrlRequest,
        fp: HTTPResponse,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> UrlRequest | None:
        validate_cover_url(newurl, configured_origins=self._allowed_origins)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _now() -> datetime:
    return datetime.now(UTC)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


@router.get("/files/{file_id}", response_class=MediaFileResponse)
@router.head("/files/{file_id}", response_class=MediaFileResponse)
def get_file(
    file_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_file(db, user, file_id):
        return fail("文件不存在", status_code=404, code="FILE_NOT_FOUND")
    file = media_resource_query(db).get_file(file_id)
    return media_streaming.send_file(
        media_streaming.stored_path(
            file.path if file else None, settings, database_backed=True
        ),
        request,
        user.id,
        media_type=file.mime_type if file else None,
        name=Path(file.path if file else "file").name,
        route="files",
        file_id=file_id,
    )


@router.get("/volumes/{volume_id}/file", response_class=MediaFileResponse)
@router.head("/volumes/{volume_id}/file", response_class=MediaFileResponse)
def get_volume_file(
    volume_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("卷册不存在", status_code=404, code="VOLUME_NOT_FOUND")
    file = media_resource_query(db).first_volume_file(volume_id)
    return media_streaming.send_file(
        media_streaming.stored_path(
            file.path if file else None, settings, database_backed=True
        ),
        request,
        user.id,
        media_type=file.mime_type if file else None,
        name=Path(file.path if file else "file").name,
        route="volume-file",
        file_id=file.id if file else volume_id,
    )


@router.get("/works/{work_id}/cover", response_class=MediaImageResponse)
@router.get("/volumes/{volume_id}/cover", response_class=MediaImageResponse)
def get_cover(
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    work_id: str | None = None,
    volume_id: str | None = None,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if work_id and not can_access_work(db, user, work_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    if volume_id and not can_access_volume(db, user, volume_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    cover_path_value = media_resource_query(db).cover_path(
        work_id=work_id,
        volume_id=volume_id,
    )
    cover_id = work_id or volume_id or "cover"
    if not work_id and not volume_id:
        return fail("条目不存在", status_code=404)
    cover_path = media_streaming.stored_path(
        cover_path_value, settings, database_backed=True
    )
    if (
        cover_path is None
        or not cover_path.is_file()
        or is_default_cover_path(cover_path_value, settings)
    ):
        stored_default = ensure_default_cover(settings)
        cover_path = media_streaming.stored_path(stored_default, settings)
    if request.query_params.get("size") == "small" and cover_path is not None:
        response = media_streaming.small_cover_response(
            cover_path, request, user.id, settings
        )
        if response is not None:
            return response
        default_path = media_streaming.stored_path(
            ensure_default_cover(settings), settings
        )
        if default_path is not None and default_path != cover_path:
            response = media_streaming.small_cover_response(
                default_path, request, user.id, settings
            )
            if response is not None:
                return response
    return media_streaming.send_file(
        cover_path,
        request,
        user.id,
        route="cover",
        file_id=cover_id,
    )


@router.get("/metadata/cover-proxy", response_class=MediaImageResponse)
def metadata_cover_proxy(
    url: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    provider_settings = list_settings(db)
    allowed_origins = configured_cover_origins(
        provider_settings.get(key) for key in _METADATA_PROVIDER_BASE_URL_KEYS
    )
    try:
        validate_cover_url(url, configured_origins=allowed_origins)
    except UnsafeCoverUrl:
        return fail("封面地址不支持", status_code=400)
    remote_request = UrlRequest(
        url,
        headers={
            "Accept": "image/*,*/*",
            "User-Agent": "Shuku Starship Python",
            "Referer": "https://book.douban.com/",
        },
    )
    try:
        opener = build_opener(_SafeCoverRedirectHandler(allowed_origins))
        with opener.open(remote_request, timeout=20) as remote_response:
            content_type = remote_response.headers.get("content-type") or "image/jpeg"
            if not content_type.lower().startswith("image/"):
                return fail("远程地址不是图片", status_code=400)
            data = remote_response.read(8 * 1024 * 1024)
    except (HTTPError, OSError, UnsafeCoverUrl) as exc:
        logger.warning("failed to proxy metadata cover url=%s error=%s", url, exc)
        return fail("封面预览加载失败", status_code=502)
    return Response(
        data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/volumes/{volume_id}/pages")
def list_volume_pages(
    volume_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    VolumePagesResponse,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("页面不存在", status_code=404, code="VOLUME_NOT_FOUND")
    units = media_page_index.list_page_units_for_volume(db, volume_id)
    if not units:
        media_page_index.ensure_volume_page_index(db, settings, volume_id)
        units = media_page_index.list_page_units_for_volume(db, volume_id)
    return VolumePagesResponse(
        data=VolumePagesPayload.model_validate({"pages": units, "total": len(units)})
    )


@router.get(
    "/volumes/{volume_id}/pages/{page_index}",
    response_class=MediaImageResponse,
)
def get_volume_page(
    volume_id: str,
    page_index: int,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("页面不存在", status_code=404, code="VOLUME_NOT_FOUND")
    unit = media_page_index.get_page_unit(db, volume_id, page_index)
    if not unit:
        media_page_index.ensure_volume_page_index(db, settings, volume_id)
        unit = media_page_index.get_page_unit(db, volume_id, page_index)
        if not unit:
            return fail("页面不存在", status_code=404)
    file = (
        media_page_index.get_library_file(db, unit.get("fileId"))
        if unit.get("fileId")
        else None
    )
    if file and file.get("kind") == "COMIC":
        metadata = _parse_json(unit.get("metadataJson"), {})
        entry_name = metadata.get("zipEntryName") or unit.get("href")
        return media_streaming.send_comic_page_zip_entry(
            media_streaming.stored_path(
                file.get("path"), settings, database_backed=True
            ),
            entry_name,
            request,
            user.id,
            settings,
            unit.get("mediaType"),
            route="volume-page-zip",
            file_id=unit.get("id") or f"{volume_id}:{page_index}",
        )
    return media_streaming.send_comic_page_file(
        media_streaming.stored_path(
            unit.get("href"), settings, database_backed=True
        ),
        request,
        user.id,
        settings,
        media_type=unit.get("mediaType"),
        route="volume-page",
        file_id=unit.get("id") or f"{volume_id}:{page_index}",
    )
