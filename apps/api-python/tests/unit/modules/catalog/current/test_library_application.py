from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Self

import pytest

from app.modules.catalog.application.dto import (
    LibraryAdminDetails,
    LibraryGrantPage,
    LibraryGrantView,
)
from app.modules.catalog.application.library_commands import (
    CreateLibrary,
    CreateLibraryCommand,
)
from app.modules.catalog.application.library_queries import (
    GetAdminLibrary,
    GetLibrary,
    ListLibraryGrants,
)
from app.modules.catalog.application.ports import (
    AuditEvent,
    LibraryGrantPageQuery,
    LibraryPageQuery,
    OutboxEvent,
    ReservedRoot,
    VisibleLibrary,
)
from app.modules.catalog.domain.access import GrantLevel, LibraryGrant
from app.modules.catalog.domain.errors import InvalidPageLimit, LibraryNotFound
from app.modules.catalog.domain.library import Library, LibraryControlState, WritePolicy
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RootObservation

NOW = datetime(2026, 8, 18, tzinfo=UTC)


def root() -> RootObservation:
    return RootObservation("/srv/books", "/srv/books", ("srv", "books"), "dev:1", True)


def make_library() -> Library:
    return Library.create(
        library_id="library-1",
        name="Books",
        root=root().registered_root,
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        now=NOW,
    )


class Epochs:
    def __init__(self) -> None:
        self.value = 0

    def next_scope_epoch(self) -> int:
        self.value += 1
        return self.value


class ClockFake:
    def now(self) -> datetime:
        return NOW


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> str:
        self.value += 1
        return f"id-{self.value}"


class RootLease:
    fence = 1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def heartbeat(self) -> None:
        return None


class RootRegistryFake:
    def __init__(self) -> None:
        self.items: tuple[ReservedRoot, ...] = ()

    def acquire(self, *, owner_token: str) -> RootLease:
        return RootLease()

    def reserved_roots(self) -> tuple[ReservedRoot, ...]:
        return self.items


class PreflightFake:
    def preflight(
        self, requested_path: str, *, path_comparison: PathComparison
    ) -> RootObservation:
        return root()

    def revalidate(
        self,
        requested_path: str,
        observation: RootObservation,
        *,
        path_comparison: PathComparison,
    ) -> RootObservation:
        return observation


class CreatePolicyFake:
    def authorize(self, actor_id: str) -> None:
        return None


@dataclass
class AuditFake:
    events: list[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class OutboxFake:
    events: list[OutboxEvent] = field(default_factory=list)

    def append(self, event: OutboxEvent) -> None:
        self.events.append(event)


class UsersFake:
    def __init__(self) -> None:
        self.active: list[str] = []
        self.bumped: list[str] = []

    def ensure_active_user(self, user_id: str) -> None:
        self.active.append(user_id)

    def ensure_can_create_library(self, user_id: str) -> None:
        self.active.append(user_id)

    def increment_authz_version(self, user_id: str) -> None:
        self.bumped.append(user_id)


class GrantsFake:
    def __init__(self) -> None:
        self.items: list[LibraryGrant] = []

    def save_preserving_last_admin(self, grant: LibraryGrant) -> bool:
        self.items.append(grant)
        return True

    def get(self, user_id: str, library_id: str) -> LibraryGrant | None:
        return next(
            (
                item
                for item in self.items
                if item.user_id == user_id and item.library_id == library_id
            ),
            None,
        )


class LibrariesFake:
    def __init__(self) -> None:
        self.items: list[Library] = []

    def insert(self, library: Library) -> None:
        self.items.append(library)


class UowFake:
    def __init__(self) -> None:
        self.libraries = LibrariesFake()
        self.grants = GrantsFake()
        self.users = UsersFake()
        self.audit = AuditFake()
        self.outbox = OutboxFake()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        return None


def test_create_grants_creator_and_bumps_authz_in_one_uow() -> None:
    uow = UowFake()
    epochs = Epochs()
    command = CreateLibrary(
        unit_of_work_factory=lambda: uow,
        create_policy=CreatePolicyFake(),
        root_preflight=PreflightFake(),
        root_registry=RootRegistryFake(),
        id_generator=Ids(),
        scope_epoch_generator=epochs,
        clock=ClockFake(),
    )
    created = command.execute(
        CreateLibraryCommand(
            actor_id="user-1",
            name="Books",
            requested_root="/srv/books",
            organization_mode=OrganizationMode.FLAT,
            path_comparison=PathComparison.SENSITIVE,
            write_policy=WritePolicy.READ_ONLY,
        )
    )
    assert created.control_state.value == "DRAFT"
    assert uow.grants.items[0].level is GrantLevel.ADMIN
    assert uow.users.bumped == ["user-1"]
    assert epochs.value == 1
    assert uow.audit.events[0].event_type == "LIBRARY_CREATED"


class QueryFake:
    def __init__(
        self,
        visible: VisibleLibrary | None,
        *,
        manageable: VisibleLibrary | None = None,
    ) -> None:
        self.visible = visible
        self.manageable = visible if manageable is None else manageable

    def get_visible(self, actor_id: str, library_id: str) -> VisibleLibrary | None:
        return self.visible

    def get_manageable(self, actor_id: str, library_id: str) -> VisibleLibrary | None:
        return self.manageable

    def list_visible(self, query: LibraryPageQuery):
        raise AssertionError

    def list_grants(self, query: LibraryGrantPageQuery) -> LibraryGrantPage:
        grant = self.manageable.grant if self.manageable is not None else None
        return LibraryGrantPage(
            items=(
                LibraryGrantView(
                    grant.user_id,
                    grant.library_id,
                    grant.level,
                    grant.scope_epoch,
                ),
            )
            if grant is not None
            else (),
            next_cursor=None,
        )

    def get_ignore_rules(self, actor_id: str, library_id: str):
        return None


def test_get_library_safe_summary_never_contains_root_and_admin_is_separate() -> None:
    visible = VisibleLibrary(
        make_library(), LibraryGrant("user-1", "library-1", GrantLevel.ADMIN, 1)
    )
    query = QueryFake(visible)
    safe = GetLibrary(query).execute(actor_id="user-1", library_id="library-1")
    admin = GetAdminLibrary(query).execute(actor_id="user-1", library_id="library-1")
    assert not hasattr(safe, "root_path")
    assert safe.topology_version == 1
    assert safe.path_comparison is PathComparison.SENSITIVE
    assert isinstance(admin, LibraryAdminDetails)
    assert admin.root_path == "/srv/books"


def test_removing_library_is_hidden_from_ordinary_get_but_manageable_by_admin() -> None:
    removing = replace(make_library(), control_state=LibraryControlState.REMOVING)
    manageable = VisibleLibrary(
        removing, LibraryGrant("user-1", "library-1", GrantLevel.ADMIN, 1)
    )
    query = QueryFake(None, manageable=manageable)
    with pytest.raises(LibraryNotFound):
        GetLibrary(query).execute(actor_id="user-1", library_id="library-1")
    details = GetAdminLibrary(query).execute(actor_id="user-1", library_id="library-1")
    assert details.control_state is LibraryControlState.REMOVING


def test_grant_listing_uses_bounded_page_contract() -> None:
    visible = VisibleLibrary(
        make_library(), LibraryGrant("user-1", "library-1", GrantLevel.ADMIN, 1)
    )
    query_port = QueryFake(visible)
    page = ListLibraryGrants(query_port).execute(
        LibraryGrantPageQuery("user-1", "library-1", limit=100)
    )
    assert [item.user_id for item in page.items] == ["user-1"]
    with pytest.raises(InvalidPageLimit):
        ListLibraryGrants(query_port).execute(
            LibraryGrantPageQuery("user-1", "library-1", limit=101)
        )
