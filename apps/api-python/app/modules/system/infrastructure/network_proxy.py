"""Persist a complete proxy snapshot in the existing system settings store."""

from sqlalchemy.orm import Session

from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.application.network_proxy import StoredProxy
from app.modules.system.domain.network_proxy import PROXY_SETTING_KEY, NetworkProxy

from .settings import get_setting, upsert_setting


def read_network_proxy(db: Session) -> NetworkProxy:
    return StoredProxy.model_validate(get_setting(db, PROXY_SETTING_KEY, {})).snapshot()


def resolve_network_proxy(db: Session, requested: StoredProxy) -> NetworkProxy:
    connection = requested.connection
    if connection is None or connection.password is not None:
        return requested.snapshot()
    previous = read_network_proxy(db).connection
    return requested.snapshot(previous.password if previous else "")


def save_network_proxy(db: Session, requested: StoredProxy) -> NetworkProxy:
    with SystemWriteTransaction(db):
        saved = resolve_network_proxy(db, requested)
        connection = saved.connection
        upsert_setting(
            db,
            PROXY_SETTING_KEY,
            {
                "connection": None
                if connection is None
                else {
                    "protocol": connection.protocol,
                    "host": connection.host,
                    "port": connection.port,
                    "username": connection.username,
                    "password": connection.password,
                },
                "presets": saved.presets,
                "domains": saved.domains,
            },
        )
    return saved
