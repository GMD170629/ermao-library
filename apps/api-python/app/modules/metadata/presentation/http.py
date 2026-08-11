"""Metadata provider HTTP surface."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.system import prepare_system_event
from app.contracts.http import MessageError
from app.contracts.http_errors import (
    BasicBadRequestError,
    BasicNotFoundError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.authorization import can_access_work
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.metadata.presentation.schemas import (
    MetadataOpfQueueStatusPayload,
    MetadataOpfQueueStatusResponse,
    MetadataProvider,
    MetadataWritebackPayload,
    MetadataWritebackResponse,
    ProviderPayload,
    ProviderResponse,
    ProvidersPayload,
    ProvidersResponse,
    ProviderTestPayload,
    ProviderTestResponse,
    UpdateMetadataProviderPipelineRequest,
    UpdateMetadataProviderRequest,
)
from app.services.metadata_file_writeback import (
    metadata_opf_queue_status,
    metadata_writeback_view,
    metadata_writeback_work_id,
)
from app.services.metadata_provider_registry import (
    get_metadata_provider,
    list_metadata_provider_pipelines,
    list_metadata_providers,
    persist_metadata_provider_pipeline_update,
    persist_metadata_provider_update,
    prepare_metadata_provider_pipeline_update,
    prepare_metadata_provider_update,
    test_metadata_provider,
)

router = APIRouter(tags=["metadata"], route_class=TypedContractRoute)


def _auth(db: Session, request: Request, settings: Settings):
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    return user


@router.get("/metadata/opf-sync/status")
def get_metadata_opf_queue_status(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[MetadataOpfQueueStatusResponse, ErrorResponses(BasicUnauthorizedError)]:
    _auth(db, request, settings)
    return MetadataOpfQueueStatusResponse(
        data=MetadataOpfQueueStatusPayload.model_validate(
            {"queue": metadata_opf_queue_status(db, settings)}
        )
    )


@router.get("/metadata/writebacks/{operation_id}")
def get_metadata_writeback(
    operation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    MetadataWritebackResponse,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    user = _auth(db, request, settings)
    work_id = metadata_writeback_work_id(db, operation_id)
    if work_id is None or not can_access_work(db, user, work_id):
        raise BasicNotFoundError(MessageError(message="元数据旁车 OPF 保存任务不存在"))
    operation = metadata_writeback_view(db, operation_id)
    if operation is None:
        raise BasicNotFoundError(MessageError(message="元数据旁车 OPF 保存任务不存在"))
    return MetadataWritebackResponse(
        data=MetadataWritebackPayload.model_validate({"operation": operation})
    )


@router.get("/metadata/providers")
def list_registered_metadata_providers(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ProvidersResponse,
    ErrorResponses(BasicUnauthorizedError),
]:
    _auth(db, request, settings)
    return ProvidersResponse(
        data=ProvidersPayload.model_validate(
            {
                "providers": list_metadata_providers(db),
                "pipelines": list_metadata_provider_pipelines(db),
            }
        )
    )


@router.put("/metadata/provider-pipelines/{media_kind}")
async def update_registered_metadata_provider_pipeline(
    media_kind: str,
    payload: UpdateMetadataProviderPipelineRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ProvidersResponse,
    ErrorResponses(BasicUnauthorizedError, BasicBadRequestError),
]:
    user = _auth(db, request, settings)
    items = [item.model_dump(by_alias=True) for item in payload.items]
    try:
        prepared = prepare_metadata_provider_pipeline_update(db, media_kind, items)
    except ValueError as exc:
        raise BasicBadRequestError(MessageError(message=str(exc))) from exc
    event = prepare_system_event(
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="metadata_provider_pipeline.updated",
        target_type="metadataProviderPipeline",
        target_id=prepared.media_kind,
        message=f"更新{prepared.media_kind}数据源组合",
        metadata={"providerIds": list(prepared.provider_ids)},
    )
    pipelines = persist_metadata_provider_pipeline_update(
        db,
        prepared,
        event=event,
    )
    return ProvidersResponse(
        data=ProvidersPayload.model_validate(
            {
                "pipelines": pipelines,
                "providers": list_metadata_providers(db),
            }
        )
    )


@router.get("/metadata/providers/{provider_id}")
def get_registered_metadata_provider(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ProviderResponse,
    ErrorResponses(BasicUnauthorizedError, BasicNotFoundError),
]:
    _auth(db, request, settings)
    provider = get_metadata_provider(db, provider_id)
    if not provider:
        raise BasicNotFoundError(MessageError(message="元数据插件不存在"))
    return ProviderResponse(
        data=ProviderPayload(provider=MetadataProvider.model_validate(provider))
    )


@router.patch("/metadata/providers/{provider_id}")
@router.put("/metadata/providers/{provider_id}")
async def update_registered_metadata_provider(
    provider_id: str,
    payload: UpdateMetadataProviderRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ProviderResponse,
    ErrorResponses(
        BasicUnauthorizedError,
        BasicBadRequestError,
        BasicNotFoundError,
    ),
]:
    user = _auth(db, request, settings)
    values = payload.model_dump(by_alias=True, exclude_unset=True)
    try:
        prepared = prepare_metadata_provider_update(db, provider_id, values)
    except ValueError as exc:
        error_type = (
            BasicNotFoundError if "不存在" in str(exc) else BasicBadRequestError
        )
        raise error_type(MessageError(message=str(exc))) from exc
    event = prepare_system_event(
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="metadata_provider.updated",
        target_type="metadataProvider",
        target_id=provider_id,
        message=f"更新元数据插件：{prepared.provider_name}",
        metadata={
            "enabled": prepared.enabled,
            "priority": prepared.priority,
        },
    )
    provider = persist_metadata_provider_update(db, prepared, event=event)
    return ProviderResponse(
        data=ProviderPayload(provider=MetadataProvider.model_validate(provider))
    )


@router.post("/metadata/providers/{provider_id}/test")
def test_registered_metadata_provider(
    provider_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ProviderTestResponse,
    ErrorResponses(
        BasicUnauthorizedError,
        BasicBadRequestError,
        BasicNotFoundError,
    ),
]:
    _auth(db, request, settings)
    try:
        result, provider = test_metadata_provider(db, provider_id)
    except ValueError as exc:
        error_type = (
            BasicNotFoundError if "不存在" in str(exc) else BasicBadRequestError
        )
        raise error_type(MessageError(message=str(exc))) from exc
    return ProviderTestResponse(
        data=ProviderTestPayload.model_validate(
            {"result": result, "provider": provider}
        )
    )
