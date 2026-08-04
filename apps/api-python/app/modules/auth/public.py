"""Stable application contracts for authentication and user administration."""

from app.modules.auth.application.commands import AuthUnitOfWork, execute_auth_write
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
    "execute_auth_write",
]
