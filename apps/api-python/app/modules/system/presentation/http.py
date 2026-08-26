"""System capability HTTP surface."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager, require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import (
    get_library_scan_settings,
    update_library_scan_settings,
)
from app.bootstrap.system import (
    clear_system_events_with_audit,
    configured_max_event_bytes,
    library_import_dashboard_snapshot,
    list_settings,
    list_system_events_page,
    management_overview_snapshot,
    persist_system_settings_update,
    prepare_system_event,
    run_system_health_checks,
    system_event_storage_view,
)
from app.contracts.http_errors import ErrorResponses
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.imports.public import (
    LibraryScanSettings,
)
from app.modules.system.application.queries import (
    SettingsUpdateError,
    app_config_payload,
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
    ClearedEventsPayload,
    ClearedEventsResponse,
    DashboardSystemStatusPayload,
    DashboardSystemStatusResponse,
    LibraryScanSystemSettingsPayload,
    LibraryScanSystemSettingsResponse,
    ManagementEventsPayload,
    ManagementEventsResponse,
    ManagementOverviewPayload,
    ManagementOverviewResponse,
    SystemSettingsResponse,
    UpdateLibraryScanSystemSettingsRequest,
    UpdateSystemSettingsRequest,
)
from app.schemas.responses import fail, ok
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


@router.get("/app-config", response_model=AppConfigResponse)
def get_public_app_config(
    http_response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_frontend_resource_version: Annotated[
        str | None, Header(alias="X-Shuku-Frontend-Resource-Version")
    ] = None,
) -> AppConfigResponse | Response:
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


@router.get("/system-settings", response_model=SystemSettingsResponse)
def get_system_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SystemSettingsResponse | Response,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return ok(system_settings_payload(list_settings(db)))


def _library_scan_settings_payload(
    db: Session, settings: Settings
) -> LibraryScanSystemSettingsPayload:
    snapshot = get_library_scan_settings(
        db,
        legacy_interval_ms=settings.library_scan_interval_ms,
    )
    return LibraryScanSystemSettingsPayload(
        watchEnabled=snapshot.watch_enabled,
        intervalMinutes=snapshot.interval_minutes,
    )


@router.get(
    "/system-settings/library-scan",
    response_model=LibraryScanSystemSettingsResponse,
)
def get_library_scan_system_settings(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LibraryScanSystemSettingsResponse | Response:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return ok(_library_scan_settings_payload(db, settings))


@router.put(
    "/system-settings/library-scan",
    response_model=LibraryScanSystemSettingsResponse,
)
def update_library_scan_system_settings(
    payload: UpdateLibraryScanSystemSettingsRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LibraryScanSystemSettingsResponse | Response:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    updated = update_library_scan_settings(
        db,
        LibraryScanSettings(
            watch_enabled=payload.watch_enabled,
            interval_minutes=payload.interval_minutes,
        ),
        legacy_interval_ms=settings.library_scan_interval_ms,
    )
    return ok(
        LibraryScanSystemSettingsPayload(
            watchEnabled=updated.watch_enabled,
            intervalMinutes=updated.interval_minutes,
        )
    )


@router.put("/system-settings", response_model=SystemSettingsResponse)
@router.patch("/system-settings", response_model=SystemSettingsResponse)
def update_system_settings(
    payload: UpdateSystemSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SystemSettingsResponse | Response,
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


@router.get("/dashboard/system-status", response_model=DashboardSystemStatusResponse)
def dashboard_system_status(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardSystemStatusResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    health = run_system_health_checks(db, settings)
    snapshot = library_import_dashboard_snapshot(db)
    return DashboardSystemStatusResponse(
        data=DashboardSystemStatusPayload.model_validate(
            dashboard_system_status_payload(
                health=health,
                enabled_libraries=snapshot["enabled_libraries"],
                current_import_task=snapshot["current_task"],
                latest_import_task=snapshot["latest_task"],
                failed_count=snapshot["failed_count"],
            )
        )
    )


@router.get("/management/events", response_model=ManagementEventsResponse)
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
    ManagementEventsResponse | Response,
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
        data=ManagementEventsPayload.model_validate(
            management_events_payload(
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
    )


@router.get("/management/overview", response_model=ManagementOverviewResponse)
def get_management_overview(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ManagementOverviewResponse | Response,
    ErrorResponses(SystemManagerRequiredError),
]:
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return ManagementOverviewResponse(
        data=ManagementOverviewPayload.model_validate(
            management_overview_snapshot(db, settings)
        )
    )


@router.delete("/management/events", response_model=ClearedEventsResponse)
def clear_system_events(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ClearedEventsResponse | Response,
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
        data=ClearedEventsPayload.model_validate(
            {"deleted": deleted, "storage": _event_storage_snapshot(db)}
        )
    )
