"""Public mobile compatibility HTTP adapter."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.typed_route import TypedContractRoute
from app.contracts.http_errors import ErrorResponses
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.mobile.application.compatibility import (
    GetMobileCompatibility,
    ServerIdentityUnavailable,
)
from app.modules.mobile.infrastructure.server_identity import (
    SqlAlchemyServerIdentityReader,
)
from app.modules.mobile.presentation.schemas import (
    MobileCapabilitiesPayload,
    MobileCompatibilityPayload,
    MobileCompatibilityResponse,
    MobileCompatibilityUnavailableBody,
    MobileCompatibilityUnavailableError,
    MobileProtocolPayload,
)

router = APIRouter(prefix="/mobile", tags=["mobile"], route_class=TypedContractRoute)


@router.get("/compatibility")
def get_mobile_compatibility(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Annotated[
    MobileCompatibilityResponse,
    ErrorResponses(MobileCompatibilityUnavailableError),
]:
    response.headers["Cache-Control"] = "no-store"
    try:
        compatibility = GetMobileCompatibility(
            SqlAlchemyServerIdentityReader(db),
            server_version=settings.app_version,
        ).execute()
    except ServerIdentityUnavailable as error:
        raise MobileCompatibilityUnavailableError(
            MobileCompatibilityUnavailableBody()
        ) from error

    return MobileCompatibilityResponse(
        data=MobileCompatibilityPayload(
            service=compatibility.service,
            serverIdentity=compatibility.server_identity,
            serverVersion=compatibility.server_version,
            protocol=MobileProtocolPayload(
                version=compatibility.protocol.version,
                minimumSupportedClientVersion=(
                    compatibility.protocol.minimum_supported_client_version
                ),
            ),
            readerSchemaVersion=compatibility.reader_schema_version,
            librarySchemaVersion=compatibility.library_schema_version,
            capabilities=MobileCapabilitiesPayload(
                setup=compatibility.capabilities.setup,
                cookieSession=compatibility.capabilities.cookie_session,
                readerV5=compatibility.capabilities.reader_v5,
                mediaRange=compatibility.capabilities.media_range,
                managedOfflineDownloads=(
                    compatibility.capabilities.managed_offline_downloads
                ),
                bookResourceAsset=compatibility.capabilities.book_resource_asset,
                bookDetailManagement=(
                    compatibility.capabilities.book_detail_management
                ),
            ),
        )
    )
