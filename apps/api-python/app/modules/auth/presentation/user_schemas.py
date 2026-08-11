"""Typed response and error contracts for user administration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError
from app.modules.auth.presentation.schemas import (
    AuthorizationView,
    AuthUser,
    UserPreferences,
)
from pydantic import Field


class AdminUser(AuthUser):
    locale: Literal["zh-CN", "en-US"]
    monitor_folder_ids: list[str] = Field(alias="monitorFolderIds")
    authorization: AuthorizationView
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UsersPayload(HttpContractModel):
    users: list[AdminUser]


class AdminUserPayload(HttpContractModel):
    user: AdminUser
    created_by: str | None = Field(default=None, alias="createdBy")


class AdminPasswordChangedPayload(HttpContractModel):
    password_changed: Literal[True] = Field(
        default=True,
        alias="passwordChanged",
    )
    sessions_revoked: Literal[True] = Field(
        default=True,
        alias="sessionsRevoked",
    )


class UserDeletedPayload(HttpContractModel):
    deleted: Literal[True] = True
    user_id: str = Field(alias="userId")


class PreferencesPayload(HttpContractModel):
    preferences: UserPreferences


class CodedMessageBody(HttpContractModel):
    message: str
    code: str


class UnsupportedPreferenceDetails(HttpContractModel):
    keys: list[str]


class UnsupportedPreferenceBody(HttpContractModel):
    message: str
    code: Literal["UNSUPPORTED_USER_PREFERENCE"] = "UNSUPPORTED_USER_PREFERENCE"
    details: UnsupportedPreferenceDetails


class UserUnauthorizedError(HttpContractError[CodedMessageBody]):
    status_code = 401
    body_model = CodedMessageBody


class UserForbiddenError(HttpContractError[CodedMessageBody]):
    status_code = 403
    body_model = CodedMessageBody


class UserBadRequestError(HttpContractError[CodedMessageBody]):
    status_code = 400
    body_model = CodedMessageBody


class UserNotFoundError(HttpContractError[CodedMessageBody]):
    status_code = 404
    body_model = CodedMessageBody


class UserConflictError(HttpContractError[CodedMessageBody]):
    status_code = 409
    body_model = CodedMessageBody


class UnsupportedPreferenceError(HttpContractError[UnsupportedPreferenceBody]):
    status_code = 400
    body_model = UnsupportedPreferenceBody


UsersResponse = SuccessEnvelope[UsersPayload]
AdminUserResponse = SuccessEnvelope[AdminUserPayload]
AdminPasswordChangedResponse = SuccessEnvelope[AdminPasswordChangedPayload]
UserDeletedResponse = SuccessEnvelope[UserDeletedPayload]
PreferencesResponse = SuccessEnvelope[PreferencesPayload]
