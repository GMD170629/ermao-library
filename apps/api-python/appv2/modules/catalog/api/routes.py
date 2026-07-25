import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import Field

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.catalog.api.schemas import (
    CreateWorkRequest,
    EditionResponse,
    ShelfRequest,
    ShelfResponse,
    ShelfUpdateRequest,
    UpdateWorkRequest,
    WorkDetailResponse,
    WorkResponse,
)
from appv2.modules.catalog.application import CatalogNotFound, CatalogService
from appv2.modules.catalog.contracts import CategoryView
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

    @router.get("/works", response_model=Page[WorkResponse])
    def works(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        query: str | None = None,
        media_type: Annotated[str | None, Query(alias="mediaType")] = None,
        visibility: str = "active",
    ) -> Page[WorkResponse]:
        del actor
        size = min(max(page_size, 1), 200)
        items, total = service.list_works(
            page=max(page, 1),
            page_size=size,
            query=query,
            media_type=media_type,
            status=visibility,
        )
        return Page(
            items=[WorkResponse.from_view(item) for item in items],
            page=max(page, 1),
            page_size=size,
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

    @router.get("/works/{work_id}", response_model=WorkDetailResponse)
    def work(work_id: uuid.UUID, actor: Actor) -> WorkDetailResponse:
        del actor
        try:
            item, editions = service.get_work(work_id)
        except CatalogNotFound as error:
            raise not_found(error) from error
        return WorkDetailResponse(
            **WorkResponse.from_view(item).model_dump(),
            editions=[EditionResponse.from_view(value) for value in editions],
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
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return WorkResponse.from_view(item)

    @router.delete("/works/{work_id}", status_code=status.HTTP_204_NO_CONTENT)
    def archive_work(work_id: uuid.UUID, actor: Writer) -> None:
        del actor
        try:
            service.update_work(
                work_id,
                title=None,
                author=None,
                summary=None,
                status="archived",
            )
        except CatalogNotFound as error:
            raise not_found(error) from error

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

    return router
