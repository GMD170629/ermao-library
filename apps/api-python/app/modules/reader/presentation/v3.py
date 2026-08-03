"""Volume-first Reader v3 HTTP surface."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Never, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.reader import reader_volume_service
from app.contracts.http_errors import ErrorResponses
from app.core.auth import get_current_user
from app.core.authorization import authorization_context, can_access_volume
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderProgressDto,
    ReaderVolumeDto,
)
from app.modules.reader.application.volume_reader import (
    ReaderFingerprintMismatch,
    ReaderVolumeFormatUnsupported,
    ReaderVolumeNotFound,
    SaveProgressCommand,
    VolumeReaderService,
)
from app.modules.reader.domain.volume_format import (
    ReaderType,
    capabilities_for_reader_type,
    reader_type_for_volume_format,
)
from app.modules.reader.presentation.v3_schemas import (
    ReaderBookmark,
    ReaderBookmarksData,
    ReaderBookmarksReplaceRequest,
    ReaderBookmarksResponse,
    ReaderBookSummary,
    ReaderBootstrapData,
    ReaderBootstrapResponse,
    ReaderCapabilities,
    ReaderConflictError,
    ReaderErrorBody,
    ReaderFileSummary,
    ReaderJsonValue,
    ReaderLocation,
    ReaderMediaVersionSummary,
    ReaderNotFoundError,
    ReaderProgressData,
    ReaderProgressPut,
    ReaderProgressRecord,
    ReaderProgressResponse,
    ReaderUnauthorizedError,
    ReaderUnitSummary,
    ReaderValidationError,
    ReaderVolumeSummary,
    ReflowableFormat,
)

router = APIRouter(
    prefix="/reader/v3",
    tags=["reader-v3"],
    route_class=TypedContractRoute,
)

_LOCATION_ADAPTER = TypeAdapter(ReaderLocation)
_METADATA_ADAPTER = TypeAdapter(dict[str, ReaderJsonValue])
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
_REFLOWABLE_FORMATS = frozenset({"epub", "mobi", "azw", "azw3", "prc", "fb2", "txt"})


def _current_user(db: Session, request: Request, settings: Settings) -> User:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        raise ReaderUnauthorizedError(
            ReaderErrorBody(message="未登录", code="UNAUTHORIZED")
        )
    return user


def _service(db: Session) -> VolumeReaderService:
    return reader_volume_service(db)


def _not_found() -> ReaderNotFoundError:
    return ReaderNotFoundError(
        ReaderErrorBody(message="卷册不存在", code="VOLUME_NOT_FOUND")
    )


def _access_scope(db: Session, user: User) -> ReaderAccessScope:
    context = authorization_context(db, user)
    return ReaderAccessScope(
        is_admin=context.is_admin,
        can_view_manual_imports=context.can_view_manual_imports,
        monitor_folder_ids=context.monitor_folder_ids,
    )


def _reader_type(volume_format: str) -> ReaderType:
    reader_type = reader_type_for_volume_format(volume_format)
    if reader_type is None:
        raise ReaderValidationError(
            ReaderErrorBody(
                message="卷册格式不支持直接阅读",
                code="VOLUME_FORMAT_UNSUPPORTED",
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


def _location_json(location: ReaderLocation, volume_id: str) -> str:
    if location.volume_id is not None and location.volume_id != volume_id:
        raise ReaderValidationError(
            ReaderErrorBody(
                message="阅读位置不属于当前卷册",
                code="VOLUME_LOCATION_MISMATCH",
            )
        )
    payload = location.model_dump(by_alias=True, exclude_none=True)
    payload["volumeId"] = volume_id
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _metadata(raw_json: str) -> dict[str, ReaderJsonValue]:
    try:
        return _METADATA_ADAPTER.validate_python(json.loads(raw_json))
    except (TypeError, ValueError, ValidationError):
        return {}


def _volume_summary(
    volume: ReaderVolumeDto,
    progress: ReaderProgressDto | None,
) -> ReaderVolumeSummary:
    reader_type = _reader_type(volume.format)
    return ReaderVolumeSummary(
        id=volume.id,
        mediaVersionId=volume.media_version_id,
        title=volume.title,
        volumeIndex=volume.volume_index,
        sortOrder=volume.sort_order,
        format=volume.format,
        readerType=reader_type.value,
        derivedFromVolumeId=volume.derived_from_volume_id,
        pageCount=volume.page_count,
        chapterCount=volume.chapter_count,
        durationMs=volume.duration_ms,
        trackCount=volume.track_count,
        progress=progress.percent if progress else 0,
        lastReadAt=progress.updated_at if progress else None,
    )


def _progress_record(
    progress: ReaderProgressDto,
    *,
    work_id: str,
    volume_format: str,
    fallback_location: ReaderLocation,
) -> ReaderProgressRecord:
    return ReaderProgressRecord(
        mutationId=progress.mutation_id or "",
        clientId=progress.client_id or "",
        clientSequence=progress.client_sequence or 0,
        contentFingerprint=progress.content_fingerprint or "",
        readerType=_reader_type(volume_format).value,
        workId=work_id,
        volumeId=progress.volume_id,
        location=_location(progress.location_json) or fallback_location,
        percent=progress.percent,
        updatedAt=progress.updated_at,
    )


def _raise_service_error(error: Exception) -> Never:
    if isinstance(error, ReaderVolumeNotFound):
        raise _not_found() from error
    if isinstance(error, ReaderVolumeFormatUnsupported):
        raise ReaderValidationError(
            ReaderErrorBody(
                message="卷册格式不支持直接阅读",
                code="VOLUME_FORMAT_UNSUPPORTED",
            )
        ) from error
    if isinstance(error, ReaderFingerprintMismatch):
        raise ReaderConflictError(
            ReaderErrorBody(
                message="卷册内容已变化，请重新载入",
                code="CONTENT_FINGERPRINT_MISMATCH",
                details={
                    "expectedContentFingerprint": error.expected,
                    "receivedContentFingerprint": error.received,
                },
            )
        ) from error
    raise error


@router.get(
    "/volumes/{volume_id}/bootstrap",
    response_model=ReaderBootstrapResponse,
    response_model_by_alias=True,
)
def reader_bootstrap_v3(
    volume_id: str,
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
    if not can_access_volume(db, user, volume_id):
        raise _not_found()
    try:
        bootstrap = _service(db).load_bootstrap(
            user_id=user.id,
            volume_id=volume_id,
            access_scope=_access_scope(db, user),
        )
    except (ReaderVolumeNotFound, ReaderVolumeFormatUnsupported) as error:
        _raise_service_error(error)

    context = bootstrap.context
    reader_type = _reader_type(context.volume.format)
    progress = bootstrap.progress_by_volume_id.get(volume_id)
    capabilities = capabilities_for_reader_type(reader_type)
    source_format: ReflowableFormat | None = None
    normalized_format = context.volume.format.lower()
    if normalized_format in _REFLOWABLE_FORMATS:
        source_format = cast(ReflowableFormat, normalized_format)
    return ReaderBootstrapResponse(
        data=ReaderBootstrapData(
            userId=user.id,
            readerType=reader_type.value,
            sourceFormat=source_format,
            contentFingerprint=bootstrap.content_fingerprint,
            book=ReaderBookSummary(
                id=context.work.id,
                title=context.work.title,
                author=context.work.author,
                coverUrl=f"/api/works/{context.work.id}/cover",
            ),
            mediaVersion=ReaderMediaVersionSummary(
                id=context.media_version.id,
                workId=context.work.id,
                mediaKind=cast(
                    Literal["EBOOK", "COMIC", "AUDIOBOOK"],
                    context.media_version.media_kind,
                ),
                completed=bootstrap.media_completed,
            ),
            volume=_volume_summary(context.volume, progress),
            availableVolumes=[
                _volume_summary(
                    volume,
                    bootstrap.progress_by_volume_id.get(volume.id),
                )
                for volume in bootstrap.available_volumes
            ],
            files=[
                ReaderFileSummary(
                    id=file.id,
                    kind=file.kind,
                    mimeType=file.mime_type,
                    sizeBytes=file.size_bytes,
                    durationMs=file.duration_ms,
                    discNumber=file.disc_number,
                    trackNumber=file.track_number,
                    sortOrder=file.sort_order,
                    url=f"/api/files/{file.id}",
                    codec=file.codec,
                )
                for file in bootstrap.files
            ],
            units=[
                ReaderUnitSummary(
                    id=unit.id,
                    index=unit.sort_order,
                    title=unit.title,
                    href=unit.href,
                    fileId=unit.file_id,
                    startMs=unit.start_ms,
                    endMs=unit.end_ms,
                    durationMs=unit.duration_ms,
                    metadata=_metadata(unit.metadata_json),
                )
                for unit in bootstrap.units
            ],
            fileUrl=f"/api/volumes/{volume_id}/file",
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
            resumeLocation=_location(bootstrap.resume_location_json),
            resumeFingerprintMismatch=bootstrap.resume_fingerprint_mismatch,
            progressPercent=progress.percent if progress else 0,
        )
    )


@router.put(
    "/volumes/{volume_id}/progress",
    response_model=ReaderProgressResponse,
    response_model_by_alias=True,
)
def save_progress_v3(
    volume_id: str,
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
        ReaderValidationError,
    ),
]:
    user = _current_user(db, request, settings)
    if not can_access_volume(db, user, volume_id):
        raise _not_found()
    location_json = _location_json(payload.location, volume_id)
    try:
        result = _service(db).save_progress(
            SaveProgressCommand(
                user_id=user.id,
                volume_id=volume_id,
                mutation_id=payload.mutation_id,
                client_id=payload.client_id,
                client_sequence=payload.client_sequence,
                content_fingerprint=payload.content_fingerprint,
                location_json=location_json,
                percent=payload.percent,
            )
        )
    except (
        ReaderVolumeNotFound,
        ReaderVolumeFormatUnsupported,
        ReaderFingerprintMismatch,
    ) as error:
        _raise_service_error(error)
    context = _service(db).get_context(volume_id)
    if context is None:
        raise _not_found()
    return ReaderProgressResponse(
        data=ReaderProgressData(
            mutationId=payload.mutation_id,
            applied=result.applied,
            progress=_progress_record(
                result.progress,
                work_id=context.work.id,
                volume_format=context.volume.format,
                fallback_location=payload.location,
            ),
        )
    )


@router.get(
    "/volumes/{volume_id}/bookmarks",
    response_model=ReaderBookmarksResponse,
    response_model_by_alias=True,
)
def list_bookmarks_v3(
    volume_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    content_fingerprint: str = Query(alias="contentFingerprint", min_length=1),
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
    if not can_access_volume(db, user, volume_id):
        raise _not_found()
    try:
        bookmarks = _service(db).list_bookmarks(
            user_id=user.id,
            volume_id=volume_id,
            content_fingerprint=content_fingerprint,
        )
    except (ReaderVolumeNotFound, ReaderFingerprintMismatch) as error:
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
    "/volumes/{volume_id}/bookmarks",
    response_model=ReaderBookmarksResponse,
    response_model_by_alias=True,
)
def replace_bookmarks_v3(
    volume_id: str,
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
    if not can_access_volume(db, user, volume_id):
        raise _not_found()
    incoming = [
        ReaderBookmarkDto(
            id="",
            bookmark_id=bookmark.id,
            location_json=_location_json(bookmark.location, volume_id),
            label=bookmark.label,
            percent=bookmark.percent,
            bookmark_created_at=bookmark.created_at,
        )
        for bookmark in payload.bookmarks
    ]
    try:
        bookmarks = _service(db).replace_bookmarks(
            user_id=user.id,
            volume_id=volume_id,
            content_fingerprint=payload.content_fingerprint,
            bookmarks=incoming,
        )
    except (ReaderVolumeNotFound, ReaderFingerprintMismatch) as error:
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
