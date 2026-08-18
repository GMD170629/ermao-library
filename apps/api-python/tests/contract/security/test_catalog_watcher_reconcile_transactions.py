from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.ports import OutboxEvent
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryObservation,
    TargetedPathAbsent,
    TargetedPathObservation,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryDiscoveryPort,
    ScanUowFactory,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceAdmissionPort,
    SourceStatExpectation,
)
from app.modules.catalog.application.watcher_ports import WatcherUowFactory
from app.modules.catalog.infrastructure.persistence import (
    CatalogLibrary,
    CatalogOutbox,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibraryReconcileIntent,
    LibraryScanRun,
    LibraryScanWorkItem,
    LibrarySourceEntry,
    LibraryWatcherState,
    LibraryWork,
    SlotState,
    SourceEntryType,
    SqlAlchemyOutboxPort,
    SqlAlchemyScanUowFactory,
    SqlAlchemyWatcherUowFactory,
    TopologyUnit,
    TopologyUnitRevision,
    UserLibraryGrant,
)
from app.modules.catalog.infrastructure.persistence import (
    FullRescanReason as StoredFullRescanReason,
)
from app.modules.catalog.infrastructure.persistence import (
    GrantLevel as StoredGrantLevel,
)
from app.modules.catalog.infrastructure.persistence import (
    ReconcileIntentPhase as StoredReconcileIntentPhase,
)
from app.modules.catalog.infrastructure.persistence import (
    ReconcileIntentState as StoredReconcileIntentState,
)
from app.modules.catalog.infrastructure.persistence import (
    RevisionState as StoredRevisionState,
)
from app.modules.catalog.infrastructure.persistence import (
    ScanState as StoredScanState,
)
from app.modules.catalog.infrastructure.persistence import (
    TopologyUnitKind as StoredTopologyUnitKind,
)
from app.modules.catalog.infrastructure.persistence import (
    WritePolicy as StoredWritePolicy,
)
from app.modules.catalog.public import (
    BoundTopologyStageBatch,
    CancelFullLibraryScan,
    CancelFullLibraryScanCommand,
    FailFullLibraryScan,
    FailFullLibraryScanCommand,
    OrganizationMode,
    PathComparison,
    PendingSourceObservation,
    ReconcileRunDisposition,
    ReconcileStale,
    RecordWatcherEvent,
    RecordWatcherEventCommand,
    RunNextReconcileSubtree,
    RunNextReconcileSubtreeCommand,
    ScanFailureCode,
    SourceObservation,
    StartFullLibraryScan,
    StartFullLibraryScanCommand,
    TopologyUnitPlan,
    WatcherEntryHint,
    WatcherEvent,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherTrustLost,
    WatcherTrustLostReason,
    WorkProjectionPlan,
    reconcile_scope,
)
from app.modules.catalog.public import (
    TopologyUnitKind as DomainTopologyUnitKind,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _MonotonicClock:
    def seconds(self) -> float:
        return 0.0


class _Ids:
    def __init__(self) -> None:
        self._next_value = 0

    def new_id(self) -> str:
        self._next_value += 1
        return f"generated-{self._next_value}"


class _DirectorySession:
    def __init__(
        self,
        *,
        observed: dict[tuple[str, ...], TargetedPathObservation],
        children: dict[tuple[str, ...], tuple[DiscoveryObservation, ...]],
    ) -> None:
        self.root_identity = "dev:root"
        self._observed = observed
        self._children = children

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return False

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]:
        return iter(self._children.get(relative_directory, ()))

    def observe_path(self, relative_path: tuple[str, ...]) -> TargetedPathObservation:
        return self._observed[relative_path]

    def revalidate_root_identity(self) -> str:
        return self.root_identity


class _DirectoryDiscovery:
    def __init__(
        self,
        *,
        observed: dict[tuple[str, ...], TargetedPathObservation],
        children: dict[tuple[str, ...], tuple[DiscoveryObservation, ...]] | None = None,
    ) -> None:
        self._observed = observed
        self._children = children or {}

    def open(self, *, canonical_root: str) -> _DirectorySession:
        assert canonical_root == "/srv/library"
        return _DirectorySession(observed=self._observed, children=self._children)


class _ForbiddenAdmission:
    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None,
    ) -> object:
        del canonical_root, relative_path, expected_stat
        raise AssertionError("directory-only reconcile must not probe file bytes")


@pytest.fixture
def persistence(
    tmp_path: Path,
) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "watcher-reconcile-contract.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine, clock=lambda: NOW)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _seed_library(
    factory: sessionmaker[Session],
    *,
    mode: OrganizationMode = OrganizationMode.FLAT,
    comparison: PathComparison = PathComparison.SENSITIVE,
    latest_sequence: int = 0,
    topology_writer_fence: int = 1,
) -> None:
    with factory.begin() as session:
        session.add_all(
            (
                CurrentUser(id="admin", display_name="Admin", role="admin"),
                CatalogLibrary(
                    id="library",
                    name="Library",
                    root_path="/srv/library",
                    root_path_key="/srv/library",
                    organization_mode=mode,
                    topology_version=1,
                    path_comparison=comparison,
                    write_policy=StoredWritePolicy.READ_ONLY,
                    control_state=LibraryControlState.ACTIVE,
                    observed_health=LibraryHealth.HEALTHY,
                    config_revision=1,
                    topology_writer_fence=topology_writer_fence,
                    next_scan_generation=2,
                    last_successful_generation=1,
                ),
                UserLibraryGrant(
                    user_id="admin",
                    library_id="library",
                    level=StoredGrantLevel.ADMIN,
                    scope_epoch=1,
                ),
                LibraryWatcherState(
                    library_id="library",
                    latest_sequence=latest_sequence,
                    overflow_through_sequence=None,
                    full_rescan_reason=None,
                    updated_at=NOW,
                ),
                _source_row(
                    source_id="root",
                    parent_id=None,
                    local_name="$root",
                    local_name_key="$root",
                    entry_type=SourceEntryType.SYNTHETIC_ROOT,
                    identity="dev:root",
                    observed_parent_epoch=None,
                ),
            )
        )


def _source_row(
    *,
    source_id: str,
    parent_id: str | None,
    local_name: str,
    local_name_key: str,
    entry_type: SourceEntryType,
    identity: str,
    observed_parent_epoch: int | None,
) -> LibrarySourceEntry:
    return LibrarySourceEntry(
        id=source_id,
        library_id="library",
        parent_entry_id=parent_id,
        local_name=local_name,
        local_name_key=local_name_key,
        entry_type=entry_type,
        filesystem_identity=identity,
        last_seen_generation=1,
        absence_confirmed_at=None,
        children_presence_epoch=0,
        next_children_presence_epoch=0,
        observed_parent_presence_epoch=observed_parent_epoch,
        pending_observed_parent_presence_epoch=None,
        layout_state=LayoutState.PRESENT,
        slot_state=SlotState.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def _intent_row(
    *,
    intent_id: str,
    first_sequence: int,
    through_sequence: int,
    scope_name: str,
    state: StoredReconcileIntentState,
    topology_writer_fence: int | None,
    running_lease_expires_at: datetime = NOW + timedelta(minutes=5),
) -> LibraryReconcileIntent:
    scope = reconcile_scope((scope_name,), PathComparison.SENSITIVE)
    running = state is StoredReconcileIntentState.RUNNING
    return LibraryReconcileIntent(
        id=intent_id,
        library_id="library",
        first_sequence=first_sequence,
        through_sequence=through_sequence,
        scope1_path=scope_name,
        scope1_key=scope.comparison_key,
        scope2_path=None,
        scope2_key=None,
        coalesce_key=f"{first_sequence:064x}",
        move_old_path=None,
        move_new_path=None,
        moved_entry_type=None,
        state=state,
        phase=StoredReconcileIntentPhase.EXECUTE,
        lease_owner="old-worker" if running else None,
        lease_expires_at=running_lease_expires_at if running else None,
        topology_writer_fence=topology_writer_fence,
        attempt=1 if running else 0,
        available_at=NOW,
        fold_after_source_entry_id=None,
        config_revision=1,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_path_snapshot="/srv/library",
        root_identity_snapshot="dev:root",
        created_at=NOW,
        updated_at=NOW,
    )


def _record(factory: sessionmaker[Session], event: WatcherEvent) -> None:
    RecordWatcherEvent(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(factory)
        ),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(
        RecordWatcherEventCommand(
            library_id="library",
            root_identity="dev:root",
            event=event,
        )
    )


def _directory(path: tuple[str, ...], identity: str) -> DiscoveredSource:
    return DiscoveredSource(path, DiscoveryEntryType.DIRECTORY, identity, None)


def _pending_directory(
    path: tuple[str, ...], *, identity: str, parent_epoch: int | None
) -> PendingSourceObservation:
    return PendingSourceObservation(
        SourceObservation(_directory(path, identity), generation=1, admission=None),
        pending_parent_epoch=parent_epoch,
    )


@pytest.mark.parametrize("nested", [False, True], ids=["top-level", "nested"])
def test_directory_collision_transitions_to_full_scan_without_stranding_running(
    persistence: sessionmaker[Session],
    nested: bool,
) -> None:
    _seed_library(
        persistence,
        mode=OrganizationMode.VOLUMES,
        comparison=PathComparison.INSENSITIVE,
    )
    observed: dict[tuple[str, ...], TargetedPathObservation]
    children: dict[tuple[str, ...], tuple[DiscoveryObservation, ...]]
    event_path: tuple[str, ...]
    if nested:
        with persistence.begin() as session:
            session.add_all(
                (
                    _source_row(
                        source_id="work",
                        parent_id="root",
                        local_name="Work",
                        local_name_key="work",
                        entry_type=SourceEntryType.DIRECTORY,
                        identity="dev:work",
                        observed_parent_epoch=0,
                    ),
                    _source_row(
                        source_id="lower-version",
                        parent_id="work",
                        local_name="version",
                        local_name_key="version",
                        entry_type=SourceEntryType.DIRECTORY,
                        identity="dev:lower-version",
                        observed_parent_epoch=0,
                    ),
                )
            )
        observed = {("Work",): _directory(("Work",), "dev:work")}
        children = {("Work",): (_directory(("Work", "Version"), "dev:upper-version"),)}
        event_path = ("Work", "Version")
    else:
        with persistence.begin() as session:
            session.add(
                _source_row(
                    source_id="lower-shelf",
                    parent_id="root",
                    local_name="shelf",
                    local_name_key="shelf",
                    entry_type=SourceEntryType.DIRECTORY,
                    identity="dev:lower-shelf",
                    observed_parent_epoch=0,
                )
            )
        observed = {("Shelf",): _directory(("Shelf",), "dev:upper-shelf")}
        children = {}
        event_path = ("Shelf",)

    _record(
        persistence,
        WatcherPathEvent(
            WatcherPathEventKind.MODIFY,
            event_path,
            WatcherEntryHint.DIRECTORY,
        ),
    )
    result = RunNextReconcileSubtree(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence)
        ),
        discovery=cast(
            DirectoryDiscoveryPort,
            _DirectoryDiscovery(observed=observed, children=children),
        ),
        admission=cast(SourceAdmissionPort, _ForbiddenAdmission()),
        clock=_Clock(),
        monotonic_clock=_MonotonicClock(),
    ).execute(RunNextReconcileSubtreeCommand("library", "worker"))

    assert result.disposition is ReconcileRunDisposition.FULL_SCAN_REQUIRED
    with persistence() as session:
        watcher = session.get(LibraryWatcherState, "library")
        assert watcher is not None
        assert watcher.full_rescan_reason is StoredFullRescanReason.COLLISION_RECHECK
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 0


def test_successor_detection_uses_through_sequence_after_cross_scope_merge(
    persistence: sessionmaker[Session],
) -> None:
    _seed_library(persistence, latest_sequence=10, topology_writer_fence=2)
    with persistence.begin() as session:
        session.add_all(
            (
                _intent_row(
                    intent_id="running",
                    first_sequence=1,
                    through_sequence=10,
                    scope_name="A",
                    state=StoredReconcileIntentState.RUNNING,
                    topology_writer_fence=2,
                ),
                _intent_row(
                    intent_id="pending",
                    first_sequence=5,
                    through_sequence=9,
                    scope_name="B",
                    state=StoredReconcileIntentState.PENDING,
                    topology_writer_fence=None,
                ),
            )
        )

    _record(
        persistence,
        WatcherMoveEvent(
            ("A", "book.epub"),
            ("B", "book.epub"),
            WatcherMovedEntryType.FILE,
        ),
    )

    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        running = uow.watcher.get_running_for_update("library")
        successor = uow.watcher.get_next_pending_for_update("library", now=NOW)
        assert running is not None and successor is not None
        assert successor.first_sequence == 5
        assert successor.through_sequence == 11
        assert uow.watcher.has_overlapping_successor(
            running.fence(presence_generation=1), running.scopes
        )


def test_expired_execute_takeover_abandons_partial_staging_before_absent_scope(
    persistence: sessionmaker[Session],
) -> None:
    _seed_library(persistence, latest_sequence=1, topology_writer_fence=2)
    with persistence.begin() as session:
        session.add(
            _intent_row(
                intent_id="crashed-intent",
                first_sequence=1,
                through_sequence=1,
                scope_name="Shelf",
                state=StoredReconcileIntentState.RUNNING,
                topology_writer_fence=2,
                running_lease_expires_at=NOW - timedelta(seconds=1),
            )
        )
        session.add(LibraryWork(id="partial-work", library_id="library"))
        session.add(
            TopologyUnit(
                id="partial-unit",
                library_id="library",
                unit_kind=StoredTopologyUnitKind.WORK_CONTAINER,
                work_owner_id="partial-work",
                version_owner_id=None,
                volume_owner_id=None,
                active_revision_id=None,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            TopologyUnitRevision(
                id="partial-revision",
                library_id="library",
                unit_id="partial-unit",
                scan_run_id=None,
                reconcile_origin_id="crashed-intent",
                unit_root_entry_id="root",
                revision=1,
                state=StoredRevisionState.STAGING,
                created_at=NOW,
            )
        )

    result = RunNextReconcileSubtree(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence)
        ),
        discovery=cast(
            DirectoryDiscoveryPort,
            _DirectoryDiscovery(
                observed={("Shelf",): TargetedPathAbsent(relative_path=("Shelf",))}
            ),
        ),
        admission=cast(SourceAdmissionPort, _ForbiddenAdmission()),
        clock=_Clock(),
        monotonic_clock=_MonotonicClock(),
    ).execute(RunNextReconcileSubtreeCommand("library", "takeover-worker"))

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    with persistence() as session:
        revision = session.get(TopologyUnitRevision, "partial-revision")
        assert revision is not None
        assert revision.state is StoredRevisionState.ABANDONED
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 0
        assert (
            session.scalar(
                select(func.count(TopologyUnitRevision.id)).where(
                    TopologyUnitRevision.reconcile_origin_id == "crashed-intent",
                    TopologyUnitRevision.state == StoredRevisionState.STAGING,
                )
            )
            == 0
        )


def test_current_pending_ancestor_proof_can_activate_but_old_or_missing_proof_cannot(
    persistence: sessionmaker[Session],
) -> None:
    _seed_library(persistence, latest_sequence=1, topology_writer_fence=2)
    with persistence.begin() as session:
        session.add(
            _intent_row(
                intent_id="pending-proof",
                first_sequence=1,
                through_sequence=1,
                scope_name="Shelf",
                state=StoredReconcileIntentState.RUNNING,
                topology_writer_fence=2,
            )
        )
    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        running = uow.watcher.get_running_for_update("library")
        assert running is not None
        fence = running.fence(presence_generation=1)
        shelf = uow.sources.upsert_reconcile_observations(
            fence,
            (_pending_directory(("Shelf",), identity="dev:shelf", parent_epoch=None),),
            observed_at=NOW,
        ).bindings[0]
        uow.commit()
    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        shelf_epoch = uow.sources.begin_directory_presence(
            fence, shelf, observed_at=NOW
        )
        uow.commit()
    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        child = uow.sources.upsert_reconcile_observations(
            fence,
            (
                _pending_directory(
                    ("Shelf", "Child"),
                    identity="dev:child",
                    parent_epoch=shelf_epoch.proposed_epoch,
                ),
            ),
            observed_at=NOW,
        ).bindings[0]
        uow.commit()

    plan = TopologyUnitPlan(
        unit_key="WORK_CONTAINER:transport-only",
        unit_kind=DomainTopologyUnitKind.WORK_CONTAINER,
        owner_path=("Shelf", "Child"),
        unit_root_path=("Shelf", "Child"),
        rows=(
            WorkProjectionPlan(
                root_path=("Shelf", "Child"),
                structure_key="domain-path-key-is-not-persisted",
                source_name="Child",
                sort_key="child",
            ),
        ),
    )
    with persistence() as session:
        shelf_row = session.get(LibrarySourceEntry, shelf.source_entry_id)
        child_row = session.get(LibrarySourceEntry, child.source_entry_id)
        assert shelf_row is not None and child_row is not None
        assert shelf_row.children_presence_epoch == 0
        assert shelf_row.next_children_presence_epoch == 1
        assert child_row.observed_parent_presence_epoch is None
        assert child_row.pending_observed_parent_presence_epoch == 1

    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        bound = uow.topology.bind_plan(fence, plan, (shelf, child))
        assert bound is not None
        assert (
            uow.topology.bind_plan(
                fence,
                plan,
                (shelf, replace(child, pending_parent_presence_epoch=None)),
            )
            is None
        )
        staging = uow.topology.begin_staging(
            fence,
            bound,
            expected_active_revision_id=None,
            created_at=NOW,
        )
        assert staging is not None
        staging = uow.topology.append_staging_batch(
            fence,
            staging,
            BoundTopologyStageBatch(
                first_row=0,
                rows=plan.rows,
                bindings=bound.projections,
                complete=True,
            ),
            staged_at=NOW,
        )
        assert uow.topology.activate_staging_group(fence, (staging,), activated_at=NOW)
        uow.commit()

    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        newer = uow.sources.begin_directory_presence(fence, shelf, observed_at=NOW)
        assert newer.proposed_epoch == 2
        uow.commit()
    with cast(WatcherUowFactory, SqlAlchemyWatcherUowFactory(persistence))() as uow:
        assert uow.topology.bind_plan(fence, plan, (shelf, child)) is None
        with pytest.raises(ReconcileStale):
            uow.sources.begin_directory_presence(fence, child, observed_at=NOW)


def _start_scan(factory: sessionmaker[Session]) -> LibraryScanRun:
    result = StartFullLibraryScan(
        unit_of_work_factory=cast(ScanUowFactory, SqlAlchemyScanUowFactory(factory)),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(StartFullLibraryScanCommand("admin", "library", "scan-worker"))
    with factory() as session:
        row = session.get(LibraryScanRun, result.scan_id)
        assert row is not None
        session.expunge(row)
        return row


def _mark_existing_wake_delivered(
    factory: sessionmaker[Session], event_type: str
) -> None:
    with factory.begin() as session:
        rows = tuple(
            session.scalars(
                select(CatalogOutbox).where(CatalogOutbox.event_type == event_type)
            )
        )
        assert len(rows) == 1
        rows[0].delivered_at = NOW


def test_failed_scan_reemits_consumed_targeted_wakeup(
    persistence: sessionmaker[Session],
) -> None:
    _seed_library(persistence)
    run = _start_scan(persistence)
    _record(
        persistence,
        WatcherPathEvent(
            WatcherPathEventKind.MODIFY,
            ("Book", "book.epub"),
            WatcherEntryHint.FILE,
        ),
    )
    _mark_existing_wake_delivered(persistence, "LIBRARY_RECONCILE_AVAILABLE")

    FailFullLibraryScan(
        unit_of_work_factory=cast(
            ScanUowFactory, SqlAlchemyScanUowFactory(persistence)
        ),
        clock=_Clock(),
    ).execute(
        FailFullLibraryScanCommand(
            "library", run.id, "scan-worker", ScanFailureCode.IO_ERROR
        )
    )

    with persistence() as session:
        stored_run = session.get(LibraryScanRun, run.id)
        wakeups = tuple(
            session.scalars(
                select(CatalogOutbox)
                .where(CatalogOutbox.event_type == "LIBRARY_RECONCILE_AVAILABLE")
                .order_by(CatalogOutbox.created_at, CatalogOutbox.id)
            )
        )
        assert stored_run is not None and stored_run.state is StoredScanState.FAILED
        assert len(wakeups) == 2
        assert sum(value.delivered_at is None for value in wakeups) == 1
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 1


def test_cancelled_scan_reemits_consumed_full_scan_wakeup(
    persistence: sessionmaker[Session],
) -> None:
    _seed_library(persistence)
    run = _start_scan(persistence)
    _record(
        persistence,
        WatcherTrustLost(WatcherTrustLostReason.BACKEND_OVERFLOW),
    )
    _mark_existing_wake_delivered(persistence, "LIBRARY_FULL_SCAN_REQUIRED")

    CancelFullLibraryScan(
        unit_of_work_factory=cast(
            ScanUowFactory, SqlAlchemyScanUowFactory(persistence)
        ),
        clock=_Clock(),
    ).execute(CancelFullLibraryScanCommand("admin", "library", run.id))

    with persistence() as session:
        stored_run = session.get(LibraryScanRun, run.id)
        wakeups = tuple(
            session.scalars(
                select(CatalogOutbox).where(
                    CatalogOutbox.event_type == "LIBRARY_FULL_SCAN_REQUIRED"
                )
            )
        )
        assert stored_run is not None and stored_run.state is StoredScanState.CANCELLED
        assert len(wakeups) == 2
        assert sum(value.delivered_at is None for value in wakeups) == 1


def test_terminal_wakeup_outbox_failure_rolls_back_scan_and_journal(
    persistence: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_library(persistence)
    run = _start_scan(persistence)
    _record(
        persistence,
        WatcherPathEvent(
            WatcherPathEventKind.MODIFY,
            ("Book", "book.epub"),
            WatcherEntryHint.FILE,
        ),
    )
    _mark_existing_wake_delivered(persistence, "LIBRARY_RECONCILE_AVAILABLE")
    original_append = SqlAlchemyOutboxPort.append

    def fail_follow_up(outbox: SqlAlchemyOutboxPort, event: OutboxEvent) -> None:
        if event.event_type == "LIBRARY_RECONCILE_AVAILABLE":
            raise RuntimeError("injected outbox failure")
        original_append(outbox, event)

    monkeypatch.setattr(SqlAlchemyOutboxPort, "append", fail_follow_up)
    with pytest.raises(RuntimeError, match="injected outbox failure"):
        FailFullLibraryScan(
            unit_of_work_factory=cast(
                ScanUowFactory, SqlAlchemyScanUowFactory(persistence)
            ),
            clock=_Clock(),
        ).execute(
            FailFullLibraryScanCommand(
                "library", run.id, "scan-worker", ScanFailureCode.IO_ERROR
            )
        )

    with persistence() as session:
        stored_run = session.get(LibraryScanRun, run.id)
        watcher = session.get(LibraryWatcherState, "library")
        assert stored_run is not None and stored_run.state is StoredScanState.PENDING
        assert watcher is not None and watcher.latest_sequence == 1
        assert watcher.full_rescan_reason is None
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 1
        assert session.scalar(select(func.count(LibraryScanWorkItem.id))) == 1
        assert (
            session.scalar(
                select(func.count(CatalogOutbox.id)).where(
                    CatalogOutbox.event_type == "LIBRARY_FULL_SCAN_FAILED"
                )
            )
            == 0
        )
