"""Typed response and error contracts for authentication HTTP endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field
from fastapi.responses import FileResponse

from app.contracts.http import HttpContractModel, MessageError, SuccessEnvelope
from app.contracts.http_errors import (
    BasicBadRequestError,
    BasicConflictError,
    BasicForbiddenError,
    BasicInternalError,
    BasicNotFoundError,
    BasicUnauthorizedError,
    HttpContractError,
    PayloadTooLargeError,
    SessionUnauthorizedError,
)


class AuthUser(HttpContractModel):
    id: str
    email: EmailStr
    name: str
    role: Literal["admin", "member"]
    status: Literal["active", "disabled"]
    can_manage_system: bool = Field(alias="canManageSystem")
    can_view_manual_imports: bool = Field(alias="canViewManualImports")
    authz_version: int = Field(alias="authzVersion")
    avatar_url: str | None = Field(alias="avatarUrl")
    locale: Literal["zh-CN", "en-US"] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class AuthorizationView(HttpContractModel):
    is_admin: bool = Field(alias="isAdmin")
    can_manage_system: bool = Field(alias="canManageSystem")
    all_library_scopes: bool = Field(alias="allLibraryScopes")
    monitor_folder_ids: list[str] = Field(alias="monitorFolderIds")
    can_view_manual_imports: bool = Field(alias="canViewManualImports")
    authz_version: int = Field(alias="authzVersion")


class UserPreferences(HttpContractModel):
    locale: Literal["zh-CN", "en-US"]
    library_view: Literal["grid", "list"] | None = Field(
        default=None,
        alias="library.view",
        exclude_if=lambda value: value is None,
    )
    audio_playback_rate: float | None = Field(
        default=None,
        alias="audio.playbackRate",
        ge=0.5,
        le=3,
        exclude_if=lambda value: value is None,
    )
    kindle_email: EmailStr | Literal[""] | None = Field(
        default=None,
        alias="kindle.email",
        exclude_if=lambda value: value is None,
    )


class SessionPayload(HttpContractModel):
    user: AuthUser
    authorization: AuthorizationView
    preferences: UserPreferences


class SetupPayload(SessionPayload):
    initialized: Literal[True] = True


class CapabilitiesPayload(HttpContractModel):
    local_password_reset: Literal[True] = Field(
        default=True,
        alias="localPasswordReset",
    )
    password_reset_file_path: str = Field(alias="passwordResetFilePath")


class SetupStatusPayload(HttpContractModel):
    initialized: bool


class UserPayload(HttpContractModel):
    user: AuthUser


class PasswordChangedPayload(HttpContractModel):
    password_changed: Literal[True] = Field(
        default=True,
        alias="passwordChanged",
    )
    requires_login: Literal[True] = Field(default=True, alias="requiresLogin")


class PasswordResetRequestPayload(HttpContractModel):
    accepted: Literal[True] = True
    message: str
    file_path: str = Field(alias="filePath")


class PasswordResetPayload(HttpContractModel):
    password_reset: Literal[True] = Field(default=True, alias="passwordReset")


class LoggedOutPayload(HttpContractModel):
    logged_out: Literal[True] = Field(default=True, alias="loggedOut")


class AvatarFileResponse(FileResponse):
    media_type = "image/webp"


class SetupRequiredDetails(HttpContractModel):
    code: Literal["SETUP_REQUIRED"] = "SETUP_REQUIRED"


class SetupRequiredBody(MessageError):
    details: SetupRequiredDetails


class AccountDisabledBody(MessageError):
    code: Literal["ACCOUNT_DISABLED"] = "ACCOUNT_DISABLED"


class SetupRequiredError(HttpContractError[SetupRequiredBody]):
    status_code = 409
    body_model = SetupRequiredBody


class AccountDisabledError(HttpContractError[AccountDisabledBody]):
    status_code = 403
    body_model = AccountDisabledBody


CapabilitiesResponse = SuccessEnvelope[CapabilitiesPayload]
SetupStatusResponse = SuccessEnvelope[SetupStatusPayload]
SessionResponse = SuccessEnvelope[SessionPayload]
SetupResponse = SuccessEnvelope[SetupPayload]
UserResponse = SuccessEnvelope[UserPayload]
PasswordChangedResponse = SuccessEnvelope[PasswordChangedPayload]
PasswordResetRequestResponse = SuccessEnvelope[PasswordResetRequestPayload]
PasswordResetResponse = SuccessEnvelope[PasswordResetPayload]
LoggedOutResponse = SuccessEnvelope[LoggedOutPayload]
