from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.session import SessionLocal
from app.db.session import engine
from app.services.download_queue import start_download_queue_worker
from app.services.kindle_queue import start_kindle_send_queue_worker


def create_app(settings_override: Settings | None = None, session_factory: Callable[[], Session] | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    factory = session_factory or SessionLocal

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if session_factory is None:
            bootstrap_database(engine, settings)
        download_queue_worker = start_download_queue_worker(factory, settings)
        kindle_send_queue_worker = start_kindle_send_queue_worker(factory, settings)
        app.state.download_queue_worker = download_queue_worker
        app.state.kindle_send_queue_worker = kindle_send_queue_worker
        try:
            yield
        finally:
            if download_queue_worker is not None:
                download_queue_worker.stop()
            if kindle_send_queue_worker is not None:
                kindle_send_queue_worker.stop()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
