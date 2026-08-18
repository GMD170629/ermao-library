"""SQLAlchemy adapters for the current Catalog application ports.

The adapters deliberately accept a caller-owned ``Session``.  They flush when
an invariant must be checked immediately, but never commit or roll back; the
Catalog unit of work owns that transaction boundary.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath, PureWindowsPath
from typing import cast
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.modules.catalog.application.dto import (
    IgnoreRulesResult,
    LibraryGrantPage,
    LibraryGrantView,
    LibraryPage,
    LibrarySummary,
)
from app.modules.catalog.application.ports import (
    AuditEvent,
    LibraryGrantPageQuery,
    LibraryPageQuery,
    OutboxEvent,
    VisibleLibrary,
)
from app.modules.catalog.domain.access import (
    GrantLevel as DomainGrantLevel,
)
from app.modules.catalog.domain.access import (
    LibraryGrant,
)
from app.modules.catalog.domain.errors import (
    LibraryConfigConflict,
    LibraryConfigurationFrozen,
    RootOverlapConflict,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule
from app.modules.catalog.domain.library import (
    Library,
)
from app.modules.catalog.domain.library import (
    LibraryControlState as DomainControlState,
)
from app.modules.catalog.domain.library import (
    LibraryHealth as DomainHealth,
)
from app.modules.catalog.domain.library import (
    WritePolicy as DomainWritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RegisteredRoot

from .enums import (
    AuditActorKind,
    GrantLevel,
    IgnoreRuleKind,
    LibraryControlState,
    LibraryHealth,
    OperationState,
)
from .enums import (
    WritePolicy as PersistenceWritePolicy,
)
from .models import (
    AdministrativeAuditEvent,
    CatalogLibrary,
    CatalogOutbox,
    LibraryIgnoreRule,
    LibraryWatcherState,
    SourceWriteOperation,
    UserLibraryGrant,
)


def _enum_value(value: object) -> str:
    return cast(str, getattr(value, "value", value))


def _root_components(root_path_key: str) -> tuple[str, ...]:
    """Reconstruct the component tuple persisted by the filesystem adapter."""

    if "\\" in root_path_key or (len(root_path_key) >= 2 and root_path_key[1] == ":"):
        parts = PureWindowsPath(root_path_key).parts
    else:
        parts = PurePosixPath(root_path_key).parts
    return tuple(parts)


def library_from_row(row: CatalogLibrary) -> Library:
    return Library(
        id=row.id,
        name=row.name,
        root=RegisteredRoot(
            canonical_path=row.root_path,
            root_path_key=row.root_path_key,
            components=_root_components(row.root_path_key),
        ),
        organization_mode=OrganizationMode(_enum_value(row.organization_mode)),
        topology_version=row.topology_version,
        path_comparison=PathComparison(_enum_value(row.path_comparison)),
        write_policy=DomainWritePolicy(_enum_value(row.write_policy)),
        control_state=DomainControlState(_enum_value(row.control_state)),
        observed_health=DomainHealth(_enum_value(row.observed_health)),
        config_revision=row.config_revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def grant_from_row(row: UserLibraryGrant) -> LibraryGrant:
    return LibraryGrant(
        user_id=row.user_id,
        library_id=row.library_id,
        level=DomainGrantLevel(_enum_value(row.level)),
        scope_epoch=row.scope_epoch,
    )


def ignore_rule_from_row(row: LibraryIgnoreRule) -> IgnoreRule:
    from app.modules.catalog.domain.ignore_rules import IgnoreRuleKind

    return IgnoreRule(
        kind=IgnoreRuleKind(_enum_value(row.kind)),
        pattern=row.pattern,
        rule_key=row.rule_key,
        enabled=row.enabled,
    )


class SqlAlchemyLibraryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, library: Library) -> None:
        existing = self._session.scalar(
            select(CatalogLibrary.id).where(
                CatalogLibrary.root_path_key == library.root.root_path_key
            )
        )
        if existing is not None:
            raise RootOverlapConflict()
        row = CatalogLibrary(
            id=library.id,
            name=library.name,
            root_path=library.root.canonical_path,
            root_path_key=library.root.root_path_key,
            organization_mode=OrganizationMode(library.organization_mode),
            topology_version=library.topology_version,
            path_comparison=PathComparison(library.path_comparison),
            write_policy=PersistenceWritePolicy(library.write_policy),
            control_state=LibraryControlState(library.control_state),
            observed_health=LibraryHealth(library.observed_health),
            config_revision=library.config_revision,
            created_at=library.created_at,
            updated_at=library.updated_at,
        )
        self._session.add(row)
        self._session.add(
            LibraryWatcherState(
                library_id=library.id,
                latest_sequence=0,
                overflow_through_sequence=None,
                full_rescan_reason=None,
                updated_at=library.created_at,
            )
        )
        # Root identity is protected by a unique constraint.  Flushing here
        # lets the application report a stable conflict before adding grants.
        self._session.flush()

    def get_for_update(self, library_id: str) -> Library | None:
        row = self._session.scalar(
            select(CatalogLibrary)
            .where(CatalogLibrary.id == library_id)
            .with_for_update()
        )
        return None if row is None else library_from_row(row)

    def update_if_revision(
        self, library: Library, *, expected_config_revision: int
    ) -> bool:
        result = self._session.execute(
            update(CatalogLibrary)
            .where(
                CatalogLibrary.id == library.id,
                CatalogLibrary.config_revision == expected_config_revision,
            )
            .values(
                name=library.name,
                organization_mode=OrganizationMode(library.organization_mode),
                topology_version=library.topology_version,
                path_comparison=PathComparison(library.path_comparison),
                write_policy=PersistenceWritePolicy(library.write_policy),
                control_state=LibraryControlState(library.control_state),
                observed_health=LibraryHealth(library.observed_health),
                config_revision=library.config_revision,
                root_path=library.root.canonical_path,
                root_path_key=library.root.root_path_key,
                updated_at=library.updated_at,
            )
        )
        return cast(CursorResult[object], result).rowcount == 1


class SqlAlchemyLibraryGrantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: str, library_id: str) -> LibraryGrant | None:
        row = self._session.scalar(
            select(UserLibraryGrant).where(
                UserLibraryGrant.user_id == user_id,
                UserLibraryGrant.library_id == library_id,
            )
        )
        return None if row is None else grant_from_row(row)

    def count_active_administrators(self, library_id: str) -> int:
        count = self._session.scalar(
            select(func.count())
            .select_from(UserLibraryGrant)
            .where(
                UserLibraryGrant.library_id == library_id,
                UserLibraryGrant.level == GrantLevel.ADMIN,
            )
        )
        return int(count or 0)

    def save_preserving_last_admin(self, grant: LibraryGrant) -> bool:
        # A read/update pair is intentional: it is portable across SQLite and
        # other SQLAlchemy dialects and remains inside the caller's UoW.
        row = self._session.get(UserLibraryGrant, (grant.user_id, grant.library_id))
        if (
            row is not None
            and _enum_value(row.level) == DomainGrantLevel.ADMIN.value
            and grant.level is not DomainGrantLevel.ADMIN
            and self.count_active_administrators(grant.library_id) <= 1
        ):
            return False
        if row is None:
            self._session.add(
                UserLibraryGrant(
                    user_id=grant.user_id,
                    library_id=grant.library_id,
                    level=GrantLevel(grant.level),
                    scope_epoch=grant.scope_epoch,
                )
            )
        else:
            row.level = GrantLevel(grant.level)
            row.scope_epoch = grant.scope_epoch
            row.updated_at = func.current_timestamp()
        self._session.flush()
        return True

    def delete_preserving_last_admin(self, user_id: str, library_id: str) -> bool:
        row = self._session.get(UserLibraryGrant, (user_id, library_id))
        if row is None:
            return False
        if (
            _enum_value(row.level) == DomainGrantLevel.ADMIN.value
            and self.count_active_administrators(library_id) <= 1
        ):
            return False
        self._session.execute(
            delete(UserLibraryGrant).where(
                UserLibraryGrant.user_id == user_id,
                UserLibraryGrant.library_id == library_id,
            )
        )
        return True


class SqlAlchemyIgnoreRuleRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(
        self,
        library_id: str,
        rules: tuple[IgnoreRule, ...],
        *,
        expected_config_revision: int,
        next_config_revision: int,
    ) -> None:
        current_revision = self._session.scalar(
            select(CatalogLibrary.config_revision).where(
                CatalogLibrary.id == library_id
            )
        )
        if current_revision != expected_config_revision:
            raise LibraryConfigConflict()
        replacement_rows = tuple(
            LibraryIgnoreRule(
                id=hashlib.sha256(
                    f"{library_id}\x00{rule.rule_key}".encode()
                ).hexdigest(),
                library_id=library_id,
                rule_key=rule.rule_key,
                pattern=rule.pattern,
                kind=IgnoreRuleKind(rule.kind),
                enabled=rule.enabled,
                config_revision=next_config_revision,
            )
            for rule in rules
        )
        delete_statement = delete(LibraryIgnoreRule).where(
            LibraryIgnoreRule.library_id == library_id
        )
        self._session.execute(delete_statement)
        self._session.add_all(replacement_rows)
        self._session.flush()


class SqlAlchemyLibraryQueryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _actor_statement(
        self,
        actor_id: str,
        library_id: str | None = None,
        *,
        management: bool = False,
    ):
        conditions = [UserLibraryGrant.user_id == actor_id]
        if library_id is not None:
            conditions.append(CatalogLibrary.id == library_id)
        if not management:
            conditions.append(
                CatalogLibrary.control_state != LibraryControlState.REMOVING
            )
        if management:
            conditions.append(UserLibraryGrant.level == GrantLevel.ADMIN)
        return (
            select(CatalogLibrary, UserLibraryGrant)
            .join(
                UserLibraryGrant,
                UserLibraryGrant.library_id == CatalogLibrary.id,
            )
            .where(*conditions)
        )

    def _visible_statement(self, actor_id: str, library_id: str | None = None):
        return self._actor_statement(actor_id, library_id)

    def _manageable_statement(self, actor_id: str, library_id: str | None = None):
        return self._actor_statement(actor_id, library_id, management=True)

    def list_visible(self, query: LibraryPageQuery) -> LibraryPage:
        statement = self._visible_statement(query.actor_id).order_by(CatalogLibrary.id)
        if query.cursor is not None:
            statement = statement.where(CatalogLibrary.id > query.cursor)
        rows = self._session.execute(statement.limit(query.limit + 1)).all()
        has_next = len(rows) > query.limit
        page_rows = rows[: query.limit]
        items = tuple(
            _summary(library_from_row(library), grant_from_row(grant))
            for library, grant in page_rows
        )
        return LibraryPage(
            items=items,
            next_cursor=(page_rows[-1][0].id if has_next and page_rows else None),
        )

    def get_visible(self, actor_id: str, library_id: str) -> VisibleLibrary | None:
        row = self._session.execute(
            self._visible_statement(actor_id, library_id)
        ).one_or_none()
        if row is None:
            return None
        library, grant = row
        return VisibleLibrary(library_from_row(library), grant_from_row(grant))

    def get_manageable(self, actor_id: str, library_id: str) -> VisibleLibrary | None:
        row = self._session.execute(
            self._manageable_statement(actor_id, library_id)
        ).one_or_none()
        if row is None:
            return None
        library, grant = row
        return VisibleLibrary(library_from_row(library), grant_from_row(grant))

    def list_grants(self, query: LibraryGrantPageQuery) -> LibraryGrantPage:
        actor = self._manageable_statement(query.actor_id, query.library_id)
        if self._session.execute(actor).first() is None:
            return LibraryGrantPage(items=(), next_cursor=None)
        statement = (
            select(UserLibraryGrant)
            .where(UserLibraryGrant.library_id == query.library_id)
            .order_by(UserLibraryGrant.user_id)
        )
        if query.cursor is not None:
            statement = statement.where(UserLibraryGrant.user_id > query.cursor)
        rows = self._session.scalars(statement.limit(query.limit + 1)).all()
        has_next = len(rows) > query.limit
        page_rows = rows[: query.limit]
        return LibraryGrantPage(
            items=tuple(
                LibraryGrantView(
                    user_id=row.user_id,
                    library_id=row.library_id,
                    level=DomainGrantLevel(_enum_value(row.level)),
                    scope_epoch=row.scope_epoch,
                )
                for row in page_rows
            ),
            next_cursor=(page_rows[-1].user_id if has_next and page_rows else None),
        )

    def get_ignore_rules(
        self, actor_id: str, library_id: str
    ) -> IgnoreRulesResult | None:
        actor = self._manageable_statement(actor_id, library_id)
        if self._session.execute(actor).first() is None:
            return None
        library = self._session.scalar(
            select(CatalogLibrary).where(CatalogLibrary.id == library_id)
        )
        if library is None:
            return None
        rows = self._session.scalars(
            select(LibraryIgnoreRule)
            .where(
                LibraryIgnoreRule.library_id == library_id,
            )
            .order_by(LibraryIgnoreRule.rule_key)
        ).all()
        return IgnoreRulesResult(
            library_id=library_id,
            config_revision=library.config_revision,
            rules=tuple(ignore_rule_from_row(row) for row in rows),
        )


def _summary(library: Library, grant: LibraryGrant) -> LibrarySummary:
    from app.modules.catalog.application.dto import summary_from_library

    return summary_from_library(library, grant.level)


class SqlAlchemyLibraryWritePolicy:
    """Same-session safety gate for READ_WRITE -> READ_ONLY."""

    _terminal_states = (
        OperationState.COMPLETED,
        OperationState.CANCELLED,
        OperationState.ABANDONED_BY_LIBRARY_REMOVAL,
        OperationState.FAILED,
    )

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_read_only_safe(self, library_id: str) -> None:
        active = self._session.scalar(
            select(SourceWriteOperation.id)
            .where(
                SourceWriteOperation.library_id == library_id,
                SourceWriteOperation.state.not_in(self._terminal_states),
            )
            .limit(1)
        )
        if active is not None:
            raise LibraryConfigurationFrozen("SOURCE_WRITE_OPERATION_ACTIVE")


class SqlAlchemyAuditPort:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> None:
        self._session.add(
            AdministrativeAuditEvent(
                id=f"audit_{uuid4().hex}",
                former_library_id=event.library_id,
                code=event.event_type,
                actor_kind=AuditActorKind.USER,
                actor_user_id=event.actor_id,
                evidence=dict(event.payload),
            )
        )


class SqlAlchemyOutboxPort:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: OutboxEvent) -> None:
        self._session.add(
            CatalogOutbox(
                id=f"outbox_{uuid4().hex}",
                library_id=event.aggregate_id,
                aggregate_type="LIBRARY",
                aggregate_id=event.aggregate_id,
                event_type=event.event_type,
                event_version=1,
                payload=dict(event.payload),
            )
        )


__all__ = [
    "SqlAlchemyAuditPort",
    "SqlAlchemyIgnoreRuleRepository",
    "SqlAlchemyLibraryGrantRepository",
    "SqlAlchemyLibraryQueryRepository",
    "SqlAlchemyLibraryRepository",
    "SqlAlchemyLibraryWritePolicy",
    "SqlAlchemyOutboxPort",
    "grant_from_row",
    "ignore_rule_from_row",
    "library_from_row",
]
