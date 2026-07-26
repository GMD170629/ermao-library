from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field

from appv2.modules.accounts.contracts import AccessScope, AccountView
from appv2.platform.http import CamelModel


class SetupRequest(CamelModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=1024)
    locale: Literal["zh-CN", "en-US"] = "zh-CN"


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class AccountResponse(CamelModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: str
    locale: str
    scopes: list[str]
    disabled: bool
    monitor_folder_ids: list[uuid.UUID]
    created_at: datetime

    @classmethod
    def from_view(cls, account: AccountView) -> AccountResponse:
        return cls(
            id=account.id,
            email=account.email,
            display_name=account.display_name,
            role=account.role,
            locale=account.locale,
            scopes=sorted(scope.value for scope in account.scopes),
            disabled=account.disabled,
            monitor_folder_ids=list(account.monitor_folder_ids),
            created_at=account.created_at,
        )


class SessionResponse(CamelModel):
    account: AccountResponse
    expires_at: datetime


class SetupStatusResponse(CamelModel):
    required: bool


class UpdateAccountRequest(CamelModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=10, max_length=1024)
    current_password: str | None = Field(default=None, max_length=1024)
    locale: Literal["zh-CN", "en-US"] | None = None


class AccountPreferences(CamelModel):
    values: dict[str, object]


class UpdateAccountPreferences(CamelModel):
    values: dict[str, object]


class CreateUserRequest(SetupRequest):
    role: Literal["admin", "member"] = "member"
    scopes: list[AccessScope] | None = None
    monitor_folder_ids: list[uuid.UUID] = Field(default_factory=list)


class AdminUpdateUserRequest(CamelModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["admin", "member"] | None = None
    disabled: bool | None = None
    locale: Literal["zh-CN", "en-US"] | None = None
    scopes: list[AccessScope] | None = None
    monitor_folder_ids: list[uuid.UUID] | None = None


class AdminPasswordRequest(CamelModel):
    password: str = Field(min_length=10, max_length=1024)


class PasswordResetRequest(CamelModel):
    email: EmailStr


class PasswordResetConfirmRequest(CamelModel):
    token: str = Field(min_length=32, max_length=1024)
    new_password: str = Field(min_length=10, max_length=1024)


class PasswordResetAccepted(CamelModel):
    accepted: bool = True
    message: str
    file_path: str


class PasswordResetCompleted(CamelModel):
    password_reset: bool = True
