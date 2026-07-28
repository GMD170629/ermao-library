from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SetupRequest(BaseModel):
    name: str = Field(default="管理员", min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    locale: Literal["zh-CN", "en-US"] = "zh-CN"

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class UpdateNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class UpdateEmailRequest(BaseModel):
    email: EmailStr
    current_password: str = Field(alias="currentPassword", min_length=1, max_length=128)


class UpdatePasswordRequest(BaseModel):
    current_password: str = Field(alias="currentPassword", min_length=1, max_length=128)
    new_password: str = Field(alias="newPassword", min_length=10, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(alias="newPassword", min_length=10, max_length=128)


class AdminCreateUserRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: Literal["admin", "member"] = "member"
    can_manage_system: bool = Field(default=False, alias="canManageSystem")
    can_view_manual_imports: bool = Field(default=False, alias="canViewManualImports")
    monitor_folder_ids: list[str] = Field(default_factory=list, alias="monitorFolderIds", max_length=500)
    locale: Literal["zh-CN", "en-US"] = "zh-CN"

    @field_validator("name", mode="before")
    @classmethod
    def normalize_admin_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("monitor_folder_ids")
    @classmethod
    def normalize_folder_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


class AdminUpdateUserRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=40)
    email: EmailStr | None = None
    role: Literal["admin", "member"] | None = None
    status: Literal["active", "disabled"] | None = None
    can_manage_system: bool | None = Field(default=None, alias="canManageSystem")
    can_view_manual_imports: bool | None = Field(default=None, alias="canViewManualImports")
    monitor_folder_ids: list[str] | None = Field(default=None, alias="monitorFolderIds", max_length=500)
    locale: Literal["zh-CN", "en-US"] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_optional_admin_name(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("monitor_folder_ids")
    @classmethod
    def normalize_optional_folder_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


class AdminSetPasswordRequest(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class AdminDeleteUserRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=191)


class UpdateUserPreferencesRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    preferences: dict[str, object]
