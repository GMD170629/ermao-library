from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Self

import pytest

from app.modules.catalog.application.dto import (
    IgnoreRulesResult,
    LibraryGrantPage,
    LibraryGrantView,
)
from app.modules.catalog.application.library_commands import (
    ActivateLibrary,
    CreateLibrary,
    CreateLibraryCommand,
    LibraryStateCommand,
    PauseLibrary,
    ReplaceLibraryIgnoreRules,
    ReplaceLibraryIgnoreRulesCommand,
    ResumeLibrary,
    RevokeLibraryGrant,
    RevokeLibraryGrantCommand,
    SetLibraryGrant,
    SetLibraryGrantCommand,
    UpdateLibrary,
    UpdateLibraryCommand,
)
from app.modules.catalog.application.library_queries import GetLibraryIgnoreRules
from app.modules.catalog.application.ports import (
    AuditEvent,
    LibraryGrantPageQuery,
    LibraryPageQuery,
    OutboxEvent,
    ReservedRoot,
    VisibleLibrary,
)
from app.modules.catalog.domain.access import GrantLevel, LibraryGrant
from app.modules.catalog.domain.errors import (
    FinalAdministratorRequired,
    InvalidLibraryTransition,
    LibraryConfigConflict,
    LibraryConfigurationFrozen,
    LibraryCreateDenied,
    LibraryForbidden,
    LibraryRemoving,
    NoLibraryChanges,
    RootIdentityChanged,
    RootOverlapConflict,
    RootUnwritable,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule, IgnoreRuleKind
from app.modules.catalog.domain.library import (
    Library,
    LibraryControlState,
    WritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RootObservation

NOW = datetime(2026, 8, 18, tzinfo=UTC)


def observation(
    path: str = "/srv/books",
    *,
    identity: str = "dev:1",
    writable: bool = True,
) -> RootObservation:
    return RootObservation(
        canonical_path=path,
        root_path_key=path.casefold(),
        components=tuple(part.casefold() for part in path.split("/") if part),
        filesystem_identity=identity,
        writable=writable,
    )


def make_library(
    *,
    state: LibraryControlState = LibraryControlState.DRAFT,
    write_policy: WritePolicy = WritePolicy.READ_ONLY,
) -> Library:
    created = Library.create(
        library_id="library-1",
        name="Books",
        root=observation().registered_root,
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.INSENSITIVE,
        write_policy=write_policy,
        now=NOW,
    )
    return replace(created, control_state=state)


class ClockFake:
    def now(self) -> datetime:
        return NOW


class Epochs:
    def __init__(self, start: int = 100) -> None:
        self.value = start
        self.calls = 0

    def next_scope_epoch(self) -> int:
        self.value += 1
        self.calls += 1
        return self.value


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> str:
        self.value += 1
        return f"id-{self.value}"


class EventSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[AuditEvent | OutboxEvent] = []
        self.fail = fail

    def append(self, event: AuditEvent | OutboxEvent) -> None:
        if self.fail:
            raise RuntimeError("event write failed")
        self.events.append(event)


class LibraryRepositoryFake:
    def __init__(self, current: Library | None = None) -> None:
        self.current = current
        self.update_allowed = True

    def insert(self, library: Library) -> None:
        self.current = library

    def get_for_update(self, library_id: str) -> Library | None:
        if self.current is None or self.current.id != library_id:
            return None
        return self.current

    def update_if_revision(
        self, library: Library, *, expected_config_revision: int
    ) -> bool:
        if (
            not self.update_allowed
            or self.current is None
            or self.current.config_revision != expected_config_revision
        ):
            return False
        self.current = library
        return True


class GrantRepositoryFake:
    def __init__(self, grants: tuple[LibraryGrant, ...] = ()) -> None:
        self.items = {(grant.user_id, grant.library_id): grant for grant in grants}
        self.save_allowed = True
        self.delete_allowed = True

    def get(self, user_id: str, library_id: str) -> LibraryGrant | None:
        return self.items.get((user_id, library_id))

    def save_preserving_last_admin(self, grant: LibraryGrant) -> bool:
        if not self.save_allowed:
            return False
        self.items[(grant.user_id, grant.library_id)] = grant
        return True

    def delete_preserving_last_admin(self, user_id: str, library_id: str) -> bool:
        if not self.delete_allowed:
            return False
        self.items.pop((user_id, library_id), None)
        return True


class IgnoreRepositoryFake:
    def __init__(self) -> None:
        self.rules: tuple[IgnoreRule, ...] = ()
        self.fail = False

    def replace(
        self,
        library_id: str,
        rules: tuple[IgnoreRule, ...],
        *,
        expected_config_revision: int,
        next_config_revision: int,
    ) -> None:
        if self.fail:
            raise RuntimeError("replace failed")
        self.rules = rules


class UsersFake:
    def __init__(self, *, create_allowed: bool = True) -> None:
        self.bumped: list[str] = []
        self.create_allowed = create_allowed

    def ensure_can_create_library(self, user_id: str) -> None:
        if not self.create_allowed:
            raise LibraryCreateDenied()

    def ensure_active_user(self, user_id: str) -> None:
        return None

    def increment_authz_version(self, user_id: str) -> None:
        self.bumped.append(user_id)


class WritePolicyFake:
    def __init__(self) -> None:
        self.checked: list[str] = []

    def ensure_read_only_safe(self, library_id: str) -> None:
        self.checked.append(library_id)


class UowFake:
    def __init__(
        self,
        *,
        library: Library | None = None,
        grants: tuple[LibraryGrant, ...] = (),
        fail_audit: bool = False,
        trace: list[str] | None = None,
    ) -> None:
        self.libraries = LibraryRepositoryFake(library)
        self.grants = GrantRepositoryFake(grants)
        self.ignore_rules = IgnoreRepositoryFake()
        self.users = UsersFake()
        self.audit = EventSink(fail=fail_audit)
        self.outbox = EventSink()
        self.write_policy = WritePolicyFake()
        self.queries = None
        self.committed = False
        self.rolled_back = False
        self.trace = trace

    def __enter__(self) -> Self:
        if self.trace is not None:
            self.trace.append("uow")
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        if exception_type is not None:
            self.rollback()
        return False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def admin_grant(user_id: str = "admin") -> LibraryGrant:
    return LibraryGrant(user_id, "library-1", GrantLevel.ADMIN, 1)


def member_grant(level: GrantLevel, user_id: str = "member") -> LibraryGrant:
    return LibraryGrant(user_id, "library-1", level, 2)


class RootLease:
    fence = 1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def heartbeat(self) -> None:
        return None


class RootRegistryFake:
    def __init__(
        self,
        roots: tuple[ReservedRoot, ...] = (),
        *,
        snapshots: tuple[tuple[ReservedRoot, ...], ...] | None = None,
        trace: list[str] | None = None,
    ) -> None:
        self.snapshots = snapshots or (roots,)
        self.trace = trace
        self.reserved_calls = 0

    def acquire(self, *, owner_token: str) -> RootLease:
        if self.trace is not None:
            self.trace.append("lease")
        return RootLease()

    def reserved_roots(self) -> tuple[ReservedRoot, ...]:
        if self.trace is not None:
            self.trace.append("reserved")
        index = min(self.reserved_calls, len(self.snapshots) - 1)
        self.reserved_calls += 1
        return self.snapshots[index]


class PreflightFake:
    def __init__(
        self,
        first: RootObservation,
        second: RootObservation | None = None,
        *,
        trace: list[str] | None = None,
    ) -> None:
        self.first = first
        self.second = second or first
        self.revalidated_requested_path: str | None = None
        self.trace = trace

    def preflight(
        self, requested_path: str, *, path_comparison: PathComparison
    ) -> RootObservation:
        if self.trace is not None:
            self.trace.append("preflight")
        return self.first

    def revalidate(
        self,
        requested_path: str,
        previous: RootObservation,
        *,
        path_comparison: PathComparison,
    ) -> RootObservation:
        if self.trace is not None:
            self.trace.append("revalidate")
        self.revalidated_requested_path = requested_path
        return self.second


class CreatePolicyFake:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace = trace

    def authorize(self, actor_id: str) -> None:
        if self.trace is not None:
            self.trace.append("authorize")


def create_use_case(
    uow: UowFake,
    preflight: PreflightFake,
    *,
    registry: RootRegistryFake | None = None,
    trace: list[str] | None = None,
) -> CreateLibrary:
    return CreateLibrary(
        unit_of_work_factory=lambda: uow,
        create_policy=CreatePolicyFake(trace),
        root_preflight=preflight,
        root_registry=registry or RootRegistryFake(),
        id_generator=Ids(),
        scope_epoch_generator=Epochs(),
        clock=ClockFake(),
    )


def create_command(
    *, write_policy: WritePolicy = WritePolicy.READ_ONLY
) -> CreateLibraryCommand:
    return CreateLibraryCommand(
        actor_id="admin",
        name="Books",
        requested_root="/alias/books",
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.INSENSITIVE,
        write_policy=write_policy,
    )


def update_use_case(
    uow: UowFake,
    *,
    preflight: PreflightFake | None = None,
    registry: RootRegistryFake | None = None,
    trace: list[str] | None = None,
) -> UpdateLibrary:
    class UpdateQueryFake:
        def get_manageable(
            self, actor_id: str, library_id: str
        ) -> VisibleLibrary | None:
            if trace is not None:
                trace.append("query")
            library = uow.libraries.get_for_update(library_id)
            grant = uow.grants.get(actor_id, library_id)
            if library is None or grant is None or grant.level is not GrantLevel.ADMIN:
                return None
            return VisibleLibrary(library, grant)

    return UpdateLibrary(
        unit_of_work_factory=lambda: uow,
        query_port=UpdateQueryFake(),
        root_preflight=preflight or PreflightFake(observation(), trace=trace),
        root_registry=registry or RootRegistryFake(trace=trace),
        id_generator=Ids(),
        clock=ClockFake(),
    )


def test_create_revalidates_original_path_and_rejects_symlink_retarget() -> None:
    preflight = PreflightFake(observation(identity="old"), observation(identity="new"))
    uow = UowFake()
    with pytest.raises(RootIdentityChanged):
        create_use_case(uow, preflight).execute(create_command())
    assert preflight.revalidated_requested_path == "/alias/books"
    assert not uow.committed


def test_create_rejects_unwritable_read_write_root_and_overlap() -> None:
    uow = UowFake()
    with pytest.raises(RootUnwritable):
        create_use_case(uow, PreflightFake(observation(writable=False))).execute(
            create_command(write_policy=WritePolicy.READ_WRITE)
        )
    trace: list[str] = []
    registry = RootRegistryFake(
        (ReservedRoot("removing-library", observation("/srv").claim),),
        trace=trace,
    )
    with pytest.raises(RootOverlapConflict):
        create_use_case(
            uow,
            PreflightFake(observation(), trace=trace),
            registry=registry,
            trace=trace,
        ).execute(create_command())
    assert trace == ["authorize", "preflight", "reserved"]
    assert registry.reserved_calls == 1


def test_create_authoritative_overlap_rechecks_roots_added_after_fast_fail() -> None:
    trace: list[str] = []
    uow = UowFake(trace=trace)
    conflict = ReservedRoot("concurrent-library", observation("/srv").claim)
    registry = RootRegistryFake(snapshots=((), (conflict,)), trace=trace)
    with pytest.raises(RootOverlapConflict):
        create_use_case(
            uow,
            PreflightFake(observation(), trace=trace),
            registry=registry,
            trace=trace,
        ).execute(create_command())
    assert registry.reserved_calls == 2
    assert trace == [
        "authorize",
        "preflight",
        "reserved",
        "lease",
        "revalidate",
        "reserved",
    ]
    assert not uow.committed


def test_create_success_keeps_authoritative_overlap_inside_lease() -> None:
    trace: list[str] = []
    uow = UowFake(trace=trace)
    registry = RootRegistryFake(snapshots=((), ()), trace=trace)
    created = create_use_case(
        uow,
        PreflightFake(observation(), trace=trace),
        registry=registry,
        trace=trace,
    ).execute(create_command())
    assert created.id
    assert registry.reserved_calls == 2
    assert trace == [
        "authorize",
        "preflight",
        "reserved",
        "lease",
        "revalidate",
        "reserved",
        "uow",
    ]


def test_create_rolls_back_when_transactional_event_write_fails() -> None:
    uow = UowFake(fail_audit=True)
    with pytest.raises(RuntimeError, match="event write failed"):
        create_use_case(uow, PreflightFake(observation())).execute(create_command())
    assert uow.rolled_back
    assert not uow.committed


def test_create_rechecks_system_create_role_inside_write_uow() -> None:
    uow = UowFake()
    uow.users.create_allowed = False
    with pytest.raises(LibraryCreateDenied):
        create_use_case(uow, PreflightFake(observation())).execute(create_command())
    assert uow.libraries.current is None
    assert uow.rolled_back


def test_update_guards_empty_patch_revision_frozen_and_removing() -> None:
    current = make_library()
    for command, error in (
        (
            UpdateLibraryCommand("admin", "library-1", 1),
            NoLibraryChanges,
        ),
        (
            UpdateLibraryCommand("admin", "library-1", 99, name="Other"),
            LibraryConfigConflict,
        ),
    ):
        uow = UowFake(library=current, grants=(admin_grant(),))
        with pytest.raises(error):
            update_use_case(uow).execute(command)
        assert not uow.committed

    frozen = UowFake(
        library=make_library(state=LibraryControlState.ACTIVATING),
        grants=(admin_grant(),),
    )
    with pytest.raises(LibraryConfigurationFrozen):
        update_use_case(frozen).execute(
            UpdateLibraryCommand(
                "admin", "library-1", 1, organization_mode=OrganizationMode.VOLUMES
            )
        )

    removing = UowFake(
        library=make_library(state=LibraryControlState.REMOVING),
        grants=(admin_grant(),),
    )
    with pytest.raises(LibraryRemoving):
        update_use_case(removing).execute(
            UpdateLibraryCommand("admin", "library-1", 1, name="Other")
        )


def test_write_policy_downgrade_check_uses_same_uow_and_cas_rolls_back() -> None:
    uow = UowFake(
        library=make_library(write_policy=WritePolicy.READ_WRITE),
        grants=(admin_grant(),),
    )
    updated = update_use_case(uow).execute(
        UpdateLibraryCommand(
            "admin", "library-1", 1, write_policy=WritePolicy.READ_ONLY
        )
    )
    assert uow.write_policy.checked == ["library-1"]
    assert updated.write_policy is WritePolicy.READ_ONLY
    assert uow.committed

    stale = UowFake(library=make_library(), grants=(admin_grant(),))
    stale.libraries.update_allowed = False
    with pytest.raises(LibraryConfigConflict):
        update_use_case(stale).execute(
            UpdateLibraryCommand("admin", "library-1", 1, name="Other")
        )
    assert stale.rolled_back


def test_read_write_enablement_revalidates_registered_root_and_writability() -> None:
    for refreshed, error in (
        (observation(writable=False), RootUnwritable),
        (observation("/srv/replaced"), RootIdentityChanged),
    ):
        uow = UowFake(library=make_library(), grants=(admin_grant(),))
        with pytest.raises(error):
            update_use_case(uow, preflight=PreflightFake(refreshed)).execute(
                UpdateLibraryCommand(
                    "admin",
                    "library-1",
                    1,
                    write_policy=WritePolicy.READ_WRITE,
                )
            )
        assert not uow.committed

    success = UowFake(library=make_library(), grants=(admin_grant(),))
    updated = update_use_case(success).execute(
        UpdateLibraryCommand(
            "admin", "library-1", 1, write_policy=WritePolicy.READ_WRITE
        )
    )
    assert updated.write_policy is WritePolicy.READ_WRITE
    assert success.committed


def test_path_comparison_refreshes_claim_under_overlap_registry_lease() -> None:
    current = make_library()
    uow = UowFake(library=current, grants=(admin_grant(),))
    refreshed = RootObservation(
        canonical_path=current.root.canonical_path,
        root_path_key=current.root.canonical_path,
        components=("srv", "books"),
        filesystem_identity="dev:1",
        writable=True,
    )
    updated = update_use_case(
        uow,
        preflight=PreflightFake(refreshed),
        registry=RootRegistryFake((ReservedRoot(current.id, current.root.claim),)),
    ).execute(
        UpdateLibraryCommand(
            "admin",
            current.id,
            1,
            path_comparison=PathComparison.SENSITIVE,
        )
    )
    assert updated.path_comparison is PathComparison.SENSITIVE
    assert updated.root == refreshed.registered_root


def test_update_orders_filesystem_work_before_writer_uow() -> None:
    trace: list[str] = []
    current = make_library()
    uow = UowFake(library=current, grants=(admin_grant(),), trace=trace)
    refreshed = observation()
    update_use_case(
        uow,
        preflight=PreflightFake(refreshed, trace=trace),
        registry=RootRegistryFake(trace=trace),
        trace=trace,
    ).execute(
        UpdateLibraryCommand(
            "admin",
            current.id,
            1,
            path_comparison=PathComparison.SENSITIVE,
        )
    )
    assert trace == [
        "query",
        "preflight",
        "lease",
        "revalidate",
        "reserved",
        "uow",
    ]


def test_update_rejects_snapshot_root_drift_before_database_cas() -> None:
    current = make_library()
    uow = UowFake(library=current, grants=(admin_grant(),))

    class MutatingQuery:
        def get_manageable(
            self, actor_id: str, library_id: str
        ) -> VisibleLibrary | None:
            moved_root = observation("/srv/moved").registered_root
            uow.libraries.current = replace(current, root=moved_root)
            return VisibleLibrary(current, admin_grant())

    with pytest.raises(LibraryConfigConflict):
        UpdateLibrary(
            unit_of_work_factory=lambda: uow,
            query_port=MutatingQuery(),
            root_preflight=PreflightFake(observation()),
            root_registry=RootRegistryFake(),
            id_generator=Ids(),
            clock=ClockFake(),
        ).execute(UpdateLibraryCommand("admin", current.id, 1, name="Other"))
    assert uow.rolled_back


@pytest.mark.parametrize(
    ("use_case_type", "initial", "expected"),
    (
        (ActivateLibrary, LibraryControlState.DRAFT, LibraryControlState.ACTIVATING),
        (PauseLibrary, LibraryControlState.ACTIVE, LibraryControlState.PAUSED),
        (ResumeLibrary, LibraryControlState.PAUSED, LibraryControlState.ACTIVE),
    ),
)
def test_state_transitions(
    use_case_type: type[ActivateLibrary | PauseLibrary | ResumeLibrary],
    initial: LibraryControlState,
    expected: LibraryControlState,
) -> None:
    uow = UowFake(library=make_library(state=initial), grants=(admin_grant(),))
    updated = use_case_type(
        unit_of_work_factory=lambda: uow, clock=ClockFake()
    ).execute(LibraryStateCommand("admin", "library-1", 1))
    assert updated.control_state is expected
    assert uow.committed


@pytest.mark.parametrize(
    ("use_case_type", "invalid_state"),
    (
        (ActivateLibrary, LibraryControlState.ACTIVE),
        (PauseLibrary, LibraryControlState.DRAFT),
        (ResumeLibrary, LibraryControlState.ACTIVE),
    ),
)
def test_state_transitions_reject_invalid_matrix(
    use_case_type: type[ActivateLibrary | PauseLibrary | ResumeLibrary],
    invalid_state: LibraryControlState,
) -> None:
    uow = UowFake(library=make_library(state=invalid_state), grants=(admin_grant(),))
    with pytest.raises(InvalidLibraryTransition):
        use_case_type(unit_of_work_factory=lambda: uow, clock=ClockFake()).execute(
            LibraryStateCommand("admin", "library-1", 1)
        )
    assert uow.rolled_back


@pytest.mark.parametrize("actor_level", (GrantLevel.READ, GrantLevel.CURATE))
def test_non_admin_cannot_change_or_revoke_grants(actor_level: GrantLevel) -> None:
    actor = member_grant(actor_level, "actor")
    target = member_grant(GrantLevel.READ, "target")
    uow = UowFake(library=make_library(), grants=(actor, target))
    with pytest.raises(LibraryForbidden):
        SetLibraryGrant(
            unit_of_work_factory=lambda: uow,
            scope_epoch_generator=Epochs(),
        ).execute(
            SetLibraryGrantCommand("actor", "library-1", "target", GrantLevel.CURATE)
        )
    with pytest.raises(LibraryForbidden):
        RevokeLibraryGrant(
            unit_of_work_factory=lambda: uow,
            scope_epoch_generator=Epochs(),
        ).execute(RevokeLibraryGrantCommand("actor", "library-1", "target"))


def test_acl_uses_atomic_last_admin_decision_epoch_and_authz_bump() -> None:
    target_admin = admin_grant("target")
    uow = UowFake(library=make_library(), grants=(admin_grant(), target_admin))
    uow.grants.save_allowed = False
    epochs = Epochs()
    with pytest.raises(FinalAdministratorRequired):
        SetLibraryGrant(
            unit_of_work_factory=lambda: uow,
            scope_epoch_generator=epochs,
        ).execute(
            SetLibraryGrantCommand("admin", "library-1", "target", GrantLevel.READ)
        )
    assert epochs.calls == 1
    assert uow.users.bumped == []
    assert uow.rolled_back

    success = UowFake(
        library=make_library(),
        grants=(admin_grant(), member_grant(GrantLevel.READ, "target")),
    )
    success_epochs = Epochs()
    result = SetLibraryGrant(
        unit_of_work_factory=lambda: success,
        scope_epoch_generator=success_epochs,
    ).execute(SetLibraryGrantCommand("admin", "library-1", "target", GrantLevel.CURATE))
    assert isinstance(result, LibraryGrantView)
    assert result.scope_epoch == 101
    assert success.users.bumped == ["target"]
    assert success.audit.events and success.outbox.events


def test_revoke_obeys_atomic_last_admin_and_removing_barrier() -> None:
    final = UowFake(library=make_library(), grants=(admin_grant(),))
    final.grants.delete_allowed = False
    epochs = Epochs()
    with pytest.raises(FinalAdministratorRequired):
        RevokeLibraryGrant(
            unit_of_work_factory=lambda: final,
            scope_epoch_generator=epochs,
        ).execute(RevokeLibraryGrantCommand("admin", "library-1", "admin"))
    assert epochs.calls == 1
    assert final.users.bumped == []

    removing = UowFake(
        library=make_library(state=LibraryControlState.REMOVING),
        grants=(admin_grant(), member_grant(GrantLevel.READ, "target")),
    )
    with pytest.raises(LibraryRemoving):
        RevokeLibraryGrant(
            unit_of_work_factory=lambda: removing,
            scope_epoch_generator=Epochs(),
        ).execute(RevokeLibraryGrantCommand("admin", "library-1", "target"))


def test_replace_ignore_rules_updates_revision_events_and_rolls_back_failures() -> None:
    rule = IgnoreRule.create(kind=IgnoreRuleKind.PATH, pattern="assets/covers")
    uow = UowFake(library=make_library(), grants=(admin_grant(),))
    result = ReplaceLibraryIgnoreRules(
        unit_of_work_factory=lambda: uow, clock=ClockFake()
    ).execute(ReplaceLibraryIgnoreRulesCommand("admin", "library-1", 1, (rule,)))
    assert result == IgnoreRulesResult("library-1", 2, (rule,))
    assert uow.audit.events and uow.outbox.events and uow.committed

    stale = UowFake(library=make_library(), grants=(admin_grant(),))
    stale.libraries.update_allowed = False
    with pytest.raises(LibraryConfigConflict):
        ReplaceLibraryIgnoreRules(
            unit_of_work_factory=lambda: stale, clock=ClockFake()
        ).execute(ReplaceLibraryIgnoreRulesCommand("admin", "library-1", 1, (rule,)))
    assert stale.rolled_back

    failed = UowFake(library=make_library(), grants=(admin_grant(),))
    failed.ignore_rules.fail = True
    with pytest.raises(RuntimeError, match="replace failed"):
        ReplaceLibraryIgnoreRules(
            unit_of_work_factory=lambda: failed, clock=ClockFake()
        ).execute(ReplaceLibraryIgnoreRulesCommand("admin", "library-1", 1, (rule,)))
    assert failed.rolled_back


def test_removing_blocks_grant_and_rule_changes() -> None:
    library = make_library(state=LibraryControlState.REMOVING)
    uow = UowFake(library=library, grants=(admin_grant(),))
    with pytest.raises(LibraryRemoving):
        SetLibraryGrant(
            unit_of_work_factory=lambda: uow,
            scope_epoch_generator=Epochs(),
        ).execute(
            SetLibraryGrantCommand("admin", "library-1", "target", GrantLevel.READ)
        )
    with pytest.raises(LibraryRemoving):
        ReplaceLibraryIgnoreRules(
            unit_of_work_factory=lambda: uow, clock=ClockFake()
        ).execute(ReplaceLibraryIgnoreRulesCommand("admin", "library-1", 1, ()))


class IgnoreQueryFake:
    def __init__(self, result: IgnoreRulesResult) -> None:
        self.result = result
        self.calls = 0

    def get_ignore_rules(
        self, actor_id: str, library_id: str
    ) -> IgnoreRulesResult | None:
        self.calls += 1
        return self.result

    def get_visible(self, actor_id: str, library_id: str) -> VisibleLibrary | None:
        raise AssertionError("must not perform a second query")

    def get_manageable(self, actor_id: str, library_id: str) -> VisibleLibrary | None:
        raise AssertionError("must not perform a second query")

    def list_visible(self, query: LibraryPageQuery):
        raise AssertionError

    def list_grants(self, query: LibraryGrantPageQuery) -> LibraryGrantPage:
        raise AssertionError


def test_ignore_rules_query_returns_revision_and_rules_atomically() -> None:
    rule = IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="cover.jpg")
    expected = IgnoreRulesResult("library-1", 7, (rule,))
    query = IgnoreQueryFake(expected)
    assert (
        GetLibraryIgnoreRules(query).execute(actor_id="admin", library_id="library-1")
        == expected
    )
    assert query.calls == 1
