"""Resource-first Reader v5 HTTP surface.

Progress is a transport envelope around an opaque Readium Locator.  The route
does not inspect Locator members; all user-facing position/progress values come
from the client's required ``presentation`` projection.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, Never, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.media import media_page_index, media_resource_query, media_streaming
from app.contracts.http_errors import ErrorResponses
from app.contracts.publication_sources import PublicationAccessScope
from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_FORMATS,
    ReaderSafetyMorphology,
    ReaderSafetyRuleId,
    reader_safety_rule,
)
from app.core.auth import get_current_user
from app.core.authorization import authorization_context, can_access_resource
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.media.public import comic_manifest_policy_failure
from app.modules.publications.public import (
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationReadError,
    PublicationResourceNotFoundError,
    PublicationResourceTooLargeError,
    PublicationUnsupportedError,
)
from app.modules.reader.application.dto import ReaderAccessScope, ReaderResourceDto
from app.modules.reader.application.resource_reader_v5 import (
    ReaderV5CapturedAtInvalid,
    ReaderV5MutationReuse,
    ReaderV5ResourceFormatUnsupported,
    ReaderV5ResourceNotFound,
    ReplaceBookmarksV5Command,
    ResourceReaderV5Service,
    SaveProgressV5Command,
    SetReadingStatusV5Command,
)
from app.modules.reader.application.v5_dto import (
    ReaderV5BookmarkDto,
    ReaderV5BookmarkInputDto,
    ReaderV5BootstrapDto,
    ReaderV5ChapterDto,
    ReaderV5PageDto,
    ReaderV5PlaybackDto,
    ReaderV5PositionDto,
    ReaderV5PresentationDto,
    ReaderV5ProgressDto,
)
from app.modules.reader.application.v5_locator import OpaqueLocator
from app.modules.reader.application.v5_position import presentation_json
from app.modules.reader.domain.resource_format import (
    capabilities_for_reader_type,
    reader_type_for_format,
)
from app.modules.reader.presentation.common_schemas import (
    ReaderAssetSummary,
    ReaderBookSummary,
    ReaderCapabilities,
    ReaderComicManifestData,
    ReaderComicManifestPage,
    ReaderComicManifestResponse,
    ReaderComicPageResponse,
    ReaderJsonValue,
    ReaderNavigationUnitSummary,
    ReaderPublicationAccess,
    ReaderReadingStatusData,
    ReaderReadingStatusPut,
    ReaderReadingStatusResponse,
    ReaderResourceSummary,
    ReaderSourceFormat,
)
from app.modules.reader.presentation.v5_schemas import (
    ReaderV5Bookmark,
    ReaderV5BookmarksData,
    ReaderV5BookmarksReplaceRequest,
    ReaderV5BookmarksResponse,
    ReaderV5BootstrapData,
    ReaderV5BootstrapResponse,
    ReaderV5Chapter,
    ReaderV5ErrorBody,
    ReaderV5MutationReuseBody,
    ReaderV5MutationReuseError,
    ReaderV5NotFoundError,
    ReaderV5Page,
    ReaderV5Playback,
    ReaderV5Position,
    ReaderV5ProgressPut,
    ReaderV5ProgressSnapshot,
    ReaderV5ProgressStateData,
    ReaderV5ProgressStateResponse,
    ReaderV5ProgressWriteData,
    ReaderV5ProgressWriteResponse,
    ReaderV5PublicationResourceResponse,
    ReaderV5UnauthorizedError,
    ReaderV5ValidationError,
)
from app.schemas.responses import fail

router = APIRouter(
    prefix="/reader/v5",
    tags=["reader-v5"],
    route_class=TypedContractRoute,
)

DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
_COMIC_SOURCE_FORMATS = frozenset(
    policy.id.value.lower()
    for policy in READER_SAFETY_FORMATS.values()
    if policy.morphology is ReaderSafetyMorphology.COMIC
)
_COMIC_IMAGE_VARIANTS: list[Literal["original", "data-saver"]] = [
    "original",
    "data-saver",
]
_METADATA_ADAPTER: TypeAdapter[dict[str, ReaderJsonValue]] = TypeAdapter(
    dict[str, ReaderJsonValue]
)


def _current_user(db: Session, request: Request, settings: Settings) -> User:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        raise ReaderV5UnauthorizedError(
            ReaderV5ErrorBody(message="未登录", code="UNAUTHORIZED")
        )
    return user


def _access_scope(db: Session, user: User) -> ReaderAccessScope:
    context = authorization_context(db, user)
    return ReaderAccessScope(
        is_admin=context.is_admin,
        can_view_manual_imports=context.can_view_manual_imports,
        library_ids=context.library_ids,
    )


def _publication_scope(scope: ReaderAccessScope) -> PublicationAccessScope:
    return PublicationAccessScope(
        is_admin=scope.is_admin,
        can_view_manual_imports=scope.can_view_manual_imports,
        library_ids=scope.library_ids,
    )


def _not_found() -> ReaderV5NotFoundError:
    return ReaderV5NotFoundError(
        ReaderV5ErrorBody(message="资源不存在", code="RESOURCE_NOT_FOUND")
    )


def _service(
    request: Request, db: Session, settings: Settings
) -> ResourceReaderV5Service:
    """Resolve the v5 application service from the process composition root."""

    factory = getattr(request.app.state, "reader_v5_service_factory", None)
    if not callable(factory):
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="Reader 服务尚未就绪", code="READER_SERVICE_UNAVAILABLE"
            )
        )
    return cast(Callable[[Session, Settings], ResourceReaderV5Service], factory)(
        db, settings
    )


def _authorized_bootstrap(
    db: Session,
    request: Request,
    settings: Settings,
    resource_id: str,
) -> tuple[User, ReaderAccessScope, ReaderV5BootstrapDto]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    scope = _access_scope(db, user)
    try:
        bootstrap = _service(request, db, settings).load_bootstrap(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=scope,
        )
    except (ReaderV5ResourceNotFound, ReaderV5ResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return user, scope, bootstrap


def _resource_summary(
    resource: ReaderResourceDto, progress: ReaderV5ProgressDto | None
) -> ReaderResourceSummary:
    reader_type = reader_type_for_format(resource.source_format)
    if reader_type is None:
        raise ReaderV5ResourceFormatUnsupported
    display_percent = progress.position.presentation.display_percent if progress else 0
    return ReaderResourceSummary(
        id=resource.id,
        bookId=resource.book_id,
        sourceNodeId=resource.source_node_id,
        title=resource.title,
        resourceIndex=resource.resource_index,
        sortOrder=resource.sort_order,
        format=resource.source_format,
        readerType=reader_type.value,
        pageCount=resource.page_count,
        chapterCount=resource.chapter_count,
        durationMs=resource.duration_ms,
        trackCount=resource.track_count,
        progress=display_percent,
        resourceCompleted=display_percent >= 100,
        lastReadAt=progress.captured_at if progress else None,
    )


def _presentation_payload(progress: ReaderV5ProgressDto) -> dict[str, object]:
    return presentation_json(progress.position.presentation)


def _position_model(progress: ReaderV5ProgressDto) -> ReaderV5Position:
    locator = json.loads(progress.position.locator.serialized)
    return ReaderV5Position.model_validate(
        {"locator": locator, "presentation": _presentation_payload(progress)}
    )


def _bookmark_model(bookmark: ReaderV5BookmarkDto) -> ReaderV5Bookmark:
    locator = json.loads(bookmark.position.locator.serialized)
    return ReaderV5Bookmark(
        id=bookmark.bookmark_id,
        position=ReaderV5Position.model_validate(
            {
                "locator": locator,
                "presentation": presentation_json(bookmark.position.presentation),
            }
        ),
        label=bookmark.label,
        createdAt=bookmark.created_at,
    )


def _snapshot(progress: ReaderV5ProgressDto) -> ReaderV5ProgressSnapshot:
    return ReaderV5ProgressSnapshot(
        schemaVersion=5,
        revision=progress.revision,
        clientId=progress.client_id,
        mutationId=UUID(progress.mutation_id),
        capturedAtEpochMillis=_epoch_millis(progress.captured_at),
        receivedAtEpochMillis=_epoch_millis(progress.received_at),
        position=_position_model(progress),
    )


def _epoch_millis(value: datetime) -> int:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return int(aware.timestamp() * 1000)


def _progress_etag(progress: ReaderV5ProgressDto | None) -> str:
    return f'"reader-v5-progress-{progress.revision if progress else 0}"'


def _chapter_dto(value: ReaderV5Chapter | None) -> ReaderV5ChapterDto | None:
    if value is None:
        return None
    return ReaderV5ChapterDto(
        href=value.href,
        title=value.title,
        index=value.index,
    )


def _page_dto(value: ReaderV5Page | None) -> ReaderV5PageDto | None:
    if value is None:
        return None
    return ReaderV5PageDto(number=value.number, total=value.total)


def _playback_dto(value: ReaderV5Playback | None) -> ReaderV5PlaybackDto | None:
    if value is None:
        return None
    return ReaderV5PlaybackDto(
        position_millis=value.position_millis,
        duration_millis=value.duration_millis,
    )


def _position_dto(position: ReaderV5Position) -> ReaderV5PositionDto:
    presentation = position.presentation
    return ReaderV5PositionDto(
        locator=OpaqueLocator.from_object(position.locator),
        presentation=ReaderV5PresentationDto(
            display_percent=presentation.display_percent,
            total_progression=presentation.total_progression,
            current_href=presentation.current_href,
            chapter=_chapter_dto(presentation.chapter),
            page=_page_dto(presentation.page),
            playback=_playback_dto(presentation.playback),
        ),
    )


def _raise_service_error(error: Exception) -> Never:
    if isinstance(error, ReaderV5ResourceNotFound):
        raise _not_found() from error
    if isinstance(error, ReaderV5ResourceFormatUnsupported):
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="资源格式不支持直接阅读", code="RESOURCE_FORMAT_UNSUPPORTED"
            )
        ) from error
    if isinstance(error, ReaderV5CapturedAtInvalid):
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="capturedAtEpochMillis 超出服务端可表示范围",
                code="READER_PROGRESS_TIMESTAMP_INVALID",
            )
        ) from error
    raise error


def _raise_publication_error(error: Exception) -> Never:
    if isinstance(error, PublicationNotFoundError):
        raise _not_found() from error
    if isinstance(error, PublicationResourceNotFoundError):
        raise ReaderV5NotFoundError(
            ReaderV5ErrorBody(message="出版物资源不存在", code=error.code)
        ) from error
    if isinstance(
        error,
        (
            PublicationCorruptError,
            PublicationReadError,
            PublicationResourceTooLargeError,
            PublicationUnsupportedError,
        ),
    ):
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="出版物资源不可用",
                code=getattr(error, "code", "PUBLICATION_READ_FAILED"),
            )
        ) from error
    raise error


@router.get(
    "/resources/{resource_id}/bootstrap",
    response_model=ReaderV5BootstrapResponse,
    response_model_by_alias=True,
)
def reader_bootstrap_v5(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderV5BootstrapResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    user, _scope, bootstrap = _authorized_bootstrap(db, request, settings, resource_id)
    context = bootstrap.context
    reader_type = reader_type_for_format(context.resource.format)
    if reader_type is None:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="资源格式不支持直接阅读", code="RESOURCE_FORMAT_UNSUPPORTED"
            )
        )
    normalized_format = context.resource.source_format.strip().lower()
    publication = None
    if normalized_format in _COMIC_SOURCE_FORMATS:
        publication = ReaderPublicationAccess(
            kind="comic",
            manifestUrl=f"/api/reader/v5/resources/{resource_id}/comic/manifest",
            pageUrlTemplate=(
                f"/api/reader/v5/resources/{resource_id}/comic/pages/{{pageIndex}}"
            ),
            imageVariants=_COMIC_IMAGE_VARIANTS,
        )
    capabilities = capabilities_for_reader_type(reader_type)
    return ReaderV5BootstrapResponse(
        ok=True,
        data=ReaderV5BootstrapData(
            schemaVersion=5,
            userId=user.id,
            readerType=reader_type.value,
            sourceFormat=cast(ReaderSourceFormat, normalized_format),
            book=ReaderBookSummary(
                id=context.book.id,
                title=context.book.title,
                author=context.book.author,
                coverUrl=f"/api/books/{context.book.id}/cover",
            ),
            resource=_resource_summary(context.resource, bootstrap.progress),
            availableResources=[
                _resource_summary(
                    resource,
                    bootstrap.progress_by_resource_id.get(resource.id),
                )
                for resource in bootstrap.available_resources
            ],
            assets=[
                ReaderAssetSummary(
                    id=asset.id,
                    title=asset.title,
                    resourceId=asset.resource_id,
                    sourceNodeId=asset.source_node_id,
                    role=asset.role,
                    mimeType=asset.mime_type,
                    sizeBytes=asset.size_bytes,
                    durationMs=asset.duration_ms,
                    discNumber=asset.disc_number,
                    trackNumber=asset.track_number,
                    sortOrder=asset.sort_order,
                    url=f"/api/assets/{asset.id}",
                    codec=asset.codec,
                )
                for asset in bootstrap.assets
            ],
            units=[
                ReaderNavigationUnitSummary(
                    id=unit.id,
                    index=unit.sort_order,
                    title=unit.title,
                    href=unit.href,
                    assetId=unit.asset_id,
                    startMs=unit.start_ms,
                    endMs=unit.end_ms,
                    durationMs=unit.duration_ms,
                    metadata=_metadata(unit.metadata_json),
                )
                for unit in bootstrap.units
            ],
            resourceUrl=f"/api/reader/v5/resources/{resource_id}/publication",
            capabilities=ReaderCapabilities(
                canGoNext=capabilities.can_go_next,
                canGoPrevious=capabilities.can_go_previous,
                canJumpToProgress=capabilities.can_jump_to_progress,
                canJumpToHref=capabilities.can_jump_to_href,
                canJumpToIndex=capabilities.can_jump_to_index,
                canZoom=capabilities.can_zoom,
                canSelectText=capabilities.can_select_text,
                supportsPagination=capabilities.supports_pagination,
                supportsScrolling=capabilities.supports_scrolling,
                supportsSpreads=capabilities.supports_spreads,
            ),
            publication=publication,
            progressSnapshot=(
                _snapshot(bootstrap.progress)
                if bootstrap.progress is not None
                else None
            ),
        ),
    )


def _metadata(raw_json: str) -> dict[str, ReaderJsonValue]:
    try:
        return _METADATA_ADAPTER.validate_python(json.loads(raw_json))
    except (TypeError, ValueError):
        return {}


@router.put(
    "/resources/{resource_id}/progress",
    response_model=ReaderV5ProgressWriteResponse,
    response_model_by_alias=True,
)
def save_progress_v5(
    resource_id: str,
    payload: ReaderV5ProgressPut,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderV5ProgressWriteResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5MutationReuseError,
        ReaderV5ValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        result = _service(request, db, settings).save_progress(
            SaveProgressV5Command(
                user_id=user.id,
                resource_id=resource_id,
                access_scope=_access_scope(db, user),
                client_id=payload.client_id,
                mutation_id=str(payload.mutation_id),
                captured_at_epoch_millis=payload.captured_at_epoch_millis,
                position=_position_dto(payload.position),
            )
        )
    except (
        ReaderV5ResourceNotFound,
        ReaderV5ResourceFormatUnsupported,
        ReaderV5CapturedAtInvalid,
    ) as error:
        _raise_service_error(error)
    except ReaderV5MutationReuse as error:
        raise ReaderV5MutationReuseError(
            ReaderV5MutationReuseBody(
                message="mutationId 已被不同 payload 使用",
                code="READER_PROGRESS_MUTATION_REUSE",
            )
        ) from error
    return ReaderV5ProgressWriteResponse(
        ok=True,
        data=ReaderV5ProgressWriteData(
            acceptedMutationId=payload.mutation_id,
            acceptedRevision=result.accepted_revision,
            currentSnapshot=_snapshot(result.current_progress),
        ),
    )


@router.get(
    "/resources/{resource_id}/publication",
    response_class=ReaderV5PublicationResourceResponse,
)
def get_publication_root_v5(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Response:
    """Serve the resource's primary publication through the v5 namespace."""

    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    asset = media_resource_query(db).first_resource_asset(resource_id)
    if asset is None:
        raise _not_found()
    return media_streaming.send_file(
        media_streaming.stored_path(
            asset.path,
            settings,
            (Path(asset.source_root),),
        ),
        request,
        user.id,
        media_type=asset.mime_type,
        name=Path(asset.path).name,
        route="reader-v5-publication",
        asset_id=asset.id,
        as_attachment=False,
    )


@router.get(
    "/resources/{resource_id}/publication/{path:path}",
    response_class=ReaderV5PublicationResourceResponse,
)
def get_publication_resource_v5(
    resource_id: str,
    path: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Response:
    """Serve a publication resource through the shared safe adapter.

    This endpoint is intentionally not advertised as a progress/Locator
    source.  It exists for clients that need a resource URL and stays within
    the active Reader protocol namespace.
    """

    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    scope = _access_scope(db, user)
    runtime = getattr(request.app.state, "publication_navigation_runtime", None)
    if runtime is None:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="出版物服务尚未就绪", code="PUBLICATION_SERVICE_UNAVAILABLE"
            )
        )
    try:
        publication = runtime.read_resource(
            session=db,
            resource_id=resource_id,
            access_scope=_publication_scope(scope),
            href=path,
        )
    except (
        PublicationNotFoundError,
        PublicationResourceNotFoundError,
        PublicationCorruptError,
        PublicationReadError,
        PublicationResourceTooLargeError,
        PublicationUnsupportedError,
    ) as error:
        _raise_publication_error(error)
    etag = f'"reader-v5-publication-{sha256(publication.content).hexdigest()}"'
    headers = {
        "Cache-Control": "private, no-store",
        "ETag": etag,
        "Vary": "Cookie",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(
        content=publication.content,
        media_type=publication.media_type,
        headers=headers,
    )


@router.get(
    "/resources/{resource_id}/progress",
    response_model=ReaderV5ProgressStateResponse,
    response_model_by_alias=True,
)
def get_progress_v5(
    resource_id: str,
    request: Request,
    response: Response,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderV5ProgressStateResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        progress = _service(request, db, settings).load_progress(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
    except (ReaderV5ResourceNotFound, ReaderV5ResourceFormatUnsupported) as error:
        _raise_service_error(error)
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": _progress_etag(progress),
        "Vary": "Cookie",
    }
    if request.headers.get("if-none-match") == headers["ETag"]:
        return cast(
            ReaderV5ProgressStateResponse,
            Response(status_code=304, headers=headers),
        )
    response.headers.update(headers)
    return ReaderV5ProgressStateResponse(
        ok=True,
        data=ReaderV5ProgressStateData(
            schemaVersion=5,
            progressSnapshot=_snapshot(progress) if progress is not None else None,
        ),
    )


@router.get(
    "/resources/{resource_id}/bookmarks",
    response_model=ReaderV5BookmarksResponse,
    response_model_by_alias=True,
)
def list_bookmarks_v5(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderV5BookmarksResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        bookmarks = _service(request, db, settings).load_bookmarks(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
    except (ReaderV5ResourceNotFound, ReaderV5ResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return ReaderV5BookmarksResponse(
        ok=True,
        data=ReaderV5BookmarksData(
            bookmarks=[_bookmark_model(bookmark) for bookmark in bookmarks]
        ),
    )


@router.put(
    "/resources/{resource_id}/bookmarks",
    response_model=ReaderV5BookmarksResponse,
    response_model_by_alias=True,
)
def replace_bookmarks_v5(
    resource_id: str,
    payload: ReaderV5BookmarksReplaceRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderV5BookmarksResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        bookmarks = _service(request, db, settings).replace_bookmarks(
            ReplaceBookmarksV5Command(
                user_id=user.id,
                resource_id=resource_id,
                access_scope=_access_scope(db, user),
                bookmarks=tuple(
                    ReaderV5BookmarkInputDto(
                        bookmark_id=bookmark.id,
                        position=_position_dto(bookmark.position),
                        label=bookmark.label,
                        created_at=bookmark.created_at,
                    )
                    for bookmark in payload.bookmarks
                ),
            )
        )
    except (ReaderV5ResourceNotFound, ReaderV5ResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return ReaderV5BookmarksResponse(
        ok=True,
        data=ReaderV5BookmarksData(
            bookmarks=[_bookmark_model(bookmark) for bookmark in bookmarks]
        ),
    )


@router.put(
    "/resources/{resource_id}/reading-status",
    response_model=ReaderReadingStatusResponse,
    response_model_by_alias=True,
)
def set_reading_status_v5(
    resource_id: str,
    payload: ReaderReadingStatusPut,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderReadingStatusResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        service = _service(request, db, settings)
        service.set_reading_status(
            SetReadingStatusV5Command(
                user_id=user.id,
                resource_id=resource_id,
                access_scope=_access_scope(db, user),
                status=payload.status,
            )
        )
        progress = service.load_progress(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
    except (ReaderV5ResourceNotFound, ReaderV5ResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return ReaderReadingStatusResponse(
        data=ReaderReadingStatusData(
            resourceId=resource_id,
            status=payload.status,
            percent=(progress.position.presentation.display_percent if progress else 0),
        )
    )


@router.get(
    "/resources/{resource_id}/reading-status",
    response_model=ReaderReadingStatusResponse,
    response_model_by_alias=True,
)
def get_reading_status_v5(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderReadingStatusResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    """Read independent v5 status without creating or deriving a Locator."""

    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    service = _service(request, db, settings)
    try:
        status = service.get_reading_status(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
        progress = service.load_progress(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
    except (ReaderV5ResourceNotFound, ReaderV5ResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return ReaderReadingStatusResponse(
        data=ReaderReadingStatusData(
            resourceId=resource_id,
            status=status.status if status is not None else "UNREAD",
            percent=(progress.position.presentation.display_percent if progress else 0),
        )
    )


@router.get(
    "/resources/{resource_id}/comic/manifest",
    response_model=ReaderComicManifestResponse,
    response_model_by_alias=True,
)
def get_comic_manifest_v5(
    resource_id: str,
    request: Request,
    response: Response,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderComicManifestResponse,
    ErrorResponses(
        ReaderV5UnauthorizedError,
        ReaderV5NotFoundError,
        ReaderV5ValidationError,
    ),
]:
    _user, _scope, bootstrap = _authorized_bootstrap(db, request, settings, resource_id)
    source_format = bootstrap.context.resource.source_format.strip().lower()
    if source_format not in _COMIC_SOURCE_FORMATS:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="当前资源不是漫画 Publication",
                code="READER_LOCATION_FORMAT_MISMATCH",
            )
        )
    index = media_page_index.resolve_read_only(
        media_page_index.load_read_only(db, resource_id)
    )
    policy_failure = comic_manifest_policy_failure(page_count=len(index.pages))
    if policy_failure is not None:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="漫画清单超过安全策略限制",
                code=policy_failure.error_code,
            )
        )
    etag = f'"comic-manifest-{index.revision.removeprefix("sha256:")}"'
    headers = {"Cache-Control": "private, no-cache", "ETag": etag, "Vary": "Cookie"}
    if request.headers.get("if-none-match") == etag:
        return cast(
            ReaderComicManifestResponse, Response(status_code=304, headers=headers)
        )
    if not index.pages:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="漫画页索引尚未就绪", code="COMIC_MANIFEST_UNAVAILABLE"
            )
        )
    pages = [
        ReaderComicManifestPage(
            pageIndex=page_index,
            resourceHref=f"pages/{page_index}",
            title=page.title or None,
            mediaType=page.media_type or "application/octet-stream",
            width=page.width,
            height=page.height,
            sizeBytes=page.size,
        )
        for page_index, page in enumerate(index.pages)
    ]
    response.headers.update(headers)
    result = ReaderComicManifestResponse(
        data=ReaderComicManifestData(
            schemaVersion=2,
            kind="comic",
            resourceId=resource_id,
            revision=index.revision,
            sourceFormat=cast(
                Literal["cbz", "zip", "cbr", "rar", "image_dir"], source_format
            ),
            pageCount=len(pages),
            readingOrder=pages,
        )
    )
    policy_failure = comic_manifest_policy_failure(
        page_count=len(index.pages),
        serialized_size_bytes=len(result.model_dump_json(by_alias=True).encode()),
    )
    if policy_failure is not None:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="漫画清单超过安全策略限制", code=policy_failure.error_code
            )
        )
    return result


@router.get(
    "/resources/{resource_id}/comic/pages/{page_index}",
    response_class=ReaderComicPageResponse,
)
def get_comic_page_v5(
    resource_id: str,
    page_index: int,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    image_variant: Annotated[
        Literal["original", "data-saver"], Query(alias="imageVariant")
    ] = "original",
    revision: str | None = None,
) -> Response:
    user, _scope, bootstrap = _authorized_bootstrap(db, request, settings, resource_id)
    source_format = bootstrap.context.resource.source_format.strip().lower()
    if source_format not in _COMIC_SOURCE_FORMATS:
        raise ReaderV5ValidationError(
            ReaderV5ErrorBody(
                message="当前资源不是漫画 Publication",
                code="READER_LOCATION_FORMAT_MISMATCH",
            )
        )
    index = media_page_index.resolve_read_only(
        media_page_index.load_read_only(db, resource_id)
    )
    if revision != index.revision:
        rule = reader_safety_rule(ReaderSafetyRuleId.COMIC_MANIFEST_REVISION)
        return fail(
            "Comic resource changed",
            status_code=412,
            code=rule.error_code.value if rule.error_code is not None else None,
            params={"ruleId": rule.id.value},
        )
    if page_index < 0 or page_index >= len(index.pages):
        raise ReaderV5NotFoundError(
            ReaderV5ErrorBody(message="漫画页面不存在", code="COMIC_PAGE_OUT_OF_RANGE")
        )
    page = index.pages[page_index]
    source = index.source_for(page.asset_id)
    if source is None or source.role not in {"PRIMARY", "PAGE"}:
        raise _not_found()
    _ = image_variant
    if source.role == "PRIMARY":
        page_response = media_streaming.send_comic_page_zip_entry(
            media_streaming.stored_path(
                source.path, settings, (Path(source.source_root),)
            ),
            page.href,
            request,
            user.id,
            settings,
            page.media_type,
            route="reader-v5-comic-page",
            asset_id=page.id,
        )
    else:
        page_response = media_streaming.send_comic_page_file(
            media_streaming.stored_path(
                page.href, settings, (Path(source.source_root),)
            ),
            request,
            user.id,
            settings,
            media_type=page.media_type,
            route="reader-v5-comic-page",
            asset_id=page.id,
        )
    page_response.headers["Cache-Control"] = "private, no-store"
    page_response.headers["X-Comic-Page-Index"] = str(page_index)
    page_response.headers["X-Comic-Resource-Href"] = f"pages/{page_index}"
    page_response.headers["X-Comic-Revision"] = index.revision
    return page_response


__all__ = ["router"]
