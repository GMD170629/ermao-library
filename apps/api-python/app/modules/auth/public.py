"""Stable application contracts for authentication and user administration."""

from app.modules.auth.application.commands import AuthUnitOfWork
from app.modules.auth.application.password_authentication import (
    AuthenticatedPrincipal,
    AuthenticatePassword,
    PasswordAuthenticated,
    PasswordAuthenticationInvalid,
    PasswordAuthenticationResult,
    PasswordAuthenticationThrottled,
    PasswordCredentials,
)

__all__ = [
    "AuthUnitOfWork",
    "AuthenticatePassword",
    "AuthenticatedPrincipal",
    "PasswordAuthenticated",
    "PasswordAuthenticationInvalid",
    "PasswordAuthenticationResult",
    "PasswordAuthenticationThrottled",
    "PasswordCredentials",
]
