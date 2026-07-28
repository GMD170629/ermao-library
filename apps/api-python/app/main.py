from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.api.router import api_router
from fastapi.exceptions import RequestValidationError

from app.api.error_handlers import (
    request_validation_error_handler,
    typed_http_error_handler,
)
from app.contracts.http_errors import HttpContractError
from app.core.auth import get_current_user
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.session import HeartbeatSessionLocal, SessionLocal
from app.db.session import engine
from app.services.download_queue import start_download_queue_worker
from app.services.kindle_queue import start_kindle_send_queue_worker
from app.services.health_runs import fail_abandoned_health_runs
from app.services.log_maintenance import SystemEventMaintenanceWorker
from app.schemas.responses import fail


SYSTEM_MANAGER_PREFIXES = (
    "/api/management",
    "/api/monitor-folders",
    "/api/system-settings",
    "/api/metadata/providers",
    "/api/sources",
    "/api/source-search-records",
    "/api/download-tasks",
    "/api/import-tasks",
    "/api/organize",
    "/api/backups",
    "/api/tracking",
    "/api/email-settings",
    "/api/system/health/",
    "/api/system/queues",
    "/api/system/queue-operations",
    "/api/system/log-settings",
)


def _requires_system_manager(path: str, method: str) -> bool:
    if path in {"/api/dashboard/system-status", "/api/system/health"}:
        return True
    if path == "/api/metadata/cover-proxy":
        return True
    if path.startswith(SYSTEM_MANAGER_PREFIXES):
        return True
    if path.startswith("/api/library/") and path not in {"/api/library/facets", "/api/library/filter-schema"}:
        return True
    if path in {"/api/works/import", "/api/works/bulk/cover", "/api/works/bulk/find-replace/preview"}:
        return True
    return method != "GET" and path.startswith("/api/metadata/")


def _vary_api_response_by_cookie(response):
    current = response.headers.get("Vary", "")
    values = [item.strip() for item in current.split(",") if item.strip()]
    if not any(item.lower() == "cookie" for item in values):
        values.append("Cookie")
    response.headers["Vary"] = ", ".join(values)
    return response


def create_app(settings_override: Settings | None = None, session_factory: Callable[[], Session] | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    factory = session_factory or SessionLocal
    if session_factory is None:
        runtime_factory = factory
        heartbeat_runtime_factory = HeartbeatSessionLocal
    else:
        injected_session = factory()
        runtime_factory = sessionmaker(
            bind=injected_session.get_bind(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        heartbeat_runtime_factory = runtime_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if session_factory is None:
            bootstrap_database(engine, settings)
        download_queue_worker = start_download_queue_worker(
            runtime_factory,
            settings,
            heartbeat_runtime_factory,
        )
        kindle_send_queue_worker = start_kindle_send_queue_worker(
            runtime_factory,
            settings,
            heartbeat_runtime_factory,
        )
        startup_db = runtime_factory()
        try:
            fail_abandoned_health_runs(startup_db)
        finally:
            startup_db.close()
        log_maintenance_worker = SystemEventMaintenanceWorker(runtime_factory)
        log_maintenance_worker.start()
        app.state.download_queue_worker = download_queue_worker
        app.state.kindle_send_queue_worker = kindle_send_queue_worker
        try:
            yield
        finally:
            if download_queue_worker is not None:
                download_queue_worker.stop()
            if kindle_send_queue_worker is not None:
                kindle_send_queue_worker.stop()
            log_maintenance_worker.stop()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_exception_handler(HttpContractError, typed_http_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.state.session_factory = runtime_factory
    app.state.close_factory_sessions = True

    @app.middleware("http")
    async def enforce_system_manager_boundary(request, call_next):
        if not _requires_system_manager(request.url.path, request.method):
            return _vary_api_response_by_cookie(await call_next(request))
        db = factory()
        try:
            user, _token, _refresh = get_current_user(db, request, settings)
            if user is None:
                return _vary_api_response_by_cookie(
                    fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
                )
            if not can_manage_system(user):
                return _vary_api_response_by_cookie(
                    fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
                )
        finally:
            if session_factory is None:
                db.close()
        return _vary_api_response_by_cookie(await call_next(request))

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
