import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from appv2.modules.accounts.contracts import AccountView, CurrentAccount
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
from appv2.platform.http import AppProblem, CamelModel, Page


class FacetsResponse(CamelModel):
    facets: dict[str, list[dict[str, object]]]


def create_router(service: CatalogService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/catalog")
    Actor = Annotated[AccountView, Depends(current_account)]

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
        page_size: int = 24,
        query: str | None = None,
        media_type: str | None = None,
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
    def create_work(payload: CreateWorkRequest, actor: Actor) -> WorkResponse:
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
    def update_work(work_id: uuid.UUID, payload: UpdateWorkRequest, actor: Actor) -> WorkResponse:
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
    def archive_work(work_id: uuid.UUID, actor: Actor) -> None:
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
    def create_shelf(payload: ShelfRequest, actor: Actor) -> ShelfResponse:
        shelf = service.create_shelf(
            owner_id=actor.id,
            name=payload.name,
            description=payload.description,
            kind=payload.kind,
            rules=payload.rules,
            pinned=payload.pinned,
        )
        return ShelfResponse.from_view(shelf)

    @router.patch("/shelves/{shelf_id}", response_model=ShelfResponse)
    def update_shelf(
        shelf_id: uuid.UUID, payload: ShelfUpdateRequest, actor: Actor
    ) -> ShelfResponse:
        try:
            shelf = service.update_shelf(
                shelf_id,
                actor.id,
                name=payload.name,
                description=payload.description,
                rules=payload.rules,
                pinned=payload.pinned,
            )
        except CatalogNotFound as error:
            raise not_found(error) from error
        return ShelfResponse.from_view(shelf)

    @router.delete("/shelves/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_shelf(shelf_id: uuid.UUID, actor: Actor) -> None:
        try:
            service.delete_shelf(shelf_id, actor.id)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.put(
        "/shelves/{shelf_id}/works/{work_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def add_shelf_item(shelf_id: uuid.UUID, work_id: uuid.UUID, actor: Actor) -> None:
        try:
            service.set_shelf_item(shelf_id, actor.id, work_id, present=True)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.delete(
        "/shelves/{shelf_id}/works/{work_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_shelf_item(shelf_id: uuid.UUID, work_id: uuid.UUID, actor: Actor) -> None:
        try:
            service.set_shelf_item(shelf_id, actor.id, work_id, present=False)
        except CatalogNotFound as error:
            raise not_found(error) from error

    @router.get("/facets", response_model=FacetsResponse)
    def facets(actor: Actor) -> FacetsResponse:
        del actor
        return FacetsResponse(facets=service.facets())

    return router
