import uuid
from collections.abc import Callable
from datetime import datetime
from email.utils import format_datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse as FastAPIFileResponse
from pydantic import Field

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.catalog.api.schemas import (
    BulkMetadataRequest,
    BulkMutationResponse,
    BulkShelfRequest,
    CreateWorkRequest,
    DuplicateGroupResponse,
    DuplicateMergeRequest,
    EditionDetailResponse,
    EditionResponse,
    FindReplacePreviewResponse,
    FindReplaceRequest,
    LibraryOperationResponse,
    MoveVolumeRequest,
    MoveVolumeToRequest,
    ShelfRequest,
    ShelfResponse,
    ShelfUpdateRequest,
    SplitEditionRequest,
    SplitEditionResponse,
    UpdateEditionRequest,
    UpdateWorkRequest,
    VolumeTransferResponse,
    WorkDetailResponse,
    WorkResponse,
)
from appv2.modules.catalog.application import CatalogNotFound, CatalogService
from appv2.modules.catalog.contracts import CategoryView, SeriesView
from appv2.platform.http import AppProblem, CamelModel, Page


class FacetsResponse(CamelModel):
    facets: dict[str, list[dict[str, object]]]


class CategoryResponse(CamelModel):
    id: uuid.UUID
    kind: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    book_count: int

    @classmethod
    def from_view(cls, value: CategoryView) -> "CategoryResponse":
        return cls(
            id=value.id,
            kind=value.kind,
            name=value.name,
            book_count=value.book_count,
        )


class SeriesResponse(CamelModel):
    name: str
    book_count: int
    latest_updated_at: datetime

    @classmethod
    def from_view(cls, value: SeriesView) -> "SeriesResponse":
        return cls.model_validate(value)


class CategoryUpdateRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)


class CategoryMergeRequest(CamelModel):
    kind: str = Field(min_length=1, max_length=50)
    target_id: uuid.UUID
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class ShelfDetailResponse(CamelModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    kind: str
    rules: dict[str, object]
    pinned: bool
    created_at: datetime
    book_count: int
    book_ids: list[uuid.UUID]
    books: list[WorkResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def create_router(service: CatalogService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/catalog")

    def require_scope(scope: AccessScope) -> Callable[[AccountView], AccountView]:
        def authorized(
            actor: Annotated[AccountView, Depends(current_account)],
        ) -> AccountView:
            if scope not in actor.scopes:
                raise AppProblem(
                    status=403,
                    code="PERMISSION_DENIED",
                    title="Permission denied",
                    message_key="permission_denied",
                    params={"scope": scope.value},
                )
            return actor

        return authorized

    Actor = Annotated[
        AccountView,
        Depends(require_scope(AccessScope.CATALOG_READ)),
    ]
    Writer = Annotated[
        AccountView,
        Depends(require_scope(AccessScope.CATALOG_WRITE)),
    ]

    def not_found(error: CatalogNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="CATALOG_RESOURCE_NOT_FOUND",
            title="Catalog resource not found",
            message_key="not_found",
        )

    def invalid(error: ValueError) -> AppProblem:
        return AppProblem(
            status=422,
            code="INVALID_CATALOG_MUTATION",
            title="Invalid catalog mutation",
            message_key="invalid_request",
        )

    @router.get("/works", response_model=Page[WorkResponse])
    def works(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        query: str | None = None,
        media_type: Annotated[str | None, Query(alias="mediaType")] = None,
        visibility: str = "active",
        series_name: Annotated[str | None, Query(alias="seriesName")] = None,
        sort: Literal[
            "recent_read",
            "recent_import",
            "title",
            "author",
            "publisher",
            "series",
        ] = "recent_read",
        sort_direction: Annotated[Literal["asc", "desc"], Query(alias="sortDirection")] = "desc",
    ) -> Page[WorkResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        items, total = service.list_works(
            page=max(page, 1),
            page_size=size,
            query=query,
            media_type=media_type,
            status=visibility,
            series_name=series_name,
            sort=sort,
            sort_direction=sort_direction,
        )
        return Page(
            items=[WorkResponse.from_view(item) for item in items],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.get("/series", response_model=Page[SeriesResponse])
    def series(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 100,
        visibility: str = "active",
    ) -> Page[SeriesResponse]:
        del actor
        values, total = service.list_series(
            page=max(page, 1),
            page_size=page_size,
            status=visibility,
        )
        return Page(
            items=[SeriesResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=page_size,
            total=total,
        )

    @router.post("/works", response_model=WorkResponse, status_code=status.HTTP_201_CREATED)
    def create_work(payload: CreateWorkRequest, actor: Writer) -> WorkResponse:
        del actor
        work = service.create_work(
            title=payload.title,
            author=payload.author,
            media_type=payload.media_type,
            metadata=payload.metadata,
        )
        return WorkResponse.from_view(work)

    @router.post(
        "/works/bulk/metadata",
        response_model=BulkMutationResponse,
    )
    def bulk_metadata(
        payload: BulkMetadataRequest,
        actor: Writer,
    ) -> BulkMutationResponse:
        del actor
        result = service.bulk_update_metadata(
            work_ids=payload.work_ids,
            author=payload.author,
            publisher=payload.publisher,
            series_name=payload.series_name,
            add_tags=payload.add_tags,
            remove_tags=payload.remove_tags,
        )
        return BulkMutationResponse.from_view(result)

    @router.post(
        "/works/bulk/find-replace/preview",
        response_model=FindReplacePreviewResponse,
    )
    def preview_find_replace(
        payload: FindReplaceRequest,
        actor: Writer,
    ) -> FindReplacePreviewResponse:
        del actor
        try:
            preview, _result = service.find_replace(
                work_ids=payload.work_ids,
                field=payload.field,
                find=payload.find,
                replacement=payload.replacement,
                regex=payload.regex,
                case_sensitive=payload.case_sensitive,
                start_number=payload.start_number,
                apply=False,
            )
        except ValueError as error:
            raise invalid(error) from error
        return FindReplacePreviewResponse.from_view(preview)

    @router.post(
        "/works/bulk/find-replace",
        response_model=BulkMutationResponse,
    )
    def apply_find_replace(
        payload: FindReplaceRequest,
        actor: Writer,
    ) -> BulkMutationResponse:
        del actor
        try:
            _preview, result = service.find_replace(
                work_ids=payload.work_ids,
                field=payload.field,
                find=payload.find,
                replacement=payload.replacement,
                regex=payload.regex,
                case_sensitive=payload.case_sensitive,
                start_number=payload.start_number,
                apply=True,
            )
        except ValueError as error:
            raise invalid(error) from error
        if result is None:
            raise RuntimeError("applied find-and-replace has no result")
        return BulkMutationResponse.from_view(result)

    @router.post(
        "/works/bulk/cover",
        response_model=BulkMutationResponse,
    )
    def bulk_cover(
        work_ids: Annotated[list[uuid.UUID], Form(alias="workIds")],
        cover: Annotated[UploadFile, File()],
        actor: Writer,
    ) -> BulkMutationResponse:
        del actor
        try:
            result = service.bulk_upload_cover(
                work_ids=work_ids,
                stream=cover.file,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        except ValueError as error:
            raise AppProblem(
                status=422,
                code="INVALID_COVER_IMAGE",
                title="Invalid cover image",
                message_key="invalid_request",
            ) from error
        return BulkMutationResponse.from_view(result)

    @router.get("/works/{work_id}", response_model=WorkDetailResponse)
    def work(work_id: uuid.UUID, actor: Actor) -> WorkDetailResponse:
        del actor
        try:
            item, editions = service.get_work_detail(work_id)
        except CatalogNotFound as error:
            raise not_found(error) from error
        return WorkDetailResponse(
            **WorkResponse.from_view(item).model_dump(),
            editions=[EditionDetailResponse.from_detail(value) for value in editions],
        )

    @router.patch("/works/{work_id}", response_model=WorkResponse)
    def update_work(
        work_id: uuid.UUID,
        payload: UpdateWorkRequest,
        actor: Writer,
    ) -> WorkResponse:
        del actor
        try:
            item = service.update_work(
                work_id,
                title=payload.title,
                author=payload.author,
                summary=payload.summary,
                status=payload.status,
                metadata=payload.metadata,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return WorkResponse.from_view(item)

    @router.get("/works/{work_id}/cover", response_class=FastAPIFileResponse)
    def cover(
        work_id: uuid.UUID,
        actor: Actor,
        size: Literal["small", "medium", "large", "original"] = "medium",
    ) -> FastAPIFileResponse:
        del actor
        try:
            resource = service.cover(work_id, size=size)
        except CatalogNotFound as error:
            raise not_found(error) from error
        return FastAPIFileResponse(
            resource.path,
            media_type=resource.media_type,
            headers={
                "ETag": resource.etag,
                "Last-Modified": format_datetime(resource.last_modified, usegmt=True),
                "Cache-Control": "private, max-age=86400",
            },
        )

    @router.post("/works/{work_id}/cover/upload", response_model=WorkResponse)
    def upload_cover(
        work_id: uuid.UUID,
        cover: Annotated[UploadFile, File()],
        actor: Writer,
    ) -> WorkResponse:
        del actor
        try:
            work = service.upload_cover(work_id, cover.file)
        except CatalogNotFound as error:
            raise not_found(error) from error
        except ValueError as error:
            raise AppProblem(
                status=422,
                code="INVALID_COVER_IMAGE",
                title="Invalid cover image",
                message_key="invalid_request",
            ) from error
        return WorkResponse.from_view(work)

    @router.delete("/works/{work_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_work(
        work_id: uuid.UUID,
        actor: Writer,
        delete_source: Annotated[bool, Query(alias="deleteSource")] = False,
    ) -> None:
        del actor
        try:
            service.delete_work(work_id, delete_source=delete_source)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.patch(
        "/works/{work_id}/editions/{edition_id}",
        response_model=EditionResponse,
    )
    def update_edition(
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        payload: UpdateEditionRequest,
        actor: Writer,
    ) -> EditionResponse:
        del actor
        try:
            edition = service.update_edition(
                work_id,
                edition_id,
                title=payload.version_name,
                language=payload.language,
                metadata=payload.metadata_patch(),
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return EditionResponse.from_view(edition)

    @router.post(
        "/works/{work_id}/editions/{edition_id}/primary",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def set_primary_edition(
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        actor: Writer,
    ) -> None:
        del actor
        try:
            service.set_primary_edition(work_id, edition_id)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.post(
        "/works/{work_id}/editions/{edition_id}/split",
        response_model=SplitEditionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def split_edition(
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        payload: SplitEditionRequest,
        actor: Writer,
    ) -> SplitEditionResponse:
        del actor
        try:
            new_work_id = service.split_edition(
                work_id,
                edition_id,
                title=payload.title,
                author=payload.author,
                copy_shelves=payload.copy_shelves,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return SplitEditionResponse(new_work_id=new_work_id)

    @router.post(
        "/works/{work_id}/volumes/{volume_id}/move",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def move_volume(
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        payload: MoveVolumeRequest,
        actor: Writer,
    ) -> None:
        del actor
        try:
            service.move_volume(
                work_id,
                volume_id,
                direction=payload.direction,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.post(
        "/works/{work_id}/volumes/{volume_id}/move-to",
        response_model=VolumeTransferResponse,
    )
    def move_volume_to(
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        payload: MoveVolumeToRequest,
        actor: Writer,
    ) -> VolumeTransferResponse:
        del actor
        try:
            service.move_volume_to(
                work_id,
                volume_id,
                target_edition_id=payload.target_edition_id,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return VolumeTransferResponse()

    @router.get("/shelves", response_model=Page[ShelfResponse])
    def shelves(actor: Actor) -> Page[ShelfResponse]:
        items = service.list_shelves(actor.id)
        return Page(
            items=[ShelfResponse.from_view(item) for item in items],
            page=1,
            page_size=max(len(items), 1),
            total=len(items),
        )

    @router.post("/shelves", response_model=ShelfResponse, status_code=status.HTTP_201_CREATED)
    def create_shelf(payload: ShelfRequest, actor: Writer) -> ShelfResponse:
        shelf = service.create_shelf(
            owner_id=actor.id,
            name=payload.name,
            description=payload.description,
            kind=payload.kind,
            rules=payload.rules,
            pinned=payload.pinned,
            book_ids=payload.book_ids,
        )
        return ShelfResponse.from_view(shelf)

    @router.get("/shelves/{shelf_id}", response_model=ShelfDetailResponse)
    def shelf(
        shelf_id: uuid.UUID,
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
    ) -> ShelfDetailResponse:
        try:
            value, works, work_ids, total = service.get_shelf(
                shelf_id,
                actor.id,
                page=max(page, 1),
                page_size=page_size,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return ShelfDetailResponse(
            **ShelfResponse.from_view(value).model_dump(),
            book_count=total,
            book_ids=work_ids,
            books=[WorkResponse.from_view(work) for work in works],
            page=max(page, 1),
            page_size=page_size,
            total=total,
            total_pages=max(1, (total + page_size - 1) // page_size),
        )

    @router.patch("/shelves/{shelf_id}", response_model=ShelfResponse)
    def update_shelf(
        shelf_id: uuid.UUID, payload: ShelfUpdateRequest, actor: Writer
    ) -> ShelfResponse:
        try:
            shelf = service.update_shelf(
                shelf_id,
                actor.id,
                name=payload.name,
                description=payload.description,
                rules=payload.rules,
                pinned=payload.pinned,
                book_ids=payload.book_ids,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return ShelfResponse.from_view(shelf)

    @router.delete("/shelves/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_shelf(shelf_id: uuid.UUID, actor: Writer) -> None:
        try:
            service.delete_shelf(shelf_id, actor.id)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.post(
        "/shelves/{shelf_id}/works/bulk",
        response_model=BulkMutationResponse,
    )
    def bulk_shelf_membership(
        shelf_id: uuid.UUID,
        payload: BulkShelfRequest,
        actor: Writer,
    ) -> BulkMutationResponse:
        try:
            result = service.bulk_shelf_membership(
                owner_id=actor.id,
                shelf_id=shelf_id,
                work_ids=payload.work_ids,
                present=payload.present,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return BulkMutationResponse.from_view(result)

    @router.put(
        "/shelves/{shelf_id}/works/{work_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def add_shelf_item(shelf_id: uuid.UUID, work_id: uuid.UUID, actor: Writer) -> None:
        try:
            service.set_shelf_item(shelf_id, actor.id, work_id, present=True)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.delete(
        "/shelves/{shelf_id}/works/{work_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_shelf_item(shelf_id: uuid.UUID, work_id: uuid.UUID, actor: Writer) -> None:
        try:
            service.set_shelf_item(shelf_id, actor.id, work_id, present=False)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.get("/facets", response_model=FacetsResponse)
    def facets(actor: Actor) -> FacetsResponse:
        del actor
        return FacetsResponse(facets=service.facets())

    @router.get("/categories", response_model=Page[CategoryResponse])
    def categories(
        actor: Actor,
        kind: str,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        search: str | None = None,
    ) -> Page[CategoryResponse]:
        del actor
        values, total = service.list_categories(
            kind=kind,
            query=search,
            page=max(page, 1),
            page_size=page_size,
        )
        return Page(
            items=[CategoryResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=page_size,
            total=total,
        )

    @router.patch("/categories/{category_id}", response_model=CategoryResponse)
    def rename_category(
        category_id: uuid.UUID,
        payload: CategoryUpdateRequest,
        actor: Writer,
    ) -> CategoryResponse:
        del actor
        try:
            category = service.rename_category(category_id, payload.name)
        except CatalogNotFound as error:
            raise not_found(error) from error
        return CategoryResponse.from_view(category)

    @router.post("/categories/merge", response_model=CategoryResponse)
    def merge_categories(
        payload: CategoryMergeRequest,
        actor: Writer,
    ) -> CategoryResponse:
        del actor
        try:
            category = service.merge_categories(
                kind=payload.kind,
                target_id=payload.target_id,
                source_ids=payload.source_ids,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return CategoryResponse.from_view(category)

    @router.delete(
        "/categories/{category_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_category(category_id: uuid.UUID, actor: Writer) -> None:
        del actor
        try:
            service.delete_category(category_id)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.get("/duplicates", response_model=Page[DuplicateGroupResponse])
    def duplicate_groups(actor: Writer) -> Page[DuplicateGroupResponse]:
        del actor
        groups = service.list_duplicate_groups()
        return Page(
            items=[DuplicateGroupResponse.from_view(group) for group in groups],
            page=1,
            page_size=max(len(groups), 1),
            total=len(groups),
        )

    @router.post(
        "/duplicates/merge",
        response_model=LibraryOperationResponse,
    )
    def merge_duplicate_works(
        payload: DuplicateMergeRequest,
        actor: Writer,
    ) -> LibraryOperationResponse:
        try:
            operation = service.merge_duplicate_works(
                actor_id=actor.id,
                target_id=payload.target_work_id,
                source_ids=payload.source_work_ids,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        except ValueError as error:
            raise invalid(error) from error
        return LibraryOperationResponse.from_view(operation)

    @router.post(
        "/operations/{operation_id}/undo",
        response_model=LibraryOperationResponse,
    )
    def undo_library_operation(
        operation_id: uuid.UUID,
        actor: Writer,
    ) -> LibraryOperationResponse:
        try:
            operation = service.undo_library_operation(
                actor_id=actor.id,
                operation_id=operation_id,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return LibraryOperationResponse.from_view(operation)

    return router
