import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import Field
from starlette.responses import StreamingResponse

from appv2.modules.accounts.contracts import AccountView, CurrentAccount
from appv2.modules.reading.application import (
    LocationClaimConflict,
    LocationClaimResult,
    ProgressConflict,
    ReadingNotFound,
    ReadingService,
)
from appv2.modules.reading.contracts import BookmarkView, ComicPage, PreferenceView, ProgressView
from appv2.platform.http import AppProblem, CamelModel, Page
from appv2.platform.http.ranges import InvalidRange, parse_range_header


class ProgressResponse(CamelModel):
    edition_id: uuid.UUID
    position: dict[str, object]
    percentage: float
    version: int
    updated_at: datetime

    @classmethod
    def from_view(cls, progress: ProgressView) -> "ProgressResponse":
        return cls(
            edition_id=progress.edition_id,
            position=progress.position,
            percentage=progress.percentage,
            version=progress.version,
            updated_at=progress.updated_at,
        )


class ProgressRequest(CamelModel):
    device_id: str = Field(min_length=1, max_length=200)
    position: dict[str, object]
    percentage: float = Field(ge=0, le=1)
    occurred_at: datetime | None = None
    expected_version: int | None = Field(default=None, ge=0)


class BookmarkResponse(CamelModel):
    id: uuid.UUID
    edition_id: uuid.UUID
    client_id: str
    label: str | None
    position: dict[str, object]
    excerpt: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, bookmark: BookmarkView) -> "BookmarkResponse":
        return cls.model_validate(bookmark)


class BookmarkRequest(CamelModel):
    client_id: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=500)
    position: dict[str, object]
    excerpt: str | None = None


class PreferenceResponse(CamelModel):
    scope: str
    target_id: uuid.UUID | None
    values: dict[str, object]
    updated_at: datetime

    @classmethod
    def from_view(cls, preference: PreferenceView) -> "PreferenceResponse":
        return cls.model_validate(preference)


class PreferenceRequest(CamelModel):
    scope: str = Field(min_length=1, max_length=30)
    target_id: uuid.UUID | None = None
    values: dict[str, object]


class ReaderTargetResponse(CamelModel):
    work_id: uuid.UUID
    work_title: str
    work_author: str | None
    edition_id: uuid.UUID
    edition_title: str
    file_id: uuid.UUID
    format: str
    media_type: str
    resource_url: str
    checksum: str


class BootstrapResponse(CamelModel):
    account_id: uuid.UUID
    target: ReaderTargetResponse
    progress: ProgressResponse | None
    bookmarks: list[BookmarkResponse]
    preference: PreferenceResponse | None


class ComicPageResponse(CamelModel):
    page_index: int
    title: str
    mime_type: str
    size: int

    @classmethod
    def from_view(cls, value: ComicPage) -> "ComicPageResponse":
        return cls(
            page_index=value.page_index,
            title=value.title,
            mime_type=value.media_type,
            size=value.size_bytes,
        )


class ComicPageIndexResponse(CamelModel):
    page_count: int
    pages: list[ComicPageResponse]


class EpubLocationClaimRequest(CamelModel):
    cache_version: int = Field(ge=1)
    content_fingerprint: str = Field(min_length=1, max_length=128)
    break_size: int = Field(ge=100, le=100_000)


class EpubLocationSaveRequest(EpubLocationClaimRequest):
    lease_token: str = Field(min_length=20, max_length=500)
    serialized: str = Field(min_length=1, max_length=20_000_000)


class EpubLocationClaimResponse(CamelModel):
    status: Literal["ready", "claimed", "generating"]
    serialized: str | None = None
    lease_token: str | None = None
    lease_expires_at: int | None = None
    retry_after_ms: int | None = None

    @classmethod
    def from_result(cls, value: LocationClaimResult) -> "EpubLocationClaimResponse":
        return cls(
            status=value.status,
            serialized=value.serialized,
            lease_token=value.lease_token,
            lease_expires_at=(
                int(value.lease_expires_at.timestamp() * 1000) if value.lease_expires_at else None
            ),
            retry_after_ms=value.retry_after_ms,
        )


def create_router(service: ReadingService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/reading")
    Actor = Annotated[AccountView, Depends(current_account)]

    def missing(error: ReadingNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="READING_RESOURCE_NOT_FOUND",
            title="Reading resource not found",
            message_key="not_found",
        )

    @router.get("/editions/{edition_id}/bootstrap", response_model=BootstrapResponse)
    def bootstrap(edition_id: uuid.UUID, actor: Actor) -> BootstrapResponse:
        try:
            target, progress, bookmarks, preference = service.bootstrap(
                user_id=actor.id, edition_id=edition_id
            )
        except ReadingNotFound as error:
            raise missing(error) from error
        return BootstrapResponse(
            account_id=actor.id,
            target=ReaderTargetResponse.model_validate(target),
            progress=ProgressResponse.from_view(progress) if progress else None,
            bookmarks=[BookmarkResponse.from_view(value) for value in bookmarks],
            preference=(PreferenceResponse.from_view(preference) if preference else None),
        )

    @router.get("/editions/{edition_id}/resource")
    def resource(
        edition_id: uuid.UUID,
        actor: Actor,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> StreamingResponse:
        try:
            requested_range = parse_range_header(range_header)
            stream = service.resource(
                user_id=actor.id,
                edition_id=edition_id,
                requested_range=requested_range,
            )
        except InvalidRange as error:
            raise AppProblem(
                status=416,
                code="INVALID_RANGE",
                title="Invalid range",
                message_key="invalid_request",
            ) from error
        except ReadingNotFound as error:
            raise missing(error) from error
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(stream.content_length),
            "ETag": stream.etag,
            "Last-Modified": stream.last_modified,
            "Content-Disposition": f'inline; filename="{stream.filename}"',
            "Cache-Control": "private, no-cache",
        }
        if stream.content_range is not None:
            headers["Content-Range"] = stream.content_range
        return StreamingResponse(
            stream.body,
            status_code=stream.status_code,
            media_type=stream.media_type,
            headers=headers,
        )

    @router.get("/volumes/{edition_id}/pages", response_model=ComicPageIndexResponse)
    def comic_pages(edition_id: uuid.UUID, actor: Actor) -> ComicPageIndexResponse:
        del actor
        try:
            pages = service.comic_pages(edition_id=edition_id)
        except ReadingNotFound as error:
            raise missing(error) from error
        return ComicPageIndexResponse(
            page_count=len(pages),
            pages=[ComicPageResponse.from_view(page) for page in pages],
        )

    @router.get("/volumes/{edition_id}/pages/{page_index}")
    def comic_page(
        edition_id: uuid.UUID,
        page_index: int,
        actor: Actor,
    ) -> StreamingResponse:
        try:
            stream = service.comic_page(
                user_id=actor.id,
                edition_id=edition_id,
                page_index=page_index,
            )
        except ReadingNotFound as error:
            raise missing(error) from error
        return StreamingResponse(
            stream.body,
            status_code=stream.status_code,
            media_type=stream.media_type,
            headers={
                "Content-Length": str(stream.content_length),
                "ETag": stream.etag,
                "Last-Modified": stream.last_modified,
                "Cache-Control": "private, max-age=86400",
                "Content-Disposition": f'inline; filename="{stream.filename}"',
            },
        )

    @router.post(
        "/editions/{edition_id}/epub-locations/claim",
        response_model=EpubLocationClaimResponse,
    )
    def claim_epub_locations(
        edition_id: uuid.UUID,
        payload: EpubLocationClaimRequest,
        actor: Actor,
    ) -> EpubLocationClaimResponse:
        try:
            result = service.claim_epub_locations(
                user_id=actor.id,
                edition_id=edition_id,
                content_fingerprint=payload.content_fingerprint,
                cache_version=payload.cache_version,
                break_size=payload.break_size,
            )
        except ReadingNotFound as error:
            raise missing(error) from error
        return EpubLocationClaimResponse.from_result(result)

    @router.put(
        "/editions/{edition_id}/epub-locations",
        response_model=EpubLocationClaimResponse,
    )
    def save_epub_locations(
        edition_id: uuid.UUID,
        payload: EpubLocationSaveRequest,
        actor: Actor,
    ) -> EpubLocationClaimResponse:
        del actor
        try:
            result = service.save_epub_locations(
                edition_id=edition_id,
                content_fingerprint=payload.content_fingerprint,
                cache_version=payload.cache_version,
                break_size=payload.break_size,
                lease_token=payload.lease_token,
                serialized=payload.serialized,
            )
        except ReadingNotFound as error:
            raise missing(error) from error
        except LocationClaimConflict as error:
            raise AppProblem(
                status=409,
                code="EPUB_LOCATION_CLAIM_CONFLICT",
                title="EPUB location claim conflict",
                message_key="conflict",
            ) from error
        return EpubLocationClaimResponse.from_result(result)

    @router.get("/editions/{edition_id}/progress", response_model=ProgressResponse | None)
    def progress(edition_id: uuid.UUID, actor: Actor) -> ProgressResponse | None:
        value = service.get_progress(user_id=actor.id, edition_id=edition_id)
        return ProgressResponse.from_view(value) if value else None

    @router.put("/editions/{edition_id}/progress", response_model=ProgressResponse)
    def save_progress(
        edition_id: uuid.UUID, payload: ProgressRequest, actor: Actor
    ) -> ProgressResponse:
        try:
            value = service.save_progress(
                user_id=actor.id,
                edition_id=edition_id,
                device_id=payload.device_id,
                position=payload.position,
                percentage=payload.percentage,
                occurred_at=payload.occurred_at,
                expected_version=payload.expected_version,
            )
        except ProgressConflict as error:
            raise AppProblem(
                status=409,
                code="PROGRESS_VERSION_CONFLICT",
                title="Reading progress conflict",
                message_key="conflict",
            ) from error
        return ProgressResponse.from_view(value)

    @router.get("/editions/{edition_id}/bookmarks", response_model=Page[BookmarkResponse])
    def bookmarks(edition_id: uuid.UUID, actor: Actor) -> Page[BookmarkResponse]:
        values = service.list_bookmarks(user_id=actor.id, edition_id=edition_id)
        return Page(
            items=[BookmarkResponse.from_view(value) for value in values],
            page=1,
            page_size=max(len(values), 1),
            total=len(values),
        )

    @router.put(
        "/editions/{edition_id}/bookmarks",
        response_model=BookmarkResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def put_bookmark(
        edition_id: uuid.UUID, payload: BookmarkRequest, actor: Actor
    ) -> BookmarkResponse:
        value = service.put_bookmark(
            user_id=actor.id,
            edition_id=edition_id,
            client_id=payload.client_id,
            label=payload.label,
            position=payload.position,
            excerpt=payload.excerpt,
        )
        return BookmarkResponse.from_view(value)

    @router.delete(
        "/editions/{edition_id}/bookmarks/{bookmark_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_bookmark(edition_id: uuid.UUID, bookmark_id: uuid.UUID, actor: Actor) -> None:
        try:
            service.delete_bookmark(
                user_id=actor.id,
                edition_id=edition_id,
                bookmark_id=bookmark_id,
            )
        except ReadingNotFound as error:
            raise missing(error) from error

    @router.get("/preferences", response_model=PreferenceResponse | None)
    def preference(
        actor: Actor,
        scope: str = "global",
        target_id: Annotated[uuid.UUID | None, Query(alias="targetId")] = None,
    ) -> PreferenceResponse | None:
        value = service.get_preference(user_id=actor.id, scope=scope, target_id=target_id)
        return PreferenceResponse.from_view(value) if value else None

    @router.put("/preferences", response_model=PreferenceResponse)
    def save_preference(payload: PreferenceRequest, actor: Actor) -> PreferenceResponse:
        value = service.save_preference(
            user_id=actor.id,
            scope=payload.scope,
            target_id=payload.target_id,
            values=payload.values,
        )
        return PreferenceResponse.from_view(value)

    return router
