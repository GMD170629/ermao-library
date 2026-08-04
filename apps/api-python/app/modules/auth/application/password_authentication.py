"""Authenticate an account password without creating a browser session."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.auth.application.ports import (
    PasswordVerificationGateway,
    PasswordVerificationRequest,
    UserCredentialReader,
)


@dataclass(frozen=True)
class PasswordCredentials:
    email: str
    password: str
    client_address: str


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: str
    email: str


@dataclass(frozen=True)
class PasswordAuthenticated:
    principal: AuthenticatedPrincipal


@dataclass(frozen=True)
class PasswordAuthenticationInvalid:
    pass


@dataclass(frozen=True)
class PasswordAuthenticationThrottled:
    retry_after_seconds: int


PasswordAuthenticationResult = (
    PasswordAuthenticated
    | PasswordAuthenticationInvalid
    | PasswordAuthenticationThrottled
)


def normalize_login_email(email: str) -> str:
    """Preserve the normalization contract used by the existing login route."""

    return email.strip().lower()


class AuthenticatePassword:
    def __init__(
        self,
        credential_reader: UserCredentialReader,
        password_verification: PasswordVerificationGateway,
    ) -> None:
        self._credential_reader = credential_reader
        self._password_verification = password_verification

    def execute(self, credentials: PasswordCredentials) -> PasswordAuthenticationResult:
        normalized_email = normalize_login_email(credentials.email)
        stored = self._credential_reader.find_by_normalized_email(normalized_email)
        is_active = stored is not None and stored.status == "active"
        verification = self._password_verification.verify(
            PasswordVerificationRequest(
                normalized_email=normalized_email,
                password=credentials.password,
                stored_password_hash=(
                    stored.password_hash if stored is not None and is_active else None
                ),
                client_address=credentials.client_address,
                cache_allowed=is_active,
            )
        )
        if verification.retry_after_seconds is not None:
            return PasswordAuthenticationThrottled(
                retry_after_seconds=verification.retry_after_seconds
            )
        if stored is None or not is_active or not verification.matched:
            return PasswordAuthenticationInvalid()
        return PasswordAuthenticated(
            principal=AuthenticatedPrincipal(user_id=stored.user_id, email=stored.email)
        )
