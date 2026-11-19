"""Persist a complete proxy snapshot in the existing system settings store."""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.domain.network_proxy import (
    PROXY_SETTING_KEY,
    NetworkProxy,
    ProxyConnection,
    ProxyPreset,
    normalize_host,
)

from .settings import get_setting, upsert_setting


class StoredConnection(BaseModel):
    protocol: Literal["http", "socks5"]
    host: str
    port: int = Field(ge=1, le=65535)
    username: str = ""
    password: SecretStr | None = None

    @field_validator("host")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_host(value)


class StoredProxy(BaseModel):
    connection: StoredConnection | None = None
    presets: list[ProxyPreset] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        return list(
            dict.fromkeys(normalize_host(domain) for domain in values if domain.strip())
        )

    def snapshot(self, previous_password: str = "") -> NetworkProxy:
        connection = self.connection
        proxy = (
            None
            if connection is None
            else ProxyConnection(
                connection.protocol,
                connection.host,
                connection.port,
                connection.username,
                connection.password.get_secret_value()
                if connection.password is not None
                else previous_password,
            )
        )
        return NetworkProxy(
            proxy, tuple(dict.fromkeys(self.presets)), tuple(self.domains)
        )


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
                "presets": list(saved.presets),
                "domains": list(saved.domains),
            },
        )
    return saved
