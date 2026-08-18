import logging
from collections.abc import Callable, Generator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.error_handlers import (
    request_validation_error_handler,
    typed_http_error_handler,
)
from app.api.router import api_router
from app.bootstrap.auth import build_password_authentication_runtime
from app.bootstrap.opds import build_opds_router
from app.bootstrap.startup_data_migrations import (
    verify_startup_data_migrations_complete,
)
from app.contracts.http_errors import HttpContractError
from app.core.auth import get_current_user
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.core.database_errors import (
    is_database_busy_error,
    is_database_operation_timeout,
)
from app.db.maintenance import database_maintenance_is_active
from app.db.session import (
    BackgroundSessionLocal,
    HeartbeatSessionLocal,
    SessionLocal,
    engine,
    get_db,
    get_short_write_db,
)
from app.schemas.responses import fail
from app.services.download_queue import start_download_queue_worker
from app.services.health_runs import fail_abandoned_health_runs
from app.services.kindle_queue import start_kindle_send_queue_worker
from app.services.log_maintenance import SystemEventMaintenanceWorker

LOGGER = logging.getLogger(__name__)

SYSTEM_MANAGER_PREFIXES = (
    "/api/management",
    "/api/libraries",
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
    if path.startswith("/api/library/") and path not in {
        "/api/library/facets",
        "/api/library/filter-schema",
        "/api/library/filter-options",
    }:
        return True
    if path in {
        "/api/works/import",
        "/api/works/bulk/cover",
        "/api/works/bulk/find-replace/preview",
    }:
        return True
    return method != "GET" and path.startswith("/api/metadata/")


def _vary_api_response_by_cookie(response):
    current = response.headers.get("Vary", "")
    values = [item.strip() for item in current.split(",") if item.strip()]
    if not any(item.lower() == "cookie" for item in values):
        values.append("Cookie")
    response.headers["Vary"] = ", ".join(values)
    return response


def create_app(
    settings_override: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> FastAPI:
    settings = settings_override or get_settings()
    factory = session_factory or SessionLocal
    if session_factory is None:
        runtime_factory = factory
        background_runtime_factory = BackgroundSessionLocal
        heartbeat_runtime_factory = HeartbeatSessionLocal
    else:
        injected_session = factory()
        try:
            runtime_factory = sessionmaker(
                bind=injected_session.get_bind(),
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
            )
        finally:
            injected_session.close()
        heartbeat_runtime_factory = runtime_factory
        background_runtime_factory = runtime_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if session_factory is None:
            verify_startup_data_migrations_complete(engine, SessionLocal)
        download_queue_worker = start_download_queue_worker(
            background_runtime_factory,
            settings,
            heartbeat_runtime_factory,
        )
        kindle_send_queue_worker = start_kindle_send_queue_worker(
            background_runtime_factory,
            settings,
            heartbeat_runtime_factory,
        )
        startup_db = background_runtime_factory()
        try:
            fail_abandoned_health_runs(startup_db)
        except OperationalError as error:
            if not (
                is_database_busy_error(error) or is_database_operation_timeout(error)
            ):
                raise
            LOGGER.warning(
                "startup_health_recovery outcome=deferred reason=%s",
                "database_busy"
                if is_database_busy_error(error)
                else "time_budget_exceeded",
            )
        finally:
            startup_db.close()
        log_maintenance_worker = SystemEventMaintenanceWorker(
            background_runtime_factory
        )
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

    app = FastAPI(
        title=settings.app_name, version=settings.app_version, lifespan=lifespan
    )
    app.add_exception_handler(HttpContractError, typed_http_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.state.session_factory = runtime_factory
    app.state.close_factory_sessions = True
    if session_factory is not None:

        def get_runtime_db() -> Generator[Session, None, None]:
            db = runtime_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = get_runtime_db
        app.dependency_overrides[get_short_write_db] = get_runtime_db
    password_authentication_runtime = build_password_authentication_runtime(settings)
    app.state.password_authentication_runtime = password_authentication_runtime

    @app.middleware("http")
    async def enforce_system_manager_boundary(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            maintenance_db = runtime_factory()
            try:
                if database_maintenance_is_active(maintenance_db):
                    return _vary_api_response_by_cookie(
                        fail(
                            "DATABASE_MAINTENANCE",
                            status_code=503,
                            code="DATABASE_MAINTENANCE",
                        )
                    )
            finally:
                maintenance_db.close()
        if not _requires_system_manager(request.url.path, request.method):
            response = await call_next(request)
            return (
                _vary_api_response_by_cookie(response)
                if request.url.path.startswith("/api")
                else response
            )
        db = runtime_factory()
        try:
            user, _token, _refresh = get_current_user(db, request, settings)
            if user is None:
                return _vary_api_response_by_cookie(
                    fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
                )
            if not can_manage_system(user):
                return _vary_api_response_by_cookie(
                    fail(
                        "需要系统管理权限",
                        status_code=403,
                        code="SYSTEM_MANAGER_REQUIRED",
                    )
                )
        finally:
            db.close()
        return _vary_api_response_by_cookie(await call_next(request))

    app.include_router(api_router, prefix="/api")
    app.include_router(
        build_opds_router(runtime_factory, settings, password_authentication_runtime)
    )
    return app


app = create_app()
