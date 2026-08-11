"""Versioned compatibility values advertised to native mobile clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SERVER_IDENTITY_SETTING_KEY = "mobile.serverIdentity"
MOBILE_SERVICE_NAME: Literal["ermao-books"] = "ermao-books"
MOBILE_PROTOCOL_VERSION: Literal[1] = 1
MINIMUM_SUPPORTED_MOBILE_CLIENT_VERSION: Literal[1] = 1
MOBILE_READER_SCHEMA_VERSION: Literal[4] = 4


@dataclass(frozen=True, slots=True)
class MobileProtocolCompatibility:
    version: Literal[1]
    minimum_supported_client_version: Literal[1]


@dataclass(frozen=True, slots=True)
class MobileCapabilities:
    setup: Literal[True]
    cookie_session: Literal[True]
    reader_v3: Literal[True]
    media_range: Literal[True]
    managed_offline_downloads: Literal[False]


@dataclass(frozen=True, slots=True)
class MobileCompatibility:
    service: Literal["ermao-books"]
    server_identity: str
    server_version: str
    protocol: MobileProtocolCompatibility
    reader_schema_version: Literal[4]
    capabilities: MobileCapabilities


def mobile_compatibility(
    *,
    server_identity: str,
    server_version: str,
) -> MobileCompatibility:
    """Build the immutable protocol snapshot for the current server."""

    return MobileCompatibility(
        service=MOBILE_SERVICE_NAME,
        server_identity=server_identity,
        server_version=server_version,
        protocol=MobileProtocolCompatibility(
            version=MOBILE_PROTOCOL_VERSION,
            minimum_supported_client_version=MINIMUM_SUPPORTED_MOBILE_CLIENT_VERSION,
        ),
        reader_schema_version=MOBILE_READER_SCHEMA_VERSION,
        capabilities=MobileCapabilities(
            setup=True,
            cookie_session=True,
            reader_v3=True,
            media_range=True,
            managed_offline_downloads=False,
        ),
    )
