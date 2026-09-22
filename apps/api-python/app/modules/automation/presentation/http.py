from app.contracts.automation_upload import UploadError

"""Cookie-only grant management; MCP credentials never authenticate these routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.automation import (
    build_automation_operation_manager,
    build_automation_settings,
    build_grant_manager,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.automation.domain.access import AutomationAccessError
from app.modules.automation.presentation.schemas import (
    CreatedGrantPayload,
    CreatedGrantResponse,
    CreateGrantRequest,
    GrantListPayload,
    GrantListResponse,
    GrantView,
    ManagedOperationFields,
    OperationListPayload,
    OperationListResponse,
    OperationPayload,
    OperationResponse,
    RevealedTokenPayload,
    RevealedTokenResponse,
    RevokedGrantPayload,
    RevokedGrantResponse,
    ServiceSettingsFields,
    ServiceSettingsResponse,
    UpdatedGrantPayload,
    UpdatedGrantResponse,
    UpdateGrantRequest,
)
from app.modules.library.public import FileMoveError
from app.modules.metadata.public import StandardMetadataError
from app.schemas.responses import fail, ok

router = APIRouter(
    prefix="/automation", tags=["automation"], route_class=TypedContractRoute
)
Database = Annotated[Session, Depends(get_db)]
Configuration = Annotated[Settings, Depends(get_settings)]


def _private(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _error(request: Request, error: AutomationAccessError) -> Response:
    code = str(error)
    status = (
        401
        if code == "UNAUTHORIZED"
        else 404
        if code.endswith("NOT_FOUND")
        else 403
        if code
        in {
            "ORIGIN_REQUIRED",
            "SYSTEM_MANAGER_REQUIRED",
            "ADMIN_REQUIRED",
            "SCOPE_REQUIRED",
        }
        else 400
    )
    message = (
        "Automation request was rejected."
        if request.headers.get("accept-language", "").lower().startswith("en")
        else "自动化请求被拒绝。"
    )
    return _private(fail(message, status_code=status, code=code))


def _check_origin(request: Request) -> None:
    # Rely on the ASGI server's trusted proxy policy, never arbitrary forwarded
    # headers supplied by the caller. The deployment prefix does not affect origin.
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("origin") != expected:
        raise AutomationAccessError("ORIGIN_REQUIRED")


@router.get("/grants", response_model=GrantListResponse)
def list_grants(
    request: Request, db: Database, settings: Configuration
) -> GrantListResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        grants = build_grant_manager(db, settings).list_owned(user.id)
        return _private(
            ok(
                GrantListPayload(
                    grants=[GrantView.from_grant(grant) for grant in grants]
                )
            )
        )
    except AutomationAccessError as error:
        return _error(request, error)


@router.post("/grants", response_model=CreatedGrantResponse)
def create_grant(
    payload: CreateGrantRequest, request: Request, db: Database, settings: Configuration
) -> CreatedGrantResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        _check_origin(request)
        created = build_grant_manager(db, settings).create(
            user_id=user.id,
            name=payload.name,
            permissions=payload.permissions(),
            lifetime_days=payload.lifetime_days,
        )
        return _private(
            ok(
                CreatedGrantPayload(
                    grant=GrantView.from_grant(created.grant), token=created.token
                )
            )
        )
    except AutomationAccessError as error:
        return _error(request, error)


@router.patch("/grants/{grant_id}", response_model=UpdatedGrantResponse)
def update_grant(
    grant_id: str,
    payload: UpdateGrantRequest,
    request: Request,
    db: Database,
    settings: Configuration,
) -> UpdatedGrantResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        _check_origin(request)
        grant = build_grant_manager(db, settings).update(
            user_id=user.id,
            grant_id=grant_id,
            name=payload.name,
            permissions=payload.permissions(),
            lifetime_days=payload.lifetime_days
            if "lifetime_days" in payload.model_fields_set
            else "keep",
        )
        return _private(ok(UpdatedGrantPayload(grant=GrantView.from_grant(grant))))
    except AutomationAccessError as error:
        return _error(request, error)


@router.delete("/grants/{grant_id}", response_model=RevokedGrantResponse)
def revoke_grant(
    grant_id: str, request: Request, db: Database, settings: Configuration
) -> RevokedGrantResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        _check_origin(request)
        build_grant_manager(db, settings).revoke(user_id=user.id, grant_id=grant_id)
        return _private(ok(RevokedGrantPayload()))
    except AutomationAccessError as error:
        return _error(request, error)


@router.get("/settings", response_model=ServiceSettingsResponse)
def get_service_settings(
    request: Request, db: Database, settings: Configuration
) -> ServiceSettingsResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        return _private(
            ok(
                ServiceSettingsFields.from_domain(
                    build_automation_settings(db).read(user.id)
                )
            )
        )
    except AutomationAccessError as error:
        return _error(request, error)


@router.put("/settings", response_model=ServiceSettingsResponse)
def update_service_settings(
    payload: ServiceSettingsFields,
    request: Request,
    db: Database,
    settings: Configuration,
) -> ServiceSettingsResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        _check_origin(request)
        saved = build_automation_settings(db).update(user.id, payload.to_domain())
        return _private(ok(ServiceSettingsFields.from_domain(saved)))
    except AutomationAccessError as error:
        return _error(request, error)


@router.get("/operations", response_model=OperationListResponse)
def list_operations(
    request: Request, db: Database, settings: Configuration
) -> OperationListResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        operations = build_automation_operation_manager(db).recent(user.id)
        return _private(
            ok(
                OperationListPayload(
                    operations=[
                        ManagedOperationFields.from_domain(value)
                        for value in operations
                    ]
                )
            )
        )
    except (
        AutomationAccessError,
        FileMoveError,
        StandardMetadataError,
        UploadError,
    ) as error:
        return _error(request, AutomationAccessError(str(error)))


@router.post("/operations/{operation_id}/cancel", response_model=OperationResponse)
def cancel_operation(
    operation_id: str, request: Request, db: Database, settings: Configuration
) -> OperationResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        _check_origin(request)
        operation = build_automation_operation_manager(db).cancel(user.id, operation_id)
        return _private(
            ok(
                OperationPayload(
                    operation=ManagedOperationFields.from_domain(operation)
                )
            )
        )
    except (
        AutomationAccessError,
        FileMoveError,
        StandardMetadataError,
        UploadError,
    ) as error:
        return _error(request, AutomationAccessError(str(error)))


@router.post("/grants/{grant_id}/reveal", response_model=RevealedTokenResponse)
def reveal_grant(
    grant_id: str, request: Request, db: Database, settings: Configuration
) -> RevealedTokenResponse | Response:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        return _private(
            auth_error or fail("UNAUTHORIZED", status_code=401, code="UNAUTHORIZED")
        )
    try:
        _check_origin(request)
        token = build_grant_manager(db, settings).reveal(
            user_id=user.id, grant_id=grant_id
        )
        return _private(ok(RevealedTokenPayload(token=token)))
    except AutomationAccessError as error:
        return _error(request, error)
