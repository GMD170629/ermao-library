"""Book, ReadableResource, and ResourceAsset HTTP adapters."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.library import (
    browse_book_contents,
    delete_resource_asset,
    list_books,
    recognize_source_node_metadata,
    resource_metadata,
    update_book,
    update_source_node_metadata,
    update_source_node_presentation,
)
from app.bootstrap.library_resource_actions import regenerate_resource_cover
from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline
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
    ReadableResourceNavigationUnit,
)
from app.models.auth import User
from app.modules.library.application.asset_commands import (
    ResourceAssetNotFoundError,
)
from app.modules.library.application.book_commands import UpdateBookCommand
from app.modules.library.application.book_contents import (
    BookContentNode,
    BookContentsNotFoundError,
)
from app.modules.library.application.book_list import BookListQuery, parse_media_kinds
from app.modules.library.application.filter_ast import (
    InvalidFilterExpression,
    parse_filter_expression,
)
from app.modules.library.application.resource_commands import (
    BookNotFoundError,
    InvalidResourceChangeError,
    LibraryActor,
    LibraryAuthorizationError,
    ResourceMetadataChanges,
    ResourceNotFoundError,
    SetResourceMediaKindsCommand,
    reclassify_resource,
    set_resource_media_kinds,
    update_resource,
)
from app.modules.library.application.resource_cover import (
    RegenerateResourceCoverCommand,
)
from app.modules.library.application.source_node_commands import (
    MAX_SOURCE_NODE_COVER_BYTES,
    SourceNodeMetadataChanges,
)
from app.modules.library.presentation.schemas import (
    AssetDeletedResponse,
    AssetsPayload,
    AssetsResponse,
    BookContentEntryView,
    BookContentsPayload,
    BookContentsResponse,
    BookPayload,
    BookResponse,
    BookshelfBookSummary,
    BooksPayload,
    BooksResponse,
    BookView,
    ManagementBookListSummary,
    ReadingUnitsResponse,
    ReclassifyResourceRequest,
    ResourceAssetView,
    ResourceBatchRequest,
    ResourceBatchResponse,
    ResourceDeletedResponse,
    ResourceImportAcceptedResponse,
    ResourcePayload,
    ResourceReclassifyResponse,
    ResourceResponse,
    ResourceSourceDeleteRequest,
    ResourcesPayload,
    ResourcesResponse,
    ResourceView,
    SourceNodeMetadataCandidateView,
    SourceNodeMetadataSearchPayload,
    SourceNodeMetadataSearchRequest,
    SourceNodeMetadataSearchResponse,
    SourceNodeMetadataUpdatedPayload,
    SourceNodeMetadataUpdatedResponse,
    UpdateBookRequest,
    UpdateResourceRequest,
    UpdateSourceNodeMetadataRequest,
)
from app.modules.library.presentation.views import (
    book_view,
    bookshelf_book_list_view,
    get_book,
    list_resource_views,
    management_book_list_view,
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


def _book_contract(value: object) -> BookView:
    return BookView.model_validate(value)


def _bookshelf_book_contract(value: object) -> BookshelfBookSummary:
    return BookshelfBookSummary.model_validate(value)


def _management_book_contract(value: object) -> ManagementBookListSummary:
    return ManagementBookListSummary.model_validate(value)


def _resource_contract(value: object) -> ResourceView:
    return ResourceView.model_validate(value)


def _asset_contract(value: object) -> ResourceAssetView:
    return ResourceAssetView.model_validate(value)


def _book_response(value: object) -> BookResponse:
    return cast(BookResponse, value)


def _books_response(value: object) -> BooksResponse:
    return cast(BooksResponse, value)


def _resources_response(value: object) -> ResourcesResponse:
    return cast(ResourcesResponse, value)


def _book_contents_response(value: object) -> BookContentsResponse:
    return cast(BookContentsResponse, value)


def _source_node_updated_response(value: object) -> SourceNodeMetadataUpdatedResponse:
    return cast(SourceNodeMetadataUpdatedResponse, value)


def _source_node_search_response(value: object) -> SourceNodeMetadataSearchResponse:
    return cast(SourceNodeMetadataSearchResponse, value)


def _book_content_entry(value: object) -> BookContentEntryView:
    return BookContentEntryView.model_validate(value)


def _resource_response(value: object) -> ResourceResponse:
    return cast(ResourceResponse, value)


def _assets_response(value: object) -> AssetsResponse:
    return cast(AssetsResponse, value)


def _import_response(value: object) -> ResourceImportAcceptedResponse:
    return cast(ResourceImportAcceptedResponse, value)


def _deleted_response(value: object) -> ResourceDeletedResponse:
    return cast(ResourceDeletedResponse, value)


def _reclassify_response(value: object) -> ResourceReclassifyResponse:
    return cast(ResourceReclassifyResponse, value)


def _batch_response(value: object) -> ResourceBatchResponse:
    return cast(ResourceBatchResponse, value)


def _reading_units_response(value: object) -> ReadingUnitsResponse:
    return cast(ReadingUnitsResponse, value)


def _asset_deleted_response(value: object) -> AssetDeletedResponse:
    return cast(AssetDeletedResponse, value)


@router.get("/books", response_model=BooksResponse)
def list_library_books(
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=0, le=500),
    search: str | None = None,
    sort: str = "updated",
    sortDirection: Literal["asc", "desc"] | None = None,
    visibility: Literal["active", "ignored"] = "active",
    type_filter: str = Query(default="", alias="type"),
    media: str | None = None,
    status: str | None = None,
    seriesName: str | None = None,
    facetKind: str | None = None,
    facetId: str | None = None,
    filters: str | None = None,
    view: Literal["full", "bookshelf", "management", "search"] = "full",
) -> BooksResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return _books_response(auth_error)
    filter_expression = None
    if filters:
        try:
            filter_payload = json.loads(filters)
            filter_expression = parse_filter_expression(filter_payload)
        except (InvalidFilterExpression, json.JSONDecodeError, TypeError, ValueError):
            return _books_response(
                fail(
                    "筛选参数无效",
                    status_code=422,
                    code="INVALID_LIBRARY_FILTER",
                )
            )
    result = list_books(
        db,
        user,
        BookListQuery(
            page=page,
            requested_page_size=pageSize if pageSize > 0 else None,
            search=search,
            keyword=None,
            sort=sort,
            sort_direction=sortDirection,
            visibility=visibility,
            type_filter=type_filter,
            media_kinds=parse_media_kinds(media or ""),
            status=status,
            series_name=seriesName,
            facet_kind=facetKind,
            facet_id=facetId,
            filter_expression=filter_expression,
            projection=view,
        ),
    )
    books: list[BookView | BookshelfBookSummary | ManagementBookListSummary] = []
    if view in {"bookshelf", "search"}:
        for item in result.books:
            books.append(_bookshelf_book_contract(bookshelf_book_list_view(item)))
    elif view == "management":
        for item in result.books:
            books.append(_management_book_contract(management_book_list_view(item)))
    else:
        for item in result.books:
            books.append(_book_contract(book_view(db, dict(item), user.id)))
    return BooksResponse(
        data=BooksPayload(
            books=books,
            page=result.page,
            pageSize=result.page_size,
            total=result.total,
            totalPages=result.total_pages,
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
        return _book_response(auth_error)
    if not can_access_book(db, user, book_id):
        return _book_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    book = get_book(db, book_id)
    if book is None:
        return _book_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    return BookResponse(
        data=BookPayload(book=_book_contract(book_view(db, dict(book), user.id)))
    )


@router.get("/books/{book_id}/contents", response_model=BookContentsResponse)
def browse_library_book_contents(
    book_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    sourceNodeId: str | None = None,
    sort: Literal["name", "type", "updated", "size"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=100, ge=1, le=200),
) -> BookContentsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return _book_contents_response(auth_error)
    if not can_access_book(db, user, book_id):
        return _book_contents_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    try:
        result = browse_book_contents(db).execute(
            book_id=book_id,
            source_node_id=sourceNodeId,
            sort=sort,
            direction=direction,
            page=page,
            page_size=pageSize,
        )
    except BookContentsNotFoundError:
        return _book_contents_response(
            fail("图书目录不存在", status_code=404, code="BOOK_CONTENTS_NOT_FOUND")
        )

    def entry(node: BookContentNode) -> BookContentEntryView:
        values = asdict(node)
        physical_kind = str(values.pop("physical_kind"))
        cover_path = values.pop("cover_path", None)
        values["kind"] = "FOLDER" if physical_kind == "DIRECTORY" else "FILE"
        values["physicalKind"] = physical_kind
        values["coverUrl"] = (
            f"/api/books/{quote(book_id, safe='')}/source-nodes/"
            f"{quote(str(values['source_node_id']), safe='')}/cover"
            if cover_path
            else None
        )
        values.pop("library_id", None)
        return _book_content_entry(values)

    return BookContentsResponse(
        data=BookContentsPayload(
            bookId=result.book_id,
            currentSourceNodeId=result.current_source_node_id,
            currentResourceId=result.current_resource_id,
            currentNode=entry(result.current_node),
            currentResourceIds=list(result.current_resource_ids),
            parentSourceNodeId=result.parent_source_node_id,
            breadcrumbs=[entry(node) for node in result.breadcrumbs],
            entries=[entry(node) for node in result.entries],
            page=result.page,
            pageSize=result.page_size,
            total=result.total,
            totalPages=max(
                1, (result.total + result.page_size - 1) // result.page_size
            ),
        )
    )


@router.patch(
    "/books/{book_id}/source-nodes/{source_node_id}",
    response_model=SourceNodeMetadataUpdatedResponse,
)
def update_book_source_node_metadata(
    book_id: str,
    source_node_id: str,
    payload: UpdateSourceNodeMetadataRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> SourceNodeMetadataUpdatedResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return _source_node_updated_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _source_node_updated_response(manager_error)
    if not can_access_book(db, user, book_id):
        return _source_node_updated_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    try:
        updated = update_source_node_metadata(db).execute(
            book_id=book_id,
            source_node_id=source_node_id,
            changes=SourceNodeMetadataChanges(
                title=payload.title,
                description=payload.description,
            ),
        )
    except ValueError:
        return _source_node_updated_response(
            fail("版本标题不能为空", status_code=400, code="INVALID_SOURCE_NODE_TITLE")
        )
    if not updated:
        return _source_node_updated_response(
            fail("版本不存在", status_code=404, code="SOURCE_NODE_NOT_FOUND")
        )
    return SourceNodeMetadataUpdatedResponse(
        data=SourceNodeMetadataUpdatedPayload(
            sourceNodeId=source_node_id,
            updated=True,
        )
    )


@router.put(
    "/books/{book_id}/source-nodes/{source_node_id}",
    response_model=SourceNodeMetadataUpdatedResponse,
)
async def update_book_source_node_presentation(
    book_id: str,
    source_node_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
    title: Annotated[str, Form(min_length=1, max_length=500)],
    description: Annotated[str | None, Form(max_length=10_000)] = None,
    removeCover: Annotated[bool, Form()] = False,
    cover: Annotated[UploadFile | None, File()] = None,
) -> SourceNodeMetadataUpdatedResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return _source_node_updated_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _source_node_updated_response(manager_error)
    if not can_access_book(db, user, book_id):
        return _source_node_updated_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    cover_content = None
    if cover is not None:
        cover_content = await cover.read(MAX_SOURCE_NODE_COVER_BYTES + 1)
        await cover.close()
    try:
        updated = update_source_node_presentation(db, settings).execute(
            book_id=book_id,
            source_node_id=source_node_id,
            title=title,
            description=description,
            cover_content=cover_content,
            remove_cover=removeCover,
        )
    except ValueError:
        return _source_node_updated_response(
            fail(
                "目录封面必须是不超过 10 MB 的 JPEG、PNG 或 WebP 图片",
                status_code=400,
                code="INVALID_SOURCE_NODE_COVER",
            )
        )
    if not updated:
        return _source_node_updated_response(
            fail("版本不存在", status_code=404, code="SOURCE_NODE_NOT_FOUND")
        )
    return SourceNodeMetadataUpdatedResponse(
        data=SourceNodeMetadataUpdatedPayload(
            sourceNodeId=source_node_id,
            updated=True,
        )
    )


@router.post(
    "/books/{book_id}/source-nodes/{source_node_id}/metadata/search",
    response_model=SourceNodeMetadataSearchResponse,
)
def search_book_source_node_metadata(
    book_id: str,
    source_node_id: str,
    payload: SourceNodeMetadataSearchRequest,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> SourceNodeMetadataSearchResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return _source_node_search_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _source_node_search_response(manager_error)
    if not can_access_book(db, user, book_id):
        return _source_node_search_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    try:
        result = recognize_source_node_metadata(db).execute(
            book_id=book_id,
            source_node_id=source_node_id,
            provider_id=payload.provider_id,
            query=payload.query,
        )
    except (LookupError, ValueError) as exc:
        return _source_node_search_response(
            fail(
                str(exc) or "元数据识别失败",
                status_code=400,
                code="METADATA_SEARCH_FAILED",
            )
        )
    if result is None:
        return _source_node_search_response(
            fail("版本不存在", status_code=404, code="SOURCE_NODE_NOT_FOUND")
        )
    return SourceNodeMetadataSearchResponse(
        data=SourceNodeMetadataSearchPayload(
            sourceNodeId=result.source_node_id,
            providerId=result.provider_id,
            query=result.query,
            message=result.message,
            candidates=[
                SourceNodeMetadataCandidateView(
                    id=candidate.id,
                    source=candidate.source,
                    title=candidate.title,
                    description=candidate.description,
                    coverUrl=candidate.cover_url,
                    confidence=candidate.confidence,
                )
                for candidate in result.candidates
            ],
        )
    )


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
        return _book_response(auth_error)
    if not can_access_book(db, user, book_id):
        return _book_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    values = payload.model_dump(by_alias=True, exclude_none=True, exclude_unset=True)
    book = update_book(db).execute(UpdateBookCommand(book_id=book_id, values=values))
    if book is None:
        return _book_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    return BookResponse(
        data=BookPayload(book=_book_contract(book_view(db, dict(book), user.id)))
    )


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
        return _resources_response(auth_error)
    if not can_access_book(db, user, book_id):
        return _resources_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    book = get_book(db, book_id)
    if book is None:
        return _resources_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
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
            resources=[_resource_contract(resource) for resource in resources],
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
        return _resource_response(auth_error)
    if not can_access_resource(db, user, resource_id):
        return _resource_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    resource = resource_view(db, resource_id, user.id)
    if resource is None:
        return _resource_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    return ResourceResponse(data=ResourcePayload(resource=_resource_contract(resource)))


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
        return _assets_response(auth_error)
    if not can_access_resource(db, user, resource_id):
        return _assets_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    resource = resource_view(db, resource_id, user.id)
    if resource is None:
        return _assets_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    all_assets = [_asset_contract(asset) for asset in resource["assets"]]
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
            totalPages=max(
                1, (len(all_assets) + normalized_size - 1) // normalized_size
            ),
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
        return _resource_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _resource_response(manager_error)
    if not can_access_book(db, user, book_id):
        return _resource_response(
            fail("图书不存在", status_code=404, code="BOOK_NOT_FOUND")
        )
    if not can_access_resource(db, user, resource_id):
        return _resource_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    resource_book_id = db.scalar(
        select(LibraryReadableResource.book_id).where(
            LibraryReadableResource.id == resource_id
        )
    )
    if resource_book_id != book_id:
        return _resource_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    changes = cast(
        ResourceMetadataChanges,
        payload.model_dump(exclude_unset=True, by_alias=False),
    )
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
        return _resource_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    except (LibraryAuthorizationError, InvalidResourceChangeError) as exc:
        return _resource_response(fail(str(exc) or "资源参数无效", status_code=400))
    updated = resource_view(db, resource_id, user.id)
    if updated is None:
        return _resource_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    return ResourceResponse(data=ResourcePayload(resource=_resource_contract(updated)))


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
        return _import_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _import_response(manager_error)
    if not can_access_book(db, user, book_id) or not can_access_resource(
        db, user, resource_id
    ):
        return _import_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    try:
        result = regenerate_resource_cover(db).execute(
            RegenerateResourceCoverCommand(
                book_id=book_id,
                resource_id=resource_id,
                now=datetime.now(UTC),
            )
        )
    except ResourceNotFoundError:
        return _import_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    return _import_response(
        ok(
            {
                "resourceId": resource_id,
                "accepted": True,
                "taskId": result.task_id,
            },
            status_code=202,
        )
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
        return _deleted_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _deleted_response(manager_error)
    if not payload.confirmation.strip():
        return _deleted_response(
            fail("删除确认不能为空", status_code=400, code="CONFIRMATION_REQUIRED")
        )
    if not can_access_book(db, user, book_id) or not can_access_resource(
        db, user, resource_id
    ):
        return _deleted_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    resource = db.get(LibraryReadableResource, resource_id)
    if resource is None or resource.book_id != book_id:
        return _deleted_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    result = build_readable_resource_pipeline(db).delete_source_node.execute(
        resource.source_node_id
    )
    if not result.ok:
        return _deleted_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    return _deleted_response(ok({"resourceId": resource_id, "deleted": True}))


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
        return _reclassify_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _reclassify_response(manager_error)
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
        return _reclassify_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    except (LibraryAuthorizationError, InvalidResourceChangeError) as exc:
        return _reclassify_response(fail(str(exc) or "资源参数无效", status_code=400))
    return _reclassify_response(
        ok(
            {
                "affectedResourceIds": list(outcome.affected_resource_ids),
                "operation": asdict(outcome.operation),
            }
        )
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
        return _batch_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _batch_response(manager_error)
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
        return _batch_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    except (LibraryAuthorizationError, InvalidResourceChangeError) as exc:
        return _batch_response(fail(str(exc) or "资源参数无效", status_code=400))
    return _batch_response(
        ok(
            {
                "affectedResourceIds": list(outcome.affected_resource_ids),
                "operationIds": list(outcome.operation_ids),
            }
        )
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
        return _reading_units_response(auth_error)
    if not can_access_book(db, user, book_id) or not can_access_resource(
        db, user, resource_id
    ):
        return _reading_units_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
    resource = resource_view(db, resource_id, user.id)
    if resource is None or resource["bookId"] != book_id:
        return _reading_units_response(
            fail("资源不存在", status_code=404, code="RESOURCE_NOT_FOUND")
        )
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
    return _reading_units_response(
        ok(
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
                    "totalPages": max(
                        1, (total + normalized_size - 1) // normalized_size
                    ),
                },
                "currentHref": None,
                "currentChapterIndex": None,
                "currentChapterTitle": None,
                "currentChapterSortOrder": None,
                "currentPageNumber": None,
                "progress": float(resource.get("progress") or 0),
            }
        )
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
        return _asset_deleted_response(auth_error)
    manager_error = _require_manager(user)
    if manager_error:
        return _asset_deleted_response(manager_error)
    if not can_access_asset(db, user, asset_id):
        return _asset_deleted_response(
            fail("资源资产不存在", status_code=404, code="ASSET_NOT_FOUND")
        )
    try:
        result = delete_resource_asset(db).execute(asset_id=asset_id)
    except ResourceAssetNotFoundError:
        return _asset_deleted_response(
            fail("资源资产不存在", status_code=404, code="ASSET_NOT_FOUND")
        )
    return _asset_deleted_response(
        ok({"assetId": result.asset_id, "deleted": result.deleted})
    )


__all__ = ["router"]
