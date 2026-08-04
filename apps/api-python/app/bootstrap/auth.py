"""Authentication and user-management composition root."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.application.password_authentication import AuthenticatePassword
from app.modules.auth.infrastructure.password_authentication import (
    BoundedPasswordVerificationGateway,
    SqlAlchemyUserCredentialReader,
)
from app.modules.auth.infrastructure.user_data import (
    delete_personal_user_data,
    list_monitor_folder_ids,
    replace_monitor_folder_access,
    validate_monitor_folder_ids,
)


def build_password_authenticator(
    session: Session,
    runtime: BoundedPasswordVerificationGateway,
) -> AuthenticatePassword:
    return AuthenticatePassword(
        credential_reader=SqlAlchemyUserCredentialReader(session),
        password_verification=runtime,
    )


def build_password_authentication_runtime(
    settings: Settings,
) -> BoundedPasswordVerificationGateway:
    return BoundedPasswordVerificationGateway(
        success_ttl_seconds=settings.opds_auth_cache_ttl_seconds,
        success_capacity=settings.opds_auth_cache_capacity,
        pair_attempt_limit=settings.opds_auth_identity_failures,
        pair_window_seconds=settings.opds_auth_identity_window_seconds,
        address_attempt_limit=settings.opds_auth_ip_failures,
        address_window_seconds=settings.opds_auth_ip_window_seconds,
    )


__all__ = [
    "build_password_authentication_runtime",
    "build_password_authenticator",
    "delete_personal_user_data",
    "list_monitor_folder_ids",
    "replace_monitor_folder_access",
    "validate_monitor_folder_ids",
]
