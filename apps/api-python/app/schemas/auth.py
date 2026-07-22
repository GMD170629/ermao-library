from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


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
