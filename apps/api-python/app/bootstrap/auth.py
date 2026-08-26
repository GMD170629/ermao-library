"""Authentication composition root.

Only dependency construction and adapter publication live here; persistence is
owned by the Auth infrastructure layer.
"""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.application.user_management import (
    CreateUser,
    DeleteUser,
    GetUser,
    ListUsers,
    ResetUserPassword,
    UpdateUser,
    UserAdministrationUseCases,
)
from app.modules.auth.infrastructure.transactions import (
    build_password_authentication_runtime,
    build_password_authenticator,
    delete_expired_or_disabled_sessions,
    list_library_ids,
    persist_account_avatar,
    persist_account_email,
    persist_account_name,
    persist_account_password,
    persist_admin_password_reset,
    persist_admin_user_create,
    persist_admin_user_delete,
    persist_admin_user_update,
    persist_confirmed_password_reset,
    persist_initial_setup,
    persist_login_session,
    persist_logout,
    persist_password_reset_request,
    persist_session_refresh,
    persist_user_preferences,
    prepare_account_avatar_publication,
    remove_password_reset_request,
    validate_library_ids,
)
from app.modules.auth.infrastructure.user_administration import (
    SqlAlchemyUserAdministrationGateway,
)
from app.modules.auth.infrastructure.user_management_queries import (
    active_admin_count,
    email_in_use,
    get_user,
    list_users,
    refresh_user,
    user_view,
)


def build_user_administration_use_cases(
    db: Session, settings: Settings
) -> UserAdministrationUseCases:
    gateway = SqlAlchemyUserAdministrationGateway(db, settings)
    return UserAdministrationUseCases(
        list_users=ListUsers(gateway),
        get_user=GetUser(gateway),
        create_user=CreateUser(gateway),
        update_user=UpdateUser(gateway),
        reset_password=ResetUserPassword(gateway),
        delete_user=DeleteUser(gateway),
    )


__all__ = [
    "active_admin_count",
    "build_password_authentication_runtime",
    "build_password_authenticator",
    "build_user_administration_use_cases",
    "delete_expired_or_disabled_sessions",
    "email_in_use",
    "get_user",
    "list_library_ids",
    "list_users",
    "persist_account_avatar",
    "persist_account_email",
    "persist_account_name",
    "persist_account_password",
    "persist_admin_password_reset",
    "persist_admin_user_create",
    "persist_admin_user_delete",
    "persist_admin_user_update",
    "persist_confirmed_password_reset",
    "persist_initial_setup",
    "persist_login_session",
    "persist_logout",
    "persist_password_reset_request",
    "persist_session_refresh",
    "persist_user_preferences",
    "prepare_account_avatar_publication",
    "refresh_user",
    "remove_password_reset_request",
    "user_view",
    "validate_library_ids",
]
