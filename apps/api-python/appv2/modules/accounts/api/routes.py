import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status

from appv2.modules.accounts.api.schemas import (
    AccountPreferences,
    AccountResponse,
    AdminPasswordRequest,
    AdminUpdateUserRequest,
    CreateUserRequest,
    LoginRequest,
    PasswordResetAccepted,
    PasswordResetCompleted,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionResponse,
    SetupRequest,
    SetupStatusResponse,
    UpdateAccountPreferences,
    UpdateAccountRequest,
)
from appv2.modules.accounts.application import (
    AccountConflict,
    AccountNotFound,
    AccountService,
    AuthenticationFailed,
    InvalidResetToken,
    SetupAlreadyCompleted,
)
from appv2.modules.accounts.contracts import AccessScope, AccountView
from appv2.platform.config import Settings
from appv2.platform.http import AppProblem, Page

SESSION_COOKIE = "shuku_v2_session"


class AccountDependency:
    def __init__(self, service: AccountService) -> None:
        self._service = service

    def __call__(
        self,
        token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> AccountView:
        if not token:
            raise AppProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                message_key="authentication_required",
            )
        try:
            return self._service.authenticate(token)
        except AuthenticationFailed as error:
            raise AppProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                message_key="authentication_required",
            ) from error


def require_scope(scope: AccessScope) -> Callable[[AccountView], AccountView]:
    def dependency(account: AccountView) -> AccountView:
        if scope not in account.scopes:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"scope": scope.value},
            )
        return account

    return dependency


def create_router(
    service: AccountService,
    settings: Settings,
    current_account: AccountDependency,
) -> APIRouter:
    router = APIRouter()

    def set_cookie(response: Response, token: str, max_age: int) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=max_age,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path=settings.cookie_path,
        )

    @router.get("/auth/setup/status", response_model=SetupStatusResponse)
    def setup_status() -> SetupStatusResponse:
        return SetupStatusResponse(required=service.setup_required())

    @router.post(
        "/auth/setup",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def setup(payload: SetupRequest, response: Response) -> SessionResponse:
        try:
            grant = service.setup(
                email=str(payload.email),
                display_name=payload.display_name,
                password=payload.password,
                locale=payload.locale,
            )
        except SetupAlreadyCompleted as error:
            raise AppProblem(
                status=409,
                code="SETUP_ALREADY_COMPLETED",
                title="Setup already completed",
                message_key="conflict",
            ) from error
        set_cookie(response, grant.token, settings.session_ttl_seconds)
        return SessionResponse(
            account=AccountResponse.from_view(grant.account),
            expires_at=grant.expires_at,
        )

    @router.post("/auth/login", response_model=SessionResponse)
    def login(payload: LoginRequest, response: Response) -> SessionResponse:
        try:
            grant = service.login(email=str(payload.email), password=payload.password)
        except (AuthenticationFailed, ValueError) as error:
            raise AppProblem(
                status=401,
                code="INVALID_CREDENTIALS",
                title="Invalid credentials",
                message_key="authentication_required",
            ) from error
        set_cookie(response, grant.token, settings.session_ttl_seconds)
        return SessionResponse(
            account=AccountResponse.from_view(grant.account),
            expires_at=grant.expires_at,
        )

    @router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        response: Response,
        token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        if token:
            service.logout(token)
        response.delete_cookie(SESSION_COOKIE, path=settings.cookie_path)

    @router.post(
        "/auth/password-reset/request",
        response_model=PasswordResetAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def request_password_reset(
        payload: PasswordResetRequest,
        request: Request,
    ) -> PasswordResetAccepted:
        path = service.request_password_reset(
            email=str(payload.email),
            app_base_url=str(request.base_url).rstrip("/"),
        )
        english = request.headers.get("accept-language", "").lower().startswith("en")
        return PasswordResetAccepted(
            message=(
                "If the account exists, a local password reset file has been created."
                if english
                else "如果账户存在，本地密码重置文件已创建。"
            ),
            file_path=str(path),
        )

    @router.post(
        "/auth/password-reset/confirm",
        response_model=PasswordResetCompleted,
    )
    def confirm_password_reset(
        payload: PasswordResetConfirmRequest,
    ) -> PasswordResetCompleted:
        try:
            service.confirm_password_reset(
                token=payload.token,
                new_password=payload.new_password,
            )
        except InvalidResetToken as error:
            raise AppProblem(
                status=400,
                code="INVALID_PASSWORD_RESET_TOKEN",
                title="Invalid password reset token",
                message_key="invalid_request",
            ) from error
        return PasswordResetCompleted()

    @router.get("/account", response_model=AccountResponse)
    def account(
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountResponse:
        return AccountResponse.from_view(actor)

    @router.patch("/account", response_model=AccountResponse)
    def update_account(
        payload: UpdateAccountRequest,
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountResponse:
        try:
            updated = service.update_account(
                actor.id,
                email=str(payload.email) if payload.email is not None else None,
                display_name=payload.display_name,
                password=payload.password,
                current_password=payload.current_password,
                locale=payload.locale,
            )
        except AccountConflict as error:
            raise AppProblem(
                status=409,
                code="ACCOUNT_CONFLICT",
                title="Account conflict",
                message_key="conflict",
            ) from error
        except AuthenticationFailed as error:
            raise AppProblem(
                status=403,
                code="CURRENT_PASSWORD_INVALID",
                title="Current password is invalid",
                message_key="permission_denied",
            ) from error
        return AccountResponse.from_view(updated)

    @router.get("/account/preferences", response_model=AccountPreferences)
    def preferences(
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountPreferences:
        return AccountPreferences(values=service.preferences(actor.id))

    @router.patch("/account/preferences", response_model=AccountPreferences)
    def save_preferences(
        payload: UpdateAccountPreferences,
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountPreferences:
        return AccountPreferences(values=service.save_preferences(actor.id, payload.values))

    def admin_actor(
        actor: Annotated[AccountView, Depends(current_account)],
    ) -> AccountView:
        return require_scope(AccessScope.USERS_WRITE)(actor)

    @router.get("/admin/users", response_model=Page[AccountResponse])
    def users(
        actor: Annotated[AccountView, Depends(admin_actor)],
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
    ) -> Page[AccountResponse]:
        del actor
        items, total = service.list_users(page=page, page_size=min(page_size, 200))
        return Page(
            items=[AccountResponse.from_view(item) for item in items],
            page=page,
            page_size=min(page_size, 200),
            total=total,
        )

    @router.post(
        "/admin/users",
        response_model=AccountResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_user(
        payload: CreateUserRequest,
        actor: Annotated[AccountView, Depends(admin_actor)],
    ) -> AccountResponse:
        del actor
        try:
            created = service.create_user(
                email=str(payload.email),
                display_name=payload.display_name,
                password=payload.password,
                role=payload.role,
                locale=payload.locale,
                scopes=frozenset(payload.scopes) if payload.scopes is not None else None,
                monitor_folder_ids=tuple(payload.monitor_folder_ids),
            )
        except AccountConflict as error:
            raise AppProblem(
                status=409,
                code="ACCOUNT_CONFLICT",
                title="Account conflict",
                message_key="conflict",
            ) from error
        return AccountResponse.from_view(created)

    @router.patch("/admin/users/{user_id}", response_model=AccountResponse)
    def update_user(
        user_id: uuid.UUID,
        payload: AdminUpdateUserRequest,
        actor: Annotated[AccountView, Depends(admin_actor)],
    ) -> AccountResponse:
        if actor.id == user_id and (payload.disabled or payload.role == "member"):
            raise AppProblem(
                status=409,
                code="CANNOT_REMOVE_OWN_ADMIN_ACCESS",
                title="Cannot remove own administrator access",
                message_key="conflict",
            )
        try:
            updated = service.update_managed_user(
                user_id,
                email=str(payload.email) if payload.email is not None else None,
                display_name=payload.display_name,
                role=payload.role,
                disabled=payload.disabled,
                locale=payload.locale,
                scopes=frozenset(payload.scopes) if payload.scopes is not None else None,
                monitor_folder_ids=(
                    tuple(payload.monitor_folder_ids)
                    if payload.monitor_folder_ids is not None
                    else None
                ),
            )
        except AccountConflict as error:
            raise AppProblem(
                status=409,
                code="ACCOUNT_CONFLICT",
                title="Account conflict",
                message_key="conflict",
            ) from error
        except AccountNotFound as error:
            raise AppProblem(
                status=404,
                code="ACCOUNT_NOT_FOUND",
                title="Account not found",
                message_key="not_found",
            ) from error
        return AccountResponse.from_view(updated)

    @router.put("/admin/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
    def set_user_password(
        user_id: uuid.UUID,
        payload: AdminPasswordRequest,
        actor: Annotated[AccountView, Depends(admin_actor)],
    ) -> None:
        del actor
        try:
            service.set_managed_password(user_id, payload.password)
        except AccountNotFound as error:
            raise AppProblem(
                status=404,
                code="ACCOUNT_NOT_FOUND",
                title="Account not found",
                message_key="not_found",
            ) from error

    @router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_user(
        user_id: uuid.UUID,
        actor: Annotated[AccountView, Depends(admin_actor)],
    ) -> None:
        if actor.id == user_id:
            raise AppProblem(
                status=409,
                code="CANNOT_DELETE_SELF",
                title="Cannot delete current account",
                message_key="conflict",
            )
        try:
            service.delete_user(user_id)
        except AccountNotFound as error:
            raise AppProblem(
                status=404,
                code="ACCOUNT_NOT_FOUND",
                title="Account not found",
                message_key="not_found",
            ) from error

    return router
