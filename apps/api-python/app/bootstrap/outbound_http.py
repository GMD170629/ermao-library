"""Bind the shared sender to the persisted API/Worker proxy snapshot."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.request import BaseHandler, OpenerDirector, Request

import httpx
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.infrastructure.outbound_http import ProxyHTTPHandler, build_outbound_opener
from app.modules.system.public import NetworkProxy, read_network_proxy

_sessions: ContextVar[Callable[[], Session]] = ContextVar(
    "outbound_http_sessions", default=SessionLocal
)


@contextmanager
def use_outbound_sessions(factory: Callable[[], Session]) -> Iterator[None]:
    token = _sessions.set(factory)
    try:
        yield
    finally:
        _sessions.reset(token)


def current_outbound_sessions() -> Callable[[], Session]:
    return _sessions.get()


def outbound_opener(
    *handlers: BaseHandler,
    snapshot: NetworkProxy | None = None,
) -> OpenerDirector:
    if snapshot is None:
        with current_outbound_sessions()() as db:
            snapshot = read_network_proxy(db)
    connection = snapshot.connection
    handler = None
    if connection is not None and (snapshot.presets or snapshot.domains):
        address = httpx.URL(
            scheme=connection.protocol, host=connection.host, port=connection.port
        )
        auth = (
            (connection.username, connection.password)
            if connection.username or connection.password
            else None
        )
        handler = ProxyHTTPHandler(httpx.Proxy(address, auth=auth), snapshot.rules_for)
    return build_outbound_opener(*handlers, proxy_handler=handler)


def open_outbound(request: Request, *, timeout: float):
    return outbound_opener().open(request, timeout=timeout)
