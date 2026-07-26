from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from appv2.composition.container import build_container
from appv2.modules.accounts.api import create_router as accounts_router
from appv2.modules.catalog.api import create_router as catalog_router
from appv2.modules.delivery.api import create_router as delivery_router
from appv2.modules.discovery.api import create_router as discovery_router
from appv2.modules.ingestion.api import create_router as ingestion_router
from appv2.modules.metadata.api import create_router as metadata_router
from appv2.modules.operations.api import create_router as operations_router
from appv2.modules.reading.api import create_router as reading_router
from appv2.modules.reporting.api import create_router as reporting_router
from appv2.platform.config import Settings
from appv2.platform.http.middleware import OriginGuardMiddleware, TraceMiddleware
from appv2.platform.http.problems import ProblemDetails, install_problem_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        yield
        container.close()

    app = FastAPI(
        title="Shuku Starship API",
        version=container.settings.app_version,
        lifespan=lifespan,
        docs_url="/api/v2/docs",
        openapi_url="/api/v2/openapi.json",
        redoc_url=None,
        responses={
            422: {
                "model": ProblemDetails,
                "description": "RFC Problem Details validation response",
            }
        },
    )
    app.state.container = container
    app.add_middleware(
        OriginGuardMiddleware,
        allowed_origins=container.settings.allowed_origins,
    )
    app.add_middleware(TraceMiddleware)
    install_problem_handlers(app)

    prefix = "/api/v2"
    app.include_router(
        accounts_router(container.accounts, container.settings, container.current_account),
        prefix=prefix,
        tags=["accounts"],
    )
    app.include_router(
        catalog_router(container.catalog, container.current_account),
        prefix=prefix,
        tags=["catalog"],
    )
    app.include_router(
        ingestion_router(container.ingestion, container.current_account),
        prefix=prefix,
        tags=["ingestion"],
    )
    app.include_router(
        metadata_router(container.metadata, container.current_account),
        prefix=prefix,
        tags=["metadata"],
    )
    app.include_router(
        reading_router(container.reading, container.current_account),
        prefix=prefix,
        tags=["reading"],
    )
    app.include_router(
        discovery_router(container.discovery, container.current_account),
        prefix=prefix,
        tags=["discovery"],
    )
    app.include_router(
        delivery_router(container.delivery, container.current_account),
        prefix=prefix,
        tags=["delivery"],
    )
    app.include_router(
        operations_router(
            container.operations,
            container.current_account,
            container.settings.app_version,
        ),
        prefix=prefix,
        tags=["operations"],
    )
    app.include_router(
        reporting_router(container.reporting, container.current_account),
        prefix=prefix,
        tags=["reporting"],
    )
    return app
