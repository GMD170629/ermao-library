"""Application query for the native mobile compatibility handshake."""

from __future__ import annotations

from typing import Protocol

from app.modules.mobile.domain.compatibility import (
    MobileCompatibility,
    mobile_compatibility,
)


class ServerIdentityReader(Protocol):
    def read_server_identity(self) -> str | None: ...


class ServerIdentityUnavailable(RuntimeError):
    """The bootstrapped server identity is missing or invalid."""


class GetMobileCompatibility:
    def __init__(
        self,
        server_identity_reader: ServerIdentityReader,
        *,
        server_version: str,
    ) -> None:
        self._server_identity_reader = server_identity_reader
        self._server_version = server_version

    def execute(self) -> MobileCompatibility:
        server_identity = self._server_identity_reader.read_server_identity()
        if server_identity is None or not server_identity.strip():
            raise ServerIdentityUnavailable("mobile server identity is unavailable")
        return mobile_compatibility(
            server_identity=server_identity,
            server_version=self._server_version,
        )
