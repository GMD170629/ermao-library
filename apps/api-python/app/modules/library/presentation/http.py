"""Library HTTP surface: dashboard, works, series, library management."""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager, require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import enqueue_import_task, import_http_store
from app.bootstrap.library import (
    library_dashboard,
    library_deletion,
    library_facet_queries,
    library_join_queries,
    library_operation_store,
    library_projections,
    library_storage,
    library_works,
    move_volume_to_work,
    reorder_volume,
)
from app.bootstrap.library import (
    list_works as list_library_works,
)
from app.bootstrap.media import media_streaming
from app.bootstrap.shelf import shelf_store
from app.bootstrap.system import prune_system_events, record_system_event
from app.contracts.http_errors import AdditionalStatusCodes, ErrorResponses
from app.contracts.imports import ImportTaskContract
from app.core.authorization import (
    authorization_context,
    can_access_edition,
    can_access_volume,
    can_access_work,
    can_manage_system,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.library.presentation.schemas import (
    BulkMutationResponse,
    CategoriesResponse,
    ContinueReadingResponse,
    ConversionResponse,
    CoverMutationResponse,
    DashboardSummaryResponse,
    DeleteCategoryResponse,
    DeletedWorkResponse,
    DetailPreferenceResponse,
    DuplicatesResponse,
    EditionMutationResponse,
    FacetsResponse,
    FilterSchemaResponse,
    FindReplacePreviewResponse,
    LibraryBadRequestError,
    LibraryConflictError,
    LibraryErrorBody,
    LibraryForbiddenError,
    LibraryNotFoundError,
    LibraryUnavailableError,
    LibraryUnprocessableError,
    ManagementFoldersResponse,
    ManagementOverviewResponse,
    MergeCategoriesResponse,
    MergeDuplicatesResponse,
    MetadataSearchResponse,
    OperationsResponse,
    RenameCategoryResponse,
    SeriesResponse,
    UndoOperationResponse,
    WorkDetailResponse,
    WorkResponse,
    WorksResponse,
    WorkStructureMutationResponse,
    WorkSummariesResponse,
)
from app.modules.library.presentation.views import (
    _active_media_view,
    _apply_remote_cover,
    _book_search_item_view,
    _bookshelf_item_view,
    _coerce_int,
    _edition_media_kind,
    _finish_metadata_organize_work,
    _get_work,
    _management_work_views,
    _metadata_context_for_work,
    _metadata_field_patch,
    _preferred_work_cover_path,
    _require_work_manager,
    _resolve_consumption_target,
    _resolve_detail_tab,
    _set_consumption_status,
    _visible_work_or_none,
    _work_view,
)
from app.modules.library.presentation.work_ops import (
    _delete_work_and_storage,
    _path_tree,
    _source_folder_preview,
)
from app.modules.library.public import (
    WorkListQuery,
    parse_media_kinds,
)
from app.modules.system.presentation.mappers import (
    serialize_system_event as _serialize_system_event,
)
from app.modules.system.public import DETAIL_TAB_KEYS
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    normalize_identity_part,
)
from app.services.default_cover import (
    cover_status,
    ensure_default_cover,
)
from app.services.health import run_system_health_checks
from app.services.library_filters import library_filter_schema
from app.services.library_management import (
    count_categories,
    delete_category,
    duplicate_groups,
    list_categories,
    merge_categories,
    merge_works,
    operation_view,
    rename_category,
    split_edition,
    sync_work_facets,
    undo_operation,
)
from app.services.metadata_provider_registry import (
    metadata_provider_registry,
    search_with_metadata_provider,
)
from app.services.text_conversion import CONVERTIBLE_TEXT_EXTS

router = APIRouter(tags=["library"], route_class=TypedContractRoute)


def _raise_library_error(
    message: str,
    status_code: int = 400,
    *,
    code: str | None = None,
) -> Never:
    body = LibraryErrorBody(message=message, code=code)
    if status_code == 403:
        raise LibraryForbiddenError(body)
    if status_code == 404:
        raise LibraryNotFoundError(body)
    if status_code == 409:
        raise LibraryConflictError(body)
    if status_code == 422:
        raise LibraryUnprocessableError(body)
    if status_code == 503:
        raise LibraryUnavailableError(body)
    raise LibraryBadRequestError(body)


logger = logging.getLogger(__name__)
_stored_path = media_streaming.stored_path


def _now() -> datetime:
    return datetime.now(UTC)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _system_auth(db: Session, request: Request, settings: Settings):
    return require_system_manager(db, request, settings)


def _prune_system_events(db: Session, max_bytes: int | None = None) -> dict[str, int]:
    return prune_system_events(db, max_bytes, commit=True)


def _record_system_event(
    db: Session,
    *,
    level: str = "info",
    source: str,
    action: str,
    message: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_system_event(
        db,
        level=level,
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        message=message,
        metadata=metadata,
        commit=True,
        prune=True,
    )


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _has_column(db: Session, table: str, column: str) -> bool:
    try:
        return any(
            item.get("name") == column
            for item in inspect(db.connection()).get_columns(table)
        )
    except Exception:
        return False


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _nullable_float(value: Any, field_label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_label}格式不正确") from None


def _nullable_int(value: Any, field_label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value) if isinstance(value, str) else value
        if int(parsed) != parsed:
            raise ValueError
        return int(parsed)
    except (TypeError, ValueError):
        raise ValueError(f"{field_label}格式不正确") from None


def _positive_int(value: Any, fallback: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(1, parsed))


async def _request_json_or_empty(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _owned_shelf(db: Session, shelf_id: str, user_id: str) -> dict[str, Any] | None:
    return shelf_store.get_owned_shelf(db, shelf_id, user_id)


def _dt(value: Any) -> str | None:
    from app.core.time import timestamp_ms_to_iso

    if value is None:
        return None
    return timestamp_ms_to_iso(value) or str(value)


@router.get("/dashboard/summary")
def dashboard_summary(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardSummaryResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    context = authorization_context(db, user)
    summary = library_dashboard.dashboard_summary(db, context, user.id)
    return DashboardSummaryResponse(
        data={
            "totalBooks": summary["totalBooks"],
            "comicBooks": summary["comicBooks"],
            "novelBooks": summary["novelBooks"],
            "storageUsedBytes": int(summary["storageUsedBytes"] or 0),
            "monitorFolderCount": summary["monitorFolderCount"],
            "lastImportAt": _dt(summary.get("lastImportAt")),
            "latestSyncAt": _dt(summary.get("latestSyncAt")),
        }
    )


@router.get("/dashboard/recent-books")
def dashboard_recent_books(
    request: Request,
    limit: int = 5,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WorkSummariesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    take = min(24, max(1, limit))
    context = authorization_context(db, user)
    works = library_dashboard.recent_books(db, context, limit=take)
    return WorkSummariesResponse(
        data={"books": [_bookshelf_item_view(work) for work in works]}
    )


@router.get("/dashboard/recent-reading")
def dashboard_recent_reading(
    request: Request,
    limit: int = 10,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WorkSummariesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    take = min(24, max(1, limit))
    context = authorization_context(db, user)
    works = library_dashboard.recent_reading(db, context, user.id, limit=take)
    return WorkSummariesResponse(
        data={"books": [_bookshelf_item_view(work) for work in works]}
    )


@router.get("/dashboard/continue-reading")
def dashboard_continue_reading(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContinueReadingResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    progress = None
    if all(
        _has_table(db, table)
        for table in ("LibraryReadingProgress", "LibraryWork", "LibraryEdition")
    ):
        context = authorization_context(db, user)
        progress = library_dashboard.continue_reading_progress(db, context, user.id)
    if not progress:
        return ContinueReadingResponse(data={"item": None})
    work = _get_work(db, progress["workId"])
    if not work or work.get("hidden"):
        return ContinueReadingResponse(data={"item": None})
    book = _work_view(db, work, user.id)
    recent_edition_id = book.get("recentEditionId")
    media_group = next(
        (
            group
            for group in book.get("mediaGroups") or []
            if group.get("recentEditionId") == recent_edition_id
        ),
        None,
    )
    media_kind = (media_group or {}).get("kind") or (
        "AUDIOBOOK"
        if book.get("type") == "audiobook"
        else "COMIC"
        if book.get("type") == "comic"
        else "EBOOK"
    )
    if media_kind == "AUDIOBOOK":
        audio_group = next(
            (
                group
                for group in book.get("mediaGroups") or []
                if group.get("kind") == "AUDIOBOOK"
            ),
            None,
        )
        resume_edition_id = (
            (audio_group or {}).get("recentEditionId")
            or (audio_group or {}).get("primaryEditionId")
            or next(
                (
                    edition.get("id")
                    for edition in book.get("editions") or []
                    if edition.get("mediaKind") == "AUDIOBOOK"
                ),
                None,
            )
        )
    else:
        resume_edition_id = recent_edition_id or book.get("editionId")
    resume_edition = next(
        (
            edition
            for edition in book.get("editions") or []
            if edition.get("id") == resume_edition_id
        ),
        None,
    )
    chapter = book.get("chapter")
    if chapter == "未开始":
        chapter = None
    return ContinueReadingResponse(
        data={
            "item": {
                "workId": book.get("id"),
                "title": book.get("title"),
                "author": book.get("author"),
                "coverUrl": book.get("coverUrl"),
                "mediaKind": media_kind,
                "resumeEditionId": resume_edition_id,
                "resumeVolumeId": book.get("recentVolumeId"),
                "progress": book.get("progress") or 0,
                "chapter": chapter,
                "lastReadAt": _dt(progress.get("updatedAt")),
                "versionName": (resume_edition or {}).get("versionName"),
                "narrator": (resume_edition or {}).get("narrator"),
            }
        }
    )


@router.get("/management/overview")
def management_overview(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ManagementOverviewResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    health = run_system_health_checks(db, settings)
    event_storage = _prune_system_events(db)
    cards = library_dashboard.management_card_counts(db)
    failed_imports = cards["failedImports"]
    failed_downloads = cards["failedDownloads"]
    pending_organize = cards["pendingOrganize"]
    file_paths = library_dashboard.list_library_file_paths(db)
    orphan_count = 0
    library_root = settings.resolved_storage_root / "library"
    if library_root.exists():
        try:
            for path in library_root.rglob("*"):
                if path.is_file() and str(path) not in file_paths:
                    orphan_count += 1
                    if orphan_count > 1000:
                        break
        except OSError:
            orphan_count = 0
    checks = {item["name"]: item for item in health["checks"]}
    recent_events = library_dashboard.recent_system_events(db, limit=8)
    storage = cards["managedStorageBytes"]
    return ManagementOverviewResponse(
        data={
            "cards": {
                "failedImports": failed_imports,
                "failedDownloads": failed_downloads,
                "orphanFiles": orphan_count,
                "pendingOrganize": pending_organize,
                "managedStorageBytes": int(storage or 0),
                "eventLogSizeBytes": event_storage["sizeBytes"],
                "eventLogMaxBytes": event_storage["maxBytes"],
            },
            "checks": {
                "database": checks.get(
                    "database", {"status": "unknown", "message": "待检测"}
                ),
                "monitorRootReadable": checks.get(
                    "monitorRootReadable", {"status": "unknown", "message": "待检测"}
                ),
                "storageWritable": checks.get(
                    "storageWritable", {"status": "unknown", "message": "待检测"}
                ),
            },
            "recentEvents": [_serialize_system_event(event) for event in recent_events],
        }
    )


@router.get("/management/folders")
def management_folders(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ManagementFoldersResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    monitor_folders = import_http_store.list_monitor_folders(db)
    source_nodes = [
        {**folder, **_source_folder_preview(str(folder.get("rootPath") or ""))}
        for folder in monitor_folders
    ]
    works = library_dashboard.list_management_works(db, limit=300)
    editions = []
    if _has_table(db, "LibraryEdition"):
        from sqlalchemy import func, select

        from app.models.library import LibraryEdition

        editions = [
            {
                "workId": row.workId,
                "sizeBytes": int(row.sizeBytes or 0),
                "editionCount": int(row.editionCount or 0),
            }
            for row in db.execute(
                select(
                    LibraryEdition.work_id.label("workId"),
                    func.coalesce(func.sum(LibraryEdition.size_bytes), 0).label(
                        "sizeBytes"
                    ),
                    func.count().label("editionCount"),
                )
                .where(LibraryEdition.hidden.is_(False))
                .group_by(LibraryEdition.work_id)
            ).all()
        ]
    size_by_work = {row.get("workId"): row for row in editions}
    work_items = [
        {
            **work,
            "sizeBytes": int(
                (size_by_work.get(work.get("id")) or {}).get("sizeBytes") or 0
            ),
            "editionCount": int(
                (size_by_work.get(work.get("id")) or {}).get("editionCount") or 0
            ),
        }
        for work in works
    ]

    def grouped(key: str, fallback: str) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for work in work_items:
            value = str(work.get(key) or fallback).strip() or fallback
            buckets.setdefault(value, []).append(work)
        return [
            {
                "name": name,
                "count": len(items),
                "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items),
                "items": items[:20],
            }
            for name, items in sorted(buckets.items(), key=lambda item: item[0])
        ]

    def grouped_series() -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for work in work_items:
            value = str(work.get("seriesName") or "").strip()
            if not value:
                continue
            buckets.setdefault(value, []).append(work)
        return [
            {
                "name": name,
                "count": len(items),
                "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items),
                "items": items[:20],
            }
            for name, items in sorted(buckets.items(), key=lambda item: item[0])
            if len(items) >= 2
        ]

    source_names = {folder.get("id"): folder.get("name") for folder in monitor_folders}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for work in work_items:
        name = source_names.get(work.get("monitorFolderId")) or "手动导入"
        by_source.setdefault(str(name), []).append(work)
    file_rows = library_dashboard.list_management_file_rows(db, limit=2000)
    managed_paths = []
    storage_root = settings.resolved_storage_root
    for file in file_rows:
        path_value = str(file.get("path") or "")
        try:
            resolved = Path(path_value).resolve()
            managed_paths.append(str(resolved.relative_to(storage_root.resolve())))
        except Exception:
            managed_paths.append(path_value)
    return ManagementFoldersResponse(
        data={
            "logical": {
                "series": grouped_series(),
                "authors": grouped("author", "未知作者"),
                "formats": grouped("workType", "未知格式"),
                "sources": [
                    {
                        "name": name,
                        "count": len(items),
                        "sizeBytes": sum(
                            int(item.get("sizeBytes") or 0) for item in items
                        ),
                        "items": items[:20],
                    }
                    for name, items in sorted(
                        by_source.items(), key=lambda item: item[0]
                    )
                ],
            },
            "disk": {
                "sources": source_nodes,
                "managed": {
                    "rootPath": str(storage_root / "library"),
                    "tree": _path_tree(managed_paths, "library"),
                },
            },
            "works": work_items,
        }
    )


@router.get("/series")
def list_series(
    request: Request,
    visibility: str = "active",
    limit: int = 50,
    minBooks: int = 2,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SeriesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "LibraryWork") or not _has_column(
        db, "LibraryWork", "seriesName"
    ):
        return SeriesResponse(data={"series": [], "total": 0})

    take = min(100, max(1, limit))
    min_books = max(1, minBooks)
    rows, total = library_facet_queries.list_series_groups(
        db,
        authorization_context(db, user),
        visibility=visibility,
        limit=take,
        min_books=min_books,
    )
    return SeriesResponse(
        data={
            "series": [
                {
                    "name": row.get("name"),
                    "bookCount": int(row.get("bookCount") or 0),
                    "latestUpdatedAt": _dt(row.get("latestUpdatedAt")),
                }
                for row in rows
            ],
            "total": total,
        }
    )


@router.get("/works")
def list_works(
    request: Request,
    page: int = 1,
    pageSize: int = 24,
    visibility: str = "active",
    search: str | None = None,
    keyword: str | None = None,
    seriesName: str | None = None,
    sort: str = "updated",
    sortDirection: str | None = None,
    view: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[WorksResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    raw_filters = (request.query_params.get("filters") or "").strip()
    filter_rules: dict[str, Any] | None = None
    if raw_filters:
        try:
            filter_rules = json.loads(raw_filters)
        except json.JSONDecodeError:
            _raise_library_error("筛选规则格式不正确", status_code=400)
    status = (request.query_params.get("status") or "").strip().upper()
    if status == "WANT":
        status = "UNREAD"
    query = WorkListQuery(
        page=page,
        page_size=page_size,
        visibility=visibility,
        search=search,
        keyword=keyword,
        series_name=seriesName,
        sort=sort,
        sort_direction=sortDirection,
        type_filter=(
            request.query_params.get("type") or request.query_params.get("format") or ""
        ).strip(),
        media_kinds=parse_media_kinds(
            (
                request.query_params.get("mediaKinds")
                or request.query_params.get("mediaKind")
                or ""
            ).strip()
        ),
        status=status or None,
        publication_status=(request.query_params.get("publicationStatus") or "")
        .strip()
        .upper()
        or None,
        tracking_status=(request.query_params.get("trackingStatus") or "")
        .strip()
        .upper()
        or None,
        tag=(request.query_params.get("tag") or "").strip() or None,
        missing_cover=(request.query_params.get("missingCover") or "").lower()
        == "true",
        new_import=(request.query_params.get("newImport") or "").lower() == "true",
        filter_rules=filter_rules,
    )
    try:
        result = list_library_works(db, user, query)
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    bookshelf_view = view == "bookshelf"
    search_view = view == "search"
    management_view = view == "management"
    default_direction = (
        "DESC"
        if sort in {"updated", "recent_read", "recent_import", "progress"}
        else "ASC"
    )
    direction = (
        sortDirection.upper()
        if sortDirection and sortDirection.lower() in {"asc", "desc"}
        else default_direction
    )
    if result.progress_sort:
        work_views = [(work, _work_view(db, work, user.id)) for work in result.works]
        work_views.sort(
            key=lambda item: (
                int(item[1].get("progress") or 0),
                item[1].get("lastReadAt") or "",
                _dt(item[0].get("updatedAt")) or "",
                str(item[0].get("id") or ""),
            ),
            reverse=direction == "DESC",
        )
        start = (page - 1) * page_size
        page_items = work_views[start : start + page_size]
        book_views = (
            [_bookshelf_item_view(work) for work, _item_view in page_items]
            if bookshelf_view
            else [_book_search_item_view(work) for work, _item_view in page_items]
            if search_view
            else _management_work_views(
                db, [work for work, _item_view in page_items], user.id
            )
            if management_view
            else [item_view for _work, item_view in page_items]
        )
    else:
        works = result.works
        book_views = (
            [_bookshelf_item_view(work) for work in works]
            if bookshelf_view
            else [_book_search_item_view(work) for work in works]
            if search_view
            else _management_work_views(db, works, user.id)
            if management_view
            else [_work_view(db, work, user.id) for work in works]
        )
    return WorksResponse(
        data={
            "books": book_views,
            "page": result.page,
            "pageSize": result.page_size,
            "total": result.total,
            "totalPages": max(
                1, (result.total + result.page_size - 1) // result.page_size
            ),
        }
    )


@router.get("/works/{work_id}")
def get_work(
    work_id: str,
    request: Request,
    detailTab: str | None = None,
    editionId: str | None = None,
    volumeId: str | None = None,
    unitPage: int | None = None,
    chapterPage: int = 1,
    chapterPageSize: int = 120,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[WorkDetailResponse, ErrorResponses(LibraryNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    work = _visible_work_or_none(db, user, work_id)
    if not work:
        _raise_library_error("作品不存在", status_code=404)
    book = _work_view(db, work, user.id)
    selected_tab = _resolve_detail_tab(
        db, user.id, work_id, book.get("detailTabs", []), detailTab
    )
    book["selectedDetailTab"] = selected_tab
    active_media, navigation = _active_media_view(
        db,
        book,
        selected_tab,
        user.id,
        editionId,
        volumeId,
        unitPage if unitPage is not None else chapterPage,
        chapterPageSize,
    )
    return WorkDetailResponse(
        data={"book": book, "activeMedia": active_media, **navigation}
    )


@router.put("/works/{work_id}/detail-preference")
async def save_work_detail_preference(
    work_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    DetailPreferenceResponse,
    ErrorResponses(
        LibraryBadRequestError,
        LibraryNotFoundError,
        LibraryConflictError,
        LibraryUnavailableError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    work = _visible_work_or_none(db, user, work_id)
    if not work:
        _raise_library_error("作品不存在", status_code=404)
    payload = await request.json()
    requested = str(payload.get("selectedTab") or "").strip().upper()
    book = _work_view(db, work, user.id)
    tabs = book.get("detailTabs", [])
    visible = {str(item.get("key")) for item in tabs}
    if requested not in DETAIL_TAB_KEYS:
        _raise_library_error("详情选项卡无效", status_code=400)
    if requested not in visible:
        _raise_library_error("该作品没有对应的媒介版本", status_code=409)
    now = _now()
    if not _has_table(db, "WorkDetailPreference"):
        _raise_library_error("详情偏好表尚未初始化", status_code=503)
    library_projections.save_detail_preference(
        db,
        user_id=user.id,
        work_id=work_id,
        selected_tab=requested,
        now=now,
    )
    db.commit()
    return DetailPreferenceResponse(
        data={"selectedDetailTab": requested, "detailTabs": tabs}
    )


@router.patch("/works/{work_id}")
async def update_work(
    work_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkResponse,
    ErrorResponses(
        LibraryBadRequestError,
        LibraryForbiddenError,
        LibraryNotFoundError,
        LibraryConflictError,
        LibraryUnprocessableError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    existing_work = _visible_work_or_none(db, user, work_id)
    if not existing_work:
        _raise_library_error("作品不存在", status_code=404)
    allowed = {
        "title",
        "author",
        "description",
        "status",
        "publicationStatus",
        "trackingStatus",
        "tags",
        "seriesName",
        "seriesIndex",
        "publishedYear",
        "hidden",
        "organized",
        "metadataQuality",
    }
    values = {
        key: (_json_text(value) if key == "tags" and isinstance(value, list) else value)
        for key, value in payload.items()
        if key in allowed
    }
    global_fields = set(values) - {"status"}
    if "ignored" in payload:
        global_fields.add("hidden")
    if global_fields and not can_manage_system(user):
        _raise_library_error(
            "需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED"
        )
    media_kind = str(payload.get("mediaKind") or "").strip().upper()
    if media_kind and media_kind not in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        _raise_library_error("媒介类型无效", status_code=400)
    if "status" in values:
        status = str(values["status"] or "").strip().upper()
        if status == "WANT":
            status = "UNREAD"
        if status not in {"UNREAD", "READING", "FINISHED"}:
            _raise_library_error("阅读状态无效", status_code=400)
        book_before_update = _work_view(db, existing_work, user.id)
        available = {
            str(item) for item in book_before_update.get("availableMediaKinds", [])
        }
        target_media_kinds = [media_kind] if media_kind else sorted(available)
        if not target_media_kinds or any(
            kind not in available for kind in target_media_kinds
        ):
            _raise_library_error("该作品没有对应的媒介版本", status_code=409)
        requested_edition_id = str(payload.get("editionId") or "").strip() or None
        requested_volume_id = str(payload.get("volumeId") or "").strip() or None
        if requested_edition_id and not can_access_edition(
            db, user, requested_edition_id
        ):
            _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")
        if requested_volume_id and not can_access_volume(db, user, requested_volume_id):
            _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")
        for target_media_kind in target_media_kinds:
            target, target_error = _resolve_consumption_target(
                db,
                work_id,
                target_media_kind,
                edition_id=requested_edition_id
                if len(target_media_kinds) == 1
                else None,
                volume_id=requested_volume_id if len(target_media_kinds) == 1 else None,
                unit_id=str(payload.get("unitId") or "").strip() or None,
            )
            if target_error:
                _raise_library_error(target_error, status_code=422)
            _set_consumption_status(
                db,
                user.id,
                work_id,
                target_media_kind,
                status,
                edition_id=(target or {}).get("editionId"),
                volume_id=(target or {}).get("volumeId"),
                unit_id=(target or {}).get("unitId"),
            )
        values.pop("status", None)
    if "ignored" in payload:
        values["hidden"] = bool(payload.get("ignored"))
    try:
        if "seriesIndex" in values:
            values["seriesIndex"] = _nullable_float(values["seriesIndex"], "系列序号")
        if "publishedYear" in values:
            values["publishedYear"] = _nullable_int(values["publishedYear"], "出版年")
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    if "title" in values or "author" in values:
        title = str(values.get("title", existing_work.get("title")) or "").strip()
        author = (
            str(values.get("author", existing_work.get("author")) or "").strip()
            or UNKNOWN_AUTHOR
        )
        if not title:
            _raise_library_error("标题不能为空", status_code=400)
        merge_key = identity_merge_key(title, author)
        values.update(
            {
                "title": title,
                "author": author,
                "normalizedTitle": normalize_identity_part(title),
                "normalizedAuthor": normalize_identity_part(author),
                "mergeKey": merge_key,
            }
        )
    if not values:
        db.commit()
        return WorkResponse(data={"book": _work_view(db, existing_work, user.id)})
    work = library_works.update_work_fields(db, work_id, values)
    if not work:
        _raise_library_error("作品不存在", status_code=404)
    sync_work_facets(db, work_id)
    work = _get_work(db, work_id) or work
    return WorkResponse(data={"book": _work_view(db, work, user.id)})


@router.delete("/works/{work_id}")
async def delete_work(
    work_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedWorkResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    payload = await _request_json_or_empty(request)
    delete_source = payload.get("deleteSource") is True
    work = _get_work(db, work_id)
    result = _delete_work_and_storage(
        db, work_id, settings, delete_source=delete_source
    )
    if result.get("deleted"):
        _record_system_event(
            db,
            level="error",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="deleted",
            target_type="work",
            target_id=work_id,
            message=f"删除书库记录：{(work or {}).get('title') or work_id}",
            metadata={
                "workTitle": (work or {}).get("title"),
                "deleteSource": delete_source,
                "deletedFiles": result.get("deletedFiles"),
                "deletedSourceFiles": result.get("deletedSourceFiles"),
                "failedFileDeletes": result.get("failedFileDeletes"),
            },
        )
    return DeletedWorkResponse(data=result)


_BULK_TEXT_FIELDS: dict[str, tuple[str, str]] = {
    "title": ("LibraryWork", "title"),
    "author": ("LibraryWork", "author"),
    "description": ("LibraryWork", "description"),
    "seriesName": ("LibraryWork", "seriesName"),
    "tags": ("LibraryWork", "tags"),
    "publisher": ("LibraryEdition", "publisher"),
    "language": ("LibraryEdition", "language"),
    "isbn": ("LibraryEdition", "isbn"),
    "identifier": ("LibraryEdition", "identifier"),
    "versionName": ("LibraryEdition", "versionName"),
    "narrator": ("LibraryEdition", "narrator"),
}
_BULK_TEMPLATE_VARIABLES = {
    "value",
    "match",
    "index",
    "index0",
    "number",
    "letter",
    "letter_upper",
}
_BULK_TEMPLATE_PATTERN = re.compile(
    r"{{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s*\|\s*(lower|upper|title|trim))?\s*}}"
)


def _bulk_work_ids(raw_ids: Any, *, maximum: int = 500) -> list[str]:
    if not isinstance(raw_ids, list):
        return []
    return list(
        dict.fromkeys(str(item).strip() for item in raw_ids if str(item).strip())
    )[:maximum]


def _primary_edition(db: Session, work_id: str) -> dict[str, Any] | None:
    return library_join_queries.get_primary_edition_row(db, work_id)


def _sequence_letters(value: int) -> str:
    number = max(1, value)
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(97 + remainder) + result
    return result


def _render_bulk_template(
    template: str, *, value: str, match: str, index: int, number: int
) -> str:
    invalid = [
        name
        for name in re.findall(r"{{\s*([^}|\s]+)", template)
        if name not in _BULK_TEMPLATE_VARIABLES
    ]
    if invalid:
        raise ValueError(f"不支持的模板变量：{invalid[0]}")
    context: dict[str, Any] = {
        "value": value,
        "match": match,
        "index": index + 1,
        "index0": index,
        "number": number,
        "letter": _sequence_letters(number),
        "letter_upper": _sequence_letters(number).upper(),
    }

    def replace_variable(template_match: re.Match[str]) -> str:
        variable, filter_name = template_match.groups()
        rendered = str(context[variable])
        if filter_name == "lower":
            return rendered.lower()
        if filter_name == "upper":
            return rendered.upper()
        if filter_name == "title":
            return rendered.title()
        if filter_name == "trim":
            return rendered.strip()
        return rendered

    return _BULK_TEMPLATE_PATTERN.sub(replace_variable, template)


def _bulk_replace_text(
    value: str,
    *,
    find: str,
    replacement: str,
    regex: bool,
    case_sensitive: bool,
    index: int,
    number: int,
) -> str:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(find if regex else re.escape(find), flags)
    except re.error as exc:
        raise ValueError(f"正则表达式无效：{exc}") from None

    def replace_match(match: re.Match[str]) -> str:
        return _render_bulk_template(
            replacement,
            value=value,
            match=match.group(0),
            index=index,
            number=number,
        )

    return pattern.sub(replace_match, value)


def _bulk_find_replace_rows(
    db: Session, payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], str | None]:
    work_ids = _bulk_work_ids(payload.get("ids") or payload.get("bookIds"))
    field = str(payload.get("field") or "").strip()
    find = str(payload.get("find") or "")
    replacement = str(payload.get("replacement") or "")
    if not work_ids:
        return [], "请选择至少一本图书"
    if field not in _BULK_TEXT_FIELDS:
        return [], "请选择可查找替换的元数据字段"
    if not find:
        return [], "查找内容不能为空"
    regex = payload.get("regex") is True
    case_sensitive = payload.get("caseSensitive") is True
    start_number = max(1, _coerce_int(payload.get("startNumber"), 1))
    try:
        _render_bulk_template(
            replacement, value="", match="", index=0, number=start_number
        )
    except ValueError as exc:
        return [], str(exc)
    table, column = _BULK_TEXT_FIELDS[field]
    results: list[dict[str, Any]] = []
    for index, work_id in enumerate(work_ids):
        work = _get_work(db, work_id)
        if not work:
            continue
        target = work if table == "LibraryWork" else _primary_edition(db, work_id)
        if not target:
            continue
        raw_value = target.get(column)
        if field == "tags":
            current_tags = [
                str(item) for item in _parse_json(raw_value, []) if str(item).strip()
            ]
            try:
                next_tags = [
                    _bulk_replace_text(
                        item,
                        find=find,
                        replacement=replacement,
                        regex=regex,
                        case_sensitive=case_sensitive,
                        index=index,
                        number=start_number + index,
                    ).strip()
                    for item in current_tags
                ]
            except ValueError as exc:
                return [], str(exc)
            next_tags = list(dict.fromkeys(item for item in next_tags if item))
            before_value: Any = current_tags
            after_value: Any = next_tags
        else:
            before_value = str(raw_value or "")
            try:
                after_value = _bulk_replace_text(
                    before_value,
                    find=find,
                    replacement=replacement,
                    regex=regex,
                    case_sensitive=case_sensitive,
                    index=index,
                    number=start_number + index,
                )
            except ValueError as exc:
                return [], str(exc)
        if before_value == after_value:
            continue
        results.append(
            {
                "workId": work_id,
                "title": work.get("title") or "未命名图书",
                "targetId": target.get("id"),
                "table": table,
                "column": column,
                "before": before_value,
                "after": after_value,
            }
        )
    return results, None


def _apply_bulk_reading_status(
    db: Session, user: User, work_ids: list[str], status: str
) -> int:
    updated = 0
    now = _now()
    context = authorization_context(db, user)
    for work_id in work_ids:
        work = _get_work(db, work_id)
        if not work:
            continue
        editions = (
            library_works.list_visible_editions_for_work(
                db, work_id=work_id, context=context
            )
            if _has_table(db, "LibraryEdition")
            else []
        )
        if not editions:
            continue
        media_editions: dict[str, dict[str, Any]] = {}
        for edition in editions:
            media_editions.setdefault(_edition_media_kind(edition), edition)
        if status == "UNREAD":
            library_works.clear_reading_state_for_work(
                db,
                user_id=user.id,
                work_id=work_id,
            )
        else:
            for media_kind, edition in media_editions.items():
                _set_consumption_status(
                    db,
                    user.id,
                    work_id,
                    media_kind,
                    status,
                    edition_id=str(edition["id"]),
                )
            if status != "FINISHED":
                updated += 1
                continue
            for edition in editions:
                if not _has_table(db, "LibraryReadingProgress"):
                    continue
                media_kind = _edition_media_kind(edition)
                library_works.mark_edition_finished(
                    db,
                    user_id=user.id,
                    work_id=work_id,
                    edition=edition,
                    reader_type=(
                        "comic"
                        if media_kind == "COMIC"
                        else "audio"
                        if media_kind == "AUDIOBOOK"
                        else "pdf"
                        if str(edition.get("format")).upper() == "PDF"
                        else "epub"
                    ),
                    now=now,
                )
        updated += 1
    db.commit()
    return updated


@router.post("/works/bulk")
async def bulk_works(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BulkMutationResponse,
    ErrorResponses(LibraryBadRequestError, LibraryForbiddenError, LibraryNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    ids = payload.get("ids") or payload.get("bookIds") or []
    action = payload.get("action")
    updated = 0
    if action is None and "ignored" in payload:
        action = "ignore" if payload.get("ignored") else "restore"
    if action is None and payload.get("deleteRecords"):
        action = "delete_records"
    normalized_scope_ids = _bulk_work_ids(ids)
    if normalized_scope_ids:
        inaccessible = [
            work_id
            for work_id in normalized_scope_ids
            if not can_access_work(db, user, work_id)
        ]
        if inaccessible:
            _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    personal_actions = {
        "set_status",
        "reading_status",
        "shelf_membership",
        "add_to_shelf",
        "remove_from_shelf",
    }
    if action not in personal_actions and not can_manage_system(user):
        _raise_library_error(
            "需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED"
        )
    if _has_table(db, "LibraryWork") and ids and action in {"delete", "delete_records"}:
        delete_source = payload.get("deleteSource") is True
        deleted_files = 0
        deleted_source_files = 0
        missing_source_files: list[str] = []
        failed_file_deletes: list[dict[str, str]] = []
        for work_id in normalized_scope_ids:
            result = _delete_work_and_storage(
                db,
                work_id,
                settings,
                delete_source=delete_source,
            )
            if result["deleted"]:
                updated += 1
                deleted_files += int(result.get("deletedFiles") or 0)
                deleted_source_files += int(result.get("deletedSourceFiles") or 0)
                missing_source_files.extend(result.get("missingSourceFiles") or [])
                failed_file_deletes.extend(result.get("failedFileDeletes") or [])
        if updated:
            _record_system_event(
                db,
                level="error",
                source="library",
                actor_type="admin",
                actor_id=user.id,
                action="bulk.deleted",
                target_type="work",
                message=f"批量删除书库记录 {updated} 个",
                metadata={
                    "ids": normalized_scope_ids,
                    "deleteSource": delete_source,
                    "deletedFiles": deleted_files,
                    "deletedSourceFiles": deleted_source_files,
                    "missingSourceFiles": missing_source_files,
                    "failedFileDeletes": failed_file_deletes,
                },
            )
        return BulkMutationResponse(
            data={
                "updated": updated,
                "deleted": updated,
                "deleteSource": delete_source,
                "deletedFiles": deleted_files,
                "deletedSourceFiles": deleted_source_files,
                "missingSourceFiles": missing_source_files,
                "failedFileDeletes": failed_file_deletes,
                "ids": normalized_scope_ids,
            }
        )
    if (
        _has_table(db, "LibraryWork")
        and ids
        and action in {"hide", "ignore", "restore", "unignore", "mark_organized"}
    ):
        hidden = action in {"hide", "ignore"}
        organized = action == "mark_organized"
        for work_id in ids:
            values = (
                {"hidden": hidden}
                if action != "mark_organized"
                else {"organized": organized}
            )
            if library_works.update_work_fields(db, str(work_id), values):
                updated += 1
        if updated:
            _record_system_event(
                db,
                level="info",
                source="library",
                actor_type="admin",
                actor_id=user.id,
                action=f"bulk.{action}",
                target_type="work",
                message=f"批量更新作品 {updated} 个",
                metadata={"ids": ids, "action": action},
            )
    elif (
        _has_table(db, "LibraryWork")
        and ids
        and action
        in {
            "add_tags",
            "remove_tags",
            "set_status",
            "add_to_shelf",
            "remove_from_shelf",
            "update_fields",
            "update_metadata",
            "shelf_membership",
            "reading_status",
            "find_replace",
        }
    ):
        normalized_ids = _bulk_work_ids(ids)
        tags = [
            str(item).strip() for item in payload.get("tags") or [] if str(item).strip()
        ]
        status = str(payload.get("status") or "").strip().upper()
        if action == "set_status" and status not in {"UNREAD", "READING", "FINISHED"}:
            _raise_library_error("阅读状态无效", status_code=400)
        if action == "reading_status" and status not in {"UNREAD", "FINISHED"}:
            _raise_library_error("批量阅读状态仅支持未读或已读", status_code=400)
        shelf_id = str(payload.get("shelfId") or "").strip()
        membership = (
            str(
                payload.get("membership")
                or ("REMOVE" if action == "remove_from_shelf" else "ADD")
            )
            .strip()
            .upper()
        )
        if action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
            shelf = _owned_shelf(db, shelf_id, user.id) if shelf_id else None
            if not shelf or str(shelf.get("kind") or "STATIC").upper() != "STATIC":
                _raise_library_error("请选择普通书架", status_code=400)
            if membership not in {"ADD", "REMOVE"}:
                _raise_library_error("书架操作无效", status_code=400)
        editable = {
            "author",
            "description",
            "publicationStatus",
            "trackingStatus",
            "seriesName",
            "seriesIndex",
            "publishedYear",
        }
        raw_fields = (
            payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        )
        fields = {key: value for key, value in raw_fields.items() if key in editable}
        if action == "find_replace":
            replacements, replace_error = _bulk_find_replace_rows(db, payload)
            if replace_error:
                _raise_library_error(replace_error, status_code=400)
            changed_work_ids: set[str] = set()
            now = _now()
            for replacement in replacements:
                if (
                    replacement["column"] == "versionName"
                    and not str(replacement["after"] or "").strip()
                ):
                    _raise_library_error("版本名称替换后不能为空", status_code=400)
                value = (
                    _json_text(replacement["after"])
                    if replacement["column"] == "tags"
                    else replacement["after"] or None
                )
                if replacement["column"] in {"title", "author"}:
                    work = _get_work(db, replacement["workId"]) or {}
                    title_value = str(
                        value
                        if replacement["column"] == "title"
                        else work.get("title") or ""
                    ).strip()
                    author_value = (
                        str(
                            value
                            if replacement["column"] == "author"
                            else work.get("author") or ""
                        ).strip()
                        or UNKNOWN_AUTHOR
                    )
                    if not title_value:
                        _raise_library_error(
                            "查找替换后的标题不能为空", status_code=400
                        )
                    library_works.update_work_fields(
                        db,
                        str(replacement["workId"]),
                        {
                            "title": title_value,
                            "author": author_value,
                            "normalizedTitle": normalize_identity_part(title_value),
                            "normalizedAuthor": normalize_identity_part(author_value),
                            "mergeKey": identity_merge_key(title_value, author_value),
                            "updatedAt": now,
                        },
                    )
                else:
                    update_values = {
                        replacement["column"]: value,
                        "updatedAt": now,
                    }
                    if replacement["table"] == "LibraryWork":
                        library_works.update_work_fields(
                            db,
                            str(replacement["targetId"]),
                            update_values,
                        )
                    else:
                        library_works.update_edition_fields(
                            db,
                            str(replacement["targetId"]),
                            update_values,
                        )
                changed_work_ids.add(str(replacement["workId"]))
            for work_id in changed_work_ids:
                sync_work_facets(db, work_id, commit=False)
            db.commit()
            updated = len(changed_work_ids)
            if updated:
                _record_system_event(
                    db,
                    level="info",
                    source="library",
                    actor_type="admin",
                    actor_id=user.id,
                    action="bulk.find_replace",
                    target_type="work",
                    message=f"批量查找替换 {updated} 本图书",
                    metadata={
                        "ids": normalized_ids,
                        "field": payload.get("field"),
                        "changedValues": len(replacements),
                    },
                )
            return BulkMutationResponse(
                data={
                    "updated": updated,
                    "changedValues": len(replacements),
                    "ids": normalized_ids,
                }
            )
        if action in {"set_status", "reading_status"}:
            updated = _apply_bulk_reading_status(db, user, normalized_ids, status)
            if updated:
                _record_system_event(
                    db,
                    level="info",
                    source="library",
                    actor_type="user",
                    actor_id=user.id,
                    action=f"bulk.reading_status.{status.lower()}",
                    target_type="work",
                    message=f"批量设置阅读状态 {updated} 本图书",
                    metadata={"ids": normalized_ids, "status": status},
                )
            return BulkMutationResponse(
                data={"updated": updated, "ids": normalized_ids, "status": status}
            )
        metadata_fields = (
            payload.get("fields")
            if action == "update_metadata" and isinstance(payload.get("fields"), dict)
            else {}
        )
        add_tags = [
            str(item).strip()
            for item in payload.get("addTags") or []
            if str(item).strip()
        ]
        remove_tags = [
            str(item).strip()
            for item in payload.get("removeTags") or []
            if str(item).strip()
        ]
        for work_id in normalized_ids:
            work = _get_work(db, work_id)
            if not work:
                continue
            if action in {"add_tags", "remove_tags"}:
                current_tags = [str(item) for item in _parse_json(work.get("tags"), [])]
                if action == "add_tags":
                    next_tags = list(dict.fromkeys([*current_tags, *tags]))
                else:
                    removed = {item.casefold() for item in tags}
                    next_tags = [
                        item for item in current_tags if item.casefold() not in removed
                    ]
                library_works.update_work_fields(
                    db,
                    work_id,
                    {"tags": _json_text(next_tags), "updatedAt": _now()},
                )
            elif action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
                if membership == "ADD":
                    shelf_store.add_shelf_work(
                        db, shelf_id=shelf_id, work_id=work_id, now=_now()
                    )
                else:
                    shelf_store.remove_shelf_work(
                        db, shelf_id=shelf_id, work_id=work_id
                    )
                db.commit()
            elif action == "update_metadata":
                work_values: dict[str, Any] = {"updatedAt": _now()}
                if "author" in metadata_fields:
                    author = (
                        str(metadata_fields.get("author") or "").strip()
                        or UNKNOWN_AUTHOR
                    )
                    work_values.update(
                        {
                            "author": author,
                            "normalizedAuthor": normalize_identity_part(author),
                            "mergeKey": identity_merge_key(
                                str(work.get("title") or ""), author
                            ),
                        }
                    )
                if "seriesName" in metadata_fields:
                    work_values["seriesName"] = (
                        str(metadata_fields.get("seriesName") or "").strip() or None
                    )
                current_tags = [
                    str(item)
                    for item in _parse_json(work.get("tags"), [])
                    if str(item).strip()
                ]
                if add_tags:
                    current_tags = list(dict.fromkeys([*current_tags, *add_tags]))
                if remove_tags:
                    removed = {item.casefold() for item in remove_tags}
                    current_tags = [
                        item for item in current_tags if item.casefold() not in removed
                    ]
                if add_tags or remove_tags:
                    work_values["tags"] = _json_text(current_tags)
                if len(work_values) > 1:
                    library_works.update_work_fields(db, work_id, work_values)
                if "publisher" in metadata_fields:
                    edition = _primary_edition(db, work_id)
                    if edition:
                        library_works.update_edition_fields(
                            db,
                            str(edition["id"]),
                            {
                                "publisher": str(
                                    metadata_fields.get("publisher") or ""
                                ).strip()
                                or None,
                                "updatedAt": _now(),
                            },
                        )
            elif fields:
                library_works.update_work_fields(
                    db,
                    work_id,
                    {**fields, "updatedAt": _now()},
                )
            sync_work_facets(db, work_id)
            updated += 1
        if updated:
            _record_system_event(
                db,
                level="info",
                source="library",
                actor_type="admin",
                actor_id=user.id,
                action=f"bulk.{action}",
                target_type="work",
                message=f"批量更新作品 {updated} 个",
                metadata={"ids": normalized_ids, "action": action},
            )
    return BulkMutationResponse(data={"updated": updated, "ids": ids})


@router.post("/works/bulk/find-replace/preview")
async def preview_bulk_find_replace(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    FindReplacePreviewResponse,
    ErrorResponses(LibraryBadRequestError, LibraryNotFoundError),
]:
    user, auth_error = _system_auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    for work_id in _bulk_work_ids(payload.get("ids") or payload.get("bookIds") or []):
        if not can_access_work(db, user, work_id):
            _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    replacements, replace_error = _bulk_find_replace_rows(db, payload)
    if replace_error:
        _raise_library_error(replace_error, status_code=400)
    return FindReplacePreviewResponse(
        data={
            "changedWorks": len({item["workId"] for item in replacements}),
            "changedValues": len(replacements),
            "items": replacements[:30],
        }
    )


def _prepare_cover_image(
    image: Image.Image, *, ratio: str | None, max_dimension: int, quality: int
) -> tuple[Image.Image, int]:
    prepared = ImageOps.exif_transpose(image).convert("RGB")
    ratios = {"2:3": 2 / 3, "3:4": 3 / 4, "1:1": 1.0}
    target_ratio = ratios.get(str(ratio or ""))
    if target_ratio:
        width, height = prepared.size
        current_ratio = width / height if height else target_ratio
        if current_ratio > target_ratio:
            crop_width = max(1, round(height * target_ratio))
            left = max(0, (width - crop_width) // 2)
            prepared = prepared.crop((left, 0, left + crop_width, height))
        elif current_ratio < target_ratio:
            crop_height = max(1, round(width / target_ratio))
            top = max(0, (height - crop_height) // 2)
            prepared = prepared.crop((0, top, width, top + crop_height))
    if max(prepared.size) > max_dimension:
        prepared.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    return prepared, quality


@router.post("/works/bulk/cover")
async def bulk_work_covers(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BulkMutationResponse, ErrorResponses(LibraryBadRequestError, LibraryNotFoundError)
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    form = await request.form()
    try:
        raw_ids = json.loads(str(form.get("ids") or "[]"))
    except json.JSONDecodeError:
        _raise_library_error("图书选择无效", status_code=400)
    work_ids = _bulk_work_ids(raw_ids)
    action = str(form.get("action") or "").strip().lower()
    if not work_ids:
        _raise_library_error("请选择至少一本图书", status_code=400)
    if any(not can_access_work(db, user, work_id) for work_id in work_ids):
        _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    if action not in {"crop", "regenerate", "compress", "replace"}:
        _raise_library_error("封面操作无效", status_code=400)
    ratio = str(form.get("ratio") or "2:3")
    if action == "crop" and ratio not in {"2:3", "3:4", "1:1"}:
        _raise_library_error("封面裁剪比例无效", status_code=400)
    quality = max(40, min(95, _coerce_int(form.get("quality"), 82)))
    max_dimension = max(600, min(3200, _coerce_int(form.get("maxDimension"), 1600)))
    upload = form.get("cover")
    uploaded_image: Image.Image | None = None
    if action == "replace":
        if not upload or not hasattr(upload, "read"):
            _raise_library_error("请选择替换封面", status_code=400)
        raw_image = await upload.read()
        if not raw_image or len(raw_image) > 12 * 1024 * 1024:
            _raise_library_error("封面文件为空或超过 12 MB", status_code=400)
        try:
            uploaded_image = Image.open(io.BytesIO(raw_image))
            uploaded_image.load()
        except (UnidentifiedImageError, OSError):
            _raise_library_error("封面文件不是可识别的图片", status_code=400)

    target_dir = settings.resolved_storage_root / "covers" / "bulk"
    target_dir.mkdir(parents=True, exist_ok=True)
    created_paths: list[Path] = []
    pending_updates: list[tuple[str, str, str]] = []
    skipped: list[dict[str, str]] = []
    try:
        for work_id in work_ids:
            work = _get_work(db, work_id)
            if not work:
                skipped.append({"workId": work_id, "reason": "作品不存在"})
                continue
            if action == "regenerate":
                relative = _preferred_work_cover_path(
                    db, work_id
                ) or ensure_default_cover(settings)
                path = _stored_path(relative, settings)
                if path is None or not path.is_file():
                    relative = ensure_default_cover(settings)
                pending_updates.append(
                    (work_id, relative, cover_status(relative, settings))
                )
                continue
            source_image: Image.Image
            if uploaded_image is not None:
                source_image = uploaded_image.copy()
            else:
                source_relative = str(
                    work.get("coverPath")
                    or _preferred_work_cover_path(db, work_id)
                    or ensure_default_cover(settings)
                )
                source_path = _stored_path(source_relative, settings)
                if source_path is None or not source_path.is_file():
                    source_path = _stored_path(ensure_default_cover(settings), settings)
                if source_path is None:
                    skipped.append({"workId": work_id, "reason": "找不到可处理的封面"})
                    continue
                try:
                    source_image = Image.open(source_path)
                    source_image.load()
                except (UnidentifiedImageError, OSError):
                    skipped.append({"workId": work_id, "reason": "当前封面无法读取"})
                    continue
            processed, output_quality = _prepare_cover_image(
                source_image,
                ratio=ratio if action == "crop" else None,
                max_dimension=max_dimension,
                quality=quality,
            )
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", work_id)[:100] or "work"
            target = target_dir / f"{safe_id}-{time_ns()}.jpg"
            processed.save(
                target,
                format="JPEG",
                quality=output_quality,
                optimize=True,
                progressive=True,
            )
            created_paths.append(target)
            relative = str(target.relative_to(settings.resolved_storage_root))
            pending_updates.append((work_id, relative, "READY"))
        now = _now()
        for work_id, relative, status in pending_updates:
            library_storage.update_work_cover(
                db,
                work_id=work_id,
                cover_path=relative,
                cover_status=status,
                now=now,
            )
        db.commit()
    except Exception:
        db.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    updated = len(pending_updates)
    if updated:
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action=f"bulk.cover.{action}",
            target_type="work",
            message=f"批量处理封面 {updated} 本图书",
            metadata={
                "ids": work_ids,
                "action": action,
                "ratio": ratio if action == "crop" else None,
                "quality": quality,
                "maxDimension": max_dimension,
                "skipped": skipped,
            },
        )
    return BulkMutationResponse(
        data={
            "updated": updated,
            "ids": [item[0] for item in pending_updates],
            "skipped": skipped,
        }
    )


@router.post("/works/{work_id}/cover/upload")
async def upload_cover(
    work_id: str,
    request: Request,
    cover: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CoverMutationResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    target_dir = settings.resolved_storage_root / "covers"
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(cover.filename or "cover.jpg").suffix or ".jpg"
    target = target_dir / f"{work_id}{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(cover.file, handle)
    relative = str(target.relative_to(settings.resolved_storage_root))
    library_storage.update_work_cover(
        db,
        work_id=work_id,
        cover_path=relative,
        cover_status="READY",
        now=_now(),
    )
    db.commit()
    return CoverMutationResponse(
        data={
            "bookId": work_id,
            "coverUrl": f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}",
        }
    )


@router.post("/works/{work_id}/cover/regenerate")
def regenerate_cover(
    work_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[CoverMutationResponse, ErrorResponses(LibraryNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    work = _get_work(db, work_id)
    if not work:
        _raise_library_error("作品不存在", status_code=404)
    cover_path = _preferred_work_cover_path(db, work_id) or ensure_default_cover(
        settings
    )
    if (
        _stored_path(cover_path, settings) is None
        or not _stored_path(cover_path, settings).is_file()
    ):
        cover_path = ensure_default_cover(settings)
    library_storage.update_work_cover(
        db,
        work_id=work_id,
        cover_path=cover_path,
        cover_status=cover_status(cover_path, settings),
        now=_now(),
    )
    db.commit()
    return CoverMutationResponse(
        data={
            "bookId": work_id,
            "coverUrl": f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}",
        }
    )


@router.get("/library/facets")
def library_facets(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FacetsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    facets = {
        kind.lower(): _visible_categories(db, user, kind)
        for kind in ("AUTHOR", "TAG", "SERIES", "PUBLISHER")
    }
    context = authorization_context(db, user)
    visible_works = library_facet_queries.list_visible_works(db, context)
    status_counts: dict[str, int] = {}
    for work in visible_works:
        status = str(_work_view(db, work, user.id).get("status") or "UNREAD")
        status_counts[status] = status_counts.get(status, 0) + 1
    status_rows = [
        {"value": value, "label": value, "count": count}
        for value, count in sorted(status_counts.items())
    ]
    media_rows = [
        {**row, "label": str(row.get("value") or "")}
        for row in library_facet_queries.media_kind_counts(db, context)
    ]
    return FacetsResponse(
        data={"facets": facets, "statuses": status_rows, "mediaKinds": media_rows}
    )


def _visible_categories(db: Session, user: User, kind: str) -> list[dict[str, Any]]:
    normalized_kind = kind.upper()
    if user.role == "admin":
        return list_categories(db, normalized_kind)
    context = authorization_context(db, user)
    rows = library_facet_queries.visible_categories(db, context, normalized_kind)
    return [
        {
            **row,
            "aliases": _parse_json(row.get("aliases"), []),
            "bookCount": int(row.get("bookCount") or 0),
        }
        for row in rows
    ]


def _scoped_filter_schema(db: Session, user: User) -> dict[str, Any]:
    schema = library_filter_schema(db)
    context = authorization_context(db, user)
    options_by_source: dict[str, list[dict[str, Any]]] = {}
    if context.is_admin:
        options_by_source = {}
    else:
        work_rows = library_facet_queries.visible_work_option_rows(db, context)
        edition_rows = library_facet_queries.visible_edition_option_rows(db, context)

        def counted(values: list[str]) -> list[dict[str, Any]]:
            counts: dict[str, int] = {}
            for value in values:
                normalized = value.strip()
                if normalized:
                    counts[normalized] = counts.get(normalized, 0) + 1
            return [
                {"value": value, "label": value, "count": count}
                for value, count in sorted(
                    counts.items(), key=lambda item: (-item[1], item[0].casefold())
                )
            ]

        authors = [
            part.strip()
            for row in work_rows
            for part in re.split(r"[、,，;/；|]+", str(row.get("author") or ""))
            if part.strip()
        ]
        tags = [
            str(tag).strip()
            for row in work_rows
            for tag in _parse_json(row.get("tags"), [])
            if str(tag).strip()
        ]
        options_by_source.update(
            {
                "authors": counted(authors),
                "tags": counted(tags),
                "series": counted(
                    [str(row.get("seriesName") or "") for row in work_rows]
                ),
                "publishers": counted(
                    [str(row.get("publisher") or "") for row in edition_rows]
                ),
                "languages": counted(
                    [str(row.get("language") or "") for row in edition_rows]
                ),
                "formats": counted(
                    [str(row.get("format") or "") for row in edition_rows]
                ),
                "importStatuses": counted(
                    [str(row.get("importStatus") or "") for row in edition_rows]
                ),
                "origins": counted(
                    [
                        *[str(row.get("origin") or "") for row in work_rows],
                        *[str(row.get("origin") or "") for row in edition_rows],
                    ]
                ),
            }
        )
        visible_media_kinds = {str(row.get("mediaKind") or "") for row in edition_rows}
        existing_media = next(
            (
                field.get("options", [])
                for field in schema["fields"]
                if field.get("optionSource") == "mediaKinds"
            ),
            [],
        )
        options_by_source["mediaKinds"] = [
            option
            for option in existing_media
            if option.get("value") in visible_media_kinds
        ]

    if context.is_admin:
        monitor_rows = sorted(
            (
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "rootPath": row.get("rootPath"),
                }
                for row in import_http_store.list_monitor_folders(db)
            ),
            key=lambda row: str(row.get("name") or "").casefold(),
        )
    elif context.monitor_folder_ids:
        allowed = set(context.monitor_folder_ids)
        monitor_rows = sorted(
            (
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "rootPath": row.get("rootPath"),
                }
                for row in import_http_store.list_monitor_folders(db)
                if str(row.get("id")) in allowed
            ),
            key=lambda row: str(row.get("name") or "").casefold(),
        )
    else:
        monitor_rows = []
    options_by_source["monitorFolders"] = [
        {
            "value": str(row["id"]),
            "label": str(row["name"]),
            "rootPath": row.get("rootPath"),
        }
        for row in monitor_rows
    ]
    shelf_rows = shelf_store.list_shelves_for_user(db, user.id)
    options_by_source["shelves"] = [
        {"value": str(row["id"]), "label": str(row["name"])}
        for row in sorted(
            (
                row
                for row in shelf_rows
                if str(row.get("kind") or "STATIC").upper() == "STATIC"
            ),
            key=lambda row: str(row.get("name") or "").casefold(),
        )
    ]
    schema["fields"] = [
        {
            **field,
            "options": options_by_source.get(
                str(field.get("optionSource")), field.get("options", [])
            ),
        }
        for field in schema["fields"]
    ]
    return schema


@router.get("/library/filter-schema")
def library_filter_options(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FilterSchemaResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return FilterSchemaResponse(data=_scoped_filter_schema(db, user))


@router.get("/library/categories")
def library_categories(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[CategoriesResponse, ErrorResponses(LibraryBadRequestError)]:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        kind = request.query_params.get("kind", "TAG")
        search = request.query_params.get("search", "")
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("pageSize", "20"))))
        total = count_categories(db, kind, search)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        items = list_categories(
            db, kind, search, limit=page_size, offset=(page - 1) * page_size
        )
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return CategoriesResponse(
        data={
            "categories": items,
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
        }
    )


@router.patch("/library/categories/{facet_id}")
async def update_library_category(
    facet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[RenameCategoryResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        result = rename_category(db, facet_id, str(payload.get("name") or ""), user.id)
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return RenameCategoryResponse(data=result)


@router.delete("/library/categories/{facet_id}")
def delete_library_category(
    facet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[DeleteCategoryResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = delete_category(db, facet_id, user.id)
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return DeleteCategoryResponse(data=result)


@router.post("/library/categories/merge")
async def merge_library_categories(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[MergeCategoriesResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        result = merge_categories(
            db,
            str(payload.get("kind") or "TAG"),
            [str(item) for item in payload.get("sourceIds") or []],
            str(payload.get("targetId") or ""),
            user.id,
        )
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return MergeCategoriesResponse(data=result)


@router.get("/library/duplicates")
def library_duplicates(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DuplicatesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    groups = duplicate_groups(db)
    for group in groups:
        group["works"] = [
            _work_view(db, work, user.id) for work in group.get("works") or []
        ]
    return DuplicatesResponse(data={"groups": groups, "total": len(groups)})


@router.post("/library/duplicates/merge")
async def merge_library_duplicates(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[MergeDuplicatesResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        result = merge_works(
            db,
            str(payload.get("targetWorkId") or ""),
            [str(item) for item in payload.get("sourceWorkIds") or []],
            user.id,
        )
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return MergeDuplicatesResponse(data=result)


@router.get("/library/operations")
def library_operations(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OperationsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    operations = library_operation_store.list_operations_for_user(db, user.id)
    return OperationsResponse(
        data={"operations": [operation_view(item) for item in operations]}
    )


@router.post("/library/operations/{operation_id}/undo")
def undo_library_operation(
    operation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[UndoOperationResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = undo_operation(db, operation_id, user.id)
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return UndoOperationResponse(data=result)


@router.post("/works/{work_id}/metadata/search")
async def metadata_search(
    work_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    MetadataSearchResponse, ErrorResponses(LibraryBadRequestError, LibraryNotFoundError)
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    payload = await request.json()
    source = str(payload.get("providerId") or payload.get("source") or "bangumi")
    if source not in metadata_provider_registry().ids():
        _raise_library_error("不支持的元数据来源", status_code=400)
    job, context = _metadata_context_for_work(db, work_id)
    if not job or not context:
        _raise_library_error("读物不存在或无权访问", status_code=404)
    query = str(payload.get("query") or "").strip() or None
    try:
        result = search_with_metadata_provider(db, context, source, query)
    except Exception as exc:
        _raise_library_error(str(exc), status_code=400)
    candidates = result.get("candidates") or []
    return MetadataSearchResponse(
        data={
            "candidates": candidates,
            "results": candidates,
            "query": query or context["work"].get("title"),
            "source": source,
            "message": result.get("message"),
        }
    )


@router.patch("/works/{work_id}/editions/{edition_id}")
async def update_work_edition(
    work_id: str,
    edition_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[EditionMutationResponse, ErrorResponses(LibraryNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    if not can_access_edition(db, user, edition_id):
        _raise_library_error(
            "版本不存在或不属于该作品", status_code=404, code="EDITION_NOT_FOUND"
        )
    edition = (
        library_works.get_visible_edition_for_work(
            db,
            edition_id=edition_id,
            work_id=work_id,
        )
        if _has_table(db, "LibraryEdition")
        else None
    )
    if not edition:
        _raise_library_error("版本不存在或不属于该作品", status_code=404)
    payload = await request.json()
    allowed = {
        "versionName",
        "description",
        "publisher",
        "publishedAt",
        "language",
        "identifier",
        "isbn",
        "narrator",
        "abridged",
    }
    values = {key: payload.get(key) for key in allowed if key in payload}
    for key in (
        "versionName",
        "publisher",
        "language",
        "identifier",
        "isbn",
        "narrator",
    ):
        if key in values:
            values[key] = str(values[key] or "").strip() or None
    values["updatedAt"] = _now()
    library_works.update_edition_fields(db, edition_id, values)
    sync_work_facets(db, work_id, commit=False)
    db.commit()
    work = _get_work(db, work_id)
    book = _work_view(db, work, user.id) if work else None
    updated_edition = next(
        (
            item
            for item in (book or {}).get("editions", [])
            if str(item.get("id")) == edition_id
        ),
        None,
    )
    if updated_edition is None:
        _raise_library_error("版本不存在或不属于该作品", status_code=404)
    return EditionMutationResponse(data={"edition": updated_edition, "book": book})


@router.post("/works/{work_id}/editions/{edition_id}/convert")
def convert_work_edition(
    work_id: str,
    edition_id: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ConversionResponse,
    AdditionalStatusCodes(202),
    ErrorResponses(LibraryBadRequestError, LibraryNotFoundError, LibraryConflictError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    if not can_access_edition(db, user, edition_id):
        _raise_library_error(
            "版本不存在或不属于该作品", status_code=404, code="EDITION_NOT_FOUND"
        )
    work = _get_work(db, work_id)
    edition = library_deletion.get_edition_for_work(
        db,
        edition_id=edition_id,
        work_id=work_id,
    )
    if edition and bool(edition.get("hidden")):
        edition = None
    if not work or not edition:
        _raise_library_error("版本不存在或不属于该作品", status_code=404)
    source_format = str(edition.get("format") or "").strip().lower()
    if f".{source_format}" not in CONVERTIBLE_TEXT_EXTS:
        _raise_library_error("该版本不支持转换为 EPUB", status_code=400)
    source_file = library_storage.first_file_for_edition(
        db,
        edition_id=edition_id,
    )
    source_path = Path(str((source_file or {}).get("path") or "")).expanduser()
    if not source_file or not source_path.is_file():
        _raise_library_error("原始文件不存在，无法转换", status_code=409)
    task, created = enqueue_import_task(
        db,
        source_path,
        origin="DEFERRED_CONVERSION",
        original_name=source_path.name,
        requested_title=str(work.get("title") or "").strip() or None,
        requested_author=str(work.get("author") or "").strip() or None,
        work_id=work_id,
        monitor_folder_id=edition.get("monitorFolderId"),
        message="已加入 EPUB 转换队列",
        allow_terminal_requeue=True,
    )
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="conversion.queued",
        target_type="importTask",
        target_id=task.id,
        message=f"加入后置转换队列：{source_path.name}",
        metadata={
            "workId": work_id,
            "editionId": edition_id,
            "sourceFormat": source_format.upper(),
        },
    )
    response.status_code = 202
    return ConversionResponse(
        data={"task": ImportTaskContract.from_dto(task).to_wire(), "created": created}
    )


@router.post("/works/{work_id}/metadata/apply")
@router.post("/works/{work_id}/editions/{edition_id}/primary")
@router.post("/works/{work_id}/editions/{edition_id}/split")
@router.post("/works/{work_id}/volumes/{volume_id}/move-to")
@router.post("/works/{work_id}/volumes/{volume_id}/move")
async def compatible_work_action(
    work_id: str,
    request: Request,
    edition_id: str | None = None,
    volume_id: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(LibraryBadRequestError, LibraryNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    if edition_id and not can_access_edition(db, user, edition_id):
        _raise_library_error(
            "版本不存在或不属于该作品", status_code=404, code="EDITION_NOT_FOUND"
        )
    if volume_id and not can_access_volume(db, user, volume_id):
        _raise_library_error(
            "卷不存在或不属于该作品", status_code=404, code="VOLUME_NOT_FOUND"
        )
    if request.url.path.endswith("/metadata/apply"):
        payload = await request.json()
        candidate = (
            payload.get("candidate")
            if isinstance(payload.get("candidate"), dict)
            else {}
        )
        fields = [str(field) for field in payload.get("fields") or []]
        if not candidate or not fields:
            _raise_library_error("请选择要应用的元数据字段", status_code=400)
        existing_work = _get_work(db, work_id)
        if not existing_work:
            _raise_library_error("作品不存在", status_code=404)
        patch = _metadata_field_patch(candidate, fields)
        if "title" in patch or "author" in patch:
            title = str(patch.get("title", existing_work.get("title")) or "").strip()
            author = (
                str(patch.get("author", existing_work.get("author")) or "").strip()
                or UNKNOWN_AUTHOR
            )
            merge_key = identity_merge_key(title, author)
            patch.update(
                {
                    "title": title,
                    "author": author,
                    "normalizedTitle": normalize_identity_part(title),
                    "normalizedAuthor": normalize_identity_part(author),
                    "mergeKey": merge_key,
                }
            )
        publisher = (
            str(candidate.get("publisher") or "").strip()
            if "publisher" in fields
            else ""
        )
        if (
            "coverUrl" in fields
            and isinstance(candidate.get("coverUrl"), str)
            and candidate.get("coverUrl").strip()
        ):
            try:
                patch.update(
                    _apply_remote_cover(
                        work_id, candidate["coverUrl"].strip(), settings
                    )
                )
            except Exception as exc:
                logger.warning(
                    "failed to apply remote cover work=%s url=%s error=%s",
                    work_id,
                    candidate.get("coverUrl"),
                    exc,
                )
        if not patch and not publisher:
            _raise_library_error("候选中没有可应用的字段", status_code=400)
        patch.update(
            {
                "organized": True,
                "organizeStatus": "APPLIED",
                "metadataQuality": 85,
                "updatedAt": _now(),
            }
        )
        work = library_works.update_work_fields(db, work_id, patch)
        if not work:
            _raise_library_error("作品不存在", status_code=404)
        if publisher and _has_table(db, "LibraryEdition"):
            primary_edition_id = str(work.get("primaryEditionId") or "")
            if not primary_edition_id:
                first_editions = library_works.list_visible_editions_for_work(
                    db,
                    work_id=work_id,
                )
                primary_edition_id = str(
                    (first_editions[0] if first_editions else {}).get("id") or ""
                )
            if primary_edition_id:
                library_works.update_edition_fields(
                    db,
                    primary_edition_id,
                    {"publisher": publisher, "updatedAt": _now()},
                )
        sync_work_facets(db, work_id, commit=False)
        finished_job_ids = _finish_metadata_organize_work(db, work_id)
        db.commit()
        return WorkStructureMutationResponse(
            data={
                "book": _work_view(db, work, user.id),
                "appliedFields": fields,
                "finishedOrganizeJobIds": finished_job_ids,
            }
        )
    if request.url.path.endswith("/split"):
        payload = await request.json()
        try:
            result = split_edition(
                db,
                work_id,
                str(edition_id or ""),
                title=str(payload.get("title") or ""),
                author=str(payload.get("author") or "").strip() or None,
                copy_shelves=payload.get("copyShelves") is not False,
                user_id=user.id,
            )
        except ValueError as exc:
            _raise_library_error(str(exc), status_code=400)
        return WorkStructureMutationResponse(data=result)
    if request.url.path.endswith("/primary") and edition_id:
        edition = (
            library_projections.get_edition(db, edition_id)
            if _has_table(db, "LibraryEdition")
            else None
        )
        if edition and (
            str(edition.get("workId") or "") != work_id or bool(edition.get("hidden"))
        ):
            edition = None
        if not edition:
            _raise_library_error("版本不存在或不属于该作品", status_code=404)
        if not _get_work(db, work_id):
            _raise_library_error("作品不存在", status_code=404)
        now = _now()
        media_kind = _edition_media_kind(edition)
        has_media_kind = _has_column(db, "LibraryEdition", "mediaKind")
        compatible_formats = (
            None
            if has_media_kind
            else (
                ("EPUB", "PDF") if media_kind == "EBOOK" else (edition.get("format"),)
            )
        )
        library_works.clear_primary_for_media_kind(
            db,
            work_id=work_id,
            media_kind=media_kind,
            formats=compatible_formats,
            now=now,
            has_media_kind_column=has_media_kind,
        )
        library_works.mark_edition_primary_for_work(
            db,
            work_id=work_id,
            edition_id=edition_id,
            work_type=edition.get("format") or "EPUB",
            now=now,
        )
        db.commit()
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="edition.primary",
            target_type="edition",
            target_id=edition_id,
            message="已更新主版本",
            metadata={"workId": work_id, "editionId": edition_id},
        )
        work = _get_work(db, work_id)
        return WorkStructureMutationResponse(
            data={
                "book": _work_view(db, work, user.id) if work else None,
                "workId": work_id,
                "editionId": edition_id,
            }
        )
    if request.url.path.endswith("/move-to") and volume_id:
        payload = await request.json()
        target_edition_id = str(payload.get("targetEditionId") or "").strip()
        if not target_edition_id:
            _raise_library_error("请选择目标版本", status_code=400)
        source = library_join_queries.get_volume_for_work(
            db, volume_id=volume_id, work_id=work_id
        )
        if not source:
            _raise_library_error("卷册不存在或不属于该作品", status_code=404)
        target = library_join_queries.get_edition_with_work_title(db, target_edition_id)
        if not target:
            _raise_library_error("目标版本不存在", status_code=404)
        target_work_id = target.get("workId")
        if target_work_id == work_id:
            _raise_library_error("请选择另一部目标图书", status_code=400)
        result = move_volume_to_work(
            db,
            source_work_id=work_id,
            volume_id=volume_id,
            target_work_id=str(target_work_id),
            source_format=str(source.get("sourceFormat") or ""),
            now=_now(),
        )
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="volume.moved" if result.merged_volume else "edition.moved",
            target_type="volume" if result.merged_volume else "edition",
            target_id=volume_id if result.merged_volume else result.source_edition_id,
            message=("合并卷册" if result.merged_volume else "转移版本")
            + f"到《{target.get('targetWorkTitle') or target_work_id}》",
            metadata={
                "sourceWorkId": work_id,
                "targetWorkId": target_work_id,
                "sourceEditionId": result.source_edition_id,
                "targetEditionId": result.target_edition_id,
                "transferMode": result.transfer_mode,
            },
        )
        source_work = _get_work(db, work_id)
        target_work = _get_work(db, target_work_id) if target_work_id else None
        return WorkStructureMutationResponse(
            data={
                "book": _work_view(db, source_work, user.id) if source_work else None,
                "targetBook": _work_view(db, target_work, user.id)
                if target_work
                else None,
                "workId": work_id,
                "targetWorkId": target_work_id,
                "volumeId": volume_id,
                "targetEditionId": result.target_edition_id,
                "transferMode": result.transfer_mode,
            }
        )
    if request.url.path.endswith("/move") and volume_id:
        payload = await request.json()
        direction = str(payload.get("direction") or "").lower()
        if direction not in {"up", "down"}:
            _raise_library_error("请选择上移或下移", status_code=400)
        volume = library_join_queries.get_volume_belonging_to_work(
            db, volume_id=volume_id, work_id=work_id
        )
        if not volume:
            _raise_library_error("卷册不存在或不属于该作品", status_code=404)
        changed = reorder_volume(
            db,
            volume_id=volume_id,
            edition_id=str(volume["editionId"]),
            direction=direction,
            now=_now(),
        )
        if not changed:
            work = _get_work(db, work_id)
            return WorkStructureMutationResponse(
                data={
                    "book": _work_view(db, work, user.id) if work else None,
                    "workId": work_id,
                    "volumeId": volume_id,
                }
            )
        db.commit()
        work = _get_work(db, work_id)
        return WorkStructureMutationResponse(
            data={
                "book": _work_view(db, work, user.id) if work else None,
                "workId": work_id,
                "volumeId": volume_id,
            }
        )
    work = _get_work(db, work_id)
    return WorkStructureMutationResponse(
        data={
            "book": _work_view(db, work, user.id) if work else None,
            "workId": work_id,
            "editionId": edition_id,
            "volumeId": volume_id,
        }
    )
