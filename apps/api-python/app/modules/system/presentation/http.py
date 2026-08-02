"""System capability HTTP surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import import_http_store
from app.bootstrap.library import library_dashboard
from app.bootstrap.media import media_streaming
from app.bootstrap.system import (
    delete_settings,
    list_event_level_facets,
    list_event_source_facets,
    list_settings,
    record_system_event,
    run_system_health_checks,
    system_event_storage_view,
    upsert_setting,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.system.application.queries import (
    SettingsUpdateError,
    app_config_payload,
    backup_created_payload,
    backup_detail_payload,
    dashboard_system_status_payload,
    management_events_empty_page,
    management_events_payload,
    parse_event_date_bounds,
    prepare_system_settings_update,
    system_settings_payload,
)
from app.modules.system.presentation.schemas import (
    AppConfigResponse,
    BackupArchiveResponse,
    BackupDeleteResponse,
    BackupResponse,
    BackupRestoreResponse,
    BackupsResponse,
    ClearedEventsResponse,
    DashboardSystemStatusResponse,
    ManagementEventsResponse,
    SystemSettingsResponse,
)
from app.modules.system.public import execute_system_transaction
from app.schemas.responses import fail, ok
from app.services.backup_service import create_backup as create_backup_archive
from app.services.backup_service import list_backups as list_backup_archives
from app.services.backup_service import restore_backup as restore_backup_archive
from app.services.import_preferences import (
    IMPORT_PREFERENCE_KEYS,
    normalize_import_setting_value,
)

router = APIRouter(tags=["system"], route_class=TypedContractRoute)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _event_storage_snapshot(db: Session) -> dict[str, int]:
    storage = system_event_storage_view(db)
    return {
        "deleted": 0,
        "sizeBytes": int(storage["sizeBytes"]),
        "maxBytes": int(storage["maxBytes"]),
    }


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


@router.get("/app-config")
def get_public_app_config(db: Session = Depends(get_db)) -> AppConfigResponse:
    return ok(app_config_payload(db))


@router.get("/system-settings")
def get_system_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SystemSettingsResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok(system_settings_payload(list_settings(db)))


@router.put("/system-settings")
@router.patch("/system-settings")
async def update_system_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SystemSettingsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    values = payload.get(
        "settings",
        {key: value for key, value in payload.items() if key != "clearSensitiveKeys"},
    )
    requested_clear_keys = payload.get("clearSensitiveKeys", [])
    if not isinstance(values, dict):
        return fail("设置格式不正确", status_code=400)
    if not isinstance(requested_clear_keys, list):
        return fail("清除凭据格式不正确", status_code=400)
    prepared = prepare_system_settings_update(
        values,
        requested_clear_keys,
        normalize_import_setting_value=normalize_import_setting_value,
        import_preference_keys=IMPORT_PREFERENCE_KEYS,
    )
    if isinstance(prepared, SettingsUpdateError):
        return fail(
            prepared.message,
            status_code=prepared.status_code,
            code=prepared.code,
            params=prepared.params,
            details=prepared.details,
        )
    saved, clear_keys = prepared

    def persist_settings_update() -> None:
        for key, value in saved.items():
            upsert_setting(db, key, value)
        if clear_keys:
            delete_settings(db, clear_keys)
            for key in clear_keys:
                saved[key] = ""
        record_system_event(
            db,
            level="warning",
            source="system",
            actor_type="admin",
            actor_id=user.id,
            action="settings.updated",
            target_type="settings",
            message=f"更新系统设置 {len(saved)} 项",
            metadata={"keys": list(saved.keys())},
            commit=False,
        )

    execute_system_transaction(db, persist_settings_update)
    return ok(system_settings_payload(saved))


@router.get("/dashboard/system-status")
def dashboard_system_status(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardSystemStatusResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    health = run_system_health_checks(db, settings)
    enabled = import_http_store.list_enabled_monitor_folder_rows(db)
    current_task, latest_task, failed_count = import_http_store.import_status_snapshot(
        db
    )
    return DashboardSystemStatusResponse(
        data=dashboard_system_status_payload(
            health=health,
            enabled_monitor_folders=enabled,
            current_import_task=current_task,
            latest_import_task=latest_task,
            failed_count=failed_count,
        )
    )


@router.get("/management/events")
def list_system_events(
    request: Request,
    page: int = 1,
    pageSize: int = 50,
    level: str | None = None,
    source: str | None = None,
    targetType: str | None = None,
    search: str | None = None,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ManagementEventsResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    if not _has_table(db, "SystemEvent"):
        return ManagementEventsResponse(
            data=management_events_empty_page(page, page_size)
        )
    storage = _event_storage_snapshot(db)
    date_from_ms, date_to_ms = parse_event_date_bounds(dateFrom, dateTo)
    events, total = library_dashboard.list_system_events_page(
        db,
        page=page,
        page_size=page_size,
        level=level,
        source=source,
        target_type=targetType,
        search=search,
        date_from_ms=date_from_ms,
        date_to_ms=date_to_ms,
    )
    sources = list_event_source_facets(db)
    levels = list_event_level_facets(db)
    return ManagementEventsResponse(
        data=management_events_payload(
            events=events,
            total=total,
            page=page,
            page_size=page_size,
            storage=storage,
            sources=sources,
            levels=levels,
        )
    )


@router.delete("/management/events")
def clear_system_events(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ClearedEventsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "SystemEvent"):
        return ClearedEventsResponse(data={"deleted": 0})
    deleted = library_dashboard.clear_info_warning_events(db)
    db.commit()
    record_system_event(
        db,
        level="info",
        source="system",
        action="events.cleared",
        actor_type="admin",
        actor_id=user.id,
        target_type="events",
        message=f"清理结构化日志 {deleted} 条",
        metadata={"deleted": deleted},
        commit=True,
    )
    return ClearedEventsResponse(
        data={"deleted": deleted, "storage": _event_storage_snapshot(db)}
    )


@router.get("/backups")
def list_backups(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BackupsResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"backups": list_backup_archives(settings)})


@router.get("/backups/{backup_id}")
def get_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BackupResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if not path.exists():
        return fail("备份不存在", status_code=404)
    return ok(backup_detail_payload(backup_id, path, list_backup_archives(settings)))


@router.post("/backups")
def create_backup(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BackupResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    backup = create_backup_archive(db, settings)
    return ok(backup_created_payload(backup), status_code=201)


@router.post("/backups/{backup_id}/restore")
def restore_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BackupRestoreResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if not path.exists():
        return fail("备份不存在", status_code=404)
    try:
        result = restore_backup_archive(db, settings, backup_id)
    except ValueError as exc:
        if str(exc) == "BACKUP_REVISION_UNSUPPORTED":
            return fail(
                "备份数据库版本不受支持，请使用旧版应用恢复后再升级。 "
                "/ Unsupported backup revision; restore it with the old "
                "application before upgrading.",
                status_code=400,
                code="BACKUP_REVISION_UNSUPPORTED",
            )
        return fail(str(exc), status_code=400)
    return ok(result)


@router.delete("/backups/{backup_id}")
def delete_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BackupDeleteResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if path.exists():
        path.unlink()
        return ok({"deleted": True, "id": backup_id})
    return ok({"deleted": False, "id": backup_id})


@router.get(
    "/backups/{backup_id}/download",
    response_class=BackupArchiveResponse,
)
def download_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return media_streaming.send_file(
        settings.resolved_storage_root / "backups" / f"{backup_id}.zip",
        request,
        user.id,
        media_type="application/zip",
        name=f"{backup_id}.zip",
        route="backup-download",
        file_id=backup_id,
    )
