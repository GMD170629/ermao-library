"""Book, ReadableResource, and ResourceAsset HTTP adapters."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.library import (
    list_books,
    resource_metadata,
    update_book_fields,
)
from app.core.authorization import (
    authorization_context,
    can_access_asset,
    can_access_book,
    can_access_resource,
    can_manage_system,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    ReadableResourceNavigationUnit,
)
from app.models.auth import User
from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    continue_source_import,
)
from app.modules.library.application.book_list import BookListQuery
from app.modules.library.presentation.schemas import (
    BookPayload,
    BookResponse,
    BooksPayload,
    BooksResponse,
    AssetsPayload,
    AssetsResponse,
    ResourcePayload,
    ResourceResponse,
    ResourcesPayload,
    ResourcesResponse,
    UpdateBookRequest,
    UpdateResourceRequest,
    ResourceSourceDeleteRequest,
    ReclassifyResourceRequest,
    ResourceBatchRequest,
    AssetDeletedResponse,
    ReadingUnitsResponse,
    ResourceBatchResponse,
    ResourceDeletedResponse,
    ResourceImportAcceptedResponse,
    ResourceReclassifyResponse,
)
from app.modules.library.application.resource_commands import (
    LibraryActor,
    BookNotFoundError,
    InvalidResourceChangeError,
    LibraryAuthorizationError,
    ResourceNotFoundError,
    ResourceReclassifyOutcome,
    SetResourceMediaKindsCommand,
    reclassify_resource,
    set_resource_media_kinds,
    update_resource,
)
from app.modules.library.presentation.views import (
    book_view,
    get_book,
    list_resource_views,
    resource_view,
)
from app.schemas.responses import fail, ok

router = APIRouter(tags=["library"], route_class=TypedContractRoute)
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _actor(db: Session, user: User) -> LibraryActor:
    context = authorization_context(db, user)
    return LibraryActor(
        user_id=context.user_id,
        can_manage_system=context.can_manage_system,
        is_admin=context.is_admin,
        can_view_manual_imports=context.can_view_manual_imports,
        library_ids=context.library_ids,
    )


def _require_manager(user: User):
    if not can_manage_system(user):
        return fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    return None


@router.get("/books", response_model=BooksResponse)
def list_library_books(
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=500),
    search: str | None = None,
    sort: str = "updated",
) -> BooksResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    result = list_books(
        db,
        user,
        BookListQuery(
            page=page,
            requested_page_size=pageSize,
            search=search,
            keyword=None,
            sort=sort,
        ),
    )
    books = [book_view(db, item, user.id) for item in result.books]
    return BooksResponse(
        data=BooksPayload(
            books=books,
            page=result.page,
            pageSize=result.page_size,
            total=result.total,
        )
    )


@router.get("/books/{book_id}", response_model=BookResponse)
def get_library_book(
    book_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> BookResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_book(db, user, book_id):
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    book = get_book(db, book_id)
    if book is None:
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    return BookResponse(data=BookPayload(book=book_view(db, book, user.id)))


@router.patch("/books/{book_id}", response_model=BookResponse)
def update_library_book(
    book_id: str,
    payload: UpdateBookRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> BookResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_book(db, user, book_id):
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    values = payload.model_dump(by_alias=True, exclude_none=True, exclude_unset=True)
    book = update_book_fields(db, book_id, values)
    if book is None:
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    db.commit()
    return BookResponse(data=BookPayload(book=book_view(db, book, user.id)))


@router.get("/books/{book_id}/resources", response_model=ResourcesResponse)
def list_book_resources(
    book_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=500),
) -> ResourcesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_book(db, user, book_id):
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    book = get_book(db, book_id)
    if book is None:
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    resources, normalized_page, normalized_size, total = list_resource_views(
        db,
        book_id,
        user.id,
        page=page,
        page_size=pageSize,
    )
    return ResourcesResponse(
        data=ResourcesPayload(
            bookId=book_id,
            resources=resources,
            page=normalized_page,
            pageSize=normalized_size,
            total=total,
            totalPages=max(1, (total + normalized_size - 1) // normalized_size),
        )
    )


@router.get("/resources/{resource_id}", response_model=ResourceResponse)
def get_library_resource(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> ResourceResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_resource(db, user, resource_id):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    resource = resource_view(db, resource_id, user.id)
    if resource is None:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    return ResourceResponse(data=ResourcePayload(resource=resource))


@router.get("/resources/{resource_id}/assets", response_model=AssetsResponse)
def list_resource_assets(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=500, ge=1, le=500),
) -> AssetsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_resource(db, user, resource_id):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    resource = resource_view(db, resource_id, user.id)
    if resource is None:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    all_assets = list(resource["assets"])
    normalized_page = max(1, page)
    normalized_size = min(500, max(1, pageSize))
    start = (normalized_page - 1) * normalized_size
    return AssetsResponse(
        data=AssetsPayload(
            resourceId=resource_id,
            assets=all_assets[start : start + normalized_size],
            page=normalized_page,
            pageSize=normalized_size,
            total=len(all_assets),
            totalPages=max(1, (len(all_assets) + normalized_size - 1) // normalized_size),
        )
    )


@router.patch(
    "/books/{book_id}/resources/{resource_id}",
    response_model=ResourceResponse,
)
def update_library_resource(
    book_id: str,
    resource_id: str,
    payload: UpdateResourceRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> ResourceResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    manager_error = _require_manager(user)
    if manager_error:
        return manager_error
    if not can_access_book(db, user, book_id):
        return fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
    if not can_access_resource(db, user, resource_id):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    resource_book_id = db.scalar(
        select(LibraryReadableResource.book_id).where(
            LibraryReadableResource.id == resource_id
        )
    )
    if resource_book_id != book_id:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    try:
        update_resource(
            resource_metadata(db),
            db,
            actor=_actor(db, user),
            book_id=book_id,
            resource_id=resource_id,
            changes=changes,
            now=datetime.now(UTC),
        )
    except (BookNotFoundError, ResourceNotFoundError):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    except (LibraryAuthorizationError, InvalidResourceChangeError) as exc:
        return fail(str(exc) or "资源参数无效", status_code=400)
    updated = resource_view(db, resource_id, user.id)
    if updated is None:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    return ResourceResponse(data=ResourcePayload(resource=updated))


@router.post(
    "/books/{book_id}/resources/{resource_id}/cover/regenerate",
    response_model=ResourceImportAcceptedResponse,
    status_code=202,
)
def regenerate_library_resource_cover(
    book_id: str,
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> ResourceImportAcceptedResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    manager_error = _require_manager(user)
    if manager_error:
        return manager_error
    if not can_access_book(db, user, book_id) or not can_access_resource(
        db, user, resource_id
    ):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    resource = db.get(LibraryReadableResource, resource_id)
    if resource is None or resource.book_id != book_id:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    metadata = db.get(LibraryReadableResourceMetadata, resource_id)
    if metadata is not None:
        metadata.cover_path = None
        metadata.cover_status = "PENDING"
        db.commit()
    result = continue_source_import(db, resource.source_node_id)
    return ok(
        {
            "resourceId": resource_id,
            "accepted": True,
            "taskId": result.task_id,
        },
        status_code=202,
    )


@router.delete(
    "/books/{book_id}/resources/{resource_id}/source",
    response_model=ResourceDeletedResponse,
)
def delete_library_resource_source(
    book_id: str,
    resource_id: str,
    payload: ResourceSourceDeleteRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> ResourceDeletedResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    manager_error = _require_manager(user)
    if manager_error:
        return manager_error
    if not payload.confirmation.strip():
        return fail("删除确认不能为空", status_code=400, code="CONFIRMATION_REQUIRED")
    if not can_access_book(db, user, book_id) or not can_access_resource(
        db, user, resource_id
    ):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    resource = db.get(LibraryReadableResource, resource_id)
    if resource is None or resource.book_id != book_id:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    result = build_readable_resource_pipeline(db).delete_source_node.execute(
        resource.source_node_id
    )
    if not result.ok:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    return ok({"resourceId": resource_id, "deleted": True})


@router.post(
    "/books/{book_id}/resources/{resource_id}/reclassify",
    response_model=ResourceReclassifyResponse,
)
def reclassify_library_resource(
    book_id: str,
    resource_id: str,
    payload: ReclassifyResourceRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> ResourceReclassifyResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    manager_error = _require_manager(user)
    if manager_error:
        return manager_error
    try:
        outcome = reclassify_resource(
            resource_metadata(db),
            db,
            actor=_actor(db, user),
            book_id=book_id,
            resource_id=resource_id,
            target_media_kind=payload.target_media_kind,
            apply_to=payload.apply_to,
            now=datetime.now(UTC),
        )
    except (BookNotFoundError, ResourceNotFoundError):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    except (LibraryAuthorizationError, InvalidResourceChangeError) as exc:
        return fail(str(exc) or "资源参数无效", status_code=400)
    return ok(
        {
            "affectedResourceIds": list(outcome.affected_resource_ids),
            "operation": asdict(outcome.operation),
        }
    )


@router.post(
    "/books/{book_id}/resources/batch",
    response_model=ResourceBatchResponse,
)
def batch_library_resource_action(
    book_id: str,
    payload: ResourceBatchRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> ResourceBatchResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    manager_error = _require_manager(user)
    if manager_error:
        return manager_error
    try:
        outcome = set_resource_media_kinds(
            resource_metadata(db),
            db,
            actor=_actor(db, user),
            book_id=book_id,
            command=SetResourceMediaKindsCommand(
                resource_ids=tuple(payload.resource_ids),
                target_media_kind=payload.target_media_kind,
            ),
            now=datetime.now(UTC),
        )
    except (BookNotFoundError, ResourceNotFoundError):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    except (LibraryAuthorizationError, InvalidResourceChangeError) as exc:
        return fail(str(exc) or "资源参数无效", status_code=400)
    return ok(
        {
            "affectedResourceIds": list(outcome.affected_resource_ids),
            "operationIds": list(outcome.operation_ids),
        }
    )


@router.get(
    "/books/{book_id}/resources/{resource_id}/reading-units",
    response_model=ReadingUnitsResponse,
)
def list_library_reading_units(
    book_id: str,
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=500),
) -> ReadingUnitsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_book(db, user, book_id) or not can_access_resource(
        db, user, resource_id
    ):
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    resource = resource_view(db, resource_id, user.id)
    if resource is None or resource["bookId"] != book_id:
        return fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
    total = int(
        db.scalar(
            select(func.count())
            .select_from(ReadableResourceNavigationUnit)
            .where(ReadableResourceNavigationUnit.resource_id == resource_id)
        )
        or 0
    )
    normalized_page = max(1, page)
    normalized_size = min(500, max(1, pageSize))
    rows = db.scalars(
        select(ReadableResourceNavigationUnit)
        .where(ReadableResourceNavigationUnit.resource_id == resource_id)
        .order_by(
            ReadableResourceNavigationUnit.sort_order.asc(),
            ReadableResourceNavigationUnit.id.asc(),
        )
        .offset((normalized_page - 1) * normalized_size)
        .limit(normalized_size)
    ).all()
    return ok(
        {
            "bookId": book_id,
            "resourceId": resource_id,
            "units": [
                {
                    "id": row.id,
                    "title": row.title,
                    "href": row.href,
                    "sortOrder": row.sort_order,
                    "unitType": row.unit_type,
                    "assetId": row.asset_id,
                    "metadataJson": row.metadata_json,
                }
                for row in rows
            ],
            "page": {
                "page": normalized_page,
                "pageSize": normalized_size,
                "total": total,
                "totalPages": max(1, (total + normalized_size - 1) // normalized_size),
            },
            "currentHref": None,
            "currentChapterIndex": None,
            "currentChapterTitle": None,
            "currentChapterSortOrder": None,
            "currentPageNumber": None,
            "progress": float(resource.get("progress") or 0),
        }
    )


@router.delete("/assets/{asset_id}", response_model=AssetDeletedResponse)
def delete_library_asset(
    asset_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> AssetDeletedResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    manager_error = _require_manager(user)
    if manager_error:
        return manager_error
    if not can_access_asset(db, user, asset_id):
        return fail("资源资产不存在", status_code=404, code="ASSET_NOT_FOUND")
    asset = db.get(LibraryResourceAsset, asset_id)
    if asset is None:
        return fail("资源资产不存在", status_code=404, code="ASSET_NOT_FOUND")
    resource_id = asset.resource_id
    db.delete(asset)
    db.flush()
    ready_assets = int(
        db.scalar(
            select(func.count())
            .select_from(LibraryResourceAsset)
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
            )
        )
        or 0
    )
    if ready_assets == 0:
        resource = db.get(LibraryReadableResource, resource_id)
        if resource is not None:
            resource.import_state = "FAILED"
    db.commit()
    return ok({"assetId": asset_id, "deleted": True})


__all__ = ["router"]
