import asyncio
import json

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.bootstrap.system import (
    active_health_run_id,
    create_or_reuse_health_run,
    create_restart_operation,
    health_run_snapshot,
    probe_database,
    prune_old_health_runs,
    queue_operation_view,
    queue_runtime_view,
    record_system_event,
    run_system_health_checks,
    set_max_event_bytes,
    start_health_run,
    system_event_storage_view,
)
from app.modules.system.public import MAX_MAX_EVENT_BYTES, MIN_MAX_EVENT_BYTES
from app.schemas.responses import fail, ok

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    health_status = run_system_health_checks(db, settings)
    status_code = status.HTTP_200_OK if health_status["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return ok(
        {"service": "shuku-starship", "status": health_status["status"]},
        status_code=status_code,
    )


@router.get("/system/health")
def system_health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return ok(run_system_health_checks(db, settings))


@router.get("/__db-ping")
def db_ping(db: Session = Depends(get_db)):
    probe_database(db)
    return ok({"database": "ok"})


def _system_manager(db: Session, request: Request, settings: Settings):
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
    if not can_manage_system(user):
        return None, fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    return user, None


@router.post("/system/health/runs")
def create_health_run(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    prune_old_health_runs(db)
    snapshot, created = create_or_reuse_health_run(db, settings, user.id)
    start_health_run(
        request.app.state.session_factory,
        bool(request.app.state.close_factory_sessions),
        settings,
        str(snapshot["runId"]),
    )
    return ok(
        {"run": snapshot, "created": created},
        status_code=201 if created else 200,
        normalize_timestamps=False,
    )


@router.get("/system/health/runs/{run_id}")
def get_health_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    snapshot = health_run_snapshot(db, run_id)
    return (
        ok({"run": snapshot}, normalize_timestamps=False)
        if snapshot
        else fail("健康检查记录不存在", status_code=404, code="HEALTH_RUN_NOT_FOUND")
    )


@router.get("/system/health/runs/{run_id}/events")
def stream_health_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    if health_run_snapshot(db, run_id) is None:
        return fail("健康检查记录不存在", status_code=404, code="HEALTH_RUN_NOT_FOUND")
    raw_last_id = request.headers.get("last-event-id") or request.query_params.get("after") or "0"
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
                has_running_item = any(item.get("status") == "running" for item in snapshot.get("items", []))
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
                    yield ": heartbeat\n\n"
                    idle_ticks = 0
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/system/queues/import/restart")
def restart_import_queue(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    if active_health_run_id(db):
        return fail("健康检查运行期间不能重启导入队列", status_code=409, code="HEALTH_RUN_ACTIVE")
    runtime = queue_runtime_view(db, "import")
    if runtime is None or runtime.get("stale") or runtime.get("status") != "running":
        return fail("导入工作进程当前不可用", status_code=409, code="IMPORT_QUEUE_OFFLINE")
    operation, created = create_restart_operation(db, user.id)
    return ok({"operation": operation, "created": created}, status_code=202)


@router.get("/system/queue-operations/{operation_id}")
def get_queue_operation(
    operation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    operation = queue_operation_view(db, operation_id)
    return ok({"operation": operation}) if operation else fail("队列操作不存在", status_code=404, code="QUEUE_OPERATION_NOT_FOUND")


@router.get("/system/log-settings")
def get_log_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"storage": system_event_storage_view(db), "minBytes": MIN_MAX_EVENT_BYTES, "maxBytes": MAX_MAX_EVENT_BYTES})


@router.put("/system/log-settings")
async def update_log_settings(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _system_manager(db, request, settings)
    if auth_error:
        return auth_error
    try:
        payload = await request.json()
        max_bytes = int(payload.get("maxBytes"))
        set_max_event_bytes(db, max_bytes)
    except (AttributeError, TypeError, ValueError):
        return fail("日志容量上限必须在 1 MB 到 100 MB 之间", status_code=400, code="INVALID_LOG_MAX_BYTES")
    record_system_event(
        db,
        source="system",
        action="settings.updated",
        message="更新系统日志容量上限",
        level="warning",
        actor_type="admin",
        actor_id=user.id,
        target_type="settings",
        metadata={"key": "system.logs.maxBytes", "maxBytes": max_bytes},
        commit=True,
    )
    return ok({"storage": system_event_storage_view(db)})
