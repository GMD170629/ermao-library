"""Validated input and persisted representation of the outbound proxy settings."""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.modules.system.domain.network_proxy import (
    NetworkProxy,
    ProxyConnection,
    ProxyPreset,
    normalize_host,
)


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
