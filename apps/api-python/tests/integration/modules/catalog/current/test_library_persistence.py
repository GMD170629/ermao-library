from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.infrastructure.catalog_user_authorization import (
    SqlAlchemyCatalogUserAuthorization,
)
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.ports import (
    AuditEvent,
    LibraryGrantPageQuery,
    LibraryPageQuery,
    OutboxEvent,
)
from app.modules.catalog.domain.access import GrantLevel, LibraryGrant
from app.modules.catalog.domain.errors import AclConflict
from app.modules.catalog.domain.ignore_rules import IgnoreRule, IgnoreRuleKind
from app.modules.catalog.domain.library import (
    Library,
    LibraryControlState,
    WritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RegisteredRoot
from app.modules.catalog.infrastructure.persistence import (
    AdministrativeAuditEvent,
    CatalogLibrary,
    CatalogOutbox,
    ContentTopologyProjectionState,
    LibraryIgnoreRule,
    LibraryRootRegistryLock,
    SqlAlchemyLibraryQueryRepository,
    SqlAlchemyLibraryUnitOfWork,
)


class _SqliteBusyError(Exception):
    sqlite_errorcode = 5


class _CleanupTrackingSession(Session):
    rollback_called = False
    close_called = False

    def rollback(self) -> None:
        self.rollback_called = True
        super().rollback()

    def close(self) -> None:
        self.close_called = True
        super().close()


def _busy_operational_error() -> OperationalError:
    return OperationalError(None, None, _SqliteBusyError("database is locked"))


def _raise_busy_on_commit(_connection: object) -> None:
    raise _busy_operational_error()


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database_path = tmp_path / "catalog-persistence.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add_all(
            (
                CurrentUser(id="admin-1", display_name="Admin", role="admin"),
                CurrentUser(id="admin-2", display_name="Admin 2", role="admin"),
                CurrentUser(id="reader-1", display_name="Reader", role="user"),
            )
        )
    yield factory
    engine.dispose()


def _library() -> Library:
    now = datetime.now(UTC)
    return Library.create(
        library_id="library-1",
        name="Books",
        root=RegisteredRoot("/srv/books", "/srv/books", ("/", "srv", "books")),
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        now=now,
    )


def _uow(session_factory: sessionmaker[Session]) -> SqlAlchemyLibraryUnitOfWork:
    return SqlAlchemyLibraryUnitOfWork(
        session_factory,
        user_authorization_factory=SqlAlchemyCatalogUserAuthorization,
    )


def test_uow_persists_library_acl_and_actor_scoped_cursor_page(
    session_factory: sessionmaker[Session],
) -> None:
    with _uow(session_factory) as uow:
        uow.users.ensure_can_create_library("admin-1")
        uow.libraries.insert(_library())
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-1", "library-1", GrantLevel.ADMIN, 1)
        )
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("reader-1", "library-1", GrantLevel.READ, 2)
        )
        uow.ignore_rules.replace(
            "library-1",
            (
                IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="draft"),
                IgnoreRule(
                    kind=IgnoreRuleKind.PATH,
                    pattern="archive/old",
                    enabled=False,
                ),
            ),
            expected_config_revision=1,
            next_config_revision=2,
        )
        uow.users.increment_authz_version("admin-1")
        uow.audit.append(AuditEvent("LIBRARY_CREATED", "admin-1", "library-1"))
        uow.outbox.append(OutboxEvent("LIBRARY_CREATED", "library-1", "admin-1"))
        uow.commit()

    with session_factory() as session:
        queries = SqlAlchemyLibraryQueryRepository(session)
        page = queries.list_grants(
            LibraryGrantPageQuery("admin-1", "library-1", limit=1)
        )
        assert page.items[0].user_id == "admin-1"
        assert page.next_cursor == "admin-1"
        assert queries.get_visible("reader-1", "library-1") is not None
        rules = queries.get_ignore_rules("admin-1", "library-1")
        assert rules is not None
        assert {rule.pattern: rule.enabled for rule in rules.rules} == {
            "archive/old": False,
            "draft": True,
        }
        assert session.scalar(select(func.count()).select_from(LibraryIgnoreRule)) == 2
        assert session.get(CurrentUser, "admin-1").authz_version == 2
        assert (
            session.scalar(select(func.count()).select_from(AdministrativeAuditEvent))
            == 1
        )
        assert session.scalar(select(func.count()).select_from(CatalogOutbox)) == 1
        projection_state = session.get(ContentTopologyProjectionState, "library-1")
        assert projection_state is not None
        assert (
            projection_state.requested_epoch,
            projection_state.claimed_epoch,
            projection_state.applied_epoch,
            projection_state.cursor_volume_id,
        ) == (0, 0, 0, None)


def test_grant_mutations_preserve_the_last_administrator(
    session_factory: sessionmaker[Session],
) -> None:
    with _uow(session_factory) as uow:
        uow.libraries.insert(_library())
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-1", "library-1", GrantLevel.ADMIN, 1)
        )
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-2", "library-1", GrantLevel.ADMIN, 2)
        )
        uow.commit()

    with _uow(session_factory) as uow:
        assert uow.grants.delete_preserving_last_admin("admin-1", "library-1")
        assert not uow.grants.delete_preserving_last_admin("admin-2", "library-1")
        uow.commit()


def test_concurrent_grant_deletes_preserve_one_administrator(
    session_factory: sessionmaker[Session],
) -> None:
    with _uow(session_factory) as uow:
        uow.libraries.insert(_library())
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-1", "library-1", GrantLevel.ADMIN, 1)
        )
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-2", "library-1", GrantLevel.ADMIN, 2)
        )
        uow.commit()

    def delete_administrator(user_id: str) -> bool:
        with _uow(session_factory) as uow:
            deleted = uow.grants.delete_preserving_last_admin(user_id, "library-1")
            uow.commit()
            return deleted

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(delete_administrator, ("admin-1", "admin-2")))

    assert sorted(results) == [False, True]


def test_uow_rolls_back_library_acl_audit_and_outbox_together(
    session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(RuntimeError), _uow(session_factory) as uow:
        uow.libraries.insert(_library())
        uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-1", "library-1", GrantLevel.ADMIN, 1)
        )
        uow.audit.append(AuditEvent("LIBRARY_CREATED", "admin-1", "library-1"))
        uow.outbox.append(OutboxEvent("LIBRARY_CREATED", "library-1", "admin-1"))
        uow.users.increment_authz_version("admin-1")
        raise RuntimeError("rollback regression")

    with session_factory() as session:
        assert session.get(CurrentUser, "admin-1").authz_version == 1
        assert (
            session.scalar(select(func.count()).select_from(AdministrativeAuditEvent))
            == 0
        )
        assert session.scalar(select(func.count()).select_from(CatalogOutbox)) == 0
        assert session.get(ContentTopologyProjectionState, "library-1") is None


def test_library_cas_persists_refreshed_root_fields(
    session_factory: sessionmaker[Session],
) -> None:
    with _uow(session_factory) as uow:
        uow.libraries.insert(_library())
        uow.commit()

    with _uow(session_factory) as uow:
        current = uow.libraries.get_for_update("library-1")
        assert current is not None
        updated = current.update_draft(
            path_comparison=PathComparison.INSENSITIVE,
            root=RegisteredRoot(
                "/srv/Books",
                "/srv/books-insensitive",
                ("/", "srv", "books-insensitive"),
            ),
            now=datetime.now(UTC),
        )
        assert uow.libraries.update_if_revision(updated, expected_config_revision=1)
        assert not uow.libraries.update_if_revision(updated, expected_config_revision=1)
        uow.commit()

    with session_factory() as session:
        row = session.get(CatalogLibrary, "library-1")
        assert row is not None
        assert row.root_path == "/srv/Books"
        assert row.root_path_key == "/srv/books-insensitive"
        assert row.config_revision == 2


def test_actor_scoped_reads_hide_removing_except_admin_management(
    session_factory: sessionmaker[Session],
) -> None:
    with _uow(session_factory) as uow:
        library = _library()
        uow.libraries.insert(library)
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("admin-1", "library-1", GrantLevel.ADMIN, 1)
        )
        assert uow.grants.save_preserving_last_admin(
            LibraryGrant("reader-1", "library-1", GrantLevel.READ, 2)
        )
        removing = replace(
            library,
            control_state=LibraryControlState.REMOVING,
            config_revision=2,
            updated_at=datetime.now(UTC),
        )
        assert uow.libraries.update_if_revision(removing, expected_config_revision=1)
        uow.commit()

    with session_factory() as session:
        queries = SqlAlchemyLibraryQueryRepository(session)
        assert queries.get_visible("admin-1", "library-1") is None
        assert queries.get_visible("reader-1", "library-1") is None
        assert queries.list_visible(LibraryPageQuery("admin-1")).items == ()
        assert queries.get_manageable("reader-1", "library-1") is None
        assert queries.get_manageable("admin-1", "library-1") is not None


def test_uow_enter_busy_maps_acl_conflict_and_cleans_up(
    session_factory: sessionmaker[Session],
) -> None:
    bind = session_factory.kw["bind"]
    assert bind is not None
    assert bind.url.database is not None
    fast_engine = create_current_engine(bind.url.database, timeout_seconds=0.01)
    blocker = session_factory()
    blocker.execute(
        update(LibraryRootRegistryLock)
        .where(LibraryRootRegistryLock.id == 1)
        .values(fence=LibraryRootRegistryLock.fence + 1)
    )
    tracked_session = _CleanupTrackingSession(bind=fast_engine)

    def tracked_factory() -> Session:
        return tracked_session

    try:
        with (
            pytest.raises(AclConflict) as raised,
            _uow(cast(sessionmaker[Session], tracked_factory)),
        ):
            pass
        assert raised.value.code == "ACL_CONFLICT"
        assert isinstance(raised.value.__cause__, OperationalError)
        assert tracked_session.rollback_called
        assert tracked_session.close_called
    finally:
        blocker.rollback()
        blocker.close()
        fast_engine.dispose()


def test_uow_commit_busy_maps_acl_conflict_and_rolls_back(
    session_factory: sessionmaker[Session],
) -> None:
    bind = session_factory.kw["bind"]
    assert bind is not None
    busy_session = _CleanupTrackingSession(bind=bind)

    def busy_factory() -> Session:
        return busy_session

    with (
        pytest.raises(AclConflict) as raised,
        _uow(cast(sessionmaker[Session], busy_factory)) as uow,
    ):
        event.listen(bind, "commit", _raise_busy_on_commit)
        try:
            uow.commit()
        finally:
            event.remove(bind, "commit", _raise_busy_on_commit)

    assert raised.value.code == "ACL_CONFLICT"
    assert isinstance(raised.value.__cause__, OperationalError)
    assert busy_session.rollback_called
    assert busy_session.close_called
