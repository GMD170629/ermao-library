"""HTTP adapter for OPDS administration settings."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.system import (
    get_setting,
    persist_opds_settings_update,
    prepare_system_event,
)
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.opds.application.settings import (
    OPDS_ENABLED_SETTING_KEY,
    OPDS_PUBLIC_BASE_URL_SETTING_KEY,
    OpdsPublicBaseUrlInvalid,
    OpdsPublicBaseUrlRequired,
    resolve_opds_settings,
    validate_opds_activation,
)
from app.modules.opds.presentation.settings_schemas import (
    OpdsSystemSettingsPayload,
    OpdsSystemSettingsResponse,
    UpdateOpdsSystemSettingsRequest,
)
from app.schemas.responses import fail, ok

router = APIRouter(tags=["system"], route_class=TypedContractRoute)


def _settings_payload(db: Session) -> OpdsSystemSettingsPayload:
    snapshot = resolve_opds_settings(
        get_setting(db, OPDS_ENABLED_SETTING_KEY, None),
        stored_public_base_url=get_setting(db, OPDS_PUBLIC_BASE_URL_SETTING_KEY, None),
    )
    return OpdsSystemSettingsPayload(
        enabled=snapshot.enabled,
        configured=snapshot.configured,
        publicBaseUrl=snapshot.public_base_url,
        catalogUrl=snapshot.catalog_url,
    )


@router.get("/system-settings/opds", response_model=OpdsSystemSettingsResponse)
def get_opds_system_settings(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpdsSystemSettingsResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None:
        return auth_error
    if user is None:
        return fail("未登录", status_code=401, code="UNAUTHORIZED")
    if not can_manage_system(user):
        return fail(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    return ok(_settings_payload(db))


@router.put("/system-settings/opds", response_model=OpdsSystemSettingsResponse)
def update_opds_system_settings(
    payload: UpdateOpdsSystemSettingsRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpdsSystemSettingsResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None:
        return auth_error
    if user is None:
        return fail("未登录", status_code=401, code="UNAUTHORIZED")
    if not can_manage_system(user):
        return fail(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    try:
        normalized_public_base_url = validate_opds_activation(
            payload.enabled, payload.public_base_url
        )
    except OpdsPublicBaseUrlRequired:
        return fail(
            "启用 OPDS 前必须填写公开 URL",
            status_code=409,
            code="OPDS_PUBLIC_BASE_URL_REQUIRED",
        )
    except OpdsPublicBaseUrlInvalid:
        return fail(
            "OPDS 公开 URL 必须是有效的 HTTP 或 HTTPS 地址，"
            "且不能包含凭据、查询参数或片段",
            status_code=400,
            code="OPDS_PUBLIC_BASE_URL_INVALID",
        )

    prepared_event = prepare_system_event(
        level="info",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="opds.settings.updated",
        target_type="settings",
        message="已开启 OPDS" if payload.enabled else "已关闭 OPDS",
        metadata={"enabled": payload.enabled},
    )
    persist_opds_settings_update(
        db,
        setting_values={
            OPDS_ENABLED_SETTING_KEY: payload.enabled,
            OPDS_PUBLIC_BASE_URL_SETTING_KEY: normalized_public_base_url,
        },
        event=prepared_event,
    )
    return ok(_settings_payload(db))
