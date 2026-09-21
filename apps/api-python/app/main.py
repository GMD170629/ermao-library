import asyncio
import logging
import signal
import threading
from collections.abc import Callable, Generator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route
from starlette.types import ExceptionHandler

from app.api.diagnostics_middleware import DiagnosticBoundaryMiddleware
from app.api.error_handlers import (
    request_validation_error_handler,
    typed_http_error_handler,
)
from app.api.router import api_router
from app.bootstrap.auth import build_password_authentication_runtime
from app.bootstrap.automation import build_mcp_endpoint
from app.bootstrap.opds import build_opds_router
from app.bootstrap.prestart import verify_current_schema
from app.bootstrap.publication_navigation import (
    build_publication_navigation_runtime,
)
from app.bootstrap.updates import UpdateRuntime
from app.contracts.http_errors import HttpContractError
from app.core.auth import get_current_user
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.core.exception_diagnostics import (
    configure_exception_storage,
    install_exception_hooks,
    install_loop_exception_handler,
    record_exception,
)
from app.core.logging_config import configure_logging
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
from app.services.kindle_queue import start_kindle_send_queue_worker
from app.services.log_maintenance import SystemEventMaintenanceWorker

LOGGER = logging.getLogger(__name__)

SYSTEM_MANAGER_PREFIXES = (
    "/api/management",
    "/api/libraries",
    "/api/system-settings",
    "/api/metadata/providers",
    "/api/download-tasks",
    "/api/organize",
    "/api/backups",
    "/api/tracking",
    "/api/email-settings",
    "/api/system/health/",
    "/api/system/log-settings",
)


def _requires_system_manager(path: str, method: str) -> bool:
    if method in {"GET", "HEAD"} and (
        path.startswith("/api/library-import-tasks/")
        or (path.startswith("/api/libraries/") and path.endswith("/import-tasks"))
    ):
        return False
    if path in {"/api/dashboard/system-status", "/api/system/health"}:
        return True
    if path == "/api/metadata/cover-proxy":
        return True
    if path.startswith(SYSTEM_MANAGER_PREFIXES):
        return True
    if (
        method == "POST"
        and path.startswith("/api/library/operations/")
        and path.endswith("/undo")
    ):
        return False
    if path.startswith("/api/library/") and path not in {
        "/api/library/facets",
        "/api/library/groupings",
        "/api/library/filter-schema",
        "/api/library/filter-options",
        "/api/library/operations/books/reading-status",
        "/api/library/operations/books/shelf-membership",
    }:
        return True
    if path == "/api/books/import":
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

    publication_navigation_runtime = build_publication_navigation_runtime(
        runtime_factory,
        settings,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        configure_exception_storage(background_runtime_factory)
        install_exception_hooks()
        if session_factory is None:
            verify_current_schema(engine)

        def report(stage: str, error: Exception) -> None:
            try:
                record_exception(
                    LOGGER,
                    "api.background_unavailable",
                    error,
                    context={"stage": stage, "outcome": "paused"},
                    source="system",
                    action="api.background_unavailable",
                )
            except Exception as diagnostic_error:  # noqa: BLE001 - safe fallback.
                LOGGER.error(
                    "api.background_unavailable stage=%s type=%s diagnostic_type=%s",
                    stage,
                    type(error).__name__,
                    type(diagnostic_error).__name__,
                )

        def release(stage: str, action: Callable[[], object]) -> None:
            try:
                action()
            except Exception as error:  # noqa: BLE001 - continue releasing other owners.
                report(stage, error)

        download_queue_worker = None
        kindle_send_queue_worker = None
        log_maintenance_worker = None
        try:
            download_queue_worker = start_download_queue_worker(
                background_runtime_factory,
                settings,
                heartbeat_runtime_factory,
            )
        except Exception as error:  # noqa: BLE001 - optional component boundary.
            report("download_start", error)
        try:
            kindle_send_queue_worker = start_kindle_send_queue_worker(
                background_runtime_factory,
                settings,
                heartbeat_runtime_factory,
            )
        except Exception as error:  # noqa: BLE001 - optional component boundary.
            report("kindle_start", error)
        try:
            log_maintenance_worker = SystemEventMaintenanceWorker(
                background_runtime_factory,
                settings=settings,
            )
            log_maintenance_worker.start()
        except Exception as error:  # noqa: BLE001 - optional component boundary.
            report("maintenance_start", error)
            if log_maintenance_worker is not None:
                release("maintenance_stop", log_maintenance_worker.stop)
        app.state.download_queue_worker = download_queue_worker
        app.state.kindle_send_queue_worker = kindle_send_queue_worker
        app.state.update_runtime = UpdateRuntime(settings)

        def stop_background() -> None:
            for worker in (
                download_queue_worker,
                kindle_send_queue_worker,
                log_maintenance_worker,
            ):
                if worker is not None:
                    release("request_stop", worker.request_stop)

        loop = asyncio.get_running_loop()
        install_loop_exception_handler(loop)
        signal_installed = (
            hasattr(signal, "SIGUSR1")
            and threading.current_thread() is threading.main_thread()
        )
        if signal_installed:
            loop.add_signal_handler(signal.SIGUSR1, stop_background)
        try:
            yield
        finally:
            stop_background()
            if signal_installed:
                loop.remove_signal_handler(signal.SIGUSR1)
            await run_in_threadpool(
                release, "update_stop", app.state.update_runtime.close
            )
            if download_queue_worker is not None:
                await run_in_threadpool(
                    release, "download_stop", download_queue_worker.stop
                )
            if kindle_send_queue_worker is not None:
                await run_in_threadpool(
                    release, "kindle_stop", kindle_send_queue_worker.stop
                )
            if log_maintenance_worker is not None:
                await run_in_threadpool(
                    release, "maintenance_stop", log_maintenance_worker.stop
                )
            release("navigation_stop", publication_navigation_runtime.close)

    app = FastAPI(
        title=settings.app_name, version=settings.app_version, lifespan=lifespan
    )
    # Starlette types handlers against ``Exception`` while dispatching the
    # registered exception class guarantees the narrower concrete type.
    app.add_exception_handler(
        HttpContractError,
        cast(ExceptionHandler, typed_http_error_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, request_validation_error_handler),
    )
    app.state.session_factory = runtime_factory
    app.state.close_factory_sessions = True
    # Reader delivery resolves its application service through app state.  The
    # composition root owns the concrete factory, while the capability
    # presentation stays independent of this module.
    from app.bootstrap.reader import reader_v5_service as build_reader_v5_service

    app.state.reader_v5_service_factory = build_reader_v5_service
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
    app.state.publication_navigation_runtime = publication_navigation_runtime

    def check_database_maintenance() -> bool:
        # Keep pool waits and the entire Session lifetime off the event loop.
        with runtime_factory() as maintenance_db:
            return database_maintenance_is_active(maintenance_db)

    # Inner boundary: unexpected route errors become a 500 envelope that still
    # carries a correlation id and never leaks internals.
    app.add_middleware(
        DiagnosticBoundaryMiddleware,
        session_factory=background_runtime_factory,
        respond_with_json=True,
    )

    @app.middleware("http")
    async def enforce_system_manager_boundary(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and await run_in_threadpool(
            check_database_maintenance
        ):
            return _vary_api_response_by_cookie(
                fail(
                    "DATABASE_MAINTENANCE",
                    status_code=503,
                    code="DATABASE_MAINTENANCE",
                )
            )
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

    # Outer boundary: middleware-layer database/permission failures are recorded
    # and then re-raised so the established propagation contract is preserved.
    app.add_middleware(
        DiagnosticBoundaryMiddleware,
        session_factory=background_runtime_factory,
        respond_with_json=False,
    )

    app.router.routes.append(
        Route(
            "/api/mcp",
            build_mcp_endpoint(runtime_factory, settings.app_version),
            methods=["GET", "POST", "DELETE"],
        )
    )
    app.include_router(api_router, prefix="/api")
    app.include_router(
        build_opds_router(runtime_factory, settings, password_authentication_runtime)
    )
    return app


app = create_app()
