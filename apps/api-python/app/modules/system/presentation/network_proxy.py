"""System manager interface for reading, saving and probing proxy settings."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager
from app.api.typed_route import TypedContractRoute
from app.bootstrap.network_proxy import (
    read_network_proxy,
    save_network_proxy,
    test_network_proxy,
)
from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import (
    BasicForbiddenError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db, release_read_transaction
from app.modules.system.application.network_proxy import StoredProxy
from app.modules.system.domain.network_proxy import (
    PROXY_PRESETS,
    NetworkProxy,
    ProxyPreset,
    ProxyProbeStatus,
    ProxyProtocol,
)

router = APIRouter(
    prefix="/system-settings/network-proxy",
    tags=["network_proxy"],
    route_class=TypedContractRoute,
)


class ConnectionView(HttpContractModel):
    protocol: ProxyProtocol
    host: str
    port: int
    username: str
    passwordConfigured: bool


class NetworkProxyView(HttpContractModel):
    connection: ConnectionView | None
    presets: list[ProxyPreset]
    domains: list[str]
    presetDomains: dict[ProxyPreset, list[str]]


class ProxyProbe(HttpContractModel):
    host: str
    rules: list[str]
    result: ProxyProbeStatus
    status: int | None = None


ProxyViewResponse = Annotated[
    SuccessEnvelope[NetworkProxyView] | Response,
    ErrorResponses(BasicUnauthorizedError, BasicForbiddenError),
]
ProbeResponse = Annotated[
    SuccessEnvelope[list[ProxyProbe]] | Response,
    ErrorResponses(BasicUnauthorizedError, BasicForbiddenError),
]


def view(snapshot: NetworkProxy) -> NetworkProxyView:
    connection = snapshot.connection
    return NetworkProxyView(
        connection=None
        if connection is None
        else ConnectionView(
            protocol=connection.protocol,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            passwordConfigured=bool(connection.password),
        ),
        presets=list(snapshot.presets),
        domains=list(snapshot.domains),
        presetDomains={key: list(domains) for key, domains in PROXY_PRESETS.items()},
    )


@router.get("", response_model=SuccessEnvelope[NetworkProxyView])
def read_proxy(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProxyViewResponse:
    _, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    return SuccessEnvelope(data=view(read_network_proxy(db)))


@router.put("", response_model=SuccessEnvelope[NetworkProxyView])
def save_proxy(
    payload: StoredProxy,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProxyViewResponse:
    _, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    release_read_transaction(db)
    return SuccessEnvelope(data=view(save_network_proxy(db, payload)))


@router.post("/test", response_model=SuccessEnvelope[list[ProxyProbe]])
def test_proxy(
    payload: StoredProxy,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProbeResponse:
    _, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    results = test_network_proxy(db, payload)
    return SuccessEnvelope(
        data=[
            ProxyProbe(
                host=item.host,
                rules=list(item.rules),
                result=item.result,
                status=item.status,
            )
            for item in results
        ]
    )
