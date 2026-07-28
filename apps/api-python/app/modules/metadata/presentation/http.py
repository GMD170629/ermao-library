"""Metadata provider HTTP surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.bootstrap.system import record_system_event
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.responses import fail, ok
from app.services.metadata_provider_registry import (
    get_metadata_provider,
    list_metadata_provider_pipelines,
    list_metadata_providers,
    test_metadata_provider,
    update_metadata_provider,
    update_metadata_provider_pipeline,
)

router = APIRouter(tags=["metadata"])


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


@router.get("/metadata/providers")
def list_registered_metadata_providers(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok(
        {
            "providers": list_metadata_providers(db),
            "pipelines": list_metadata_provider_pipelines(db),
        }
    )


@router.put("/metadata/provider-pipelines/{work_type}")
async def update_registered_metadata_provider_pipeline(
    work_type: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    try:
        pipelines = update_metadata_provider_pipeline(db, work_type, items)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    record_system_event(
        db,
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="metadata_provider_pipeline.updated",
        target_type="metadataProviderPipeline",
        target_id=work_type,
        message=f"更新{work_type}数据源组合",
        metadata={"providerIds": [item.get("providerId") for item in items or []]},
        commit=True,
        prune=True,
    )
    return ok({"pipelines": pipelines, "providers": list_metadata_providers(db)})


@router.get("/metadata/providers/{provider_id}")
def get_registered_metadata_provider(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    provider = get_metadata_provider(db, provider_id)
    if not provider:
        return fail("元数据插件不存在", status_code=404)
    return ok({"provider": provider})


@router.patch("/metadata/providers/{provider_id}")
@router.put("/metadata/providers/{provider_id}")
async def update_registered_metadata_provider(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    if not isinstance(payload, dict):
        return fail("插件配置格式不正确", status_code=400)
    try:
        provider = update_metadata_provider(db, provider_id, payload)
    except ValueError as exc:
        return fail(str(exc), status_code=404 if "不存在" in str(exc) else 400)
    record_system_event(
        db,
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="metadata_provider.updated",
        target_type="metadataProvider",
        target_id=provider_id,
        message=f"更新元数据插件：{provider.get('name') or provider_id}",
        metadata={"enabled": provider.get("enabled"), "priority": provider.get("priority")},
        commit=True,
        prune=True,
    )
    return ok({"provider": provider})


@router.post("/metadata/providers/{provider_id}/test")
def test_registered_metadata_provider(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result, provider = test_metadata_provider(db, provider_id)
    except ValueError as exc:
        return fail(str(exc), status_code=404 if "不存在" in str(exc) else 400)
    return ok({"result": result, "provider": provider})
