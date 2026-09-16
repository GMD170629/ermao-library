"""Administrator-only update inspection, preparation and installation requests."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager, require_user
from app.api.typed_route import TypedContractRoute
from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import (
    BasicBadRequestError,
    BasicConflictError,
    BasicForbiddenError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.authorization import can_manage_system
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.responses import fail, ok

from ..application.models import PreparationState, UpdateCheck, UpdateError
from ..application.preparation import UpdatePreparation

router = APIRouter(tags=["updates"], route_class=TypedContractRoute)


class RuntimeInfo(HttpContractModel):
    current_version: str
    supported: bool


class PrepareRequest(HttpContractModel):
    version: str = Field(
        pattern=r"^(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})$"
    )


class InstallRequest(PrepareRequest):
    plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def use_cases(request: Request) -> UpdatePreparation:
    return request.app.state.update_runtime.use_cases


def update_error(error: UpdateError) -> Response:
    return fail(
        "应用更新请求失败，请查看错误码。 / Application update request failed; see the error code.",
        status_code=409 if error.code == "UPDATE_BUSY" else 400,
        code=error.code,
    )


@router.get("/updates/check", response_model=SuccessEnvelope[UpdateCheck])
def check_updates(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    updates: UpdatePreparation = Depends(use_cases),
) -> Annotated[
    SuccessEnvelope[UpdateCheck] | Response,
    ErrorResponses(BasicBadRequestError, BasicUnauthorizedError, BasicForbiddenError),
]:
    actor, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    try:
        return ok(updates.check(actor is not None and can_manage_system(actor)))
    except UpdateError as rejected:
        return update_error(rejected)


@router.post(
    "/updates/prepare",
    status_code=202,
    response_model=SuccessEnvelope[PreparationState],
)
def prepare_update(
    payload: PrepareRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    updates: UpdatePreparation = Depends(use_cases),
) -> Annotated[
    SuccessEnvelope[PreparationState] | Response,
    ErrorResponses(
        BasicBadRequestError,
        BasicUnauthorizedError,
        BasicForbiddenError,
        BasicConflictError,
    ),
]:
    actor, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    # Existing sessions retain SameSite=Lax; this JSON-only mutation also rejects
    # cross-site browser fetches. No GET endpoint can start a preparation.
    if request.headers.get("sec-fetch-site") == "cross-site":
        return fail(
            "禁止跨站请求 / Cross-site request forbidden",
            status_code=403,
            code="CROSS_SITE_REQUEST",
        )
    try:
        return ok(
            updates.prepare(
                actor is not None and can_manage_system(actor), payload.version
            ),
            status_code=202,
        )
    except UpdateError as rejected:
        return update_error(rejected)


@router.post(
    "/updates/install",
    status_code=202,
    response_model=SuccessEnvelope[PreparationState],
)
def install_update(
    payload: InstallRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    updates: UpdatePreparation = Depends(use_cases),
) -> Annotated[
    SuccessEnvelope[PreparationState] | Response,
    ErrorResponses(
        BasicBadRequestError,
        BasicUnauthorizedError,
        BasicForbiddenError,
        BasicConflictError,
    ),
]:
    actor, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    # Existing sessions retain SameSite=Lax; this JSON-only mutation also rejects
    # cross-site browser fetches. No GET endpoint can start a preparation.
    if request.headers.get("sec-fetch-site") == "cross-site":
        return fail(
            "禁止跨站请求 / Cross-site request forbidden",
            status_code=403,
            code="CROSS_SITE_REQUEST",
        )
    try:
        return ok(
            updates.install(
                actor is not None and can_manage_system(actor),
                payload.version,
                payload.sha256,
                payload.plan_sha256,
            ),
            status_code=202,
        )
    except UpdateError as rejected:
        return update_error(rejected)


@router.get("/updates/status", response_model=SuccessEnvelope[PreparationState])
def update_status(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    updates: UpdatePreparation = Depends(use_cases),
) -> Annotated[
    SuccessEnvelope[PreparationState] | Response,
    ErrorResponses(
        BasicBadRequestError,
        BasicUnauthorizedError,
        BasicForbiddenError,
        BasicConflictError,
    ),
]:
    actor, error = require_system_manager(db, request, settings)
    if error is not None:
        return error
    try:
        return ok(updates.status(actor is not None and can_manage_system(actor)))
    except UpdateError as rejected:
        return update_error(rejected)


@router.get("/updates/runtime", response_model=SuccessEnvelope[RuntimeInfo])
def runtime_info(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    updates: UpdatePreparation = Depends(use_cases),
) -> Annotated[
    SuccessEnvelope[RuntimeInfo] | Response,
    ErrorResponses(BasicUnauthorizedError),
]:
    _, error = require_user(db, request, settings)
    if error is not None:
        return error
    return ok(
        RuntimeInfo(
            current_version=updates.current, supported=updates.environment is not None
        )
    )
