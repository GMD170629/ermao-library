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
from app.modules.auth.application.user_management import (
    AdminUserView,
    CreateUser,
    CreateUserCommand,
    DeleteUser,
    GetUser,
    ListUsers,
    ResetUserPassword,
    UpdateUser,
    UpdateUserCommand,
    UserAdministrationActor,
    UserAdministrationError,
    UserAdministrationGateway,
    UserAdministrationUseCases,
)

__all__ = [
    "AdminUserView",
    "AuthUnitOfWork",
    "AuthenticatePassword",
    "AuthenticatedPrincipal",
    "CreateUser",
    "CreateUserCommand",
    "DeleteUser",
    "GetUser",
    "ListUsers",
    "PasswordAuthenticated",
    "PasswordAuthenticationInvalid",
    "PasswordAuthenticationResult",
    "PasswordAuthenticationThrottled",
    "PasswordCredentials",
    "ResetUserPassword",
    "UpdateUser",
    "UpdateUserCommand",
    "UserAdministrationActor",
    "UserAdministrationError",
    "UserAdministrationGateway",
    "UserAdministrationUseCases",
]
