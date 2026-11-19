"""Typed HTTP interface for application-directory storage management."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager
from app.api.typed_route import TypedContractRoute
from app.bootstrap.storage import storage_management
from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import (
    BasicBadRequestError,
    BasicForbiddenError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.core.exception_diagnostics import capture_exception
from app.db.session import get_db, release_read_transaction
from app.modules.system.application.storage import (
    CLEANABLE,
    StorageCategory,
    StorageUsage,
)
from app.schemas.responses import fail

router = APIRouter(tags=["system"], route_class=TypedContractRoute)


class CategoryUsage(HttpContractModel):
    id: StorageCategory
    sizeBytes: int
    clearable: bool


class UsagePayload(HttpContractModel):
    root: str
    categories: list[CategoryUsage]


def payload(usage: StorageUsage) -> UsagePayload:
    return UsagePayload(
        root=usage.root,
        categories=[
            CategoryUsage(id=key, sizeBytes=size, clearable=key in CLEANABLE)
            for key, size in usage.sizes.items()
        ],
    )


@router.get("/system/storage", response_model=SuccessEnvelope[UsagePayload])
def storage_usage(
    request: Request,
    category: StorageCategory | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SuccessEnvelope[UsagePayload] | Response,
    ErrorResponses(BasicUnauthorizedError, BasicForbiddenError),
]:
    actor, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    authorized = actor is not None and can_manage_system(actor)
    release_read_transaction(db)
    use_cases = storage_management(settings)
    return SuccessEnvelope(
        data=payload(use_cases.usage(authorized=authorized, category=category))
    )


@router.delete(
    "/system/storage/{category}", response_model=SuccessEnvelope[UsagePayload]
)
def clear_storage(
    category: Literal["cache", "logs", "backups", "updates", "uploads"],
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    SuccessEnvelope[UsagePayload] | Response,
    ErrorResponses(BasicBadRequestError, BasicUnauthorizedError, BasicForbiddenError),
]:
    actor, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    authorized = actor is not None and can_manage_system(actor)
    release_read_transaction(db)
    use_cases = storage_management(settings)
    try:
        return SuccessEnvelope(
            data=payload(use_cases.clear(category, authorized=authorized))
        )
    except (OSError, ValueError) as error:
        capture_exception(error)
        return fail("清理失败，请重试", status_code=400, code="STORAGE_CLEANUP_FAILED")
