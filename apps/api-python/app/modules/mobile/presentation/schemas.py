"""Typed HTTP schemas for the mobile compatibility handshake."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError


class MobileProtocolPayload(HttpContractModel):
    version: Literal[1] = 1
    minimum_supported_client_version: Literal[1] = Field(
        default=1,
        alias="minimumSupportedClientVersion",
    )


class MobileCapabilitiesPayload(HttpContractModel):
    setup: Literal[True] = True
    cookie_session: Literal[True] = Field(default=True, alias="cookieSession")
    reader_v4: Literal[True] = Field(default=True, alias="readerV4")
    media_range: Literal[True] = Field(default=True, alias="mediaRange")
    managed_offline_downloads: Literal[False] = Field(
        default=False,
        alias="managedOfflineDownloads",
    )


class MobileCompatibilityPayload(HttpContractModel):
    service: Literal["ermao-books"] = "ermao-books"
    server_identity: str = Field(alias="serverIdentity", min_length=1, max_length=191)
    server_version: str = Field(alias="serverVersion", min_length=1)
    protocol: MobileProtocolPayload
    reader_schema_version: Literal[4] = Field(default=4, alias="readerSchemaVersion")
    capabilities: MobileCapabilitiesPayload


class MobileCompatibilityUnavailableBody(HttpContractModel):
    message: Literal["MOBILE_COMPATIBILITY_UNAVAILABLE"] = (
        "MOBILE_COMPATIBILITY_UNAVAILABLE"
    )
    code: Literal["MOBILE_COMPATIBILITY_UNAVAILABLE"] = (
        "MOBILE_COMPATIBILITY_UNAVAILABLE"
    )


class MobileCompatibilityUnavailableError(
    HttpContractError[MobileCompatibilityUnavailableBody]
):
    status_code = 503
    body_model = MobileCompatibilityUnavailableBody


MobileCompatibilityResponse = SuccessEnvelope[MobileCompatibilityPayload]
