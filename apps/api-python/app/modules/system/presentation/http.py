"""System capability HTTP surface."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager, require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.media import media_streaming
from app.bootstrap.system import (
    clear_system_events_with_audit,
    configured_max_event_bytes,
    get_setting,
    library_import_dashboard_snapshot,
    list_settings,
    list_system_events_page,
    persist_opds_settings_update,
    persist_system_settings_update,
    prepare_system_event,
    run_system_health_checks,
    system_event_storage_view,
)
from app.contracts.http_errors import ErrorResponses
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.opds.public import (
    OPDS_ENABLED_SETTING_KEY,
    OPDS_PUBLIC_BASE_URL_SETTING_KEY,
    OpdsPublicBaseUrlInvalid,
    OpdsPublicBaseUrlRequired,
    resolve_opds_settings,
    validate_opds_activation,
)
from app.modules.system.application.queries import (
    SettingsUpdateError,
    app_config_payload,
    backup_created_payload,
    backup_detail_payload,
    dashboard_system_status_payload,
    management_events_payload,
    parse_event_date_bounds,
    prepare_system_settings_update,
    system_settings_payload,
)
from app.modules.system.presentation.health_schemas import SystemManagerRequiredError
from app.modules.system.presentation.schemas import (
    AppConfigPayload,
    AppConfigResponse,
    BackupArchiveResponse,
    BackupDeleteResponse,
    BackupResponse,
    BackupRestoreRequest,
    BackupRestoreResponse,
    BackupsResponse,
    ClearedEventsResponse,
    DashboardSystemStatusResponse,
    ManagementEventsResponse,
    OpdsSystemSettingsPayload,
    OpdsSystemSettingsResponse,
    SystemSettingsResponse,
    UpdateOpdsSystemSettingsRequest,
    UpdateSystemSettingsRequest,
)
from app.schemas.responses import fail, ok
from app.services.backup_service import create_backup as create_backup_archive
from app.services.backup_service import list_backups as list_backup_archives
from app.services.backup_service import restore_backup as restore_backup_archive
from app.services.import_preferences import (
    IMPORT_PREFERENCE_KEYS,
    normalize_import_setting_value,
)

router = APIRouter(tags=["system"], route_class=TypedContractRoute)


def _event_storage_snapshot(db: Session) -> dict[str, int]:
    storage = system_event_storage_view(db)
    return {
        "deleted": 0,
        "sizeBytes": int(storage["sizeBytes"]),
        "maxBytes": int(storage["maxBytes"]),
    }


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _system_manager(db: Session, request: Request, settings: Settings):
    return require_system_manager(db, request, settings)


@router.get("/app-config")
def get_public_app_config(
    http_response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_frontend_resource_version: Annotated[
        str | None, Header(alias="X-Shuku-Frontend-Resource-Version")
    ] = None,
) -> AppConfigResponse:
    http_response.headers["Cache-Control"] = "private, no-store"
    return AppConfigResponse(
        data=AppConfigPayload.model_validate(
            app_config_payload(
                db,
                current_frontend_resource_version=current_frontend_resource_version,
                latest_version=settings.app_version,
            )
        )
    )


@router.get("/system-settings")
def get_system_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SystemSettingsResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return ok(system_settings_payload(list_settings(db)))


def _opds_settings_payload(db: Session) -> OpdsSystemSettingsPayload:
    snapshot = resolve_opds_settings(
        get_setting(db, OPDS_ENABLED_SETTING_KEY, None),
        stored_public_base_url=get_setting(db, OPDS_PUBLIC_BASE_URL_SETTING_KEY, None),
    )
    return OpdsSystemSettingsPayload(
        enabled=snapshot.enabled,
        configured=snapshot.configured,
        publicBaseUrl=snapshot.public_base_url,
        catalogUrl=snapshot.catalog_url,
    )


@router.get("/system-settings/opds")
def get_opds_system_settings(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpdsSystemSettingsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_manage_system(user):
        return fail(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    return ok(_opds_settings_payload(db))


@router.put("/system-settings/opds")
def update_opds_system_settings(
    payload: UpdateOpdsSystemSettingsRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpdsSystemSettingsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_manage_system(user):
        return fail(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    try:
        normalized_public_base_url = validate_opds_activation(
            payload.enabled, payload.public_base_url
        )
    except OpdsPublicBaseUrlRequired:
        return fail(
            "启用 OPDS 前必须填写公开 URL",
            status_code=409,
            code="OPDS_PUBLIC_BASE_URL_REQUIRED",
        )
    except OpdsPublicBaseUrlInvalid:
        return fail(
            "OPDS 公开 URL 必须是有效的 HTTP 或 HTTPS 地址，"
            "且不能包含凭据、查询参数或片段",
            status_code=400,
            code="OPDS_PUBLIC_BASE_URL_INVALID",
        )

    prepared_settings = {
        OPDS_ENABLED_SETTING_KEY: payload.enabled,
        OPDS_PUBLIC_BASE_URL_SETTING_KEY: normalized_public_base_url,
    }
    prepared_event = prepare_system_event(
        level="info",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="opds.settings.updated",
        target_type="settings",
        message="已开启 OPDS" if payload.enabled else "已关闭 OPDS",
        metadata={"enabled": payload.enabled},
    )

    persist_opds_settings_update(
        db,
        setting_values=prepared_settings,
        event=prepared_event,
    )
    return ok(_opds_settings_payload(db))


@router.put("/system-settings")
@router.patch("/system-settings")
def update_system_settings(
    payload: UpdateSystemSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SystemSettingsResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    prepared = prepare_system_settings_update(
        payload.settings,
        payload.clear_sensitive_keys,
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
    saved_with_clears = {**saved, **{key: "" for key in clear_keys}}
    prepared_event = prepare_system_event(
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="settings.updated",
        target_type="settings",
        message=f"更新系统设置 {len(saved_with_clears)} 项",
        metadata={"keys": list(saved_with_clears)},
    )

    persist_system_settings_update(
        db,
        setting_values=saved,
        clear_keys=tuple(clear_keys),
        event=prepared_event,
    )
    return ok(system_settings_payload(saved_with_clears))


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
    snapshot = library_import_dashboard_snapshot(db)
    return DashboardSystemStatusResponse(
        data=dashboard_system_status_payload(
            health=health,
            enabled_libraries=snapshot["enabled_libraries"],
            current_import_task=snapshot["current_task"],
            latest_import_task=snapshot["latest_task"],
            failed_count=snapshot["failed_count"],
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
) -> Annotated[
    ManagementEventsResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    date_from_ms, date_to_ms = parse_event_date_bounds(dateFrom, dateTo)
    snapshot = list_system_events_page(
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
    return ManagementEventsResponse(
        data=management_events_payload(
            events=snapshot.events,
            total=snapshot.total,
            page=snapshot.page,
            page_size=page_size,
            storage={
                "deleted": 0,
                "sizeBytes": snapshot.size_bytes,
                "maxBytes": configured_max_event_bytes(db),
            },
            sources=snapshot.sources,
            levels=snapshot.levels,
        )
    )


@router.delete("/management/events")
def clear_system_events(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ClearedEventsResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    prepared_event = prepare_system_event(
        level="info",
        source="system",
        action="events.cleared",
        actor_type="admin",
        actor_id=user.id,
        target_type="events",
        message="清理结构化日志",
    )

    deleted = clear_system_events_with_audit(db, event=prepared_event)
    return ClearedEventsResponse(
        data={"deleted": deleted, "storage": _event_storage_snapshot(db)}
    )


@router.get("/backups")
def list_backups(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BackupsResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"backups": list_backup_archives(settings)})


@router.get("/backups/{backup_id}")
def get_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BackupResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if not path.exists():
        return fail("备份不存在", status_code=404)
    return ok(backup_detail_payload(backup_id, path, list_backup_archives(settings)))


@router.post("/backups", status_code=201)
def create_backup(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BackupResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    backup = create_backup_archive(db, settings)
    return ok(backup_created_payload(backup), status_code=201)


@router.post("/backups/{backup_id}/restore")
def restore_backup(
    backup_id: str,
    request: Request,
    _payload: BackupRestoreRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BackupRestoreResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
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
) -> Annotated[
    BackupDeleteResponse,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
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
) -> Annotated[Response, ErrorResponses(SystemManagerRequiredError)]:
    user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return media_streaming.send_file(
        settings.resolved_storage_root / "backups" / f"{backup_id}.zip",
        request,
        user.id,
        media_type="application/zip",
        name=f"{backup_id}.zip",
        route="backup-download",
        asset_id=backup_id,
    )
