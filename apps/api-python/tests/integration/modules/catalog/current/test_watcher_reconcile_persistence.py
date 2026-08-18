from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser  # noqa: F401
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    SourceObservation,
    TargetedPathAbsent,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)
from app.modules.catalog.application.watcher_dto import (
    BoundTopologyStageBatch,
    PendingSourceObservation,
    ProvenMoveEvidence,
    ReconcileFence,
    ReconcileIntent,
    ReconcileIntentPhase,
    ReconcileIntentState,
    SourceRebindRejectionReason,
    required_topology_source_paths,
)
from app.modules.catalog.domain.admission import (
    DirectFileEvidence,
    SourceAdmissionEvidence,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    SourceKind,
)
from app.modules.catalog.domain.scan import (
    AssetMembershipPlan,
    ReadingMorphology,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
)
from app.modules.catalog.domain.scan import (
    AssetRole as DomainAssetRole,
)
from app.modules.catalog.domain.scan import (
    TopologyUnitKind as DomainTopologyUnitKind,
)
from app.modules.catalog.domain.scan import (
    VersionKind as DomainVersionKind,
)
from app.modules.catalog.domain.watcher import (
    FullRescanReason,
    ReconcileConflict,
    ReconcileScope,
    ReconcileStale,
    WatcherMovedEntryType,
)
from app.modules.catalog.infrastructure.persistence import (
    CatalogLibrary,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibraryReconcileIntent,
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryWatcherState,
    LibraryWork,
    RevisionState,
    ScanStage,
    ScanState,
    SlotState,
    SourceEntryType,
    SqlAlchemyScanUowFactory,
    SqlAlchemyWatcherUowFactory,
    TopologyUnit,
    TopologyUnitKind,
    TopologyUnitRevision,
    WritePolicy,
)


class _SqliteBusyError(Exception):
    sqlite_errorcode = 5


class _CleanupTrackingSession(Session):
    rollback_called = False
    close_called = False

    def rollback(self) -> None:
        _CleanupTrackingSession.rollback_called = True
        super().rollback()

    def close(self) -> None:
        _CleanupTrackingSession.close_called = True
        super().close()


def _raise_busy(
    _connection: object,
    _cursor: object,
    _statement: str,
    _parameters: object,
    _context: object,
    _executemany: bool,
) -> NoReturn:
    raise OperationalError(None, None, _SqliteBusyError("database is locked"))


@pytest.fixture
def persistence(tmp_path: Path):
    database_path = tmp_path / "watcher-reconcile.sqlite3"
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
    control_state: LibraryControlState = LibraryControlState.ACTIVE,
    last_successful_generation: int | None = 1,
) -> None:
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add_all(
            (
                CatalogLibrary(
                    id="library",
                    name="Library",
                    root_path="/srv/library",
                    root_path_key="/srv/library",
                    organization_mode=OrganizationMode.FLAT,
                    topology_version=1,
                    path_comparison=PathComparison.SENSITIVE,
                    write_policy=WritePolicy.READ_ONLY,
                    control_state=control_state,
                    observed_health=LibraryHealth.HEALTHY,
                    config_revision=1,
                    topology_writer_fence=1,
                    next_scan_generation=2,
                    last_successful_generation=last_successful_generation,
                ),
                LibraryWatcherState(
                    library_id="library",
                    latest_sequence=0,
                    overflow_through_sequence=None,
                    full_rescan_reason=None,
                    updated_at=now,
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
                    created_at=now,
                    updated_at=now,
                ),
            )
        )


def _pending_intent(now: datetime, *, intent_id: str = "intent") -> ReconcileIntent:
    return ReconcileIntent(
        intent_id=intent_id,
        library_id="library",
        first_sequence=1,
        through_sequence=1,
        scopes=(ReconcileScope(("Shelf",), "5:7368656c66"),),
        move_evidence=None,
        state=ReconcileIntentState.PENDING,
        phase=ReconcileIntentPhase.EXECUTE,
        lease_owner=None,
        lease_expires_at=None,
        topology_writer_fence=None,
        attempt=0,
        available_at=now,
        fold_after_source_entry_id=None,
        config_revision=1,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_path_snapshot="/srv/library",
        root_identity_snapshot="dev:root",
        created_at=now,
        updated_at=now,
    )


def _queue_and_claim(factory: sessionmaker[Session], now: datetime) -> ReconcileIntent:
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        pending = _pending_intent(now)
        assert (
            uow.watcher.append_or_replace(
                expected_latest_sequence=0,
                intent=pending,
                replaced_intent_ids=(),
            )
            is not None
        )
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None
        writer_fence = uow.libraries.reserve_reconcile_writer(
            "library", expected_topology_writer_fence=1
        )
        assert writer_fence == 2
        claimed = uow.watcher.claim(
            pending,
            current,
            owner_token="worker-a",
            topology_writer_fence=writer_fence,
            now=now,
            lease_expires_at=now + timedelta(seconds=10),
        )
        assert claimed is not None
        uow.commit()
        return claimed


def _fence(intent: ReconcileIntent, *, presence_generation: int = 1) -> ReconcileFence:
    assert intent.lease_owner is not None
    assert intent.topology_writer_fence is not None
    return ReconcileFence(
        library_id=intent.library_id,
        intent_id=intent.intent_id,
        through_sequence=intent.through_sequence,
        config_revision=intent.config_revision,
        organization_mode=intent.organization_mode,
        topology_version=intent.topology_version,
        path_comparison=intent.path_comparison,
        root_path_snapshot=intent.root_path_snapshot,
        root_identity=intent.root_identity_snapshot,
        topology_writer_fence=intent.topology_writer_fence,
        lease_owner=intent.lease_owner,
        presence_generation=presence_generation,
    )


def _pending_directory(
    path: tuple[str, ...],
    *,
    identity: str,
    parent_epoch: int | None,
) -> PendingSourceObservation:
    return PendingSourceObservation(
        SourceObservation(
            DiscoveredSource(
                relative_path=path,
                entry_type=DiscoveryEntryType.DIRECTORY,
                filesystem_identity=identity,
                expected_stat=None,
            ),
            generation=1,
            admission=None,
        ),
        pending_parent_epoch=parent_epoch,
    )


def _pending_pdf(
    path: tuple[str, ...],
    *,
    identity: str,
    parent_epoch: int,
) -> PendingSourceObservation:
    expectation = SourceStatExpectation(1, 1, 128, 1)
    admission = SourceAdmissionEvidence(
        path,
        EntryType.FILE,
        AdmissionKind.PRIMARY,
        source_format=SourceFormat.PDF,
        evidence=DirectFileEvidence(SourceFormat.PDF, 4, 64),
    )
    return PendingSourceObservation(
        SourceObservation(
            DiscoveredSource(
                relative_path=path,
                entry_type=DiscoveryEntryType.FILE,
                filesystem_identity=identity,
                expected_stat=expectation,
            ),
            generation=1,
            admission=admission,
        ),
        pending_parent_epoch=parent_epoch,
    )


def _layered_plans(work_name: str) -> tuple[TopologyUnitPlan, ...]:
    work_path = (work_name,)
    version_path = (*work_path, "Edition")
    volume_path = (*version_path, "book.pdf")
    return (
        TopologyUnitPlan(
            unit_key=f"WORK_CONTAINER:{work_name}",
            unit_kind=DomainTopologyUnitKind.WORK_CONTAINER,
            owner_path=work_path,
            unit_root_path=work_path,
            rows=(WorkProjectionPlan(work_path, "domain-work", work_name, work_name),),
        ),
        TopologyUnitPlan(
            unit_key=f"VERSION_CONTAINER:{work_name}",
            unit_kind=DomainTopologyUnitKind.VERSION_CONTAINER,
            owner_path=version_path,
            unit_root_path=version_path,
            rows=(
                VersionProjectionPlan(
                    work_path,
                    version_path,
                    DomainVersionKind.DIRECTORY,
                    "domain-version",
                    "Edition",
                    "edition",
                ),
            ),
        ),
        TopologyUnitPlan(
            unit_key=f"SINGLE_FILE_VOLUME:{work_name}",
            unit_kind=DomainTopologyUnitKind.SINGLE_FILE_VOLUME,
            owner_path=volume_path,
            unit_root_path=volume_path,
            rows=(
                VolumeProjectionPlan(
                    work_path,
                    version_path,
                    volume_path,
                    SourceKind.SINGLE_FILE,
                    ReadingMorphology.PDF,
                    "domain-volume",
                    "book.pdf",
                    "book",
                ),
                AssetMembershipPlan(
                    volume_path,
                    volume_path,
                    SourceFormat.PDF,
                    DomainAssetRole.PRIMARY,
                    0,
                    0,
                ),
            ),
        ),
    )


def test_watcher_uow_rolls_back_and_busy_enter_preserves_cause(persistence) -> None:
    engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert (
            uow.watcher.append_or_replace(
                expected_latest_sequence=0,
                intent=_pending_intent(now),
                replaced_intent_ids=(),
            )
            is not None
        )

    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        assert state is not None and state.latest_sequence == 0
        assert session.scalar(select(LibraryReconcileIntent.id)) is None

    tracking_factory = sessionmaker(
        engine,
        class_=_CleanupTrackingSession,
        expire_on_commit=False,
    )
    _CleanupTrackingSession.rollback_called = False
    _CleanupTrackingSession.close_called = False
    event.listen(engine, "before_cursor_execute", _raise_busy)
    try:
        with (
            pytest.raises(ReconcileConflict) as raised,
            SqlAlchemyWatcherUowFactory(tracking_factory)(),
        ):
            pass
    finally:
        event.remove(engine, "before_cursor_execute", _raise_busy)
    assert isinstance(raised.value.__cause__, OperationalError)
    assert _CleanupTrackingSession.rollback_called
    assert _CleanupTrackingSession.close_called


def test_successor_detection_uses_coalesced_through_sequence(persistence) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    running = _queue_and_claim(factory, now)
    successor = replace(
        _pending_intent(now, intent_id="successor"),
        first_sequence=running.first_sequence,
        through_sequence=running.through_sequence + 1,
    )
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert (
            uow.watcher.append_or_replace(
                expected_latest_sequence=running.through_sequence,
                intent=successor,
                replaced_intent_ids=(),
            )
            is not None
        )
        uow.commit()

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert uow.watcher.has_overlapping_successor(
            _fence(running),
            running.scopes,
        )


@pytest.mark.parametrize(
    ("control_state", "last_generation"),
    (
        (LibraryControlState.ACTIVATING, 1),
        (LibraryControlState.ACTIVE, None),
    ),
)
def test_reconcile_writer_requires_initialized_active_library(
    persistence,
    control_state: LibraryControlState,
    last_generation: int | None,
) -> None:
    _, factory = persistence
    _seed_library(
        factory,
        control_state=control_state,
        last_successful_generation=last_generation,
    )
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert (
            uow.libraries.reserve_reconcile_writer(
                "library", expected_topology_writer_fence=1
            )
            is None
        )


def test_expired_restart_and_running_full_rescan_are_atomic(persistence) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    restart_at = now + timedelta(seconds=11)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None
        restarted = uow.watcher.take_over_expired(
            claimed,
            current,
            owner_token="worker-b",
            now=restart_at,
            lease_expires_at=restart_at + timedelta(minutes=1),
        )
        assert restarted is not None
        assert restarted.attempt == 2
        assert restarted.lease_owner == "worker-b"
        assert restarted.topology_writer_fence == 3
        uow.commit()

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        transition = uow.watcher.force_full_rescan_from_running(
            _fence(restarted),
            reason=FullRescanReason.COLLISION_RECHECK,
            observed_at=restart_at + timedelta(seconds=1),
        )
        assert transition is not None
        assert transition.state.latest_sequence == 1
        assert transition.state.overflow_through_sequence == 1
        assert transition.state.full_rescan_reason is FullRescanReason.COLLISION_RECHECK
        assert transition.topology_writer_fence == 4
        assert transition.invalidated_running_intent_id == "intent"
        uow.commit()

    with factory() as session:
        library = session.get(CatalogLibrary, "library")
        assert library is not None and library.topology_writer_fence == 4
        assert session.scalar(select(LibraryReconcileIntent.id)) is None


def test_full_rescan_preserves_first_reason_and_clears_only_exact_watermark(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        first = uow.watcher.force_full_rescan(
            "library",
            expected_latest_sequence=0,
            reason=FullRescanReason.DISCONNECTED,
            observed_at=now,
        )
        assert first is not None
        assert first.newly_required
        second = uow.watcher.force_full_rescan(
            "library",
            expected_latest_sequence=1,
            reason=FullRescanReason.BACKEND_OVERFLOW,
            observed_at=now + timedelta(seconds=1),
        )
        assert second is not None
        assert second.state.latest_sequence == 2
        assert second.state.overflow_through_sequence == 2
        assert second.state.full_rescan_reason is FullRescanReason.DISCONNECTED
        assert not second.newly_required
        uow.commit()

    with factory.begin() as session:
        session.add(
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
                watcher_sequence_watermark=1,
                state=ScanState.FINALIZING,
                failure_code=None,
                lease_owner="scan-worker",
                lease_expires_at=now + timedelta(minutes=5),
                heartbeat_at=now,
                stage=ScanStage.FINALIZE,
                discovered_count=0,
                diagnostic_count=0,
                started_at=now,
                finished_at=None,
                created_by_user_id=None,
            )
        )

    with SqlAlchemyScanUowFactory(factory)() as uow:
        first_finalize = uow.watcher.finalize_full_scan(
            "library",
            watcher_sequence_watermark=1,
            completed_at=now + timedelta(seconds=2),
        )
        assert first_finalize.state.full_rescan_reason is FullRescanReason.DISCONNECTED
        uow.commit()

    with factory.begin() as session:
        session.execute(
            update(LibraryScanRun)
            .where(LibraryScanRun.id == "scan")
            .values(watcher_sequence_watermark=2)
        )

    with SqlAlchemyScanUowFactory(factory)() as uow:
        exact_finalize = uow.watcher.finalize_full_scan(
            "library",
            watcher_sequence_watermark=2,
            completed_at=now + timedelta(seconds=3),
        )
        assert exact_finalize.state.overflow_through_sequence is None
        assert exact_finalize.state.full_rescan_reason is None
        uow.commit()


def test_full_scan_start_invalidates_live_reconcile_with_stale_config(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    assert claimed.lease_expires_at is not None
    with factory.begin() as session:
        session.execute(
            update(CatalogLibrary)
            .where(CatalogLibrary.id == "library")
            .values(config_revision=2)
        )

    with SqlAlchemyScanUowFactory(factory)() as uow:
        current = uow.libraries.get_for_scan_for_update("library")
        assert current is not None and current.config_revision == 2
        start = uow.watcher.prepare_full_scan_start(current, now=now)
        assert start is not None
        assert start.watcher_sequence_watermark == 1
        assert start.topology_writer_fence == 3
        uow.commit()

    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        assert state is not None
        assert state.overflow_through_sequence == 1
        assert state.full_rescan_reason is not None
        assert session.scalar(select(LibraryReconcileIntent.id)) is None


def test_full_scan_start_does_not_invalidate_same_snapshot_live_reconcile(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _queue_and_claim(factory, now)

    with SqlAlchemyScanUowFactory(factory)() as uow:
        current = uow.libraries.get_for_scan_for_update("library")
        assert current is not None
        assert uow.watcher.prepare_full_scan_start(current, now=now) is None

    with factory() as session:
        running = session.scalar(select(LibraryReconcileIntent))
        assert running is not None
        assert running.state.value == "RUNNING"


def test_pending_claim_restamps_current_config_revision(persistence) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    pending = _pending_intent(now)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert uow.watcher.append_or_replace(
            expected_latest_sequence=0,
            intent=pending,
            replaced_intent_ids=(),
        )
        uow.commit()
    with factory.begin() as session:
        session.execute(
            update(CatalogLibrary)
            .where(CatalogLibrary.id == "library")
            .values(config_revision=2)
        )

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None and current.config_revision == 2
        writer_fence = uow.libraries.reserve_reconcile_writer(
            "library",
            expected_topology_writer_fence=current.topology_writer_fence,
        )
        assert writer_fence == 2
        claimed = uow.watcher.claim(
            pending,
            current,
            owner_token="worker",
            topology_writer_fence=writer_fence,
            now=now,
            lease_expires_at=now + timedelta(minutes=1),
        )
        assert claimed is not None
        assert claimed.config_revision == 2
        assert claimed.phase is ReconcileIntentPhase.EXECUTE
        uow.commit()


def test_structurally_stale_pending_sets_constant_rescan_fence(persistence) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    pending = _pending_intent(now)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert uow.watcher.append_or_replace(
            expected_latest_sequence=0,
            intent=pending,
            replaced_intent_ids=(),
        )
        uow.commit()
    with factory.begin() as session:
        session.execute(
            update(CatalogLibrary)
            .where(CatalogLibrary.id == "library")
            .values(root_path="/srv/relocated", config_revision=2)
        )

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None
        transition = uow.watcher.force_full_rescan_from_pending(
            pending,
            current,
            reason=FullRescanReason.ROOT_CHANGED,
            observed_at=now,
        )
        assert transition is not None and transition.newly_required
        assert transition.topology_writer_fence == 1
        assert transition.invalidated_running_intent_id is None
        uow.commit()

    with factory() as session:
        state = session.get(LibraryWatcherState, "library")
        assert state is not None
        assert state.overflow_through_sequence == 1
        assert session.scalar(select(LibraryReconcileIntent.id)) is None


def test_execute_takeover_abandons_staging_and_rolls_back_atomically(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    with factory.begin() as session:
        session.add(LibraryWork(id="work", library_id="library"))
        session.add(
            TopologyUnit(
                id="unit",
                library_id="library",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work",
                version_owner_id=None,
                volume_owner_id=None,
                active_revision_id=None,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            TopologyUnitRevision(
                id="revision",
                library_id="library",
                unit_id="unit",
                scan_run_id=None,
                reconcile_origin_id="intent",
                unit_root_entry_id="root",
                revision=1,
                state=RevisionState.STAGING,
                created_at=now,
            )
        )

    takeover_at = now + timedelta(seconds=11)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None
        assert uow.watcher.take_over_expired(
            claimed,
            current,
            owner_token="worker-b",
            now=takeover_at,
            lease_expires_at=takeover_at + timedelta(minutes=1),
        )

    with factory() as session:
        revision = session.get(TopologyUnitRevision, "revision")
        library = session.get(CatalogLibrary, "library")
        assert revision is not None and revision.state is RevisionState.STAGING
        assert library is not None and library.topology_writer_fence == 2

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None
        taken = uow.watcher.take_over_expired(
            claimed,
            current,
            owner_token="worker-b",
            now=takeover_at,
            lease_expires_at=takeover_at + timedelta(minutes=1),
        )
        assert taken is not None and taken.phase is ReconcileIntentPhase.EXECUTE
        assert taken.fold_after_source_entry_id is None
        uow.commit()

    with factory() as session:
        revision = session.get(TopologyUnitRevision, "revision")
        assert revision is not None and revision.state is RevisionState.ABANDONED


def test_fold_takeover_preserves_phase_and_cursor(persistence) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        folded = uow.watcher.begin_fold(_fence(claimed), now=now)
        assert folded is not None
        advanced = uow.watcher.advance_fold_cursor(
            _fence(folded),
            after_source_entry_id="source-cursor",
            now=now,
        )
        assert advanced is not None
        uow.commit()

    takeover_at = now + timedelta(seconds=11)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        current = uow.libraries.get_for_reconcile_for_update("library")
        assert current is not None
        taken = uow.watcher.take_over_expired(
            advanced,
            current,
            owner_token="worker-b",
            now=takeover_at,
            lease_expires_at=takeover_at + timedelta(minutes=1),
        )
        assert taken is not None
        assert taken.phase is ReconcileIntentPhase.FOLD
        assert taken.fold_after_source_entry_id == "source-cursor"
        uow.commit()


def test_scan_terminal_resume_prioritizes_overflow_over_pending_replay(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    pending = _pending_intent(now)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        assert uow.watcher.append_or_replace(
            expected_latest_sequence=0,
            intent=pending,
            replaced_intent_ids=(),
        )
        uow.commit()

    with SqlAlchemyScanUowFactory(factory)() as uow:
        outcome = uow.watcher.resume_after_full_scan_terminal(
            "library",
            observed_at=now,
        )
        assert outcome.replay_available
        assert outcome.state.full_rescan_reason is None

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        transition = uow.watcher.force_full_rescan(
            "library",
            expected_latest_sequence=1,
            reason=FullRescanReason.BACKEND_OVERFLOW,
            observed_at=now,
        )
        assert transition is not None
        uow.commit()

    with SqlAlchemyScanUowFactory(factory)() as uow:
        outcome = uow.watcher.resume_after_full_scan_terminal(
            "library",
            observed_at=now,
        )
        assert not outcome.replay_available
        assert outcome.state.full_rescan_reason is FullRescanReason.BACKEND_OVERFLOW


def test_directory_pending_epoch_proof_rejects_an_orphaned_attempt(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    fence = _fence(claimed)

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        shelf_outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (_pending_directory(("Shelf",), identity="dev:shelf", parent_epoch=None),),
            observed_at=now,
        )
        shelf = shelf_outcome.bindings[0]
        uow.commit()
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        shelf_epoch = uow.sources.begin_directory_presence(
            fence,
            shelf,
            observed_at=now,
        )
        assert shelf_epoch.proposed_epoch == 1
        uow.commit()
    plan = TopologyUnitPlan(
        unit_key="WORK_CONTAINER:child",
        unit_kind=DomainTopologyUnitKind.WORK_CONTAINER,
        owner_path=("Shelf", "Child"),
        unit_root_path=("Shelf", "Child"),
        rows=(
            WorkProjectionPlan(
                ("Shelf", "Child"),
                "domain-path-key-is-not-persisted",
                "Child",
                "child",
            ),
        ),
    )
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        child_outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (
                _pending_directory(
                    ("Shelf", "Child"),
                    identity="dev:child",
                    parent_epoch=shelf_epoch.proposed_epoch,
                ),
            ),
            observed_at=now,
        )
        child = child_outcome.bindings[0]
        assert child.pending_parent_presence_epoch == 1
        assert uow.topology.bind_plan(fence, plan, (shelf, child)) is not None
        assert (
            uow.sources.begin_directory_presence(
                fence,
                child,
                observed_at=now,
            ).proposed_epoch
            == 1
        )
        uow.commit()
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        retried_shelf_epoch = uow.sources.begin_directory_presence(
            fence,
            shelf,
            observed_at=now,
        )
        assert retried_shelf_epoch.proposed_epoch == 2
        uow.commit()
    with SqlAlchemyWatcherUowFactory(factory)() as uow, pytest.raises(ReconcileStale):
        assert uow.topology.bind_plan(fence, plan, (shelf, child)) is None
        uow.sources.begin_directory_presence(
            fence,
            child,
            observed_at=now,
        )


def test_physically_present_excluded_top_level_clears_absence_without_creation(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    fence = _fence(claimed)
    original = _pending_directory(("Ignored",), identity="dev:old", parent_epoch=None)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (original,),
            observed_at=now,
        )
        uow.commit()
    source_id = outcome.bindings[0].source_entry_id
    with factory.begin() as session:
        row = session.get(LibrarySourceEntry, source_id)
        assert row is not None
        row.absence_confirmed_at = now

    observed = DiscoveredSource(
        ("Ignored",),
        DiscoveryEntryType.DIRECTORY,
        "dev:new",
        None,
    )
    unknown = DiscoveredSource(
        ("NeverCatalogued",),
        DiscoveryEntryType.DIRECTORY,
        "dev:unknown",
        None,
    )
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        uow.sources.exclude_observed_top_level(fence, observed, excluded_at=now)
        uow.sources.exclude_observed_top_level(fence, unknown, excluded_at=now)
        uow.commit()

    with factory() as session:
        row = session.get(LibrarySourceEntry, source_id)
        assert row is not None
        assert row.filesystem_identity == "dev:new"
        assert row.absence_confirmed_at is None
        assert row.layout_state is LayoutState.INVALID
        assert (
            session.scalar(
                select(LibrarySourceEntry.id).where(
                    LibrarySourceEntry.local_name == "NeverCatalogued"
                )
            )
            is None
        )


def test_trusted_work_rename_only_revises_the_local_work_projection(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    fence = _fence(claimed)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        work_outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (_pending_directory(("Old",), identity="dev:work", parent_epoch=None),),
            observed_at=now,
        )
        work = work_outcome.bindings[0]
        work_epoch = uow.sources.begin_directory_presence(
            fence,
            work,
            observed_at=now,
        )
        version_outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (
                _pending_directory(
                    ("Old", "Edition"),
                    identity="dev:version",
                    parent_epoch=work_epoch.proposed_epoch,
                ),
            ),
            observed_at=now,
        )
        assert uow.sources.flip_directory_presence(fence, work_epoch, completed_at=now)
        version = version_outcome.bindings[0]
        version_epoch = uow.sources.begin_directory_presence(
            fence,
            version,
            observed_at=now,
        )
        volume_outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (
                _pending_pdf(
                    ("Old", "Edition", "book.pdf"),
                    identity="dev:book",
                    parent_epoch=version_epoch.proposed_epoch,
                ),
            ),
            observed_at=now,
        )
        assert uow.sources.flip_directory_presence(
            fence,
            version_epoch,
            completed_at=now,
        )
        original_by_path = {
            binding.relative_path: binding
            for binding in (
                *work_outcome.bindings,
                *version_outcome.bindings,
                *volume_outcome.bindings,
            )
        }
        original_bound = []
        original_staging = []
        for plan in _layered_plans("Old"):
            bindings = tuple(
                original_by_path[path] for path in required_topology_source_paths(plan)
            )
            bound = uow.topology.bind_plan(fence, plan, bindings, bound_at=now)
            assert bound is not None
            staging = uow.topology.begin_staging(
                fence,
                bound,
                expected_active_revision_id=None,
                created_at=now,
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
                staged_at=now,
            )
            original_bound.append(bound)
            original_staging.append(staging)
        assert uow.topology.activate_staging_group(
            fence,
            tuple(original_staging),
            activated_at=now,
        )
        uow.commit()

    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        moved = uow.sources.apply_proven_move(
            fence,
            ProvenMoveEvidence(
                source_path=("Old",),
                destination_path=("Renamed",),
                filesystem_identity="dev:work",
                entry_type=WatcherMovedEntryType.DIRECTORY,
                source_absence=TargetedPathAbsent(("Old",)),
            ),
            observed_at=now + timedelta(seconds=1),
        )
        assert moved.binding is not None
        renamed_plans = _layered_plans("Renamed")
        renamed_paths = tuple(
            dict.fromkeys(
                path
                for plan in renamed_plans
                for path in required_topology_source_paths(plan)
            )
        )
        renamed_bindings = uow.sources.resolve_path_bindings(fence, renamed_paths)
        renamed_by_path = {
            binding.relative_path: binding for binding in renamed_bindings
        }
        renamed_bound = []
        for plan in renamed_plans:
            bound = uow.topology.bind_plan(
                fence,
                plan,
                tuple(
                    renamed_by_path[path]
                    for path in required_topology_source_paths(plan)
                ),
                bound_at=now + timedelta(seconds=1),
            )
            assert bound is not None
            renamed_bound.append(bound)
        assert tuple(value.unit_id for value in renamed_bound) == tuple(
            value.unit_id for value in original_bound
        )
        work_staging = uow.topology.begin_staging(
            fence,
            renamed_bound[0],
            expected_active_revision_id=original_staging[0].revision_id,
            created_at=now + timedelta(seconds=1),
        )
        assert work_staging is not None
        for index in (1, 2):
            assert (
                uow.topology.begin_staging(
                    fence,
                    renamed_bound[index],
                    expected_active_revision_id=original_staging[index].revision_id,
                    created_at=now + timedelta(seconds=1),
                )
                is None
            )
        work_staging = uow.topology.append_staging_batch(
            fence,
            work_staging,
            BoundTopologyStageBatch(
                first_row=0,
                rows=renamed_plans[0].rows,
                bindings=renamed_bound[0].projections,
                complete=True,
            ),
            staged_at=now + timedelta(seconds=1),
        )
        assert uow.topology.activate_staging_group(
            fence,
            (work_staging,),
            activated_at=now + timedelta(seconds=1),
        )
        uow.commit()

    with factory() as session:
        active_revision_ids = tuple(
            session.get(TopologyUnit, value.unit_id).active_revision_id
            for value in renamed_bound
        )
        assert active_revision_ids == (
            work_staging.revision_id,
            original_staging[1].revision_id,
            original_staging[2].revision_id,
        )


def test_proven_move_rejects_invalid_source_and_bounded_identity_fanout(
    persistence,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    fence = _fence(claimed)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (_pending_directory(("Old",), identity="dev:moved", parent_epoch=None),),
            observed_at=now,
        )
        uow.commit()
    source_id = outcome.bindings[0].source_entry_id
    evidence = ProvenMoveEvidence(
        source_path=("Old",),
        destination_path=("New",),
        filesystem_identity="dev:moved",
        entry_type=WatcherMovedEntryType.DIRECTORY,
        source_absence=TargetedPathAbsent(("Old",)),
    )

    with factory.begin() as session:
        source = session.get(LibrarySourceEntry, source_id)
        assert source is not None
        source.layout_state = LayoutState.INVALID
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        rejected = uow.sources.apply_proven_move(fence, evidence, observed_at=now)
        assert rejected.rejection_reason is SourceRebindRejectionReason.SOURCE_NOT_FOUND

    with factory.begin() as session:
        source = session.get(LibrarySourceEntry, source_id)
        assert source is not None
        source.layout_state = LayoutState.PRESENT
        session.add_all(
            LibrarySourceEntry(
                id=f"peer-{index}",
                library_id="library",
                parent_entry_id="root",
                local_name=f"Peer-{index}",
                local_name_key=f"Peer-{index}",
                entry_type=SourceEntryType.DIRECTORY,
                filesystem_identity="dev:moved",
                last_seen_generation=1,
                absence_confirmed_at=None,
                children_presence_epoch=0,
                next_children_presence_epoch=0,
                observed_parent_presence_epoch=0,
                pending_observed_parent_presence_epoch=None,
                layout_state=LayoutState.PRESENT,
                slot_state=SlotState.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            for index in range(101)
        )
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        rejected = uow.sources.apply_proven_move(fence, evidence, observed_at=now)
        assert (
            rejected.rejection_reason is SourceRebindRejectionReason.IDENTITY_AMBIGUOUS
        )


@pytest.mark.parametrize(
    ("layout_state", "slot_state", "last_seen_generation"),
    (
        (LayoutState.INVALID, SlotState.COLLIDING, 1),
        (LayoutState.PRESENT, SlotState.ACTIVE, 0),
    ),
)
def test_proven_move_rejects_invalid_destination_parent(
    persistence,
    layout_state: LayoutState,
    slot_state: SlotState,
    last_seen_generation: int,
) -> None:
    _, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    claimed = _queue_and_claim(factory, now)
    fence = _fence(claimed)
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        outcome = uow.sources.upsert_reconcile_observations(
            fence,
            (
                _pending_directory(("Old",), identity="dev:moved", parent_epoch=None),
                _pending_directory(
                    ("Destination",), identity="dev:destination", parent_epoch=None
                ),
            ),
            observed_at=now,
        )
        uow.commit()
    destination_id = next(
        binding.source_entry_id
        for binding in outcome.bindings
        if binding.relative_path == ("Destination",)
    )
    with factory.begin() as session:
        destination = session.get(LibrarySourceEntry, destination_id)
        assert destination is not None
        destination.layout_state = layout_state
        destination.slot_state = slot_state
        destination.last_seen_generation = last_seen_generation

    evidence = ProvenMoveEvidence(
        source_path=("Old",),
        destination_path=("Destination", "New"),
        filesystem_identity="dev:moved",
        entry_type=WatcherMovedEntryType.DIRECTORY,
        source_absence=TargetedPathAbsent(("Old",)),
    )
    with SqlAlchemyWatcherUowFactory(factory)() as uow:
        rejected = uow.sources.apply_proven_move(fence, evidence, observed_at=now)
        assert rejected.rejection_reason is SourceRebindRejectionReason.TARGET_COLLISION
