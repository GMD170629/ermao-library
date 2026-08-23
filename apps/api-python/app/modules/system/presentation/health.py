import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.bootstrap.system import (
    create_or_reuse_health_run,
    health_run_snapshot,
    persist_log_settings_update,
    prepare_system_event,
    probe_database,
    prune_old_health_runs,
    run_system_health_checks,
    start_health_run,
    system_event_storage_view,
)
from app.contracts.http_errors import AdditionalStatusCodes, ErrorResponses
from app.core.auth import get_current_user
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.system.domain.events import validate_log_max_bytes
from app.modules.system.presentation.health_schemas import (
    DatabasePingPayload,
    DatabasePingResponse,
    HealthEventStreamResponse,
    HealthRunNotFoundBody,
    HealthRunNotFoundError,
    HealthRunPayload,
    HealthRunResponse,
    InvalidLogMaxBytesBody,
    InvalidLogMaxBytesError,
    LogSettingsPayload,
    LogSettingsResponse,
    ServiceHealthPayload,
    ServiceHealthResponse,
    SystemHealthPayload,
    SystemHealthResponse,
    SystemManagerRequiredBody,
    SystemManagerRequiredError,
    UnauthorizedBody,
    UnauthorizedError,
    UpdateLogSettingsRequest,
)
from app.modules.system.public import (
    MAX_MAX_EVENT_BYTES,
    MIN_MAX_EVENT_BYTES,
)

router = APIRouter(tags=["health"], route_class=TypedContractRoute)


@router.get("/health")
def health(
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[ServiceHealthResponse, AdditionalStatusCodes(503)]:
    health_status = run_system_health_checks(db, settings)
    response.status_code = (
        status.HTTP_200_OK
        if health_status["status"] == "ok"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return ServiceHealthResponse(
        data=ServiceHealthPayload(
            service="ermao-books",
            status=str(health_status["status"]),
        )
    )


@router.get("/system/health")
def system_health(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SystemHealthResponse:
    return SystemHealthResponse(
        data=SystemHealthPayload.model_validate(run_system_health_checks(db, settings))
    )


@router.get("/__db-ping")
def db_ping(db: Session = Depends(get_db)) -> DatabasePingResponse:
    probe_database(db)
    return DatabasePingResponse(data=DatabasePingPayload(database="ok"))


def _system_manager(db: Session, request: Request, settings: Settings):
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        raise UnauthorizedError(UnauthorizedBody())
    if not can_manage_system(user):
        raise SystemManagerRequiredError(
            SystemManagerRequiredBody(message="需要系统管理权限")
        )
    return user


@router.post("/system/health/runs")
def create_health_run(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    HealthRunResponse,
    AdditionalStatusCodes(201),
    ErrorResponses(UnauthorizedError, SystemManagerRequiredError),
]:
    user = _system_manager(db, request, settings)
    prune_old_health_runs(db)
    snapshot, created = create_or_reuse_health_run(db, settings, user.id)
    start_health_run(
        request.app.state.session_factory,
        bool(request.app.state.close_factory_sessions),
        settings,
        str(snapshot["runId"]),
    )
    response.status_code = 201 if created else 200
    return HealthRunResponse(
        data=HealthRunPayload.model_validate({"run": snapshot, "created": created})
    )


@router.get("/system/health/runs/{run_id}")
def get_health_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    HealthRunResponse,
    ErrorResponses(
        UnauthorizedError,
        SystemManagerRequiredError,
        HealthRunNotFoundError,
    ),
]:
    _system_manager(db, request, settings)
    snapshot = health_run_snapshot(db, run_id)
    if snapshot is None:
        raise HealthRunNotFoundError(
            HealthRunNotFoundBody(message="健康检查记录不存在")
        )
    return HealthRunResponse(data=HealthRunPayload.model_validate({"run": snapshot}))


@router.get(
    "/system/health/runs/{run_id}/events",
    response_class=HealthEventStreamResponse,
)
def stream_health_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    HealthEventStreamResponse,
    ErrorResponses(
        UnauthorizedError,
        SystemManagerRequiredError,
        HealthRunNotFoundError,
    ),
]:
    _system_manager(db, request, settings)
    if health_run_snapshot(db, run_id) is None:
        raise HealthRunNotFoundError(
            HealthRunNotFoundBody(message="健康检查记录不存在")
        )
    raw_last_id = (
        request.headers.get("last-event-id") or request.query_params.get("after") or "0"
    )
    try:
        initial_version = max(0, int(raw_last_id))
    except ValueError:
        initial_version = 0
    factory = request.app.state.session_factory
    close_sessions = bool(request.app.state.close_factory_sessions)

    async def events():
        last_version = initial_version
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                return
            stream_db = factory()
            try:
                snapshot = health_run_snapshot(stream_db, run_id)
            finally:
                if close_sessions:
                    stream_db.close()
            if snapshot is None:
                return
            version = int(snapshot.get("version") or 0)
            if version > last_version:
                has_running_item = any(
                    item.get("status") == "running"
                    for item in snapshot.get("items", [])
                )
                event_name = (
                    "run.completed"
                    if snapshot.get("status") in {"completed", "warning", "error"}
                    else "run.failed"
                    if snapshot.get("status") == "failed"
                    else "run.started"
                    if last_version == 0 and version == 1
                    else "check.started"
                    if has_running_item
                    else "check.updated"
                )
                payload = json.dumps({"run": snapshot}, ensure_ascii=False, default=str)
                yield f"id: {version}\nevent: {event_name}\ndata: {payload}\n\n"
                last_version = version
                idle_ticks = 0
                if snapshot.get("status") != "running":
                    return
            else:
                idle_ticks += 1
                if idle_ticks >= 15:
                    yield ": keep-alive\n\n"
                    idle_ticks = 0
            await asyncio.sleep(1)

    return HealthEventStreamResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/system/log-settings")
def get_log_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    LogSettingsResponse,
    ErrorResponses(UnauthorizedError, SystemManagerRequiredError),
]:
    _system_manager(db, request, settings)
    return LogSettingsResponse(
        data=LogSettingsPayload.model_validate(
            {
                "storage": system_event_storage_view(db),
                "minBytes": MIN_MAX_EVENT_BYTES,
                "maxBytes": MAX_MAX_EVENT_BYTES,
            }
        )
    )


@router.put("/system/log-settings")
def update_log_settings(
    payload: UpdateLogSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    LogSettingsResponse,
    ErrorResponses(
        UnauthorizedError,
        SystemManagerRequiredError,
        InvalidLogMaxBytesError,
    ),
]:
    user = _system_manager(db, request, settings)
    try:
        max_bytes = validate_log_max_bytes(payload.max_bytes)
    except ValueError:
        raise InvalidLogMaxBytesError(
            InvalidLogMaxBytesBody(message="日志容量上限必须在 1 MB 到 100 MB 之间")
        )
    prepared_event = prepare_system_event(
        source="system",
        action="settings.updated",
        message="更新系统日志容量上限",
        level="warning",
        actor_type="admin",
        actor_id=user.id,
        target_type="settings",
        metadata={"key": "system.logs.maxBytes", "maxBytes": max_bytes},
    )

    persist_log_settings_update(db, max_bytes=max_bytes, event=prepared_event)
    return LogSettingsResponse(
        data=LogSettingsPayload.model_validate(
            {"storage": system_event_storage_view(db)}
        )
    )
