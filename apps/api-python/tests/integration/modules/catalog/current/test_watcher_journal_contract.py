from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.ports import OutboxEvent
from app.modules.catalog.application.scan_dto import StartFullLibraryScanCommand
from app.modules.catalog.application.scan_lifecycle import StartFullLibraryScan
from app.modules.catalog.application.scan_ports import ScanUowFactory
from app.modules.catalog.application.watcher_dto import (
    RecordWatcherEventCommand,
    WatcherIngestDisposition,
    WatcherIngestResult,
)
from app.modules.catalog.application.watcher_ingestion import RecordWatcherEvent
from app.modules.catalog.application.watcher_ports import WatcherUowFactory
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.scan import ScanConflict
from app.modules.catalog.domain.watcher import (
    FullRescanReason as DomainFullRescanReason,
)
from app.modules.catalog.domain.watcher import (
    WatcherEntryHint,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherTrustLost,
    WatcherTrustLostReason,
    reconcile_scope,
)
from app.modules.catalog.infrastructure.persistence import (
    CatalogLibrary,
    CatalogOutbox,
    FullRescanReason,
    GrantLevel,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibraryReconcileIntent,
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryWatcherState,
    ReconcileIntentPhase,
    ReconcileIntentState,
    ScanStage,
    ScanState,
    SlotState,
    SourceEntryType,
    SqlAlchemyOutboxPort,
    SqlAlchemyScanUowFactory,
    SqlAlchemyWatcherUowFactory,
    UserLibraryGrant,
    WritePolicy,
)

NOW = datetime(2026, 8, 18, 10, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def __init__(self) -> None:
        self._next_value = 0

    def new_id(self) -> str:
        self._next_value += 1
        return f"generated-{self._next_value}"


class _InjectedOutboxFailure(RuntimeError):
    pass


@pytest.fixture
def persistence(
    tmp_path: Path,
) -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    database_path = tmp_path / "watcher-journal-contract.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def _seed_library(
    factory: sessionmaker[Session],
    *,
    latest_sequence: int = 0,
    overflow_through_sequence: int | None = None,
    full_rescan_reason: FullRescanReason | None = None,
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
                    organization_mode=OrganizationMode.FLAT,
                    topology_version=1,
                    path_comparison=PathComparison.SENSITIVE,
                    write_policy=WritePolicy.READ_ONLY,
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
                    level=GrantLevel.ADMIN,
                    scope_epoch=1,
                ),
                LibraryWatcherState(
                    library_id="library",
                    latest_sequence=latest_sequence,
                    overflow_through_sequence=overflow_through_sequence,
                    full_rescan_reason=full_rescan_reason,
                    updated_at=NOW,
                ),
                LibrarySourceEntry(
                    id="root",
                    library_id="library",
                    parent_entry_id=None,
                    local_name="$root",
                    local_name_key="$root",
                    entry_type=SourceEntryType.SYNTHETIC_ROOT,
                    filesystem_identity="dev:root",
                    last_seen_generation=1,
                    absence_confirmed_at=None,
                    children_presence_epoch=0,
                    next_children_presence_epoch=0,
                    observed_parent_presence_epoch=None,
                    pending_observed_parent_presence_epoch=None,
                    layout_state=LayoutState.PRESENT,
                    slot_state=SlotState.ACTIVE,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            )
        )


def _intent_row(
    sequence: int,
    *,
    name: str,
    first_sequence: int | None = None,
    state: ReconcileIntentState = ReconcileIntentState.PENDING,
    lease_expires_at: datetime | None = None,
    topology_writer_fence: int | None = None,
) -> LibraryReconcileIntent:
    running = state is ReconcileIntentState.RUNNING
    scope = reconcile_scope((name,), PathComparison.SENSITIVE)
    return LibraryReconcileIntent(
        id=f"intent-{sequence}",
        library_id="library",
        first_sequence=sequence if first_sequence is None else first_sequence,
        through_sequence=sequence,
        scope1_path=name,
        scope1_key=scope.comparison_key,
        scope2_path=None,
        scope2_key=None,
        coalesce_key=f"{sequence:064x}",
        move_old_path=None,
        move_new_path=None,
        moved_entry_type=None,
        state=state,
        phase=ReconcileIntentPhase.EXECUTE,
        lease_owner="old-worker" if running else None,
        lease_expires_at=lease_expires_at if running else None,
        topology_writer_fence=topology_writer_fence if running else None,
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


def _record_use_case(factory: sessionmaker[Session]) -> RecordWatcherEvent:
    return RecordWatcherEvent(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(factory)
        ),
        id_generator=_Ids(),
        clock=_Clock(),
    )


def _record_path(use_case: RecordWatcherEvent, name: str) -> WatcherIngestResult:
    return use_case.execute(
        RecordWatcherEventCommand(
            library_id="library",
            root_identity="dev:root",
            event=WatcherPathEvent(
                WatcherPathEventKind.MODIFY,
                (name, "book.epub"),
                WatcherEntryHint.FILE,
            ),
        )
    )


def test_journal_accepts_2000_pending_intents_then_fences_at_2001(
    persistence: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = persistence
    _seed_library(factory, latest_sequence=1_999)
    with factory.begin() as session:
        session.add_all(
            _intent_row(sequence, name=f"Work-{sequence:04d}")
            for sequence in range(1, 2_000)
        )
    record = _record_use_case(factory)

    boundary = _record_path(record, "Work-2000")

    assert boundary.sequence == 2_000
    assert boundary.disposition is WatcherIngestDisposition.QUEUED
    with factory() as session:
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 2_000
        state = session.get(LibraryWatcherState, "library")
        assert state is not None and state.overflow_through_sequence is None

    overflow = _record_path(record, "Work-2001")

    assert overflow.sequence == 2_001
    assert overflow.disposition is WatcherIngestDisposition.FULL_SCAN_REQUIRED
    assert overflow.full_rescan_reason is DomainFullRescanReason.JOURNAL_CAPACITY
    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        assert state is not None
        assert state.latest_sequence == 2_001
        assert state.overflow_through_sequence == 2_001
        assert state.full_rescan_reason is FullRescanReason.JOURNAL_CAPACITY
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 0


def test_force_rescan_rolls_back_running_successor_and_fence_together(
    persistence: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = persistence
    _seed_library(factory, latest_sequence=1, topology_writer_fence=2)
    with factory.begin() as session:
        session.add(
            _intent_row(
                1,
                name="Work",
                state=ReconcileIntentState.RUNNING,
                lease_expires_at=NOW + timedelta(minutes=5),
                topology_writer_fence=2,
            )
        )
    record = _record_use_case(factory)

    successor = _record_path(record, "Work")

    assert successor.sequence == 2
    assert successor.disposition is WatcherIngestDisposition.QUEUED
    with monkeypatch.context() as failure:

        def raise_after_transition(
            _outbox: SqlAlchemyOutboxPort, _event: OutboxEvent
        ) -> None:
            raise _InjectedOutboxFailure

        failure.setattr(SqlAlchemyOutboxPort, "append", raise_after_transition)
        with pytest.raises(_InjectedOutboxFailure):
            record.execute(
                RecordWatcherEventCommand(
                    "library",
                    "dev:root",
                    WatcherTrustLost(WatcherTrustLostReason.BACKEND_OVERFLOW),
                )
            )

    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        library = session.get(CatalogLibrary, "library")
        intent_states = tuple(
            session.scalars(
                select(LibraryReconcileIntent.state).order_by(
                    LibraryReconcileIntent.through_sequence
                )
            )
        )
        assert state is not None and state.latest_sequence == 2
        assert state.overflow_through_sequence is None
        assert library is not None and library.topology_writer_fence == 2
        assert intent_states == (
            ReconcileIntentState.RUNNING,
            ReconcileIntentState.PENDING,
        )

    forced = record.execute(
        RecordWatcherEventCommand(
            "library",
            "dev:root",
            WatcherTrustLost(WatcherTrustLostReason.BACKEND_OVERFLOW),
        )
    )

    assert forced.sequence == 3
    assert forced.disposition is WatcherIngestDisposition.FULL_SCAN_REQUIRED
    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        library = session.get(CatalogLibrary, "library")
        assert state is not None and state.overflow_through_sequence == 3
        assert library is not None and library.topology_writer_fence == 3
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 0


def test_existing_rescan_fence_keeps_first_reason_and_one_notification(
    persistence: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = persistence
    _seed_library(factory)
    record = _record_use_case(factory)

    first = record.execute(
        RecordWatcherEventCommand(
            "library",
            "dev:root",
            WatcherTrustLost(WatcherTrustLostReason.DISCONNECTED),
        )
    )
    second = record.execute(
        RecordWatcherEventCommand(
            "library",
            "dev:root",
            WatcherTrustLost(WatcherTrustLostReason.BACKEND_OVERFLOW),
        )
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.full_rescan_reason is DomainFullRescanReason.DISCONNECTED
    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        notification_count = session.scalar(
            select(func.count(CatalogOutbox.id)).where(
                CatalogOutbox.event_type == "LIBRARY_FULL_SCAN_REQUIRED"
            )
        )
        assert state is not None
        assert state.latest_sequence == 2
        assert state.overflow_through_sequence == 2
        assert state.full_rescan_reason is FullRescanReason.DISCONNECTED
        assert notification_count == 1


def test_full_scan_watermark_retains_spanning_row_and_clears_at_latest(
    persistence: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = persistence
    _seed_library(
        factory,
        latest_sequence=3,
        overflow_through_sequence=2,
        full_rescan_reason=FullRescanReason.DISCONNECTED,
    )
    with factory.begin() as session:
        session.add_all(
            (
                _intent_row(1, name="Covered"),
                _intent_row(3, first_sequence=2, name="Spanning"),
                LibraryScanRun(
                    id="scan",
                    library_id="library",
                    generation=2,
                    config_revision=1,
                    mode_snapshot=OrganizationMode.FLAT,
                    root_path_snapshot="/srv/library",
                    path_comparison_snapshot=PathComparison.SENSITIVE,
                    topology_version_snapshot=1,
                    root_identity_snapshot="dev:root",
                    topology_writer_fence=1,
                    watcher_sequence_watermark=2,
                    state=ScanState.FINALIZING,
                    failure_code=None,
                    lease_owner="scan-worker",
                    lease_expires_at=NOW + timedelta(minutes=5),
                    heartbeat_at=NOW,
                    stage=ScanStage.FINALIZE,
                    discovered_count=0,
                    diagnostic_count=0,
                    started_at=NOW,
                    finished_at=None,
                    created_by_user_id=None,
                ),
            )
        )

    with SqlAlchemyScanUowFactory(factory)() as uow:
        first = uow.watcher.finalize_full_scan(
            "library",
            watcher_sequence_watermark=2,
            completed_at=NOW + timedelta(seconds=1),
        )
        uow.commit()

    assert first.discarded_intent_count == 1
    assert first.state.full_rescan_reason is DomainFullRescanReason.DISCONNECTED
    with factory() as session:
        assert tuple(session.scalars(select(LibraryReconcileIntent.id))) == (
            "intent-3",
        )

    with factory.begin() as session:
        session.execute(
            update(LibraryScanRun)
            .where(LibraryScanRun.id == "scan")
            .values(watcher_sequence_watermark=3)
        )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        exact = uow.watcher.finalize_full_scan(
            "library",
            watcher_sequence_watermark=3,
            completed_at=NOW + timedelta(seconds=2),
        )
        uow.commit()

    assert exact.discarded_intent_count == 1
    assert exact.state.overflow_through_sequence is None
    assert exact.state.full_rescan_reason is None
    with factory() as session:
        assert session.scalar(select(func.count(LibraryReconcileIntent.id))) == 0


def test_scan_start_conflicts_with_live_snapshot_but_cleans_invalidated_writer(
    persistence: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = persistence
    _seed_library(factory, latest_sequence=1, topology_writer_fence=2)
    with factory.begin() as session:
        session.add(
            _intent_row(
                1,
                name="Work",
                state=ReconcileIntentState.RUNNING,
                lease_expires_at=NOW + timedelta(minutes=5),
                topology_writer_fence=2,
            )
        )
    start = StartFullLibraryScan(
        unit_of_work_factory=cast(ScanUowFactory, SqlAlchemyScanUowFactory(factory)),
        id_generator=_Ids(),
        clock=_Clock(),
    )
    command = StartFullLibraryScanCommand(
        actor_id="admin",
        library_id="library",
        owner_token="scan-worker",
    )

    with pytest.raises(ScanConflict):
        start.execute(command)

    with factory() as session:
        running = session.scalar(select(LibraryReconcileIntent))
        assert running is not None and running.state is ReconcileIntentState.RUNNING
        assert session.scalar(select(LibraryScanRun.id)) is None

    with factory.begin() as session:
        session.execute(
            update(CatalogLibrary)
            .where(CatalogLibrary.id == "library")
            .values(config_revision=2)
        )

    run = start.execute(command)

    assert run.watcher_sequence_watermark == 1
    assert run.config_revision == 2
    assert run.state.value == "PENDING"
    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        assert state is not None
        assert state.overflow_through_sequence == 1
        assert state.full_rescan_reason is FullRescanReason.UNTRUSTED
        assert session.scalar(select(LibraryReconcileIntent.id)) is None
        assert session.scalar(select(func.count(LibraryScanRun.id))) == 1
