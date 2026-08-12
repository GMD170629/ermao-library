from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.modules.mobile.public import SERVER_IDENTITY_SETTING_KEY


def _store_server_identity(db: Session, server_identity: str) -> None:
    db.add(
        SystemSetting(
            key=SERVER_IDENTITY_SETTING_KEY,
            value=server_identity,
        )
    )
    db.commit()


def test_mobile_compatibility_is_public_and_uses_the_typed_contract(
    client,
    db_session: Session,
    test_settings,
) -> None:
    _store_server_identity(db_session, "server_contract_identity")

    response = client.get("/api/mobile/compatibility")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "ok": True,
        "data": {
            "service": "ermao-books",
            "serverIdentity": "server_contract_identity",
            "serverVersion": test_settings.app_version,
            "protocol": {
                "version": 1,
                "minimumSupportedClientVersion": 1,
            },
            "readerSchemaVersion": 4,
            "capabilities": {
                "setup": True,
                "cookieSession": True,
                "readerV4": True,
                "mediaRange": True,
                "managedOfflineDownloads": False,
            },
        },
    }


def test_mobile_compatibility_openapi_exposes_the_success_envelope(client) -> None:
    operation = client.app.openapi()["paths"]["/api/mobile/compatibility"]["get"]
    success_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    assert success_schema["$ref"].endswith(
        "/SuccessEnvelope_MobileCompatibilityPayload_"
    )
