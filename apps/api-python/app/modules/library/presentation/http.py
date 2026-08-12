"""Library HTTP surface: dashboard, works, series, library management."""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager, require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import import_http_store
from app.bootstrap.library import (
    PreparedWorkFacetWrite,
    library_cover_publication,
    library_dashboard,
    library_facet_queries,
    library_facet_references,
    library_groupings,
    library_operation_store,
    library_works,
    load_metadata_apply_job_ids,
    load_work_facet_projections,
    prepare_work_facet_write,
    volume_structure_commands,
    work_merge_gateway,
)
from app.bootstrap.library import (
    bookshelf_items as get_bookshelf_items,
)
from app.bootstrap.library import (
    library_filter_options as search_library_filter_options,
)
from app.bootstrap.library import (
    library_filter_schema as get_library_filter_schema,
)
from app.bootstrap.library import (
    library_request_mutations as get_library_request_mutations,
)
from app.bootstrap.library import (
    list_works as list_library_works,
)
from app.bootstrap.media import media_streaming
from app.bootstrap.metadata import (
    load_metadata_writeback_projection,
)
from app.bootstrap.shelf import shelf_store
from app.bootstrap.system import (
    prepare_system_event,
    system_event_storage_view,
)
from app.contracts.http_errors import ErrorResponses
from app.contracts.retired_resources import RetiredResourceError, retired_resource_error
from app.core.authorization import (
    authorization_context,
    can_access_volume,
    can_access_work,
    can_manage_system,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.models.library import (
    LibraryMediaVersion,
    LibraryVolume,
)
from app.modules.library.application.filter_options import LibraryFilterOptionSource
from app.modules.library.application.request_mutations import (
    ApplyWorkMetadata,
    BulkReadingStatusMutation,
    BulkShelfMembershipMutation,
    BulkWorkMutation,
    CompensateCoverPublication,
    CoverMutation,
    CoverPublicationFailure,
    CoverRecordMutation,
    DetailPreferenceMutation,
    LibraryRequestMutationGateway,
    MetadataApplyMutation,
    SaveDetailPreference,
    UpdateBulkReadingStatus,
    UpdateBulkShelfMembership,
    UpdateBulkWorks,
    UpdateCoverRecords,
    UpdateWorkRecord,
    WorkRecordMutation,
)
from app.modules.library.application.volume_commands import (
    BatchVolumeCommand,
    InvalidVolumeChangeError,
    LibraryActor,
    LibraryAuthorizationError,
    NewWorkInput,
    OperationSummary,
    VolumeNotFoundError,
    WorkNotFoundError,
    batch_volume_resources,
    delete_volume_resource,
    move_volume_resource,
    reclassify_volume_resource,
    reorder_volume_resource,
    split_volume_resource,
    update_volume_resource,
)
from app.modules.library.application.work_merge import (
    CreateMergedWork,
    MergeCommand,
    MergeMetadata,
    PreviewWorkMerge,
    WorkMergeError,
    WorkMergeInProgressError,
    WorkMergeNotFoundError,
)
from app.modules.library.presentation.filter_mappers import (
    filter_options_payload,
    filter_schema_payload,
)
from app.modules.library.presentation.schemas import (
    BatchSetMediaKindRequest,
    BatchTransferVolumesRequest,
    BatchVolumeMutationResponse,
    BatchVolumeRequest,
    BulkCoverRequest,
    BulkFindReplaceRequest,
    BulkMutationResponse,
    BulkWorkRequest,
    CategoriesResponse,
    ContinueReadingResponse,
    CoverMutationResponse,
    CreateWorkMergeRequest,
    DashboardSummaryResponse,
    DeleteCategoryResponse,
    DeletedWorkResponse,
    DetailPreferenceResponse,
    DuplicatesResponse,
    FacetsResponse,
    FilterOptionsResponse,
    FilterSchemaResponse,
    FindReplacePreviewResponse,
    LibraryBadRequestError,
    LibraryConflictError,
    LibraryErrorBody,
    LibraryForbiddenError,
    LibraryGroupingsResponse,
    LibraryNotFoundError,
    LibraryUnavailableError,
    LibraryUnprocessableError,
    ManagementFoldersResponse,
    ManagementOverviewResponse,
    MergeCategoriesRequest,
    MergeCategoriesResponse,
    MergeDuplicatesRequest,
    MergeDuplicatesResponse,
    MetadataApplyRequest,
    MetadataApplyResponse,
    MetadataSearchRequest,
    MetadataSearchResponse,
    MoveVolumeRequest,
    OperationsResponse,
    ReclassifyVolumeRequest,
    RenameCategoryRequest,
    RenameCategoryResponse,
    ReorderVolumeRequest,
    SaveDetailPreferenceRequest,
    SeriesResponse,
    SplitVolumeRequest,
    UndoOperationResponse,
    UpdateVolumeRequest,
    UpdateWorkRequest,
    WorkDetailResponse,
    WorkDetailSummaryResponse,
    WorkMergePreviewResponse,
    WorkMergeResponse,
    WorkMergeSelectionRequest,
    WorkReadingUnitsResponse,
    WorkResponse,
    WorksResponse,
    WorkStructureMutationResponse,
    WorkSummariesResponse,
    WorkVolumePageResponse,
)
from app.modules.library.presentation.views import (
    _active_media_view,
    _coerce_int,
    _cover_url,
    _get_work,
    _management_work_views,
    _metadata_context_for_work,
    _metadata_field_patch,
    _preferred_work_cover_path,
    _require_work_manager,
    _resolve_detail_tab,
    _visible_work_or_none,
    _work_detail_summary_view,
    _work_reading_units_view,
    _work_view,
    _work_views,
    _work_volume_page_view,
    bookshelf_item_views,
)
from app.modules.library.presentation.work_ops import (
    _delete_work_and_storage,
    _delete_works_and_storage,
    _path_tree,
    _source_folder_preview,
)
from app.modules.library.public import (
    InvalidFilterExpression,
    WorkFacetProjection,
    WorkListQuery,
    parse_filter_expression,
    parse_media_kinds,
    prepare_work_facet,
)
from app.modules.metadata.public import (
    MetadataWritebackProjection,
    PreparedWritebackIntent,
    prepare_metadata_writeback_intents,
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
from app.services.library_management import (
    delete_category,
    duplicate_groups_page,
    list_categories,
    list_categories_page,
    merge_categories,
    merge_works,
    operation_view,
    rename_category,
    undo_operation,
)
from app.services.metadata_file_writeback import (
    metadata_writeback_view,
)
from app.services.metadata_provider_registry import (
    metadata_provider_registry,
    search_with_metadata_provider,
)

router = APIRouter(tags=["library"], route_class=TypedContractRoute)


def _request_mutations(db: Session) -> LibraryRequestMutationGateway:
    return get_library_request_mutations(db)


def _library_actor(db: Session, user: User) -> LibraryActor:
    context = authorization_context(db, user)
    return LibraryActor(
        user_id=context.user_id,
        can_manage_system=context.can_manage_system,
        is_admin=context.is_admin,
        can_view_manual_imports=context.can_view_manual_imports,
        monitor_folder_ids=context.monitor_folder_ids,
    )


def _operation_payload(operation: OperationSummary) -> dict[str, object]:
    return {
        "id": operation.id,
        "action": operation.action,
        "status": operation.status,
        "summary": operation.summary,
        "expiresAt": operation.expires_at,
        "undoAvailable": operation.undo_available,
    }


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


def _raise_edition_resource_retired() -> Never:
    raise retired_resource_error("/api/works/{workId}/volumes/{volumeId}")


logger = logging.getLogger(__name__)
_stored_path = media_streaming.stored_path


def _now() -> datetime:
    return datetime.now(UTC)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _system_auth(db: Session, request: Request, settings: Settings):
    return require_system_manager(db, request, settings)


def _updated_metadata_projection(
    projection: MetadataWritebackProjection,
    values: dict[str, Any],
) -> MetadataWritebackProjection:
    changes: dict[str, Any] = {}
    for source_name, projection_name in (
        ("title", "title"),
        ("author", "author"),
        ("description", "description"),
        ("tags", "tags_json"),
        ("seriesName", "series_name"),
        ("seriesIndex", "series_index"),
        ("coverPath", "cover_path"),
        ("updatedAt", "source_revision"),
    ):
        if source_name in values:
            changes[projection_name] = values[source_name]
    return replace(projection, **changes) if changes else projection


def _prepare_work_writebacks(
    db: Session,
    *,
    work_id: str,
    source: str,
    values: dict[str, Any] | None = None,
    media_version_id: str | None = None,
    volume_id: str | None = None,
    volume_values_by_id: dict[str, dict[str, Any]] | None = None,
) -> tuple[PreparedWritebackIntent, ...]:
    projection = load_metadata_writeback_projection(
        db,
        work_id=work_id,
        media_version_id=media_version_id,
        volume_id=volume_id,
    )
    projection = _updated_metadata_projection(projection, values or {})
    if volume_values_by_id:
        projection = replace(
            projection,
            volumes=tuple(
                replace(volume, **volume_values_by_id.get(volume.id, {}))
                for volume in projection.volumes
            ),
        )
    return prepare_metadata_writeback_intents(
        projection,
        source=source,
        volume_id=volume_id,
    )


def _prepare_facet_write_for_updates(
    db: Session,
    updates: tuple[tuple[str, dict[str, Any]], ...],
    *,
    now: datetime,
) -> PreparedWorkFacetWrite:
    """Load once, then finish all facet parsing before the first write."""

    projections = {
        projection.work_id: projection
        for projection in load_work_facet_projections(
            db, tuple(work_id for work_id, _values in updates)
        )
    }
    prepared = []
    for work_id, values in updates:
        projection = projections.get(work_id)
        if projection is None:
            continue
        prepared.append(
            prepare_work_facet(
                WorkFacetProjection(
                    work_id=work_id,
                    author=(
                        str(values["author"])
                        if values.get("author") is not None
                        else None
                    )
                    if "author" in values
                    else projection.author,
                    tags_source=(
                        str(values.get("tags") or "[]")
                        if "tags" in values
                        else projection.tags_source
                    ),
                    series_name=(
                        str(values["seriesName"])
                        if values.get("seriesName") is not None
                        else None
                    )
                    if "seriesName" in values
                    else projection.series_name,
                )
            )
        )
    return prepare_work_facet_write(tuple(prepared), now=now)


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


def _bookshelf_views(
    db: Session,
    user: User,
    works: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries = get_bookshelf_items(db).execute(
        context=authorization_context(db, user),
        work_ids=tuple(str(work["id"]) for work in works),
    )
    return bookshelf_item_views(summaries)


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
            "ebookBooks": summary["ebookBooks"],
            "comicBooks": summary["comicBooks"],
            "audiobookBooks": summary["audiobookBooks"],
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
    return WorkSummariesResponse(data={"books": _bookshelf_views(db, user, works)})


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
    return WorkSummariesResponse(data={"books": _bookshelf_views(db, user, works)})


@router.get("/dashboard/continue-reading")
def dashboard_continue_reading(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContinueReadingResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    context = authorization_context(db, user)
    progress = library_dashboard.continue_reading_progress(db, context, user.id)
    if not progress:
        return ContinueReadingResponse(data={"item": None})
    work_id = str(progress.get("workId") or "")
    work_summary = {
        "id": work_id,
        "coverPath": progress.get("coverPath"),
        "updatedAt": progress.get("workUpdatedAt"),
    }
    return ContinueReadingResponse(
        data={
            "item": {
                "workId": work_id,
                "title": progress.get("title") or "未命名作品",
                "author": progress.get("author") or "未知作者",
                "coverUrl": _cover_url("works", work_id, work_summary, size="medium"),
                "mediaKind": progress.get("mediaKind"),
                "volumeFormat": progress.get("volumeFormat"),
                "readerType": progress.get("readerType"),
                "resumeVolumeId": progress.get("volumeId"),
                "progress": float(progress.get("percent") or 0),
                "chapter": None,
                "lastReadAt": _dt(progress.get("updatedAt")),
                "volumeTitle": progress.get("volumeTitle"),
                "narrator": progress.get("narrator"),
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
    event_storage = system_event_storage_view(db)
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
    from sqlalchemy import func

    volumes = [
        {
            "workId": row.workId,
            "sizeBytes": int(row.sizeBytes or 0),
            "volumeCount": int(row.volumeCount or 0),
        }
        for row in db.execute(
            select(
                LibraryMediaVersion.work_id.label("workId"),
                func.coalesce(func.sum(LibraryVolume.size_bytes), 0).label("sizeBytes"),
                func.count().label("volumeCount"),
            )
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .where(LibraryVolume.hidden.is_(False))
            .group_by(LibraryMediaVersion.work_id)
        ).all()
    ]
    size_by_work = {row.get("workId"): row for row in volumes}
    work_items = [
        {
            **work,
            "sizeBytes": int(
                (size_by_work.get(work.get("id")) or {}).get("sizeBytes") or 0
            ),
            "volumeCount": int(
                (size_by_work.get(work.get("id")) or {}).get("volumeCount") or 0
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

    def grouped_media_kinds() -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for work in work_items:
            for media_kind in work.get("availableMediaKinds") or []:
                buckets.setdefault(str(media_kind), []).append(work)
        return [
            {
                "name": name,
                "count": len(items),
                "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items),
                "items": items[:20],
            }
            for name, items in sorted(buckets.items(), key=lambda item: item[0])
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
                "formats": grouped_media_kinds(),
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


@router.get("/library/groupings")
def list_library_groupings(
    request: Request,
    kind: str,
    page: int = 1,
    pageSize: int = 50,
    search: str = "",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    LibraryGroupingsResponse,
    ErrorResponses(LibraryBadRequestError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    normalized_page = max(1, page)
    normalized_page_size = min(100, max(1, pageSize))
    try:
        result = library_groupings(db).execute(
            kind=kind,
            context=authorization_context(db, user),
            search=search,
            page=normalized_page,
            page_size=normalized_page_size,
        )
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return LibraryGroupingsResponse(
        data={
            "kind": kind.strip().upper(),
            "groups": [
                {
                    "id": group.id,
                    "name": group.name,
                    "bookCount": group.book_count,
                    "updatedAt": group.updated_at,
                    "representativeWorks": [
                        {
                            "id": work.id,
                            "title": work.title,
                            "author": work.author,
                            "coverUrl": _cover_url(
                                "works",
                                work.id,
                                {
                                    "coverPath": work.cover_path,
                                    "updatedAt": work.updated_at,
                                },
                                size="medium",
                            ),
                        }
                        for work in group.representative_works
                    ],
                }
                for group in result.groups
            ],
            "page": normalized_page,
            "pageSize": normalized_page_size,
            "total": result.total,
            "totalPages": max(
                1,
                (result.total + normalized_page_size - 1) // normalized_page_size,
            ),
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
    page_size = None if pageSize == 0 else pageSize
    raw_filters = (request.query_params.get("filters") or "").strip()
    filter_expression = None
    if raw_filters:
        try:
            decoded_filters = json.loads(raw_filters)
        except json.JSONDecodeError:
            _raise_library_error("筛选规则格式不正确", status_code=400)
        try:
            filter_expression = parse_filter_expression(decoded_filters)
        except InvalidFilterExpression as exc:
            message = str(exc)
            _raise_library_error(
                message,
                status_code=400,
                code=(
                    "UNSUPPORTED_FILTER_DIMENSION"
                    if message.startswith("不支持的筛选维度：")
                    else "INVALID_FILTER_EXPRESSION"
                ),
            )
    status = (request.query_params.get("status") or "").strip().upper()
    if status == "WANT":
        status = "UNREAD"
    statuses = tuple(
        dict.fromkeys(
            "UNREAD" if item.strip().upper() == "WANT" else item.strip().upper()
            for item in (request.query_params.get("statuses") or "").split(",")
            if item.strip()
        )
    )
    facet_kind = (request.query_params.get("facetKind") or "").strip().upper()
    facet_id = (request.query_params.get("facetId") or "").strip()
    if bool(facet_kind) != bool(facet_id) or (
        facet_kind and facet_kind not in {"SERIES", "AUTHOR"}
    ):
        _raise_library_error("分类筛选参数无效", status_code=400)
    query = WorkListQuery(
        page=page,
        requested_page_size=page_size,
        visibility=visibility,
        search=search,
        keyword=keyword,
        series_name=seriesName,
        facet_kind=facet_kind or None,
        facet_id=facet_id or None,
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
        statuses=statuses,
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
        filter_expression=filter_expression,
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
        result_page_size = result.page_size
        start = (page - 1) * result_page_size
        page_items = work_views[start : start + result_page_size]
        book_views = (
            _bookshelf_views(db, user, [work for work, _item_view in page_items])
            if bookshelf_view or search_view
            else _management_work_views(
                db, [work for work, _item_view in page_items], user.id
            )
            if management_view
            else [item_view for _work, item_view in page_items]
        )
    else:
        works = result.works
        book_views = (
            _bookshelf_views(db, user, works)
            if bookshelf_view or search_view
            else _management_work_views(db, works, user.id)
            if management_view
            else [_work_view(db, work, user.id) for work in works]
        )
    applied_facet = (
        library_facet_references(db).visible_facet(
            context=authorization_context(db, user),
            kind=facet_kind,
            facet_id=facet_id,
        )
        if facet_kind and facet_id
        else None
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
            "appliedFacet": (
                {
                    "id": applied_facet.id,
                    "kind": applied_facet.kind,
                    "name": applied_facet.name,
                }
                if applied_facet is not None
                else None
            ),
        }
    )


@router.get("/works/{work_id}")
def get_work(
    work_id: str,
    request: Request,
    detailTab: str | None = None,
    volumeId: str | None = None,
    unitPage: int | None = None,
    chapterPage: int = 1,
    chapterPageSize: int = 120,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkDetailSummaryResponse | WorkDetailResponse,
    ErrorResponses(LibraryNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    work = _visible_work_or_none(db, user, work_id)
    if not work:
        _raise_library_error("作品不存在", status_code=404)
    facet_references = library_facet_references(db).for_visible_work(work_id)
    navigation_requested = bool(request.query_params)
    book = _work_view(
        db,
        work,
        user.id,
        volume_limit_per_media=None if navigation_requested else 10,
        include_files=True,
    )
    book["seriesFacet"] = (
        {
            "id": facet_references.series.id,
            "kind": facet_references.series.kind,
            "name": facet_references.series.name,
        }
        if facet_references.series is not None
        else None
    )
    book["authorFacets"] = [
        {"id": facet.id, "kind": facet.kind, "name": facet.name}
        for facet in facet_references.authors
    ]
    if not navigation_requested:
        return WorkDetailSummaryResponse(data={"book": _work_detail_summary_view(book)})
    selected_tab = _resolve_detail_tab(
        db, user.id, work_id, book.get("detailTabs", []), detailTab
    )
    book["selectedDetailTab"] = selected_tab
    active_media, navigation = _active_media_view(
        db,
        book,
        selected_tab,
        user.id,
        volumeId,
        unitPage if unitPage is not None else chapterPage,
        chapterPageSize,
    )
    return WorkDetailResponse(
        data={"book": book, "activeMedia": active_media, **navigation}
    )


@router.get("/works/{work_id}/media-versions/{media_version_id}/volumes")
def get_work_media_version_volumes(
    work_id: str,
    media_version_id: str,
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 100,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[WorkVolumePageResponse, ErrorResponses(LibraryNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _visible_work_or_none(db, user, work_id):
        _raise_library_error("作品不存在", status_code=404)
    result = _work_volume_page_view(
        db,
        user=user,
        work_id=work_id,
        media_version_id=media_version_id,
        page=page,
        page_size=pageSize,
    )
    if result is None:
        _raise_library_error("媒介版本不存在", status_code=404)
    return WorkVolumePageResponse(data=result)


@router.get("/works/{work_id}/volumes/{volume_id}/reading-units")
def get_work_volume_reading_units(
    work_id: str,
    volume_id: str,
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=200)] = 120,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[WorkReadingUnitsResponse, ErrorResponses(LibraryNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _visible_work_or_none(db, user, work_id):
        _raise_library_error("作品不存在", status_code=404)
    result = _work_reading_units_view(
        db,
        user=user,
        work_id=work_id,
        volume_id=volume_id,
        page=page,
        page_size=pageSize,
    )
    if result is None:
        _raise_library_error("卷册不存在", status_code=404)
    return WorkReadingUnitsResponse(data=result)


@router.put("/works/{work_id}/detail-preference")
async def save_work_detail_preference(
    work_id: str,
    payload: SaveDetailPreferenceRequest,
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
    requested = payload.selected_tab.strip().upper()
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
    SaveDetailPreference(_request_mutations(db), db).execute(
        DetailPreferenceMutation(
            user_id=user.id,
            work_id=work_id,
            selected_tab=requested,
            now=now,
        )
    )
    return DetailPreferenceResponse(
        data={"selectedDetailTab": requested, "detailTabs": tabs}
    )


@router.patch("/works/{work_id}")
async def update_work(
    work_id: str,
    request_payload: UpdateWorkRequest,
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
    payload = request_payload.model_dump(by_alias=True, exclude_unset=True)
    existing_work = _visible_work_or_none(db, user, work_id)
    if not existing_work:
        _raise_library_error("作品不存在", status_code=404)
    allowed = {
        "title",
        "author",
        "description",
        "publicationStatus",
        "trackingStatus",
        "tags",
        "seriesName",
        "seriesIndex",
        "hidden",
        "organized",
        "metadataQuality",
    }
    values = {
        key: (_json_text(value) if key == "tags" and isinstance(value, list) else value)
        for key, value in payload.items()
        if key in allowed
    }
    global_fields = set(values)
    if "ignored" in payload:
        global_fields.add("hidden")
    if global_fields and not can_manage_system(user):
        _raise_library_error(
            "需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED"
        )
    if "ignored" in payload:
        values["hidden"] = bool(payload.get("ignored"))
    try:
        if "seriesIndex" in values:
            values["seriesIndex"] = _nullable_float(values["seriesIndex"], "系列序号")
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
        return WorkResponse(data={"book": _work_view(db, existing_work, user.id)})
    writeback_intents = (
        _prepare_work_writebacks(
            db,
            work_id=work_id,
            source="WORK_METADATA_EDIT",
            values=values,
        )
        if global_fields.intersection(
            {"title", "author", "description", "tags", "seriesName", "seriesIndex"}
        )
        else ()
    )
    facet_write = _prepare_facet_write_for_updates(db, ((work_id, values),), now=_now())
    work = UpdateWorkRecord(_request_mutations(db), db).execute(
        WorkRecordMutation(
            work_id=work_id,
            values=values,
            facet_write=facet_write,
            writeback_intents=writeback_intents,
        )
    )
    if not work:
        _raise_library_error("作品不存在", status_code=404)
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
    deletion_event = prepare_system_event(
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
        },
    )
    result = _delete_work_and_storage(
        db,
        work_id,
        settings,
        delete_source=delete_source,
        events=(deletion_event,),
    )
    return DeletedWorkResponse(data=result)


_BULK_TEXT_FIELDS: dict[str, tuple[str, str]] = {
    "title": ("LibraryWork", "title"),
    "author": ("LibraryWork", "author"),
    "description": ("LibraryWork", "description"),
    "seriesName": ("LibraryWork", "seriesName"),
    "tags": ("LibraryWork", "tags"),
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


def _require_merge_scope(db: Session, user: User, work_ids: list[str]) -> None:
    if not can_manage_system(user):
        _raise_library_error(
            "需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED"
        )
    if any(not can_access_work(db, user, work_id) for work_id in work_ids):
        _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")


def _raise_work_merge_error(error: WorkMergeError) -> Never:
    if isinstance(error, WorkMergeNotFoundError):
        _raise_library_error(str(error), status_code=404, code=error.code)
    if isinstance(error, WorkMergeInProgressError):
        _raise_library_error(str(error), status_code=409, code=error.code)
    _raise_library_error(str(error), status_code=400, code=error.code)


@router.post("/works/merge/preview")
def preview_work_merge(
    payload: WorkMergeSelectionRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkMergePreviewResponse,
    ErrorResponses(
        LibraryBadRequestError,
        LibraryForbiddenError,
        LibraryNotFoundError,
        LibraryConflictError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    _require_merge_scope(db, user, payload.work_ids)
    try:
        preview = PreviewWorkMerge(work_merge_gateway(db)).execute(payload.work_ids)
    except WorkMergeError as error:
        _raise_work_merge_error(error)
    return WorkMergePreviewResponse(
        data={
            "works": list(preview.works),
            "mediaGroups": list(preview.media_groups),
            "suggestedMetadata": {
                "title": preview.suggested_metadata.title,
                "author": preview.suggested_metadata.author,
                "description": preview.suggested_metadata.description,
                "seriesName": preview.suggested_metadata.series_name,
                "seriesIndex": preview.suggested_metadata.series_index,
                "tags": list(preview.suggested_metadata.tags),
            },
            "defaultCoverVolumeId": preview.default_cover_volume_id,
            "writeMetadataToFiles": preview.write_metadata_to_files,
        }
    )


@router.post("/works/merge")
def create_work_merge(
    payload: CreateWorkMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkMergeResponse,
    ErrorResponses(
        LibraryBadRequestError,
        LibraryForbiddenError,
        LibraryNotFoundError,
        LibraryConflictError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    _require_merge_scope(db, user, payload.work_ids)
    try:
        result = CreateMergedWork(work_merge_gateway(db), db).execute(
            MergeCommand(
                work_ids=tuple(payload.work_ids),
                metadata=MergeMetadata(
                    title=payload.metadata.title,
                    author=payload.metadata.author,
                    description=payload.metadata.description,
                    series_name=payload.metadata.series_name,
                    series_index=payload.metadata.series_index,
                    tags=tuple(payload.metadata.tags),
                ),
                cover_volume_id=payload.cover_volume_id,
                actor_id=user.id,
            )
        )
    except WorkMergeError as error:
        _raise_work_merge_error(error)
    return WorkMergeResponse(
        data={
            "workId": result.work_id,
            "sourceWorkIds": list(result.source_work_ids),
            "mediaVersions": list(result.media_versions),
            "metadataWritebacks": list(result.metadata_writebacks),
            "operation": result.operation,
        }
    )


def _first_volume(db: Session, work_id: str) -> dict[str, Any] | None:
    volume = db.scalar(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryMediaVersion.work_id == work_id, LibraryVolume.hidden.is_(False))
        .order_by(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
        .limit(1)
    )
    return library_works.entity_as_legacy_dict(volume) if volume is not None else None


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
    works_by_id = {
        str(work["id"]): work
        for work in library_works.list_works_by_ids(db, tuple(work_ids))
    }
    for index, work_id in enumerate(work_ids):
        work = works_by_id.get(work_id)
        if not work:
            continue
        target = work
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


@router.post("/works/bulk")
async def bulk_works(
    request_payload: BulkWorkRequest,
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
    payload = request_payload.model_dump(by_alias=True, exclude_unset=True)
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
        deletion_event = prepare_system_event(
            level="error",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="bulk.deleted",
            target_type="work",
            message=f"批量删除书库记录 {len(normalized_scope_ids)} 个",
            metadata={
                "ids": normalized_scope_ids,
                "deleteSource": delete_source,
            },
        )
        deletion_result = _delete_works_and_storage(
            db,
            tuple(normalized_scope_ids),
            settings,
            delete_source=delete_source,
            events=(deletion_event,),
        )
        updated = int(deletion_result["deletedDatabaseRecords"])
        deleted_files = int(deletion_result["deletedFiles"])
        deleted_source_files = int(deletion_result["deletedSourceFiles"])
        missing_source_files = list(deletion_result["missingSourceFiles"])
        failed_file_deletes = list(deletion_result["failedFileDeletes"])
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
        updates = tuple(
            (
                work_id,
                {"hidden": hidden}
                if action != "mark_organized"
                else {"organized": organized},
            )
            for work_id in normalized_scope_ids
        )
        mutation_event = prepare_system_event(
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action=f"bulk.{action}",
            target_type="work",
            message=f"批量更新作品 {len(updates)} 个",
            metadata={"ids": ids, "action": action},
        )
        updated = UpdateBulkWorks(_request_mutations(db), db).execute(
            BulkWorkMutation(
                updates=updates,
                events=(mutation_event,),
            )
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
            writeback_values_by_work: dict[str, dict[str, Any]] = {}
            for replacement in replacements:
                changed_work_id = str(replacement["workId"])
                column = str(replacement["column"])
                if column in {
                    "title",
                    "author",
                    "description",
                    "tags",
                    "seriesName",
                    "seriesIndex",
                }:
                    value = (
                        _json_text(replacement["after"])
                        if column == "tags"
                        else replacement["after"] or None
                    )
                    writeback_values_by_work.setdefault(changed_work_id, {}).update(
                        {column: value, "updatedAt": now}
                    )
            writeback_intents = tuple(
                intent
                for changed_work_id, final_values in writeback_values_by_work.items()
                for intent in _prepare_work_writebacks(
                    db,
                    work_id=changed_work_id,
                    source="BULK_FIND_REPLACE",
                    values=final_values,
                )
            )
            facet_write = _prepare_facet_write_for_updates(
                db,
                tuple(writeback_values_by_work.items()),
                now=now,
            )
            works_by_id = {
                str(work["id"]): work
                for work in library_works.list_works_by_ids(
                    db, tuple(writeback_values_by_work)
                )
            }
            work_update_rows: list[tuple[str, dict[str, Any]]] = []
            for replacement in replacements:
                value = (
                    _json_text(replacement["after"])
                    if replacement["column"] == "tags"
                    else replacement["after"] or None
                )
                if replacement["column"] in {"title", "author"}:
                    work = works_by_id.get(str(replacement["workId"]), {})
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
                    work_update_rows.append(
                        (
                            str(replacement["workId"]),
                            {
                                "title": title_value,
                                "author": author_value,
                                "normalizedTitle": normalize_identity_part(title_value),
                                "normalizedAuthor": normalize_identity_part(
                                    author_value
                                ),
                                "mergeKey": identity_merge_key(
                                    title_value, author_value
                                ),
                                "updatedAt": now,
                            },
                        )
                    )
                else:
                    update_values = {
                        replacement["column"]: value,
                        "updatedAt": now,
                    }
                    work_update_rows.append(
                        (str(replacement["targetId"]), update_values)
                    )
                changed_work_ids.add(str(replacement["workId"]))
            mutation_event = prepare_system_event(
                level="info",
                source="library",
                actor_type="admin",
                actor_id=user.id,
                action="bulk.find_replace",
                target_type="work",
                message=f"批量查找替换 {len(changed_work_ids)} 本图书",
                metadata={
                    "ids": normalized_ids,
                    "field": payload.get("field"),
                    "changedValues": len(replacements),
                },
            )
            updated = len(changed_work_ids)
            UpdateBulkWorks(_request_mutations(db), db).execute(
                BulkWorkMutation(
                    updates=tuple(work_update_rows),
                    facet_write=facet_write,
                    writeback_intents=writeback_intents,
                    events=(mutation_event,) if updated else (),
                )
            )
            return BulkMutationResponse(
                data={
                    "updated": updated,
                    "changedValues": len(replacements),
                    "ids": normalized_ids,
                }
            )
        if action in {"set_status", "reading_status"}:
            selected_count = len(normalized_ids)
            mutation_event = prepare_system_event(
                level="info",
                source="library",
                actor_type="user",
                actor_id=user.id,
                action=f"bulk.reading_status.{status.lower()}",
                target_type="work",
                message=f"批量设置阅读状态 {selected_count} 本图书",
                metadata={"ids": normalized_ids, "status": status},
            )
            updated = UpdateBulkReadingStatus(_request_mutations(db), db).execute(
                BulkReadingStatusMutation(
                    context=authorization_context(db, user),
                    work_ids=tuple(normalized_ids),
                    status=status,
                    now=_now(),
                    events=(mutation_event,),
                )
            )
            return BulkMutationResponse(
                data={"updated": updated, "ids": normalized_ids, "status": status}
            )
        metadata_fields = (
            payload.get("fields")
            if action == "update_metadata" and isinstance(payload.get("fields"), dict)
            else {}
        )
        unsupported_metadata_fields = set(metadata_fields) - {
            "author",
            "seriesName",
        }
        if unsupported_metadata_fields:
            _raise_library_error(
                "批量元数据更新包含不支持的字段",
                status_code=400,
                code="UNSUPPORTED_METADATA_FIELD",
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
        bulk_now = _now()
        prepared_updates: list[tuple[str, dict[str, Any]]] = []
        prepared_writebacks: list[PreparedWritebackIntent] = []
        works_by_id = {
            str(work["id"]): work
            for work in library_works.list_works_by_ids(db, tuple(normalized_ids))
        }
        for work_id in normalized_ids:
            work = works_by_id.get(work_id)
            if not work:
                continue
            work_values: dict[str, Any] = {}
            if action in {"add_tags", "remove_tags"}:
                current_tags = [str(item) for item in _parse_json(work.get("tags"), [])]
                if action == "add_tags":
                    next_tags = list(dict.fromkeys([*current_tags, *tags]))
                else:
                    removed = {item.casefold() for item in tags}
                    next_tags = [
                        item for item in current_tags if item.casefold() not in removed
                    ]
                work_values = {
                    "tags": _json_text(next_tags),
                    "updatedAt": bulk_now,
                }
            elif action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
                prepared_updates.append((work_id, {}))
                continue
            elif action == "update_metadata":
                work_values = {"updatedAt": bulk_now}
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
            elif fields:
                work_values = {**fields, "updatedAt": bulk_now}
            prepared_updates.append((work_id, work_values))
            if action in {
                "add_tags",
                "remove_tags",
                "update_fields",
                "update_metadata",
            }:
                prepared_writebacks.extend(
                    _prepare_work_writebacks(
                        db,
                        work_id=work_id,
                        source="BULK_METADATA_EDIT",
                        values=work_values if len(work_values) > 1 else {},
                    )
                )

        facet_write = _prepare_facet_write_for_updates(
            db,
            tuple(prepared_updates),
            now=bulk_now,
        )
        mutation_event = prepare_system_event(
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action=f"bulk.{action}",
            target_type="work",
            message=f"批量更新作品 {len(prepared_updates)} 个",
            metadata={"ids": normalized_ids, "action": action},
        )

        if action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
            membership_work_ids = tuple(
                work_id for work_id, _values in prepared_updates
            )
            updated = UpdateBulkShelfMembership(_request_mutations(db), db).execute(
                BulkShelfMembershipMutation(
                    shelf_id=shelf_id,
                    work_ids=membership_work_ids,
                    now=bulk_now,
                    membership=membership,
                    events=(mutation_event,),
                )
            )
        else:
            effective_updates = tuple(
                (work_id, work_values)
                for work_id, work_values in prepared_updates
                if work_values
                and not (action == "update_metadata" and len(work_values) == 1)
            )
            updated = UpdateBulkWorks(_request_mutations(db), db).execute(
                BulkWorkMutation(
                    updates=effective_updates,
                    facet_write=facet_write,
                    writeback_intents=tuple(prepared_writebacks),
                    events=(mutation_event,),
                    reported_count=len(prepared_updates),
                )
            )
    return BulkMutationResponse(data={"updated": updated, "ids": ids})


@router.post("/works/bulk/find-replace/preview")
async def preview_bulk_find_replace(
    request_payload: BulkFindReplaceRequest,
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
    payload = request_payload.model_dump(by_alias=True, exclude_unset=True)
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
    payload: Annotated[BulkCoverRequest, Form()],
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BulkMutationResponse, ErrorResponses(LibraryBadRequestError, LibraryNotFoundError)
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        raw_ids = json.loads(payload.ids)
    except json.JSONDecodeError:
        _raise_library_error("图书选择无效", status_code=400)
    work_ids = _bulk_work_ids(raw_ids)
    action = payload.action.strip().lower()
    if not work_ids:
        _raise_library_error("请选择至少一本图书", status_code=400)
    if any(not can_access_work(db, user, work_id) for work_id in work_ids):
        _raise_library_error("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    if action not in {"crop", "regenerate", "compress", "replace"}:
        _raise_library_error("封面操作无效", status_code=400)
    ratio = payload.ratio
    if action == "crop" and ratio not in {"2:3", "3:4", "1:1"}:
        _raise_library_error("封面裁剪比例无效", status_code=400)
    quality = max(40, min(95, payload.quality))
    max_dimension = max(600, min(3200, payload.max_dimension))
    upload = payload.cover
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
        writeback_intents = tuple(
            intent
            for work_id, relative, _status in pending_updates
            for intent in _prepare_work_writebacks(
                db,
                work_id=work_id,
                source="BULK_COVER_EDIT",
                values={"coverPath": relative, "updatedAt": now},
            )
        )
        cover_event = prepare_system_event(
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action=f"bulk.cover.{action}",
            target_type="work",
            message=f"批量处理封面 {len(pending_updates)} 本图书",
            metadata={
                "ids": work_ids,
                "action": action,
                "ratio": ratio if action == "crop" else None,
                "quality": quality,
                "maxDimension": max_dimension,
                "skipped": skipped,
            },
        )
        updated = UpdateCoverRecords(_request_mutations(db), db).execute(
            CoverMutation(
                records=tuple(
                    CoverRecordMutation(
                        work_id=work_id,
                        cover_path=relative,
                        cover_status=status,
                    )
                    for work_id, relative, status in pending_updates
                ),
                now=now,
                writeback_intents=writeback_intents,
                events=(cover_event,) if pending_updates else (),
            )
        )
    except Exception:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
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
    now = _now()
    writeback_intents = _prepare_work_writebacks(
        db,
        work_id=work_id,
        source="COVER_UPLOAD",
        values={"coverPath": relative, "updatedAt": now},
    )
    UpdateCoverRecords(_request_mutations(db), db).execute(
        CoverMutation(
            records=(
                CoverRecordMutation(
                    work_id=work_id,
                    cover_path=relative,
                    cover_status="READY",
                ),
            ),
            now=now,
            writeback_intents=writeback_intents,
        )
    )
    return CoverMutationResponse(
        data={
            "bookId": work_id,
            "coverUrl": (
                f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}"
            ),
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
    now = _now()
    writeback_intents = _prepare_work_writebacks(
        db,
        work_id=work_id,
        source="COVER_REGENERATE",
        values={"coverPath": cover_path, "updatedAt": now},
    )
    UpdateCoverRecords(_request_mutations(db), db).execute(
        CoverMutation(
            records=(
                CoverRecordMutation(
                    work_id=work_id,
                    cover_path=cover_path,
                    cover_status=cover_status(cover_path, settings),
                ),
            ),
            now=now,
            writeback_intents=writeback_intents,
        )
    )
    return CoverMutationResponse(
        data={
            "bookId": work_id,
            "coverUrl": (
                f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}"
            ),
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
        for kind in ("AUTHOR", "TAG", "SERIES")
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


@router.get("/library/filter-schema")
def get_library_filter_schema_route(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FilterSchemaResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    context = authorization_context(db, user)
    result = get_library_filter_schema(db).execute(context)
    return FilterSchemaResponse(data=filter_schema_payload(result))


@router.get("/library/filter-options")
def search_library_filter_option_values(
    request: Request,
    source: Annotated[LibraryFilterOptionSource, Query()],
    query: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FilterOptionsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    context = authorization_context(db, user)
    result = search_library_filter_options(db).execute(
        context,
        source=source,
        query=query,
        limit=limit,
    )
    return FilterOptionsResponse(data=filter_options_payload(result))


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
        items, total, page = list_categories_page(
            db,
            kind,
            search,
            page=page,
            page_size=page_size,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
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
    payload: RenameCategoryRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[RenameCategoryResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = rename_category(db, facet_id, payload.name, user.id)
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
    payload: MergeCategoriesRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[MergeCategoriesResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = merge_categories(
            db,
            payload.kind,
            payload.source_ids,
            payload.target_id,
            user.id,
        )
    except ValueError as exc:
        _raise_library_error(str(exc), status_code=400)
    return MergeCategoriesResponse(data=result)


@router.get("/library/duplicates")
def library_duplicates(
    request: Request,
    page: int = 1,
    pageSize: int = 20,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DuplicatesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    groups, total, page = duplicate_groups_page(
        db,
        page=page,
        page_size=page_size,
    )
    works = [work for group in groups for work in group.get("works") or []]
    work_views = {
        str(work["id"]): view
        for work, view in zip(works, _work_views(db, works, user.id), strict=True)
    }
    for group in groups:
        group["works"] = [
            work_views[str(work["id"])] for work in group.get("works") or []
        ]
    return DuplicatesResponse(
        data={
            "groups": groups,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        }
    )


@router.post("/library/duplicates/merge")
async def merge_library_duplicates(
    payload: MergeDuplicatesRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[MergeDuplicatesResponse, ErrorResponses(LibraryBadRequestError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = merge_works(
            db,
            payload.target_work_id,
            payload.source_work_ids,
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
    payload: MetadataSearchRequest,
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
    source = payload.provider_id or payload.source or "bangumi"
    if source not in metadata_provider_registry().ids():
        _raise_library_error("不支持的元数据来源", status_code=400)
    job, context = _metadata_context_for_work(db, work_id)
    if not job or not context:
        _raise_library_error("读物不存在或无权访问", status_code=404)
    query = str(payload.query or "").strip() or None
    try:
        result = search_with_metadata_provider(db, context, source, query)
    except Exception as exc:
        _raise_library_error(str(exc), status_code=400)
    candidates = []
    for raw_candidate in result.get("candidates") or []:
        if not isinstance(raw_candidate, dict):
            continue
        volume_metadata = {
            "publisher": raw_candidate.get("publisher"),
            "publishedAt": raw_candidate.get("publishedAt"),
            "language": raw_candidate.get("language"),
            "isbn": raw_candidate.get("isbn"),
        }
        candidates.append(
            {
                key: value
                for key, value in {
                    **raw_candidate,
                    "publisher": None,
                    "publishedYear": None,
                    "isbn": None,
                    "volumeMetadata": {
                        key: value
                        for key, value in volume_metadata.items()
                        if value not in (None, "")
                    }
                    or None,
                }.items()
                if key not in {"publisher", "publishedYear", "isbn"}
            }
        )
    return MetadataSearchResponse(
        data={
            "candidates": candidates,
            "results": candidates,
            "query": query or context["work"].get("title"),
            "source": source,
            "message": result.get("message"),
        }
    )


@router.patch("/works/{work_id}/editions/{edition_id}", status_code=410)
@router.post("/works/{work_id}/editions/{edition_id}/primary", status_code=410)
@router.post("/works/{work_id}/editions/{edition_id}/split", status_code=410)
async def update_work_edition(
    work_id: str,
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    _raise_edition_resource_retired()


@router.patch("/works/{work_id}/volumes/{volume_id}")
def update_work_volume(
    work_id: str,
    volume_id: str,
    payload: UpdateVolumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(
        LibraryForbiddenError,
        LibraryNotFoundError,
        LibraryUnprocessableError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is not None:
        changes["title"] = str(changes["title"]).strip()
    try:
        update_volume_resource(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            work_id=work_id,
            volume_id=volume_id,
            changes=changes,
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    except InvalidVolumeChangeError as exc:
        _raise_library_error(str(exc), status_code=422, code="VOLUME_TITLE_REQUIRED")
    refreshed_work = _get_work(db, work_id)
    return WorkStructureMutationResponse(
        data={
            "book": (
                _work_view(db, refreshed_work, user.id) if refreshed_work else None
            ),
            "workId": work_id,
            "volumeId": volume_id,
        }
    )


@router.post("/works/{work_id}/volumes/batch")
def batch_work_volumes(
    work_id: str,
    payload: BatchVolumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BatchVolumeMutationResponse,
    ErrorResponses(
        LibraryBadRequestError,
        LibraryForbiddenError,
        LibraryNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        outcome = batch_volume_resources(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            work_id=work_id,
            command=BatchVolumeCommand(
                action=payload.action,
                volume_ids=tuple(payload.volume_ids),
                target_media_kind=(
                    payload.target_media_kind
                    if isinstance(payload, BatchSetMediaKindRequest)
                    else None
                ),
                target_work_id=(
                    payload.target_work_id
                    if isinstance(payload, BatchTransferVolumesRequest)
                    else None
                ),
            ),
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    except InvalidVolumeChangeError as exc:
        _raise_library_error(
            "批量卷册操作请求无效",
            status_code=400,
            code=str(exc),
        )
    refreshed_work = _get_work(db, work_id)
    return BatchVolumeMutationResponse(
        data={
            "book": _work_view(db, refreshed_work, user.id) if refreshed_work else None,
            "workId": work_id,
            "affectedVolumeIds": list(outcome.affected_volume_ids),
            "targetWorkIds": list(outcome.target_work_ids),
            "operationIds": list(outcome.operation_ids),
            "deletedWork": outcome.deleted_work,
        }
    )


@router.post("/works/{work_id}/volumes/{volume_id}/reclassify")
def reclassify_work_volume(
    work_id: str,
    volume_id: str,
    payload: ReclassifyVolumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(
        LibraryBadRequestError,
        LibraryForbiddenError,
        LibraryNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        outcome = reclassify_volume_resource(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            work_id=work_id,
            volume_id=volume_id,
            target_media_kind=payload.target_media_kind.strip().upper(),
            apply_to=payload.apply_to.strip().upper(),
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    except InvalidVolumeChangeError as exc:
        code = str(exc)
        _raise_library_error(
            "内容分类或应用范围无效",
            status_code=400,
            code=code,
        )
    refreshed_work = _get_work(db, work_id)
    return WorkStructureMutationResponse(
        data={
            "book": (
                _work_view(db, refreshed_work, user.id) if refreshed_work else None
            ),
            "workId": work_id,
            "volumeId": volume_id,
            "targetMediaVersionId": outcome.target_media_version_id,
            "operation": _operation_payload(outcome.operation),
        }
    )


@router.post("/works/{work_id}/volumes/{volume_id}/move")
def reorder_work_volume(
    work_id: str,
    volume_id: str,
    payload: ReorderVolumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(
        LibraryForbiddenError,
        LibraryNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        reorder_volume_resource(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            work_id=work_id,
            volume_id=volume_id,
            direction=payload.direction,
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    refreshed_work = _get_work(db, work_id)
    return WorkStructureMutationResponse(
        data={
            "book": (
                _work_view(db, refreshed_work, user.id) if refreshed_work else None
            ),
            "workId": work_id,
            "volumeId": volume_id,
        }
    )


@router.post("/works/{work_id}/volumes/{volume_id}/move-to")
def move_work_volume(
    work_id: str,
    volume_id: str,
    payload: MoveVolumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(
        LibraryForbiddenError,
        LibraryNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        outcome = move_volume_resource(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            source_work_id=work_id,
            volume_id=volume_id,
            target_work_id=payload.target_work_id,
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    source_work = _get_work(db, work_id)
    target_work = _get_work(db, payload.target_work_id)
    return WorkStructureMutationResponse(
        data={
            "book": (_work_view(db, source_work, user.id) if source_work else None),
            "targetBook": (
                _work_view(db, target_work, user.id) if target_work else None
            ),
            "workId": work_id,
            "targetWorkId": payload.target_work_id,
            "volumeId": volume_id,
            "targetMediaVersionId": outcome.move.target_media_version_id,
            "transferMode": outcome.move.transfer_mode,
            "operation": _operation_payload(outcome.operation),
        }
    )


@router.post("/works/{work_id}/volumes/{volume_id}/split")
def split_work_volume(
    work_id: str,
    volume_id: str,
    payload: SplitVolumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(
        LibraryForbiddenError,
        LibraryNotFoundError,
        LibraryUnprocessableError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        outcome = split_volume_resource(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            source_work_id=work_id,
            volume_id=volume_id,
            new_work=NewWorkInput(
                title=payload.title.strip(),
                author=payload.author,
            ),
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    except InvalidVolumeChangeError as exc:
        _raise_library_error(str(exc), status_code=422, code="WORK_TITLE_REQUIRED")
    new_work = _get_work(db, outcome.target_work_id)
    return WorkStructureMutationResponse(
        data={
            "book": _work_view(db, new_work, user.id) if new_work else None,
            "workId": work_id,
            "targetWorkId": outcome.target_work_id,
            "volumeId": volume_id,
            "targetMediaVersionId": outcome.move.target_media_version_id,
            "transferMode": outcome.move.transfer_mode,
            "operation": _operation_payload(outcome.operation),
        }
    )


@router.delete("/works/{work_id}/volumes/{volume_id}")
def delete_work_volume(
    work_id: str,
    volume_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    WorkStructureMutationResponse,
    ErrorResponses(
        LibraryForbiddenError,
        LibraryNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        outcome = delete_volume_resource(
            volume_structure_commands(db),
            db,
            actor=_library_actor(db, user),
            work_id=work_id,
            volume_id=volume_id,
            now=_now(),
        )
    except WorkNotFoundError:
        _raise_library_error(
            "作品不存在或无权访问",
            status_code=404,
            code="WORK_NOT_FOUND",
        )
    except VolumeNotFoundError:
        _raise_library_error(
            "卷册不存在或不属于该作品",
            status_code=404,
            code="VOLUME_NOT_FOUND",
        )
    except LibraryAuthorizationError:
        _raise_library_error(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    remaining_work = _get_work(db, work_id)
    return WorkStructureMutationResponse(
        data={
            "book": (
                _work_view(db, remaining_work, user.id) if remaining_work else None
            ),
            "workId": work_id,
            "volumeId": volume_id,
            "deletedMediaVersion": outcome.deleted_media_version,
            "deletedWork": outcome.deleted_work,
            "operation": _operation_payload(outcome.operation),
        }
    )


@router.post("/works/{work_id}/metadata/apply")
async def apply_work_metadata(
    work_id: str,
    payload: MetadataApplyRequest,
    request: Request,
    apply_to_all_volumes: Annotated[bool, Query(alias="applyToAllVolumes")] = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    MetadataApplyResponse,
    ErrorResponses(LibraryBadRequestError, LibraryNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    user_id = user.id
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    candidate = payload.candidate.model_dump(by_alias=True)
    fields = list(payload.fields)
    existing_work = _get_work(db, work_id)
    if not existing_work:
        _raise_library_error("作品不存在", status_code=404)
    volume_fields = {"publisher", "publishedAt", "language", "isbn"}
    volume_selected = bool(volume_fields.intersection(fields))
    volume_required = volume_selected
    target_media_version: LibraryMediaVersion | None = None
    target_volumes: list[LibraryVolume] = []
    if volume_required:
        if payload.media_version_id:
            target_media_version = db.scalar(
                select(LibraryMediaVersion).where(
                    LibraryMediaVersion.id == payload.media_version_id,
                    LibraryMediaVersion.work_id == work_id,
                )
            )
        elif payload.volume_id:
            if not can_access_volume(db, user, payload.volume_id):
                _raise_library_error(
                    "卷册不存在", status_code=404, code="VOLUME_NOT_FOUND"
                )
            target_media_version = db.scalar(
                select(LibraryMediaVersion)
                .join(
                    LibraryVolume,
                    LibraryVolume.media_version_id == LibraryMediaVersion.id,
                )
                .where(
                    LibraryVolume.id == payload.volume_id,
                    LibraryMediaVersion.work_id == work_id,
                )
            )
        else:
            media_versions = list(
                db.scalars(
                    select(LibraryMediaVersion)
                    .where(LibraryMediaVersion.work_id == work_id)
                    .order_by(LibraryMediaVersion.created_at.asc())
                ).all()
            )
            if len(media_versions) == 1:
                target_media_version = media_versions[0]
        if target_media_version is None:
            _raise_library_error(
                "无法确定当前媒体版本",
                status_code=400,
                code="MEDIA_VERSION_TARGET_REQUIRED",
            )
        volume_query = select(LibraryVolume).where(
            LibraryVolume.media_version_id == target_media_version.id,
            LibraryVolume.hidden.is_(False),
        )
        if not apply_to_all_volumes:
            if not payload.volume_id:
                _raise_library_error(
                    "请选择要应用元数据的卷册",
                    status_code=400,
                    code="VOLUME_TARGET_REQUIRED",
                )
            volume_query = volume_query.where(LibraryVolume.id == payload.volume_id)
        target_volumes = list(
            db.scalars(
                volume_query.order_by(
                    LibraryVolume.sort_order.asc(), LibraryVolume.id.asc()
                )
            ).all()
        )
        if not target_volumes:
            _raise_library_error(
                "当前媒体版本没有可应用的卷册",
                status_code=400,
                code="MEDIA_VERSION_HAS_NO_VOLUMES",
            )
    patch = _metadata_field_patch(candidate, fields)
    if "title" in patch or "author" in patch:
        title = str(patch.get("title", existing_work.get("title")) or "").strip()
        author = (
            str(patch.get("author", existing_work.get("author")) or "").strip()
            or UNKNOWN_AUTHOR
        )
        patch.update(
            {
                "title": title,
                "author": author,
                "normalizedTitle": normalize_identity_part(title),
                "normalizedAuthor": normalize_identity_part(author),
                "mergeKey": identity_merge_key(title, author),
            }
        )
    nested_volume_metadata = candidate.get("volumeMetadata")
    volume_metadata = (
        dict(nested_volume_metadata) if isinstance(nested_volume_metadata, dict) else {}
    )
    for volume_field in volume_fields:
        if volume_metadata.get(volume_field) is None:
            volume_metadata[volume_field] = candidate.get(volume_field)
    target_media_version_id = (
        target_media_version.id if target_media_version is not None else None
    )
    target_volume_ids = tuple(volume.id for volume in target_volumes)
    target_volume_id = (
        target_volume_ids[0] if target_volume_ids and not apply_to_all_volumes else None
    )
    previous_cover_path_value = existing_work.get("coverPath")
    previous_cover_path = (
        str(previous_cover_path_value) if previous_cover_path_value else None
    )
    db.close()

    cover_gateway = library_cover_publication(settings)
    prepared_cover = None
    cover_url = candidate.get("coverUrl")
    if "coverUrl" in fields and isinstance(cover_url, str) and cover_url.strip():
        try:
            prepared_cover = cover_gateway.prepare(
                work_id=work_id,
                cover_url=cover_url.strip(),
            )
        except (OSError, ValueError) as exc:
            logger.warning(
                "failed to prepare remote cover work=%s url=%s error=%s",
                work_id,
                cover_url,
                exc,
            )
        else:
            patch.update(
                {
                    "coverPath": prepared_cover.stored_path,
                    "coverStatus": "READY",
                }
            )
    if not patch and not volume_selected:
        _raise_library_error("候选中没有可应用的字段", status_code=400)
    volume_updated_at = _now()
    patch.update(
        {
            "organized": True,
            "organizeStatus": "APPLIED",
            "metadataQuality": 85,
            "updatedAt": volume_updated_at,
        }
    )
    volume_values_by_id: dict[str, dict[str, Any]] = {}
    volume_update_rows: list[dict[str, Any]] = []
    for target_volume_id_value in target_volume_ids:
        volume_values: dict[str, Any] = {}
        if "publisher" in fields:
            volume_values["publisher"] = (
                str(volume_metadata.get("publisher") or "").strip() or None
            )
        if "publishedAt" in fields:
            volume_values["published_at"] = volume_metadata.get("publishedAt")
        if "language" in fields:
            volume_values["language"] = (
                str(volume_metadata.get("language") or "").strip() or None
            )
        if "isbn" in fields:
            volume_values["isbn"] = (
                str(volume_metadata.get("isbn") or "").strip() or None
            )
        volume_values_by_id[target_volume_id_value] = volume_values
        if volume_values:
            volume_update_rows.append(
                {
                    "id": target_volume_id_value,
                    **volume_values,
                    "updated_at": volume_updated_at,
                }
            )
    try:
        writeback_intents = _prepare_work_writebacks(
            db,
            work_id=work_id,
            source="MANUAL_METADATA_APPLY",
            values=patch,
            media_version_id=target_media_version_id,
            volume_id=target_volume_id,
            volume_values_by_id=volume_values_by_id,
        )
        facet_write = _prepare_facet_write_for_updates(
            db, ((work_id, patch),), now=volume_updated_at
        )
        finished_job_ids = load_metadata_apply_job_ids(db, work_id)
    except Exception:
        if prepared_cover is not None:
            cover_gateway.discard(prepared_cover)
        raise
    db.close()
    try:
        mutation_result = ApplyWorkMetadata(_request_mutations(db), db).execute(
            MetadataApplyMutation(
                work_id=work_id,
                work_values=patch,
                volume_rows=tuple(volume_update_rows),
                facet_write=facet_write,
                writeback_intents=writeback_intents,
                finished_job_ids=finished_job_ids,
                now=volume_updated_at,
            )
        )
    except Exception:
        if prepared_cover is not None:
            cover_gateway.discard(prepared_cover)
        raise
    if prepared_cover is not None:
        try:
            cover_gateway.publish(prepared_cover)
        except OSError as exc:
            logger.warning(
                "failed to publish remote cover work=%s target=%s error=%s",
                work_id,
                prepared_cover.final_path,
                exc,
            )
            CompensateCoverPublication(_request_mutations(db), db).execute(
                CoverPublicationFailure(
                    work_id=work_id,
                    expected_cover_path=prepared_cover.stored_path,
                    expected_updated_at=volume_updated_at,
                    fallback_cover_path=previous_cover_path,
                    now=_now(),
                )
            )
            mutation_result = replace(
                mutation_result,
                work=_get_work(db, work_id),
            )
    if not mutation_result.work:
        _raise_library_error("作品不存在", status_code=404)
    writeback_operation_ids = mutation_result.writeback_operation_ids
    return MetadataApplyResponse(
        data={
            "book": _work_view(db, mutation_result.work, user_id),
            "appliedFields": fields,
            "finishedOrganizeJobIds": list(mutation_result.finished_job_ids),
            "metadataWriteback": (
                metadata_writeback_view(db, writeback_operation_ids[0])
                if writeback_operation_ids
                else None
            ),
        }
    )
