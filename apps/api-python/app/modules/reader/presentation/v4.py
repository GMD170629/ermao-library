"""Resource-first Reader v4 HTTP surface."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal, Never, cast, overload

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.api.typed_route import TypedContractRoute
from app.bootstrap.media import media_page_index, media_streaming
from app.bootstrap.publications import (
    ensure_publication_navigation,
)
from app.bootstrap.reader import reader_resource_service
from app.contracts.http_errors import ErrorResponses
from app.core.auth import get_current_user
from app.core.authorization import authorization_context, can_access_resource
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.publications.public import (
    PublicationAccessScope,
    PublicationCorruptError,
    PublicationNavigationSourceChangedError,
    PublicationNotFoundError,
    PublicationUnsupportedError,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderAudioExactLocationDto,
    ReaderBookmarkDto,
    ReaderBootstrapDto,
    ReaderComicExactLocationDto,
    ReaderEngineLocatorDto,
    ReaderExactLocationDto,
    ReaderPdfExactLocationDto,
    ReaderProgressDto,
    ReaderReflowableExactLocationDto,
    ReaderResourceDto,
)
from app.modules.reader.application.resource_reader import (
    ReaderLocationFormatMismatch,
    ReaderLocatorMediaTypeMismatch,
    ReaderLocatorResourceMismatch,
    ReaderProgressBaseRevisionInvalid,
    ReaderProgressRevisionConflict,
    ReaderResourceFormatUnsupported,
    ReaderResourceNotFound,
    ReplaceBookmarksCommand,
    ResourceReaderService,
    SaveProgressCommand,
    SetResourceReadingStatusCommand,
)
from app.modules.reader.domain.resource_format import (
    ReaderType,
    capabilities_for_reader_type,
    reader_type_for_format,
)
from app.modules.reader.presentation.v4_schemas import (
    AudioExactLocation,
    ComicExactLocation,
    ExactReaderLocation,
    OpaqueReadiumEngineLocator,
    PdfExactLocation,
    ReaderAssetSummary,
    ReaderBookmark,
    ReaderBookmarksData,
    ReaderBookmarksReplaceRequest,
    ReaderBookmarksResponse,
    ReaderBookSummary,
    ReaderBootstrapData,
    ReaderBootstrapResponse,
    ReaderCapabilities,
    ReaderComicArchiveResponse,
    ReaderComicDownloadArtifact,
    ReaderComicManifestData,
    ReaderComicManifestPage,
    ReaderComicManifestResponse,
    ReaderComicPageResponse,
    ReaderConflictError,
    ReaderErrorBody,
    ReaderJsonValue,
    ReaderLocation,
    ReaderNavigationUnitSummary,
    ReaderNotFoundError,
    ReaderProgressConflictBody,
    ReaderProgressConflictError,
    ReaderProgressPut,
    ReaderProgressResponse,
    ReaderProgressSnapshot,
    ReaderProgressStateData,
    ReaderProgressStateResponse,
    ReaderPublicationAccess,
    ReaderReadingStatusData,
    ReaderReadingStatusPut,
    ReaderReadingStatusResponse,
    ReaderResourceSummary,
    ReaderSourceFormat,
    ReaderUnauthorizedError,
    ReaderValidationError,
    ReadiumEngineLocator,
    ReadiumLocatorPayload,
    ReflowableExactLocation,
)

router = APIRouter(
    prefix="/reader/v4",
    tags=["reader-v4"],
    route_class=TypedContractRoute,
)

_LOCATION_ADAPTER: TypeAdapter[ReaderLocation] = TypeAdapter(ReaderLocation)
_METADATA_ADAPTER = TypeAdapter(dict[str, ReaderJsonValue])
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
_PUBLICATION_SERVER_FORMATS = frozenset({"epub", "mobi", "azw", "azw3", "prc", "txt"})
LOGGER = logging.getLogger(__name__)
_COMIC_SOURCE_FORMATS = frozenset({"cbz", "zip", "cbr", "rar"})
_COMIC_IMAGE_VARIANTS: list[Literal["original", "data-saver"]] = [
    "original",
    "data-saver",
]
_COMIC_ARCHIVE_MIME_TYPES = {
    "cbz": "application/vnd.comicbook+zip",
    "zip": "application/zip",
    "cbr": "application/vnd.comicbook-rar",
    "rar": "application/vnd.rar",
}


def _current_user(db: Session, request: Request, settings: Settings) -> User:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        raise ReaderUnauthorizedError(
            ReaderErrorBody(message="未登录", code="UNAUTHORIZED")
        )
    return user


def _service(db: Session, settings: Settings) -> ResourceReaderService:
    return reader_resource_service(db, settings)


def _not_found() -> ReaderNotFoundError:
    return ReaderNotFoundError(
        ReaderErrorBody(message="资源不存在", code="RESOURCE_NOT_FOUND")
    )


def _access_scope(db: Session, user: User) -> ReaderAccessScope:
    context = authorization_context(db, user)
    return ReaderAccessScope(
        is_admin=context.is_admin,
        can_view_manual_imports=context.can_view_manual_imports,
        library_ids=context.library_ids,
    )


def _publication_access_scope(scope: ReaderAccessScope) -> PublicationAccessScope:
    return PublicationAccessScope(
        is_admin=scope.is_admin,
        can_view_manual_imports=scope.can_view_manual_imports,
        library_ids=tuple(scope.library_ids),
    )


def _authorized_bootstrap(
    db: Session,
    request: Request,
    settings: Settings,
    resource_id: str,
) -> tuple[User, ReaderAccessScope, ReaderBootstrapDto]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    scope = _access_scope(db, user)
    try:
        bootstrap = _service(db, settings).load_bootstrap(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=scope,
        )
    except (ReaderResourceNotFound, ReaderResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return user, scope, bootstrap


def _comic_source(bootstrap: ReaderBootstrapDto) -> tuple[ReaderAssetDto, str]:
    context = bootstrap.context
    source_format = context.resource.format.strip().lower()
    if source_format not in _COMIC_SOURCE_FORMATS:
        raise ReaderValidationError(
            ReaderErrorBody(
                message="当前资源不是漫画 Publication",
                code="READER_LOCATION_FORMAT_MISMATCH",
            )
        )
    source = next(
        (
            item
            for item in bootstrap.assets
            if item.role.strip().upper() in {"COMIC", "CBZ", "ZIP", "CBR", "RAR"}
        ),
        None,
    )
    if source is None:
        raise _not_found()
    return source, source_format


def _runtime_session_factory(request: Request) -> sessionmaker[Session]:
    factory: object = request.app.state.session_factory
    if not isinstance(factory, sessionmaker):
        raise TypeError("application session factory is unavailable")
    return cast(sessionmaker[Session], factory)


def _reader_type(resource_format: str) -> ReaderType:
    reader_type = reader_type_for_format(resource_format)
    if reader_type is None:
        raise ReaderValidationError(
            ReaderErrorBody(
                message="资源格式不支持直接阅读",
                code="RESOURCE_FORMAT_UNSUPPORTED",
            )
        )
    return reader_type


def _location(raw_json: str | None) -> ReaderLocation | None:
    if not raw_json:
        return None
    try:
        return _LOCATION_ADAPTER.validate_json(raw_json)
    except ValidationError:
        return None


@overload
def _location_json(location: None) -> None: ...


@overload
def _location_json(location: ReaderLocation) -> str: ...


def _location_json(location: ReaderLocation | None) -> str | None:
    if location is None:
        return None
    payload = location.model_dump(by_alias=True, exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _engine_dto(
    value: ReadiumEngineLocator | OpaqueReadiumEngineLocator,
) -> ReaderEngineLocatorDto:
    return ReaderEngineLocatorDto(
        platform=value.platform,
        version=value.version,
        payload_json=json.dumps(
            value.payload.model_dump(by_alias=True, exclude_none=True)
            if isinstance(value.payload, ReadiumLocatorPayload)
            else value.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def _exact_location_dto(value: ExactReaderLocation) -> ReaderExactLocationDto:
    if isinstance(value, ReflowableExactLocation):
        payload = value.engine_locator.payload
        return ReaderReflowableExactLocationDto(
            resource_href=payload.href,
            media_type=payload.type,
            resource_progression=payload.locations.progression,
            total_progression=payload.locations.total_progression,
            engine_locator=_engine_dto(value.engine_locator),
        )
    if isinstance(value, PdfExactLocation):
        return ReaderPdfExactLocationDto(
            page_index=value.page_index,
            page_progression=value.page_progression,
            engine_locator=(
                _engine_dto(value.engine_locator)
                if value.engine_locator is not None
                else None
            ),
        )
    if isinstance(value, ComicExactLocation):
        return ReaderComicExactLocationDto(
            page_index=value.page_index,
            resource_href=value.resource_href,
            engine_locator=(
                _engine_dto(value.engine_locator)
                if value.engine_locator is not None
                else None
            ),
        )
    return ReaderAudioExactLocationDto(
        asset_id=value.asset_id,
        chapter_id=value.chapter_id,
        position_millis=value.position_millis,
        engine_locator=(
            _engine_dto(value.engine_locator)
            if value.engine_locator is not None
            else None
        ),
    )


def _opaque_engine_model(
    value: ReaderEngineLocatorDto | None,
) -> OpaqueReadiumEngineLocator | None:
    if value is None:
        return None
    payload = json.loads(value.payload_json)
    if not isinstance(payload, dict):
        raise TypeError("Stored Readium engine payload is not an object")
    return OpaqueReadiumEngineLocator(
        engine="readium",
        platform=value.platform,
        version=value.version,
        payload=payload,
    )


def _exact_location_model(value: ReaderExactLocationDto) -> ExactReaderLocation:
    if isinstance(value, ReaderReflowableExactLocationDto):
        return ReflowableExactLocation(
            kind="reflowable",
            engineLocator=ReadiumEngineLocator(
                engine="readium",
                platform=value.engine_locator.platform,
                version=value.engine_locator.version,
                payload=ReadiumLocatorPayload.model_validate_json(
                    value.engine_locator.payload_json
                ),
            ),
        )
    if isinstance(value, ReaderPdfExactLocationDto):
        return PdfExactLocation(
            kind="pdf",
            pageIndex=value.page_index,
            pageProgression=value.page_progression,
            engineLocator=_opaque_engine_model(value.engine_locator),
        )
    if isinstance(value, ReaderComicExactLocationDto):
        return ComicExactLocation(
            kind="comic",
            pageIndex=value.page_index,
            resourceHref=value.resource_href,
            engineLocator=_opaque_engine_model(value.engine_locator),
        )
    return AudioExactLocation(
        kind="audio",
        assetId=value.asset_id,
        chapterId=value.chapter_id,
        positionMillis=value.position_millis,
        engineLocator=_opaque_engine_model(value.engine_locator),
    )


def _metadata(raw_json: str) -> dict[str, ReaderJsonValue]:
    try:
        return _METADATA_ADAPTER.validate_python(json.loads(raw_json))
    except (TypeError, ValueError, ValidationError):
        return {}


def _epoch_millis(value: datetime) -> int:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return int(aware.timestamp() * 1000)


def _resource_summary(
    resource: ReaderResourceDto,
    progress: ReaderProgressDto | None,
) -> ReaderResourceSummary:
    reader_type = _reader_type(resource.format)
    return ReaderResourceSummary(
        id=resource.id,
        bookId=resource.book_id,
        sourceNodeId=resource.source_node_id,
        title=resource.title,
        resourceIndex=resource.resource_index,
        sortOrder=resource.sort_order,
        format=resource.format,
        mediaKind=resource.media_kind,
        readerType=reader_type.value,
        pageCount=resource.page_count,
        chapterCount=resource.chapter_count,
        durationMs=resource.duration_ms,
        trackCount=resource.track_count,
        progress=progress.percent if progress else 0,
        resourceCompleted=bool(progress and progress.percent >= 100),
        lastReadAt=progress.progressed_at if progress else None,
    )


def _progress_snapshot(
    progress: ReaderProgressDto,
) -> ReaderProgressSnapshot:
    if progress.exact_location is None or progress.revision < 1:
        raise ValueError("Exact Reader v4 progress requires a revisioned Locator")
    return ReaderProgressSnapshot(
        schemaVersion=4,
        revision=progress.revision,
        clientId=progress.client_id or "shuku-library",
        locator=_exact_location_model(progress.exact_location),
        displayPercent=progress.percent,
        receivedAtEpochMillis=_epoch_millis(progress.updated_at),
        capturedAtEpochMillis=_epoch_millis(progress.progressed_at),
    )


def _progress_etag(progress: ReaderProgressDto | None) -> str:
    return f'"reader-progress-{progress.revision if progress is not None else 0}"'


def _raise_service_error(error: Exception) -> Never:
    if isinstance(error, ReaderResourceNotFound):
        raise _not_found() from error
    if isinstance(error, ReaderResourceFormatUnsupported):
        raise ReaderValidationError(
            ReaderErrorBody(
                message="资源格式不支持直接阅读",
                code="RESOURCE_FORMAT_UNSUPPORTED",
            )
        ) from error
    if isinstance(error, ReaderLocationFormatMismatch):
        raise ReaderValidationError(
            ReaderErrorBody(
                message="阅读位置格式与资源格式不匹配",
                code="READER_LOCATION_FORMAT_MISMATCH",
                details={
                    "expectedKind": error.expected,
                    "receivedKind": error.received,
                },
            )
        ) from error
    if isinstance(error, ReaderLocatorMediaTypeMismatch):
        raise ReaderValidationError(
            ReaderErrorBody(
                message="Readium Locator 媒体类型与资源格式不匹配",
                code="READER_LOCATOR_MEDIA_TYPE_MISMATCH",
                details={
                    "expectedReaderType": error.expected,
                    "receivedMediaType": error.received,
                },
            )
        ) from error
    if isinstance(error, ReaderLocatorResourceMismatch):
        raise ReaderValidationError(
            ReaderErrorBody(
                message="Readium Locator 资源不属于当前 Publication",
                code="READER_LOCATOR_RESOURCE_INVALID",
                details={"href": error.href, "mediaType": error.media_type},
            )
        ) from error
    if isinstance(error, ReaderProgressBaseRevisionInvalid):
        raise ReaderValidationError(
            ReaderErrorBody(
                message="阅读进度基准版本无效",
                code="READER_PROGRESS_BASE_REVISION_INVALID",
            )
        ) from error
    raise error


@router.get(
    "/resources/{resource_id}/bootstrap",
    response_model=ReaderBootstrapResponse,
    response_model_by_alias=True,
)
def reader_bootstrap_v4(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderBootstrapResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    user_id = user.id
    reader_scope = _access_scope(db, user)
    publication_scope = _publication_access_scope(reader_scope)
    try:
        ensure_publication_navigation(
            _runtime_session_factory(request),
            settings,
        ).execute(resource_id=resource_id, access_scope=publication_scope)
    except (
        OSError,
        PublicationCorruptError,
        PublicationNotFoundError,
        PublicationNavigationSourceChangedError,
        PublicationUnsupportedError,
    ) as error:
        LOGGER.warning(
            "reader_navigation_generation outcome=unavailable resource_id=%s "
            "error_type=%s",
            resource_id,
            type(error).__name__,
        )
    try:
        bootstrap = _service(db, settings).load_bootstrap(
            user_id=user_id,
            resource_id=resource_id,
            access_scope=reader_scope,
        )
    except (ReaderResourceNotFound, ReaderResourceFormatUnsupported) as error:
        _raise_service_error(error)

    context = bootstrap.context
    reader_type = _reader_type(context.resource.format)
    progress = bootstrap.progress_by_resource_id.get(resource_id)
    capabilities = capabilities_for_reader_type(reader_type)
    normalized_format = context.resource.format.lower()
    publication_access = None
    if normalized_format in _PUBLICATION_SERVER_FORMATS:
        publication_access = ReaderPublicationAccess(
            kind="reflowable",
            manifestUrl=(
                f"/api/reader/v4/resources/{resource_id}/publication/manifest.json"
            ),
            positionsUrl=(
                f"/api/reader/v4/resources/{resource_id}/publication/positions.json"
            ),
        )
    elif normalized_format in _COMIC_SOURCE_FORMATS:
        comic_source, comic_source_format = _comic_source(bootstrap)
        publication_access = ReaderPublicationAccess(
            kind="comic",
            manifestUrl=f"/api/reader/v4/resources/{resource_id}/comic/manifest",
            pageUrlTemplate=(
                f"/api/reader/v4/resources/{resource_id}/comic/pages/{{pageIndex}}"
            ),
            imageVariants=_COMIC_IMAGE_VARIANTS,
            downloadArtifact=ReaderComicDownloadArtifact(
                url=f"/api/reader/v4/resources/{resource_id}/comic/archive",
                sourceFormat=cast(
                    Literal["cbz", "zip", "cbr", "rar"], comic_source_format
                ),
                mimeType=(
                    comic_source.mime_type
                    or _COMIC_ARCHIVE_MIME_TYPES[comic_source_format]
                ),
                sizeBytes=comic_source.size_bytes,
            ),
        )
    return ReaderBootstrapResponse(
        data=ReaderBootstrapData(
            schemaVersion=4,
            userId=user_id,
            readerType=reader_type.value,
            sourceFormat=cast(ReaderSourceFormat, normalized_format),
            book=ReaderBookSummary(
                id=context.book.id,
                title=context.book.title,
                author=context.book.author,
                coverUrl=f"/api/books/{context.book.id}/cover",
            ),
            resource=_resource_summary(context.resource, progress),
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
            resourceUrl=f"/api/resources/{resource_id}",
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
            publication=publication_access,
            progressSnapshot=(
                _progress_snapshot(progress)
                if progress is not None
                and progress.revision >= 1
                and bootstrap.resume_location_json is not None
                else None
            ),
        )
    )


@router.get(
    "/resources/{resource_id}/comic/manifest",
    response_model=ReaderComicManifestResponse,
    response_model_by_alias=True,
)
def get_comic_manifest_v4(
    resource_id: str,
    request: Request,
    response: Response,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderComicManifestResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderValidationError,
    ),
]:
    _user, _scope, bootstrap = _authorized_bootstrap(db, request, settings, resource_id)
    _source, source_format = _comic_source(bootstrap)
    index = media_page_index.resolve_read_only(
        media_page_index.load_read_only(db, resource_id)
    )
    etag = f'W/"comic-manifest-{resource_id}-{len(index.pages)}"'
    cache_headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "Vary": "Cookie",
    }
    if request.headers.get("if-none-match") == etag:
        return cast(
            ReaderComicManifestResponse,
            Response(status_code=304, headers=cache_headers),
        )
    if not index.pages:
        raise ReaderValidationError(
            ReaderErrorBody(
                message="漫画页索引尚未就绪",
                code="COMIC_MANIFEST_UNAVAILABLE",
            )
        )
    pages = [
        ReaderComicManifestPage(
            pageIndex=canonical_index,
            resourceHref=f"pages/{canonical_index}",
            title=page.title or None,
            mediaType=page.media_type or "application/octet-stream",
            width=page.width,
            height=page.height,
            sizeBytes=page.size,
        )
        for canonical_index, page in enumerate(index.pages)
    ]
    response.headers.update(cache_headers)
    return ReaderComicManifestResponse(
        data=ReaderComicManifestData(
            schemaVersion=1,
            kind="comic",
            resourceId=resource_id,
            sourceFormat=cast(Literal["cbz", "zip", "cbr", "rar"], source_format),
            pageCount=len(pages),
            readingOrder=pages,
        )
    )


@router.get(
    "/resources/{resource_id}/comic/pages/{page_index}",
    response_class=ReaderComicPageResponse,
)
def get_comic_page_v4(
    resource_id: str,
    page_index: int,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    image_variant: Annotated[
        Literal["original", "data-saver"],
        Query(alias="imageVariant"),
    ] = "original",
) -> Response:
    user, _scope, _bootstrap = _authorized_bootstrap(db, request, settings, resource_id)
    index = media_page_index.resolve_read_only(
        media_page_index.load_read_only(db, resource_id)
    )
    if page_index < 0 or page_index >= len(index.pages):
        raise ReaderNotFoundError(
            ReaderErrorBody(
                message="漫画页面不存在",
                code="COMIC_PAGE_OUT_OF_RANGE",
            )
        )
    page = index.pages[page_index]
    source = index.source_for(page.asset_id)
    if source is None or source.role != "PRIMARY":
        raise _not_found()
    _ = image_variant
    page_response = media_streaming.send_comic_page_zip_entry(
        media_streaming.stored_path(source.path, settings, database_backed=True),
        page.href,
        request,
        user.id,
        settings,
        page.media_type,
        route="reader-v4-comic-page",
        asset_id=page.id,
    )
    page_response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    page_response.headers["X-Comic-Page-Index"] = str(page_index)
    page_response.headers["X-Comic-Resource-Href"] = f"pages/{page_index}"
    return page_response


@router.get(
    "/resources/{resource_id}/comic/archive",
    response_class=ReaderComicArchiveResponse,
)
def download_comic_archive_v4(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Response:
    user, _scope, bootstrap = _authorized_bootstrap(db, request, settings, resource_id)
    source, source_format = _comic_source(bootstrap)
    indexed_source = media_page_index.resolve_read_only(
        media_page_index.load_read_only(db, resource_id)
    ).source_for(source.id)
    if indexed_source is None:
        raise _not_found()
    return media_streaming.send_file(
        media_streaming.stored_path(
            indexed_source.path,
            settings,
            database_backed=True,
        ),
        request,
        user.id,
        media_type=source.mime_type or _COMIC_ARCHIVE_MIME_TYPES[source_format],
        route="reader-v4-comic-archive",
        asset_id=source.id,
        as_attachment=True,
    )


@router.put(
    "/resources/{resource_id}/reading-status",
    response_model=ReaderReadingStatusResponse,
    response_model_by_alias=True,
)
def set_resource_reading_status_v4(
    resource_id: str,
    payload: ReaderReadingStatusPut,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderReadingStatusResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        progress = _service(db, settings).set_resource_reading_status(
            SetResourceReadingStatusCommand(
                user_id=user.id,
                resource_id=resource_id,
                access_scope=_access_scope(db, user),
                status=payload.status,
            )
        )
    except (ReaderResourceNotFound, ReaderResourceFormatUnsupported) as error:
        _raise_service_error(error)
    return ReaderReadingStatusResponse(
        data=ReaderReadingStatusData(
            resourceId=resource_id,
            status=payload.status,
            percent=progress.percent if progress is not None else 0,
        )
    )


@router.put(
    "/resources/{resource_id}/progress",
    response_model=ReaderProgressResponse,
    response_model_by_alias=True,
)
def save_progress_v4(
    resource_id: str,
    payload: ReaderProgressPut,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderProgressResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderConflictError,
        ReaderProgressConflictError,
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        progress = _service(db, settings).save_progress(
            SaveProgressCommand(
                user_id=user.id,
                resource_id=resource_id,
                access_scope=_access_scope(db, user),
                client_id=payload.client_id,
                mutation_id=str(payload.mutation_id),
                base_revision=payload.base_revision,
                location=_exact_location_dto(payload.locator),
                captured_at_epoch_millis=payload.captured_at_epoch_millis,
            )
        )
    except (
        ReaderResourceNotFound,
        ReaderResourceFormatUnsupported,
        ReaderLocationFormatMismatch,
        ReaderLocatorMediaTypeMismatch,
        ReaderLocatorResourceMismatch,
        ReaderProgressBaseRevisionInvalid,
    ) as error:
        _raise_service_error(error)
    except ReaderProgressRevisionConflict as error:
        raise ReaderProgressConflictError(
            ReaderProgressConflictBody(
                message="另一设备已更新阅读位置",
                current=_progress_snapshot(error.current),
            )
        ) from error
    return ReaderProgressResponse(data=_progress_snapshot(progress))


@router.get(
    "/resources/{resource_id}/progress",
    response_model=ReaderProgressStateResponse,
    response_model_by_alias=True,
)
def get_progress_v4(
    resource_id: str,
    request: Request,
    response: Response,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderProgressStateResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        progress = _service(db, settings).load_progress(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
    except (ReaderResourceNotFound, ReaderResourceFormatUnsupported) as error:
        _raise_service_error(error)
    etag = _progress_etag(progress)
    headers = {"Cache-Control": "private, no-cache", "ETag": etag, "Vary": "Cookie"}
    if request.headers.get("if-none-match") == etag:
        return cast(
            ReaderProgressStateResponse,
            Response(status_code=304, headers=headers),
        )
    for name, value in headers.items():
        response.headers[name] = value
    return ReaderProgressStateResponse(
        data=ReaderProgressStateData(
            schemaVersion=4,
            progressSnapshot=_progress_snapshot(progress)
            if progress is not None
            else None,
        )
    )


@router.get(
    "/resources/{resource_id}/bookmarks",
    response_model=ReaderBookmarksResponse,
    response_model_by_alias=True,
)
def list_bookmarks_v4(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderBookmarksResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderConflictError,
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    try:
        bookmarks = _service(db, settings).list_bookmarks(
            user_id=user.id,
            resource_id=resource_id,
            access_scope=_access_scope(db, user),
        )
    except ReaderResourceNotFound as error:
        _raise_service_error(error)
    return ReaderBookmarksResponse(
        data=ReaderBookmarksData(
            bookmarks=[
                ReaderBookmark(
                    id=bookmark.bookmark_id,
                    location=_LOCATION_ADAPTER.validate_json(bookmark.location_json),
                    label=bookmark.label,
                    percent=bookmark.percent,
                    createdAt=bookmark.bookmark_created_at,
                )
                for bookmark in bookmarks
            ]
        )
    )


@router.put(
    "/resources/{resource_id}/bookmarks",
    response_model=ReaderBookmarksResponse,
    response_model_by_alias=True,
)
def replace_bookmarks_v4(
    resource_id: str,
    payload: ReaderBookmarksReplaceRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[
    ReaderBookmarksResponse,
    ErrorResponses(
        ReaderUnauthorizedError,
        ReaderNotFoundError,
        ReaderConflictError,
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_resource(db, user, resource_id):
        raise _not_found()
    incoming = [
        ReaderBookmarkDto(
            id="",
            bookmark_id=bookmark.id,
            location_json=_location_json(bookmark.location),
            label=bookmark.label,
            percent=bookmark.percent,
            bookmark_created_at=bookmark.created_at,
        )
        for bookmark in payload.bookmarks
    ]
    try:
        bookmarks = _service(db, settings).replace_bookmarks(
            ReplaceBookmarksCommand(
                user_id=user.id,
                resource_id=resource_id,
                access_scope=_access_scope(db, user),
                bookmarks=tuple(incoming),
                location_kinds=tuple(
                    bookmark.location.kind for bookmark in payload.bookmarks
                ),
            )
        )
    except (
        ReaderResourceNotFound,
        ReaderResourceFormatUnsupported,
        ReaderLocationFormatMismatch,
    ) as error:
        _raise_service_error(error)
    return ReaderBookmarksResponse(
        data=ReaderBookmarksData(
            bookmarks=[
                ReaderBookmark(
                    id=bookmark.bookmark_id,
                    location=_LOCATION_ADAPTER.validate_json(bookmark.location_json),
                    label=bookmark.label,
                    percent=bookmark.percent,
                    createdAt=bookmark.bookmark_created_at,
                )
                for bookmark in bookmarks
            ]
        )
    )
