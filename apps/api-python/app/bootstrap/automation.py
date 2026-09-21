"""Compose automation grant use cases; no request or persistence behavior."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.bootstrap.reader import reader_v5_library_queries
from app.core.time import now_timestamp_ms
from app.db.maintenance import database_maintenance_is_active
from app.modules.auth.infrastructure.automation_identity import (
    SqlAlchemyAutomationIdentity,
)
from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.grants import (
    AuthorizeAutomation,
    ManageGrants,
    RecordGrantUse,
)
from app.modules.automation.application.settings import ConfigureAutomation
from app.modules.automation.infrastructure.credentials import AutomationCredentials
from app.modules.automation.infrastructure.grants import SqlAlchemyGrantStore
from app.modules.automation.infrastructure.runtime import DatabaseAutomationRuntime
from app.modules.automation.presentation.mcp import AutomationMcpEndpoint
from app.modules.library.application.queries import (
    GetSmartShelfBookIds,
    SmartShelfCriteria,
)
from app.modules.library.infrastructure.automation_access import (
    SqlAlchemyVisibleLibraryIds,
)
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries
from app.modules.library.infrastructure.queries import SqlAlchemyLibraryQueries
from app.modules.shelf.infrastructure.catalog import SqlAlchemyCatalogShelfQueries
from app.modules.system.infrastructure.automation_audit import SqlAlchemyAutomationAudit
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)


def build_automation_settings(db: Session) -> ConfigureAutomation:
    return ConfigureAutomation(
        SqlAlchemyAutomationSettings(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        db,
        SqlAlchemyAutomationAudit(db),
    )


def build_grant_manager(db: Session) -> ManageGrants:
    return ManageGrants(
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationCredentials(),
        db,
        now_timestamp_ms,
        SqlAlchemyAutomationAudit(db),
    )


def build_automation_authorizer(db: Session) -> AuthorizeAutomation:
    return AuthorizeAutomation(
        SqlAlchemyGrantStore(db),
        SqlAlchemyAutomationIdentity(db, SqlAlchemyVisibleLibraryIds(db)),
        AutomationCredentials(),
        now_timestamp_ms,
    )


def build_automation_catalog(db: Session) -> AutomationCatalog:
    smart = GetSmartShelfBookIds(
        SqlAlchemyLibraryQueries(db, reader_queries=reader_v5_library_queries(db))
    )
    return AutomationCatalog(
        SqlAlchemyVisibleLibraryIds(db),
        SqlAlchemyCatalogQueries(db),
        SqlAlchemyCatalogShelfQueries(
            db,
            lambda rules, user_id: smart.execute(
                SmartShelfCriteria.from_external(rules), user_id=user_id
            ),
        ),
    )


def build_mcp_endpoint(
    session_factory: Callable[[], Session], version: str
) -> AutomationMcpEndpoint:
    return AutomationMcpEndpoint(
        DatabaseAutomationRuntime(
            session_factory,
            SqlAlchemyAutomationSettings,
            build_automation_authorizer,
            build_automation_catalog,
            database_maintenance_is_active,
            lambda db: RecordGrantUse(SqlAlchemyGrantStore(db), db, now_timestamp_ms),
        ),
        version,
    )
