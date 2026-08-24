"""Media file, cover, and page HTTP surface."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Annotated, Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as UrlRequest

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.media import (
    effective_book_cover_query,
    media_page_index,
    media_resource_query,
    media_streaming,
    resource_preview,
)
from app.contracts.http_errors import (
    BasicBadRequestError,
    BasicNotFoundError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.authorization import (
    authorization_context,
    can_access_asset,
    can_access_book,
    can_access_resource,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import LibraryReadableResource
from app.modules.media.application.cover_proxy import (
    UnsafeCoverUrl,
    configured_cover_origins,
    validate_cover_url,
)
from app.modules.media.application.resource_preview import (
    ResourcePreviewAccessScope,
    ResourcePreviewNotFoundError,
    ResourcePreviewUnavailableError,
)
from app.modules.media.presentation.schemas import (
    MediaAssetResponse,
    MediaImageResponse,
    ResourceDownloadResponse,
    ResourcePage,
    ResourcePagesPayload,
    ResourcePagesResponse,
)
from app.schemas.responses import fail
from app.services.default_cover import ensure_default_cover, is_default_cover_path
from app.services.metadata_provider_registry import get_metadata_provider

router = APIRouter(tags=["media"], route_class=TypedContractRoute)
logger = logging.getLogger(__name__)
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
PARTIAL_CONTENT_RESPONSE: dict[int | str, dict[str, Any]] = {
    206: {"description": "Partial content"}
}


class _SafeCoverRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_origins: frozenset[tuple[str, str, int | None]]) -> None:
        super().__init__()
        self._allowed_origins = allowed_origins

    def redirect_request(
        self,
        req: UrlRequest,
        fp: IO[bytes],
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


def _mark_cover_fallback(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Shuku-Cover-Fallback"] = "1"
    return response


@router.get(
    "/assets/{asset_id}",
    response_class=MediaAssetResponse,
    responses=PARTIAL_CONTENT_RESPONSE,
)
@router.head(
    "/assets/{asset_id}",
    response_class=MediaAssetResponse,
    responses=PARTIAL_CONTENT_RESPONSE,
)
def get_asset(
    asset_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    download: bool = False,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_asset(db, user, asset_id):
        return fail("资源资产不存在", status_code=404, code="ASSET_NOT_FOUND")
    asset = media_resource_query(db).get_asset(asset_id)
    return media_streaming.send_file(
        media_streaming.stored_path(
            asset.path if asset else None,
            settings,
            (Path(asset.source_root),) if asset else (),
        ),
        request,
        user.id,
        media_type=asset.mime_type if asset else None,
        name=Path(asset.path if asset else "asset").name,
        route="assets",
        asset_id=asset_id,
        as_attachment=download,
    )


@router.get(
    "/resources/{resource_id}/asset",
    response_class=MediaAssetResponse,
    responses=PARTIAL_CONTENT_RESPONSE,
)
@router.head(
    "/resources/{resource_id}/asset",
    response_class=MediaAssetResponse,
    responses=PARTIAL_CONTENT_RESPONSE,
)
def get_resource_asset(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    download: bool = False,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_resource(db, user, resource_id):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    asset = media_resource_query(db).first_resource_asset(resource_id)
    return media_streaming.send_file(
        media_streaming.stored_path(
            asset.path if asset else None,
            settings,
            (Path(asset.source_root),) if asset else (),
        ),
        request,
        user.id,
        media_type=asset.mime_type if asset else None,
        name=Path(asset.path if asset else "asset").name,
        route="resource-asset",
        asset_id=asset.id if asset else resource_id,
        as_attachment=download,
    )


@router.get(
    "/resources/{resource_id}/previews/{page_index}",
    response_class=MediaImageResponse,
)
def get_resource_preview(
    resource_id: str,
    page_index: int,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    authorization = authorization_context(db, user)
    try:
        preview = resource_preview(db, settings).execute(
            scope=ResourcePreviewAccessScope(
                is_admin=authorization.is_admin,
                library_ids=authorization.library_ids,
            ),
            resource_id=resource_id,
            page_index=page_index,
        )
    except ResourcePreviewNotFoundError:
        return fail("预览不存在", status_code=404, code="PREVIEW_NOT_FOUND")
    except ResourcePreviewUnavailableError:
        return fail("预览暂时不可用", status_code=422, code="PREVIEW_UNAVAILABLE")
    headers = {
        "Cache-Control": "private, max-age=86400",
        "ETag": preview.etag,
        "Vary": "Cookie",
    }
    if request.headers.get("if-none-match") == preview.etag:
        return Response(status_code=304, headers=headers)
    return Response(
        content=preview.content,
        media_type=preview.media_type,
        headers=headers,
    )


@router.post(
    "/books/{book_id}/resources/download",
    response_model=ResourceDownloadResponse,
)
def download_resource(
    book_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ResourceDownloadResponse | Response,
    ErrorResponses(
        BasicBadRequestError,
        BasicUnauthorizedError,
        BasicNotFoundError,
    ),
]:
    _ = book_id, request, db, settings
    return fail(
        "目录资源不支持生成压缩包下载",
        status_code=501,
        code="DIRECTORY_RESOURCE_DOWNLOAD_UNSUPPORTED",
    )


@router.get("/books/{book_id}/cover", response_class=MediaImageResponse)
@router.get("/resources/{resource_id}/cover", response_class=MediaImageResponse)
@router.get(
    "/books/{book_id}/source-nodes/{source_node_id}/cover",
    response_class=MediaImageResponse,
)
def get_cover(
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    book_id: str | None = None,
    resource_id: str | None = None,
    source_node_id: str | None = None,
) -> Annotated[
    Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if book_id and not can_access_book(db, user, book_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    if resource_id and not can_access_resource(db, user, resource_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    if resource_id:
        resource_book_id = db.scalar(
            select(LibraryReadableResource.book_id).where(
                LibraryReadableResource.id == resource_id
            )
        )
        if not resource_book_id or not can_access_book(db, user, str(resource_book_id)):
            return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    cover_path_value: str | None = None
    cover_path: Path | None = None
    using_fallback = False
    if source_node_id is not None:
        if book_id is None:
            return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
        source_node_cover = media_resource_query(db).source_node_cover(
            book_id=book_id,
            source_node_id=source_node_id,
        )
        if not source_node_cover.found:
            return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
        cover_path_value = source_node_cover.path
        cover_id = source_node_id
    elif book_id is not None:
        for candidate in effective_book_cover_query(db).execute(book_id):
            candidate_path = media_streaming.stored_path(
                candidate.stored_path, settings
            )
            if candidate_path is not None and candidate_path.is_file():
                cover_path_value = candidate.stored_path
                cover_path = candidate_path
                break
        cover_id = book_id or resource_id or "cover"
    else:
        cover_path_value = media_resource_query(db).cover_path(
            resource_id=resource_id,
        )
        cover_path = media_streaming.stored_path(cover_path_value, settings)
        cover_id = resource_id or "cover"
    if not book_id and not resource_id and not source_node_id:
        return fail("条目不存在", status_code=404)
    if cover_path is None and cover_path_value is not None:
        cover_path = media_streaming.stored_path(cover_path_value, settings)
    if (
        cover_path is None
        or not cover_path.is_file()
        or is_default_cover_path(cover_path_value, settings)
    ):
        stored_default = ensure_default_cover(settings)
        cover_path = media_streaming.stored_path(stored_default, settings)
        using_fallback = True
    if request.query_params.get("size") == "small" and cover_path is not None:
        response = media_streaming.small_cover_response(
            cover_path, request, user.id, settings
        )
        if response is not None:
            return _mark_cover_fallback(response) if using_fallback else response
        default_path = media_streaming.stored_path(
            ensure_default_cover(settings), settings
        )
        if default_path is not None and default_path != cover_path:
            response = media_streaming.small_cover_response(
                default_path, request, user.id, settings
            )
            if response is not None:
                return _mark_cover_fallback(response)
    response = media_streaming.send_file(
        cover_path,
        request,
        user.id,
        route="cover",
        asset_id=cover_id,
    )
    return _mark_cover_fallback(response) if using_fallback else response


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
    provider_configs = [
        (get_metadata_provider(db, provider_id) or {}).get("config", {})
        for provider_id in ("douban", "bangumi")
    ]
    allowed_origins = configured_cover_origins(
        config.get("baseUrl") for config in provider_configs if isinstance(config, dict)
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


@router.get("/resources/{resource_id}/pages", response_model=ResourcePagesResponse)
def list_resource_pages(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ResourcePagesResponse | Response,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_resource(db, user, resource_id):
        return fail("页面不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    projection = media_page_index.load_read_only(db, resource_id)
    db.close()
    index = media_page_index.resolve_read_only(projection)
    pages = [
        ResourcePage(
            id=unit.id,
            resourceId=unit.resource_id,
            assetId=unit.asset_id,
            unitType=unit.unit_type,
            title=unit.title,
            href=unit.href,
            mediaType=unit.media_type,
            sortOrder=unit.sort_order,
            width=unit.width,
            height=unit.height,
            size=unit.size,
            metadataJson=unit.metadata_json,
            createdAt=unit.created_at,
            updatedAt=unit.updated_at,
        )
        for unit in index.pages
    ]
    return ResourcePagesResponse(
        data=ResourcePagesPayload(pages=pages, total=len(pages))
    )


@router.get(
    "/resources/{resource_id}/pages/{page_index}",
    response_class=MediaImageResponse,
    responses=PARTIAL_CONTENT_RESPONSE,
)
def get_resource_page(
    resource_id: str,
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
    if not can_access_resource(db, user, resource_id):
        return fail("页面不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    actor_id = user.id
    projection = media_page_index.load_read_only(db, resource_id)
    db.close()
    index = media_page_index.resolve_read_only(projection)
    unit = index.page(page_index)
    if unit is None:
        return fail("页面不存在", status_code=404)
    source = index.source_for(unit.asset_id)
    if source and source.role == "PRIMARY":
        metadata = _parse_json(unit.metadata_json, {})
        entry_name = metadata.get("zipEntryName") or unit.href
        return media_streaming.send_comic_page_zip_entry(
            media_streaming.stored_path(
                source.path, settings, (Path(source.source_root),)
            ),
            entry_name,
            request,
            actor_id,
            settings,
            unit.media_type,
            route="resource-page-archive-entry",
            asset_id=unit.id or f"{resource_id}:{page_index}",
        )
    return media_streaming.send_comic_page_file(
        media_streaming.stored_path(
            unit.href if source is not None else None,
            settings,
            (Path(source.source_root),) if source is not None else (),
        ),
        request,
        actor_id,
        settings,
        media_type=unit.media_type,
        route="resource-page",
        asset_id=unit.id or f"{resource_id}:{page_index}",
    )
