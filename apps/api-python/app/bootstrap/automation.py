"""Compose automation grant use cases; no request or persistence behavior."""

from sqlalchemy.orm import Session

from app.core.time import now_timestamp_ms
from app.modules.auth.infrastructure.automation_identity import (
    SqlAlchemyAutomationIdentity,
)
from app.modules.automation.application.grants import AuthorizeAutomation, ManageGrants
from app.modules.automation.infrastructure.credentials import AutomationCredentials
from app.modules.automation.infrastructure.grants import SqlAlchemyGrantStore
from app.modules.library.infrastructure.automation_access import (
    SqlAlchemyVisibleLibraryIds,
)


def build_grant_manager(db: Session) -> ManageGrants:
    return ManageGrants(
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationCredentials(),
        db,
        now_timestamp_ms,
    )


def build_automation_authorizer(db: Session) -> AuthorizeAutomation:
    return AuthorizeAutomation(
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationCredentials(),
        now_timestamp_ms,
    )
