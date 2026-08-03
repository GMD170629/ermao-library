"""Application ports for password authentication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredPasswordCredential:
    user_id: str
    email: str
    password_hash: str
    status: str


@dataclass(frozen=True)
class PasswordVerificationRequest:
    normalized_email: str
    password: str
    stored_password_hash: str | None
    client_address: str
    cache_allowed: bool


@dataclass(frozen=True)
class PasswordVerificationResult:
    matched: bool
    retry_after_seconds: int | None = None


class UserCredentialReader(Protocol):
    def find_by_normalized_email(
        self, normalized_email: str
    ) -> StoredPasswordCredential | None: ...


class PasswordVerificationGateway(Protocol):
    def verify(
        self, request: PasswordVerificationRequest
    ) -> PasswordVerificationResult: ...
