from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self

import pytest

from app.modules.catalog.application import (
    full_scan_execution as full_scan_execution_module,
)
from app.modules.catalog.application.content_dto import (
    ContentTopologyProjectionRequestOutcome,
    ContentTopologyProjectionState,
    SourceContentObservationOutcome,
)
from app.modules.catalog.application.full_scan_execution import RunFullLibraryScan
from app.modules.catalog.application.ports import AuditEvent, OutboxEvent
from app.modules.catalog.application.scan_dto import (
    CancelFullLibraryScanCommand,
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryObservation,
    FailFullLibraryScanCommand,
    FullScanRun,
    FullScanWorkItem,
    PathCollision,
    RunFullLibraryScanCommand,
    ScanFailureCode,
    ScanFence,
    ScanLibrarySnapshot,
    SourceObservation,
    SourceObservationOutcome,
    SourcePathBinding,
    StagingRevision,
    StartFullLibraryScanCommand,
    TakeOverFullLibraryScanCommand,
    WriterReservation,
)
from app.modules.catalog.application.scan_lifecycle import (
    CancelFullLibraryScan,
    FailFullLibraryScan,
    StartFullLibraryScan,
    TakeOverFullLibraryScan,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)
from app.modules.catalog.application.watcher_dto import (
    BoundProjectionKind,
    BoundTopologyProjection,
    BoundTopologyStageBatch,
    BoundTopologyUnitPlan,
    FullScanWatcherStart,
    WatcherFinalizeOutcome,
    WatcherResumeOutcome,
    WatcherState,
)
from app.modules.catalog.domain.access import GrantLevel, LibraryGrant
from app.modules.catalog.domain.admission import (
    AudioCodec,
    AudioEvidence,
    DirectFileEvidence,
    SourceAdmissionEvidence,
)
from app.modules.catalog.domain.library import LibraryControlState, LibraryHealth
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    PathComparison,
    SidecarRole,
    SourceFormat,
)
from app.modules.catalog.domain.scan import (
    MAX_AUDIO_TRACKS,
    AssetMembershipPlan,
    ScanConflict,
    ScanDiagnostic,
    ScanRootIdentityChanged,
    ScanStage,
    ScanStale,
    ScanState,
    TopologyUnitKind,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
)
from app.modules.catalog.domain.watcher import FullRescanReason

NOW = datetime(2026, 8, 18, tzinfo=UTC)
STAT = SourceStatExpectation(1, 2, 3, 4)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _MonotonicClock:
    def seconds(self) -> float:
        return 0.0


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> str:
        self.value += 1
        return f"new-{self.value}"


class _AuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class _OutboxSink:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []
        self.fail_on_event_type: str | None = None

    def append(self, event: OutboxEvent) -> None:
        if event.event_type == self.fail_on_event_type:
            raise RuntimeError("outbox unavailable")
        self.events.append(event)


class _DiagnosticSink:
    def __init__(self) -> None:
        self.values: list[ScanDiagnostic] = []

    def record(
        self,
        _fence: ScanFence,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None:
        assert observed_at == NOW
        self.values.extend(diagnostics)


class _CollisionSink:
    def __init__(self) -> None:
        self.values: list[PathCollision] = []

    def record(
        self,
        _fence: ScanFence,
        collisions: tuple[PathCollision, ...],
        *,
        observed_at: datetime,
    ) -> None:
        assert observed_at == NOW
        self.values.extend(collisions)


def _library(
    *,
    root: str = "/library",
    mode: OrganizationMode = OrganizationMode.FLAT,
    comparison: PathComparison = PathComparison.SENSITIVE,
    config_revision: int = 1,
    writer_fence: int = 1,
    next_generation: int = 2,
    state: LibraryControlState = LibraryControlState.ACTIVE,
) -> ScanLibrarySnapshot:
    return ScanLibrarySnapshot(
        library_id="library-1",
        canonical_root=root,
        organization_mode=mode,
        topology_version=1,
        path_comparison=comparison,
        control_state=state,
        observed_health=LibraryHealth.HEALTHY,
        config_revision=config_revision,
        topology_writer_fence=writer_fence,
        next_scan_generation=next_generation,
        last_successful_generation=None,
    )


def _run(
    library: ScanLibrarySnapshot,
    *,
    scan_id: str = "scan-1",
    generation: int = 1,
    state: ScanState = ScanState.PENDING,
    stage: ScanStage = ScanStage.DISCOVER,
    root_identity: str | None = None,
    owner: str = "worker-1",
    expired: bool = False,
) -> FullScanRun:
    started = None if state is ScanState.PENDING else NOW
    return FullScanRun(
        scan_id=scan_id,
        library_id=library.library_id,
        canonical_root=library.canonical_root,
        generation=generation,
        config_revision=library.config_revision,
        organization_mode=library.organization_mode,
        topology_version=library.topology_version,
        path_comparison=library.path_comparison,
        root_identity=root_identity,
        topology_writer_fence=library.topology_writer_fence,
        state=state,
        failure_code=None,
        stage=stage,
        lease_owner=owner,
        lease_expires_at=NOW + timedelta(seconds=-1 if expired else 60),
        heartbeat_at=NOW,
        discovered_count=0,
        diagnostic_count=0,
        created_by_actor_id="admin-1",
        started_at=started,
        finished_at=None,
        watcher_sequence_watermark=0,
    )


def _work(run: FullScanRun) -> FullScanWorkItem:
    running = run.state is not ScanState.PENDING
    return FullScanWorkItem(
        work_item_id=f"work-{run.scan_id}",
        library_id=run.library_id,
        scan_id=run.scan_id,
        root_path_snapshot=run.root_path_snapshot,
        scope_relative_path=(),
        state=ScanState.RUNNING if running else ScanState.PENDING,
        stage=run.stage,
        lease_owner=run.lease_owner if running else None,
        lease_expires_at=run.lease_expires_at if running else None,
        attempt=1 if running else 0,
        available_at=NOW,
        idempotency_key=f"root:{run.library_id}:{run.generation}",
        discovered_count=0,
    )


class _Store:
    def __init__(
        self,
        library: ScanLibrarySnapshot,
        *,
        run: FullScanRun | None = None,
        work: FullScanWorkItem | None = None,
        synthetic_root_identity: str | None = None,
        collision_paths: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
        unchanged_topology: bool = False,
    ) -> None:
        self.library = library
        self.run = run
        self.work = work
        self.synthetic_root_identity = synthetic_root_identity
        self.collision_paths = collision_paths
        self.unchanged_topology = unchanged_topology
        self.collision_emitted = False
        self.cancel_invalidated_succeeds = True
        self.invalidated_run: FullScanRun | None = None
        self.audit = _AuditSink()
        self.outbox = _OutboxSink()
        self.diagnostics = _DiagnosticSink()
        self.collisions = _CollisionSink()
        self.calls: list[str] = []
        self.observations: list[SourceObservation] = []
        self.content_observation_calls = 0
        self.source_bindings: dict[tuple[str, ...], SourcePathBinding] = {}
        self.work_ids: dict[str, str] = {}
        self.version_ids: dict[tuple[str, str | None], str] = {}
        self.volume_ids: dict[str, str] = {}
        self.asset_ids: dict[tuple[str, str], str] = {}
        self.unit_ids: dict[tuple[TopologyUnitKind, str], str] = {}
        self.next_topology_id = 0
        self.plans: list[TopologyUnitPlan] = []
        self.activation_groups: list[tuple[StagingRevision, ...]] = []
        self.scan_lease_updates: list[tuple[str, datetime]] = []
        self.work_lease_updates: list[tuple[str, datetime]] = []
        self.abandoned_scan_count = 0
        self.watcher_sequence = 0
        self.watcher_full_rescan_reason: FullRescanReason | None = None
        self.watcher_pending = False
        self.commits = 0
        self.rollbacks = 0

    # Library repository
    def get_for_scan_for_update(self, library_id: str) -> ScanLibrarySnapshot | None:
        return self.library if library_id == self.library.library_id else None

    def reserve_topology_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
        expected_next_generation: int,
    ) -> WriterReservation | None:
        self.calls.append("reserve")
        if (
            library_id != self.library.library_id
            or expected_topology_writer_fence != self.library.topology_writer_fence
            or expected_next_generation != self.library.next_scan_generation
        ):
            return None
        reservation = WriterReservation(
            self.library.next_scan_generation,
            self.library.topology_writer_fence + 1,
        )
        self.library = replace(
            self.library,
            topology_writer_fence=reservation.topology_writer_fence,
            next_scan_generation=reservation.generation + 1,
        )
        return reservation

    def take_over_topology_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
    ) -> int | None:
        if (
            library_id != self.library.library_id
            or expected_topology_writer_fence != self.library.topology_writer_fence
        ):
            return None
        next_fence = expected_topology_writer_fence + 1
        self.library = replace(self.library, topology_writer_fence=next_fence)
        return next_fence

    def finalize_generation(self, fence: ScanFence, *, completed_at: datetime) -> bool:
        assert completed_at == NOW
        self.calls.append("finalize_generation")
        self.library = replace(
            self.library,
            control_state=LibraryControlState.ACTIVE,
            observed_health=LibraryHealth.HEALTHY,
            last_successful_generation=fence.generation,
        )
        return True

    def set_health_if_fence(
        self,
        _fence: ScanFence,
        *,
        health: LibraryHealth,
        observed_at: datetime,
    ) -> bool:
        assert observed_at == NOW
        self.library = replace(self.library, observed_health=health)
        return True

    # Full-scan/watcher coordination
    def prepare_full_scan_start(
        self,
        library: ScanLibrarySnapshot,
        *,
        now: datetime,
    ) -> FullScanWatcherStart | None:
        assert library == self.library and now == NOW
        self.calls.append("prepare_watcher")
        return FullScanWatcherStart(
            watcher_sequence_watermark=self.watcher_sequence,
            topology_writer_fence=self.library.topology_writer_fence,
        )

    def finalize_full_scan(
        self,
        library_id: str,
        *,
        watcher_sequence_watermark: int,
        completed_at: datetime,
    ) -> WatcherFinalizeOutcome:
        assert library_id == self.library.library_id and completed_at == NOW
        assert watcher_sequence_watermark <= self.watcher_sequence
        self.calls.append("finalize_watcher")
        overflow_through = (
            self.watcher_sequence
            if self.watcher_full_rescan_reason is not None
            else None
        )
        return WatcherFinalizeOutcome(
            state=WatcherState(
                library_id,
                self.watcher_sequence,
                overflow_through,
                self.watcher_full_rescan_reason,
            ),
            discarded_intent_count=0,
            replay_available=self.watcher_sequence > watcher_sequence_watermark,
        )

    def resume_after_full_scan_terminal(
        self,
        library_id: str,
        *,
        observed_at: datetime,
    ) -> WatcherResumeOutcome:
        assert library_id == self.library.library_id and observed_at == NOW
        self.calls.append("resume_watcher")
        overflow_through = (
            self.watcher_sequence
            if self.watcher_full_rescan_reason is not None
            else None
        )
        return WatcherResumeOutcome(
            state=WatcherState(
                library_id,
                self.watcher_sequence,
                overflow_through,
                self.watcher_full_rescan_reason,
            ),
            replay_available=(
                self.watcher_pending and self.watcher_full_rescan_reason is None
            ),
        )

    # Scan run repository
    def get_active_for_update(self, library_id: str) -> FullScanRun | None:
        if self.run is None or self.run.library_id != library_id:
            return None
        if self.run.state in {
            ScanState.PENDING,
            ScanState.RUNNING,
            ScanState.FINALIZING,
        }:
            return self.run
        return None

    def get_for_update(self, library_id: str, scan_id: str) -> FullScanRun | None:
        if self.run is None or (self.run.library_id, self.run.scan_id) != (
            library_id,
            scan_id,
        ):
            return None
        return self.run

    def insert(self, run: FullScanRun) -> None:
        self.calls.append("insert_run")
        self.run = run

    def start_running(
        self,
        _fence: ScanFence,
        *,
        root_identity: str,
        started_at: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        assert self.run is not None
        self.calls.append("start_running")
        self.scan_lease_updates.append(("start_running", lease_expires_at))
        self.run = replace(
            self.run,
            state=ScanState.RUNNING,
            root_identity=root_identity,
            started_at=started_at,
            lease_expires_at=lease_expires_at,
        )
        return self.run

    def cancel_invalidated(
        self,
        run: FullScanRun,
        *,
        current_library: ScanLibrarySnapshot,
        cancelled_at: datetime,
    ) -> FullScanRun | None:
        self.calls.append("cancel_invalidated")
        assert current_library == self.library
        if not self.cancel_invalidated_succeeds or self.run != run:
            return None
        self.invalidated_run = replace(
            run,
            state=ScanState.CANCELLED,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=cancelled_at,
        )
        self.run = self.invalidated_run
        return self.invalidated_run

    def take_over_expired(
        self,
        _fence: ScanFence,
        *,
        new_owner_token: str,
        new_topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        assert self.run is not None and self.run.lease_expires_at <= now
        finalizing = self.run.state is ScanState.FINALIZING
        self.run = replace(
            self.run,
            state=ScanState.FINALIZING if finalizing else ScanState.RUNNING,
            stage=ScanStage.FINALIZE if finalizing else ScanStage.DISCOVER,
            lease_owner=new_owner_token,
            lease_expires_at=lease_expires_at,
            topology_writer_fence=new_topology_writer_fence,
        )
        return self.run

    def guard_mutation(self, _fence: ScanFence, *, now: datetime) -> bool:
        return (
            self.run is not None
            and self.run.lease_owner == _fence.lease_owner
            and self.run.lease_expires_at is not None
            and self.run.lease_expires_at > now
        )

    def heartbeat(
        self,
        _fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int = 0,
        diagnostic_increment: int = 0,
    ) -> FullScanRun | None:
        self.calls.append("scan_heartbeat")
        if (
            self.run is None
            or self.run.lease_owner != _fence.lease_owner
            or self.run.lease_expires_at is None
            or self.run.lease_expires_at <= now
        ):
            return None
        self.scan_lease_updates.append(("heartbeat", lease_expires_at))
        self.run = replace(
            self.run,
            heartbeat_at=now,
            lease_expires_at=lease_expires_at,
            discovered_count=self.run.discovered_count + discovered_increment,
            diagnostic_count=self.run.diagnostic_count + diagnostic_increment,
        )
        return self.run

    def cancel(
        self,
        run: FullScanRun,
        *,
        cancelled_at: datetime,
        next_topology_writer_fence: int,
    ) -> FullScanRun | None:
        self.calls.append("cancel")
        if (
            self.run != run
            or self.library.topology_writer_fence != next_topology_writer_fence
        ):
            return None
        self.run = replace(
            run,
            state=ScanState.CANCELLED,
            topology_writer_fence=next_topology_writer_fence,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=cancelled_at,
        )
        return self.run

    def set_stage(
        self,
        _fence: ScanFence,
        *,
        expected_stage: ScanStage,
        next_stage: ScanStage,
        now: datetime | None = None,
    ) -> bool:
        if now is not None:
            assert self.run is not None and self.run.stage is expected_stage
            self.run = replace(self.run, stage=next_stage)
        else:
            assert self.work is not None and self.work.stage is expected_stage
            self.work = replace(self.work, stage=next_stage)
        return True

    def begin_finalizing(
        self,
        _fence: ScanFence,
        *,
        expected_stage: ScanStage,
        now: datetime,
    ) -> FullScanRun | None:
        assert self.run is not None and self.run.stage is expected_stage
        self.run = replace(
            self.run,
            state=ScanState.FINALIZING,
            stage=ScanStage.FINALIZE,
            heartbeat_at=now,
        )
        return self.run

    def complete(
        self, _fence: ScanFence, *, completed_at: datetime
    ) -> FullScanRun | None:
        assert self.run is not None
        self.run = replace(
            self.run,
            state=ScanState.COMPLETED,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=completed_at,
        )
        return self.run

    def fail(
        self,
        _fence: ScanFence,
        *,
        failure_code: ScanFailureCode,
        failed_at: datetime,
    ) -> FullScanRun | None:
        assert self.run is not None
        self.run = replace(
            self.run,
            state=ScanState.FAILED,
            failure_code=failure_code,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=failed_at,
        )
        return self.run

    # Root work repository
    def insert_root(self, work_item: FullScanWorkItem) -> None:
        self.calls.append("insert_work")
        self.work = work_item

    def get_root_for_update(
        self, library_id: str, scan_id: str
    ) -> FullScanWorkItem | None:
        if self.work is None or (self.work.library_id, self.work.scan_id) != (
            library_id,
            scan_id,
        ):
            return None
        return self.work

    def claim_pending_root(
        self,
        _fence: ScanFence,
        *,
        work_item_id: str,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanWorkItem | None:
        assert self.work is not None and self.work.work_item_id == work_item_id
        self.work_lease_updates.append(("claim", lease_expires_at))
        self.work = replace(
            self.work,
            state=ScanState.RUNNING,
            lease_owner=owner_token,
            lease_expires_at=lease_expires_at,
            attempt=self.work.attempt + 1,
        )
        return self.work

    def take_over_expired_root(
        self,
        _fence: ScanFence,
        *,
        new_owner_token: str,
        new_topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
        restart_from_root: bool,
    ) -> FullScanWorkItem | None:
        assert self.work is not None and self.work.lease_expires_at <= now
        self.work = replace(
            self.work,
            state=ScanState.RUNNING,
            stage=ScanStage.DISCOVER if restart_from_root else self.work.stage,
            lease_owner=new_owner_token,
            lease_expires_at=lease_expires_at,
            attempt=self.work.attempt + 1,
        )
        return self.work

    def heartbeat_root(
        self,
        _fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int,
    ) -> bool:
        self.calls.append("work_heartbeat")
        if (
            self.work is None
            or self.work.lease_owner != _fence.lease_owner
            or self.work.lease_expires_at is None
            or self.work.lease_expires_at <= now
        ):
            return False
        self.work_lease_updates.append(("heartbeat", lease_expires_at))
        self.work = replace(
            self.work,
            lease_expires_at=lease_expires_at,
            discovered_count=self.work.discovered_count + discovered_increment,
        )
        return True

    def delete_for_terminal(self, library_id: str, scan_id: str) -> bool:
        self.calls.append("delete_work")
        if self.work is None or (self.work.library_id, self.work.scan_id) != (
            library_id,
            scan_id,
        ):
            return False
        self.work = None
        return True

    # Source observations
    def bind_synthetic_root(
        self,
        _fence: ScanFence,
        *,
        observed_identity: str,
        observed_at: datetime,
    ) -> bool:
        assert observed_at == NOW
        self.calls.append("bind_root")
        if self.synthetic_root_identity is None:
            self.synthetic_root_identity = observed_identity
            return True
        return self.synthetic_root_identity == observed_identity

    def upsert_observations(
        self,
        _fence: ScanFence,
        observations: tuple[SourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome:
        assert observed_at == NOW
        self.observations.extend(observations)
        bindings: list[SourcePathBinding] = []
        for observation in observations:
            path = observation.source.relative_path
            binding = self.source_bindings.get(path)
            if binding is None:
                binding = SourcePathBinding(
                    path,
                    f"source-{len(self.source_bindings) + 1}",
                    observation.source.filesystem_identity,
                )
                self.source_bindings[path] = binding
            if binding not in bindings:
                bindings.append(binding)
        if self.collision_paths is None or self.collision_emitted:
            return SourceObservationOutcome(bindings=tuple(bindings))
        second = self.collision_paths[1]
        if not any(value.source.relative_path == second for value in observations):
            return SourceObservationOutcome(bindings=tuple(bindings))
        self.collision_emitted = True
        return SourceObservationOutcome(
            collisions=(
                PathCollision(
                    parent_path=second[:-1],
                    comparison_key="collision-key",
                    related_paths=self.collision_paths,
                ),
            ),
            bindings=tuple(bindings),
        )

    def observe_sources(
        self,
        _fence: object,
        observations: tuple[object, ...],
        *,
        observed_at: datetime,
    ) -> SourceContentObservationOutcome:
        assert observed_at == NOW
        self.content_observation_calls += len(observations)
        return SourceContentObservationOutcome((), 0, False)

    def record_topology_activation(
        self,
        _fence: object,
        _staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> ContentTopologyProjectionRequestOutcome:
        assert activated_at == NOW
        return ContentTopologyProjectionRequestOutcome(
            ContentTopologyProjectionState("library-1", 1, 0, 0, None),
            False,
        )

    # Topology repository
    def abandon_scan_staging(
        self, _fence: ScanFence, *, abandoned_at: datetime
    ) -> None:
        assert abandoned_at == NOW
        self.abandoned_scan_count += 1

    def abandon_cancelled_scan_staging(
        self,
        library_id: str,
        scan_id: str,
        *,
        abandoned_at: datetime,
    ) -> bool:
        self.calls.append("abandon_cancelled")
        return (
            self.run is not None
            and self.run.state is ScanState.CANCELLED
            and (self.run.library_id, self.run.scan_id) == (library_id, scan_id)
            and abandoned_at == NOW
        )

    def _new_topology_id(self, prefix: str) -> str:
        self.next_topology_id += 1
        return f"{prefix}-{self.next_topology_id}"

    def bind_plan(
        self,
        _fence: ScanFence,
        plan: TopologyUnitPlan,
        source_bindings: tuple[SourcePathBinding, ...],
        *,
        bound_at: datetime,
    ) -> BoundTopologyUnitPlan | None:
        assert bound_at == NOW
        source_by_path = {
            binding.relative_path: binding.source_entry_id
            for binding in source_bindings
        }
        projections: list[BoundTopologyProjection] = []
        for row_index, row in enumerate(plan.rows):
            if isinstance(row, WorkProjectionPlan):
                root_source_id = source_by_path[row.root_path]
                stable_id = self.work_ids.get(root_source_id)
                if stable_id is None:
                    stable_id = self._new_topology_id("work")
                    self.work_ids[root_source_id] = stable_id
                projection = BoundTopologyProjection(
                    row_index,
                    BoundProjectionKind.WORK,
                    stable_id,
                    None,
                    None,
                    source_by_path[row.root_path],
                    None,
                    row.structure_key,
                )
            elif isinstance(row, VersionProjectionPlan):
                parent_id = self.work_ids[source_by_path[row.work_path]]
                root_source_id = (
                    None if row.root_path is None else source_by_path[row.root_path]
                )
                version_key = (parent_id, root_source_id)
                stable_id = self.version_ids.get(version_key)
                if stable_id is None:
                    stable_id = self._new_topology_id("version")
                    self.version_ids[version_key] = stable_id
                projection = BoundTopologyProjection(
                    row_index,
                    BoundProjectionKind.VERSION,
                    stable_id,
                    parent_id,
                    BoundProjectionKind.WORK,
                    None if row.root_path is None else source_by_path[row.root_path],
                    None,
                    row.structure_key,
                )
            elif isinstance(row, VolumeProjectionPlan):
                work_id = self.work_ids[source_by_path[row.work_path]]
                version_source_id = (
                    None
                    if row.version_path is None
                    else source_by_path[row.version_path]
                )
                parent_id = self.version_ids[(work_id, version_source_id)]
                root_source_id = source_by_path[row.root_path]
                stable_id = self.volume_ids.get(root_source_id)
                if stable_id is None:
                    stable_id = self._new_topology_id("volume")
                    self.volume_ids[root_source_id] = stable_id
                projection = BoundTopologyProjection(
                    row_index,
                    BoundProjectionKind.VOLUME,
                    stable_id,
                    parent_id,
                    BoundProjectionKind.VERSION,
                    source_by_path[row.root_path],
                    None,
                    row.structure_key,
                )
            elif isinstance(row, AssetMembershipPlan):
                parent_id = self.volume_ids[source_by_path[row.volume_path]]
                source_id = source_by_path[row.source_path]
                asset_key = (parent_id, source_id)
                stable_id = self.asset_ids.get(asset_key)
                if stable_id is None:
                    stable_id = self._new_topology_id("asset")
                    self.asset_ids[asset_key] = stable_id
                projection = BoundTopologyProjection(
                    row_index,
                    BoundProjectionKind.ASSET,
                    stable_id,
                    parent_id,
                    BoundProjectionKind.VOLUME,
                    None,
                    source_by_path[row.source_path],
                    None,
                )
            else:
                raise TypeError("unsupported topology projection")
            projections.append(projection)
        owner_kind = (
            BoundProjectionKind.WORK
            if plan.unit_kind
            in {TopologyUnitKind.WORK_CONTAINER, TopologyUnitKind.AUDIOBOOK_WORK}
            else BoundProjectionKind.VERSION
            if plan.unit_kind is TopologyUnitKind.VERSION_CONTAINER
            else BoundProjectionKind.VOLUME
        )
        owner_id = next(
            value.stable_id for value in projections if value.kind is owner_kind
        )
        unit_key = (plan.unit_kind, owner_id)
        unit_id = self.unit_ids.get(unit_key)
        if unit_id is None:
            unit_id = self._new_topology_id("unit")
            self.unit_ids[unit_key] = unit_id
        return BoundTopologyUnitPlan(
            plan=plan,
            unit_id=unit_id,
            owner_stable_id=owner_id,
            source_bindings=source_bindings,
            projections=tuple(projections),
        )

    def abandon_incomplete(
        self, _fence: ScanFence, *, unit_id: str, abandoned_at: datetime
    ) -> None:
        assert unit_id and abandoned_at == NOW

    def get_active_revision_id(self, library_id: str, *, unit_id: str) -> str | None:
        assert library_id == self.library.library_id and unit_id
        return None

    def begin_staging(
        self,
        _fence: ScanFence,
        plan: BoundTopologyUnitPlan,
        *,
        expected_active_revision_id: str | None,
        created_at: datetime,
    ) -> StagingRevision | None:
        assert expected_active_revision_id is None and created_at == NOW
        self.plans.append(plan.plan)
        if self.unchanged_topology:
            return None
        number = len(self.plans)
        return StagingRevision(
            revision_id=f"revision-{number}",
            unit_id=plan.unit_id,
            expected_active_revision_id=None,
            expected_row_count=len(plan.plan.rows),
            staged_row_count=0,
        )

    def append_staging_batch(
        self,
        _fence: ScanFence,
        staging: StagingRevision,
        batch: BoundTopologyStageBatch,
        *,
        staged_at: datetime,
    ) -> StagingRevision:
        assert staged_at == NOW and batch.first_row == staging.staged_row_count
        self.calls.append("append_batch")
        return replace(
            staging,
            staged_row_count=staging.staged_row_count + len(batch.rows),
        )

    def activate_staging_group(
        self,
        _fence: ScanFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> bool:
        assert activated_at == NOW
        self.calls.append("activate")
        assert all(
            value.staged_row_count == value.expected_row_count for value in staging
        )
        self.activation_groups.append(staging)
        return True

    # ACL
    def get(self, user_id: str, library_id: str) -> LibraryGrant | None:
        if (user_id, library_id) != ("admin-1", self.library.library_id):
            return None
        return LibraryGrant(user_id, library_id, GrantLevel.ADMIN, 1)


class _UnitOfWork:
    def __init__(self, store: _Store) -> None:
        self._store = store
        self.libraries = store
        self.scans = store
        self.work_items = store
        self.sources = store
        self.content_observations = store
        self.content_topology = store
        self.topology = store
        self.diagnostics = store.diagnostics
        self.collisions = store.collisions
        self.watcher = store
        self.grants = store
        self.audit = store.audit
        self.outbox = store.outbox

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is not None:
            self._store.rollbacks += 1
        return False

    def commit(self) -> None:
        self._store.commits += 1

    def rollback(self) -> None:
        self._store.rollbacks += 1


class _UnitOfWorkFactory:
    def __init__(self, store: _Store) -> None:
        self.store = store

    def __call__(self) -> _UnitOfWork:
        return _UnitOfWork(self.store)


class _DiscoverySession:
    def __init__(
        self,
        identity: str,
        directories: dict[tuple[str, ...], tuple[DiscoveryObservation, ...]],
    ) -> None:
        self._identity = identity
        self._directories = directories

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @property
    def root_identity(self) -> str:
        return self._identity

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]:
        return iter(self._directories.get(relative_directory, ()))

    def revalidate_root_identity(self) -> str:
        return self._identity


class _Discovery:
    def __init__(
        self,
        identity: str,
        directories: dict[tuple[str, ...], tuple[DiscoveryObservation, ...]],
    ) -> None:
        self.identity = identity
        self.directories = directories

    def open(self, *, canonical_root: str) -> _DiscoverySession:
        assert canonical_root
        return _DiscoverySession(self.identity, self.directories)


class _LazyOversizedDiscoverySession:
    def __init__(self, mode: OrganizationMode, track_count: int) -> None:
        self._mode = mode
        self._track_count = track_count

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @property
    def root_identity(self) -> str:
        return "dev:root"

    def iter_directory(
        self,
        relative_directory: tuple[str, ...],
    ) -> Iterator[DiscoveryObservation]:
        work = ("Work",)
        version = ("Work", "Version")
        volume = ("Work", "Version", "Volume")
        if relative_directory == ():
            return iter((_directory(work),))
        if self._mode is OrganizationMode.AUDIOBOOK and relative_directory == work:
            return (
                _file(("Work", f"track-{index}.mp3"))
                for index in range(self._track_count)
            )
        if relative_directory == work:
            return iter((_directory(version),))
        if relative_directory == version:
            return iter((_directory(volume),))
        if relative_directory == volume:
            return (
                _file((*volume, f"track-{index}.mp3"))
                for index in range(self._track_count)
            )
        raise AssertionError(f"unexpected directory: {relative_directory!r}")

    def revalidate_root_identity(self) -> str:
        return self.root_identity


class _LazyOversizedDiscovery:
    def __init__(self, mode: OrganizationMode, track_count: int) -> None:
        self._mode = mode
        self._track_count = track_count

    def open(self, *, canonical_root: str) -> _LazyOversizedDiscoverySession:
        assert canonical_root == "/library"
        return _LazyOversizedDiscoverySession(self._mode, self._track_count)


class _Admission:
    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionEvidence:
        assert canonical_root and expected_stat is not None
        return SourceAdmissionEvidence(
            relative_path=relative_path,
            entry_type=EntryType.FILE,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.TXT,
            evidence=DirectFileEvidence(
                SourceFormat.TXT,
                probe_bytes_examined=1,
                probe_byte_budget=16,
            ),
        )


class _AudioAdmission:
    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionEvidence:
        assert canonical_root and expected_stat is not None
        return SourceAdmissionEvidence(
            relative_path=relative_path,
            entry_type=EntryType.FILE,
            admission=AdmissionKind.AUDIO_TRACK,
            source_format=SourceFormat.MP3,
            evidence=AudioEvidence(
                SourceFormat.MP3,
                AudioCodec.MPEG_LAYER_III,
                probe_bytes_examined=1,
                probe_byte_budget=16,
            ),
        )


class _SidecarAdmission:
    def __init__(self, role: SidecarRole) -> None:
        self.role = role

    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionEvidence:
        assert canonical_root and expected_stat is not None
        return SourceAdmissionEvidence(
            relative_path=relative_path,
            entry_type=EntryType.FILE,
            admission=AdmissionKind.SIDECAR,
            sidecar_role=self.role,
        )


class _ForbiddenAdmission:
    def probe(self, **_kwargs: object) -> SourceAdmissionEvidence:
        raise AssertionError("an empty library must not invoke admission")


def _file(path: tuple[str, ...]) -> DiscoveredSource:
    return DiscoveredSource(path, DiscoveryEntryType.FILE, f"file:{path[-1]}", STAT)


def _directory(path: tuple[str, ...]) -> DiscoveredSource:
    return DiscoveredSource(path, DiscoveryEntryType.DIRECTORY, f"dir:{path[-1]}", None)


def _execute_run(
    store: _Store,
    discovery: _Discovery | _LazyOversizedDiscovery,
    *,
    admission: _Admission | _AudioAdmission | _SidecarAdmission | _ForbiddenAdmission,
    lease_seconds: int = 60,
) -> object:
    assert store.run is not None and store.run.lease_owner is not None
    run = store.run
    return RunFullLibraryScan(
        unit_of_work_factory=_UnitOfWorkFactory(store),
        discovery=discovery,
        admission=admission,
        clock=_Clock(),
        monotonic_clock=_MonotonicClock(),
    ).execute(
        RunFullLibraryScanCommand(
            run.library_id,
            run.scan_id,
            run.lease_owner,
            lease_seconds=lease_seconds,
        )
    )


def test_start_rejects_a_current_live_run_without_mutating_it() -> None:
    library = _library()
    active = _run(library)
    store = _Store(library, run=active, work=_work(active))

    with pytest.raises(ScanConflict):
        StartFullLibraryScan(
            unit_of_work_factory=_UnitOfWorkFactory(store),
            id_generator=_Ids(),
            clock=_Clock(),
        ).execute(StartFullLibraryScanCommand("admin-1", "library-1", "worker-2"))

    assert store.run == active
    assert store.calls == []
    assert store.rollbacks == 1


def test_start_captures_required_watcher_watermark_before_writer_reservation() -> None:
    library = _library()
    store = _Store(library)
    store.watcher_sequence = 7

    created = StartFullLibraryScan(
        unit_of_work_factory=_UnitOfWorkFactory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(StartFullLibraryScanCommand("admin-1", "library-1", "worker-1"))

    assert created.watcher_sequence_watermark == 7
    assert store.calls.index("prepare_watcher") < store.calls.index("reserve")


@pytest.mark.parametrize(
    "current_library",
    (
        _library(config_revision=2),
        _library(root="/replacement"),
        _library(comparison=PathComparison.INSENSITIVE),
        _library(mode=OrganizationMode.VOLUMES),
        _library(writer_fence=2),
    ),
)
def test_start_atomically_invalidates_a_stale_live_run(
    current_library: ScanLibrarySnapshot,
) -> None:
    original_library = _library()
    active = _run(original_library)
    store = _Store(current_library, run=active, work=_work(active))

    created = StartFullLibraryScan(
        unit_of_work_factory=_UnitOfWorkFactory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(StartFullLibraryScanCommand("admin-1", "library-1", "worker-2"))

    assert store.invalidated_run is not None
    assert store.invalidated_run.state is ScanState.CANCELLED
    assert created.root_path_snapshot == current_library.canonical_root
    assert store.work is not None
    assert store.work.root_path_snapshot == created.root_path_snapshot
    assert store.calls[:5] == [
        "cancel_invalidated",
        "abandon_cancelled",
        "delete_work",
        "prepare_watcher",
        "reserve",
    ]
    assert [event.event_type for event in store.audit.events] == [
        "LIBRARY_FULL_SCAN_STARTED"
    ]
    assert [event.event_type for event in store.outbox.events] == [
        "LIBRARY_FULL_SCAN_INVALIDATED",
        "LIBRARY_FULL_SCAN_STARTED",
    ]


def test_start_rolls_back_when_invalidation_cas_loses() -> None:
    original = _library()
    active = _run(original)
    store = _Store(_library(config_revision=2), run=active, work=_work(active))
    store.cancel_invalidated_succeeds = False

    with pytest.raises(ScanStale):
        StartFullLibraryScan(
            unit_of_work_factory=_UnitOfWorkFactory(store),
            id_generator=_Ids(),
            clock=_Clock(),
        ).execute(StartFullLibraryScanCommand("admin-1", "library-1", "worker-2"))

    assert "reserve" not in store.calls
    assert "insert_run" not in store.calls
    assert store.rollbacks == 1


@pytest.mark.parametrize(
    ("state", "stage", "root_identity"),
    (
        (ScanState.PENDING, ScanStage.DISCOVER, None),
        (ScanState.RUNNING, ScanStage.DISCOVER, "dev:root"),
        (ScanState.FINALIZING, ScanStage.FINALIZE, "dev:root"),
    ),
)
def test_admin_cancel_terminates_an_expired_live_run_without_a_live_lease(
    state: ScanState,
    stage: ScanStage,
    root_identity: str | None,
) -> None:
    library = _library()
    run = _run(
        library,
        state=state,
        stage=stage,
        root_identity=root_identity,
        expired=True,
    )
    old_fence = run.fence()
    store = _Store(library, run=run, work=_work(run))

    cancelled = CancelFullLibraryScan(
        unit_of_work_factory=_UnitOfWorkFactory(store),
        clock=_Clock(),
    ).execute(CancelFullLibraryScanCommand("admin-1", "library-1", "scan-1"))

    assert cancelled.state is ScanState.CANCELLED
    assert cancelled.topology_writer_fence == library.topology_writer_fence + 1
    assert store.work is None
    assert store.abandoned_scan_count == 0
    assert store.calls[-4:] == [
        "cancel",
        "abandon_cancelled",
        "delete_work",
        "resume_watcher",
    ]
    assert store.guard_mutation(old_fence, now=NOW) is False
    assert [event.event_type for event in store.audit.events] == [
        "LIBRARY_FULL_SCAN_CANCELLED"
    ]


@pytest.mark.parametrize(
    "current_library",
    (
        _library(config_revision=2),
        _library(state=LibraryControlState.PAUSED),
        _library(state=LibraryControlState.REMOVING),
    ),
)
def test_admin_cancel_uses_terminal_invalidation_for_a_stale_or_frozen_library(
    current_library: ScanLibrarySnapshot,
) -> None:
    original = _library()
    run = _run(
        original, state=ScanState.RUNNING, root_identity="dev:root", expired=True
    )
    store = _Store(current_library, run=run, work=_work(run))

    cancelled = CancelFullLibraryScan(
        unit_of_work_factory=_UnitOfWorkFactory(store),
        clock=_Clock(),
    ).execute(CancelFullLibraryScanCommand("admin-1", "library-1", "scan-1"))

    assert cancelled.state is ScanState.CANCELLED
    assert store.calls[-4:] == [
        "cancel_invalidated",
        "abandon_cancelled",
        "delete_work",
        "resume_watcher",
    ]
    assert store.work is None


@pytest.mark.parametrize("terminal", ("failed", "cancelled"))
@pytest.mark.parametrize(
    ("watcher_pending", "rescan_reason", "expected_follow_up"),
    (
        (False, None, None),
        (True, None, "LIBRARY_RECONCILE_AVAILABLE"),
        (False, FullRescanReason.BACKEND_OVERFLOW, "LIBRARY_FULL_SCAN_REQUIRED"),
    ),
)
def test_terminal_scan_resumes_only_durable_watcher_work(
    terminal: str,
    watcher_pending: bool,
    rescan_reason: FullRescanReason | None,
    expected_follow_up: str | None,
) -> None:
    library = _library()
    run = _run(library, state=ScanState.RUNNING, root_identity="dev:root")
    store = _Store(library, run=run, work=_work(run))
    store.watcher_sequence = 7
    store.watcher_pending = watcher_pending
    store.watcher_full_rescan_reason = rescan_reason

    if terminal == "failed":
        result = FailFullLibraryScan(
            unit_of_work_factory=_UnitOfWorkFactory(store),
            clock=_Clock(),
        ).execute(
            FailFullLibraryScanCommand(
                "library-1",
                "scan-1",
                "worker-1",
                ScanFailureCode.IO_ERROR,
            )
        )
        terminal_event = "LIBRARY_FULL_SCAN_FAILED"
        assert result.state is ScanState.FAILED
    else:
        result = CancelFullLibraryScan(
            unit_of_work_factory=_UnitOfWorkFactory(store),
            clock=_Clock(),
        ).execute(CancelFullLibraryScanCommand("admin-1", "library-1", "scan-1"))
        terminal_event = "LIBRARY_FULL_SCAN_CANCELLED"
        assert result.state is ScanState.CANCELLED

    expected_events = [terminal_event]
    if expected_follow_up is not None:
        expected_events.append(expected_follow_up)
    assert [event.event_type for event in store.outbox.events] == expected_events
    assert store.calls[-1] == "resume_watcher"
    assert store.commits == 1


@pytest.mark.parametrize("terminal", ("failed", "cancelled"))
def test_terminal_watcher_wake_failure_rolls_back_the_scan_transaction(
    terminal: str,
) -> None:
    library = _library()
    run = _run(library, state=ScanState.RUNNING, root_identity="dev:root")
    store = _Store(library, run=run, work=_work(run))
    store.watcher_pending = True
    store.outbox.fail_on_event_type = "LIBRARY_RECONCILE_AVAILABLE"

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        if terminal == "failed":
            FailFullLibraryScan(
                unit_of_work_factory=_UnitOfWorkFactory(store),
                clock=_Clock(),
            ).execute(
                FailFullLibraryScanCommand(
                    "library-1",
                    "scan-1",
                    "worker-1",
                    ScanFailureCode.IO_ERROR,
                )
            )
        else:
            CancelFullLibraryScan(
                unit_of_work_factory=_UnitOfWorkFactory(store),
                clock=_Clock(),
            ).execute(CancelFullLibraryScanCommand("admin-1", "library-1", "scan-1"))

    assert store.rollbacks == 1
    assert store.commits == 0


def test_pending_claim_renews_run_and_root_work_to_one_deadline() -> None:
    library = _library()
    run = replace(_run(library), lease_expires_at=NOW + timedelta(microseconds=1))
    store = _Store(library, run=run, work=_work(run))

    _execute_run(
        store,
        _Discovery("dev:root", {(): ()}),
        admission=_ForbiddenAdmission(),
        lease_seconds=7,
    )

    deadline = NOW + timedelta(seconds=7)
    assert store.scan_lease_updates[0] == ("heartbeat", deadline)
    assert store.work_lease_updates[:2] == [
        ("claim", deadline),
        ("heartbeat", deadline),
    ]
    assert ("start_running", deadline) in store.scan_lease_updates
    assert ("heartbeat", deadline) in store.work_lease_updates


def test_each_large_unit_staging_batch_renews_the_paired_lease_before_commit() -> None:
    library = _library(mode=OrganizationMode.AUDIOBOOK)
    run = _run(library)
    work_path = ("Work",)
    tracks = tuple(_file(("Work", f"Track-{number:04}.mp3")) for number in range(501))
    store = _Store(library, run=run, work=_work(run))

    result = _execute_run(
        store,
        _Discovery("dev:root", {(): (_directory(work_path),), work_path: tracks}),
        admission=_AudioAdmission(),
        lease_seconds=1,
    )

    assert result.units_activated == 1
    batch_indexes = [
        index for index, call in enumerate(store.calls) if call == "append_batch"
    ]
    assert len(batch_indexes) >= 2
    assert all(
        store.calls[index + 1 : index + 3] == ["scan_heartbeat", "work_heartbeat"]
        for index in batch_indexes
    )
    activation_index = store.calls.index("activate")
    assert store.calls[activation_index - 2 : activation_index] == [
        "scan_heartbeat",
        "work_heartbeat",
    ]
    deadline = NOW + timedelta(seconds=1)
    assert all(value == deadline for _kind, value in store.scan_lease_updates)
    assert all(value == deadline for _kind, value in store.work_lease_updates)


@pytest.mark.parametrize(
    "mode",
    (OrganizationMode.AUDIOBOOK, OrganizationMode.VOLUMES),
)
def test_oversized_multi_asset_scan_bounds_opaque_binding_cache(
    monkeypatch: pytest.MonkeyPatch,
    mode: OrganizationMode,
) -> None:
    peak_binding_count = 0
    original_flush = full_scan_execution_module._ScanExecution._flush_slice

    def track_binding_count(
        execution: full_scan_execution_module._ScanExecution,
        *,
        force: bool,
    ) -> None:
        nonlocal peak_binding_count
        original_flush(execution, force=force)
        peak_binding_count = max(
            peak_binding_count,
            len(execution._source_bindings),
        )

    monkeypatch.setattr(
        full_scan_execution_module._ScanExecution,
        "_flush_slice",
        track_binding_count,
    )
    library = _library(mode=mode)
    run = _run(library)
    store = _Store(library, run=run, work=_work(run))

    result = _execute_run(
        store,
        _LazyOversizedDiscovery(mode, MAX_AUDIO_TRACKS * 2),
        admission=_AudioAdmission(),
    )

    assert result.units_activated == 0
    assert store.run is not None and store.run.state is ScanState.COMPLETED
    assert peak_binding_count <= MAX_AUDIO_TRACKS + 500


def test_empty_scan_binds_durable_root_and_finalizes_generation() -> None:
    library = _library(state=LibraryControlState.ACTIVATING)
    run = _run(library)
    store = _Store(library, run=run, work=_work(run))

    result = _execute_run(
        store,
        _Discovery("dev:root", {(): ()}),
        admission=_ForbiddenAdmission(),
    )

    assert result.run.state is ScanState.COMPLETED
    assert result.units_activated == 0
    assert store.synthetic_root_identity == "dev:root"
    assert store.library.last_successful_generation == run.generation
    assert store.library.control_state is LibraryControlState.ACTIVE
    assert store.work is None
    assert store.calls.index("bind_root") < store.calls.index("start_running")
    assert [event.event_type for event in store.outbox.events] == [
        "LIBRARY_FULL_SCAN_COMPLETED"
    ]
    assert store.audit.events == []


def test_finalize_emits_one_reconcile_signal_for_events_after_watermark() -> None:
    library = _library()
    run = _run(library)
    store = _Store(library, run=run, work=_work(run))
    store.watcher_sequence = 1

    _execute_run(
        store,
        _Discovery("dev:root", {(): ()}),
        admission=_ForbiddenAdmission(),
    )

    assert [event.event_type for event in store.outbox.events] == [
        "LIBRARY_FULL_SCAN_COMPLETED",
        "LIBRARY_RECONCILE_AVAILABLE",
    ]


def test_finalize_keeps_concurrent_rescan_fence_and_emits_one_scan_signal() -> None:
    library = _library()
    run = _run(library)
    store = _Store(library, run=run, work=_work(run))
    store.watcher_sequence = 1
    store.watcher_full_rescan_reason = FullRescanReason.BACKEND_OVERFLOW

    _execute_run(
        store,
        _Discovery("dev:root", {(): ()}),
        admission=_ForbiddenAdmission(),
    )

    required = [
        event
        for event in store.outbox.events
        if event.event_type == "LIBRARY_FULL_SCAN_REQUIRED"
    ]
    assert len(required) == 1
    assert dict(required[0].payload) == {
        "scanId": "scan-1",
        "generation": 1,
        "reason": "BACKEND_OVERFLOW",
        "throughSequence": 1,
    }


def test_finalize_follow_up_outbox_failure_rolls_back_terminal_transaction() -> None:
    library = _library()
    run = _run(library)
    store = _Store(library, run=run, work=_work(run))
    store.watcher_sequence = 1
    store.outbox.fail_on_event_type = "LIBRARY_RECONCILE_AVAILABLE"

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        _execute_run(
            store,
            _Discovery("dev:root", {(): ()}),
            admission=_ForbiddenAdmission(),
        )

    assert store.rollbacks == 1
    assert all(
        event.event_type != "LIBRARY_RECONCILE_AVAILABLE"
        for event in store.outbox.events
    )


def test_replaced_physical_root_fails_without_overwriting_durable_identity() -> None:
    library = _library()
    run = _run(library)
    store = _Store(
        library,
        run=run,
        work=_work(run),
        synthetic_root_identity="dev:original",
    )

    with pytest.raises(ScanRootIdentityChanged):
        _execute_run(
            store,
            _Discovery("dev:replacement", {(): ()}),
            admission=_ForbiddenAdmission(),
        )

    assert store.synthetic_root_identity == "dev:original"
    assert store.run is not None
    assert store.run.state is ScanState.FAILED
    assert store.run.failure_code is ScanFailureCode.ROOT_IDENTITY_CHANGED
    assert store.library.observed_health is LibraryHealth.UNAVAILABLE
    assert store.work is None
    assert "start_running" not in store.calls
    assert [event.event_type for event in store.outbox.events] == [
        "LIBRARY_FULL_SCAN_FAILED"
    ]


@pytest.mark.parametrize(
    ("role", "name"),
    (
        (SidecarRole.OPF, "Book.opf"),
        (SidecarRole.ARTWORK, "Book.jpg"),
        (SidecarRole.LYRICS, "Track.lrc"),
        (SidecarRole.CUE, "Album.cue"),
    ),
)
def test_pr5_passes_typed_sidecar_to_source_observation_without_materializing_it(
    role: SidecarRole,
    name: str,
) -> None:
    library = _library()
    run = _run(library)
    store = _Store(library, run=run, work=_work(run))

    result = _execute_run(
        store,
        _Discovery("dev:root", {(): (_file((name,)),)}),
        admission=_SidecarAdmission(role),
    )

    assert result.units_activated == 0
    assert store.plans == []
    assert len(store.observations) == 1
    assert store.content_observation_calls == 1
    admission = store.observations[0].admission
    assert isinstance(admission, SourceAdmissionEvidence)
    assert admission.sidecar_role is role


@pytest.mark.parametrize(
    ("comparison", "first_name", "second_name"),
    (
        (PathComparison.INSENSITIVE, "A.txt", "a.txt"),
        (
            PathComparison.SENSITIVE,
            unicodedata.normalize("NFC", "café.txt"),
            unicodedata.normalize("NFD", "café.txt"),
        ),
    ),
)
@pytest.mark.parametrize("reverse", (False, True))
def test_comparison_collision_blocks_both_spellings_before_materialization(
    comparison: PathComparison,
    first_name: str,
    second_name: str,
    *,
    reverse: bool,
) -> None:
    ordered_names = (second_name, first_name) if reverse else (first_name, second_name)
    paths = ((ordered_names[0],), (ordered_names[1],))
    library = _library(comparison=comparison)
    run = _run(library)
    store = _Store(
        library,
        run=run,
        work=_work(run),
        collision_paths=paths,
    )

    result = _execute_run(
        store,
        _Discovery("dev:root", {(): (_file(paths[0]), _file(paths[1]))}),
        admission=_Admission(),
    )

    assert result.units_activated == 1
    assert [plan.owner_path for plan in store.plans] == [paths[0]]
    assert [value.related_paths for value in store.collisions.values] == [paths]
    activated = [
        event
        for event in store.outbox.events
        if event.event_type == "CATALOG_TOPOLOGY_UNIT_ACTIVATED"
    ]
    assert len(activated) == 1


@pytest.mark.parametrize("unchanged", (False, True))
def test_volumes_first_child_activates_parent_group_atomically(
    unchanged: bool,
) -> None:
    library = _library(mode=OrganizationMode.VOLUMES)
    run = _run(library)
    store = _Store(
        library,
        run=run,
        work=_work(run),
        unchanged_topology=unchanged,
    )
    work = ("Work",)
    version = ("Work", "Edition")
    volume = ("Work", "Edition", "Volume.txt")

    result = _execute_run(
        store,
        _Discovery(
            "dev:root",
            {
                (): (_directory(work),),
                work: (_directory(version),),
                version: (_file(volume),),
            },
        ),
        admission=_Admission(),
    )

    assert result.units_activated == (0 if unchanged else 3)
    assert store.content_observation_calls == 1
    assert len(store.plans) == 3
    assert [len(group) for group in store.activation_groups] == (
        [] if unchanged else [3]
    )
    activated = [
        event
        for event in store.outbox.events
        if event.event_type == "CATALOG_TOPOLOGY_UNIT_ACTIVATED"
    ]
    assert len(activated) == (0 if unchanged else 3)
    assert all(
        {key for key, _value in event.payload}
        == {"scanId", "generation", "unitId", "unitRevisionId"}
        for event in activated
    )


def test_full_scan_reuses_opaque_ids_only_for_the_exact_raw_slot() -> None:
    library = _library()
    first_run = _run(library)
    store = _Store(library, run=first_run, work=_work(first_run))
    original = ("book.txt",)
    original_source = DiscoveredSource(
        original,
        DiscoveryEntryType.FILE,
        "dev:77",
        STAT,
    )

    _execute_run(
        store,
        _Discovery("dev:root", {(): (original_source,)}),
        admission=_Admission(),
    )
    original_source_id = store.source_bindings[original].source_entry_id
    original_work_id = store.work_ids[original_source_id]
    original_unit_id = next(iter(store.unit_ids.values()))

    second_run = _run(store.library, scan_id="scan-2", generation=2)
    store.run = second_run
    store.work = _work(second_run)
    _execute_run(
        store,
        _Discovery("dev:root", {(): (original_source,)}),
        admission=_Admission(),
    )

    assert store.source_bindings[original].source_entry_id == original_source_id
    assert store.work_ids[original_source_id] == original_work_id
    assert original_unit_id in store.unit_ids.values()


def test_full_scan_does_not_infer_offline_rename_from_filesystem_identity() -> None:
    library = _library()
    first_run = _run(library)
    store = _Store(library, run=first_run, work=_work(first_run))
    original = ("book.txt",)
    renamed = ("renamed.txt",)

    _execute_run(
        store,
        _Discovery(
            "dev:root",
            {
                (): (
                    DiscoveredSource(
                        original,
                        DiscoveryEntryType.FILE,
                        "dev:77",
                        STAT,
                    ),
                )
            },
        ),
        admission=_Admission(),
    )
    original_source_id = store.source_bindings[original].source_entry_id
    original_work_id = store.work_ids[original_source_id]

    second_run = _run(store.library, scan_id="scan-2", generation=2)
    store.run = second_run
    store.work = _work(second_run)
    _execute_run(
        store,
        _Discovery(
            "dev:root",
            {
                (): (
                    DiscoveredSource(
                        renamed,
                        DiscoveryEntryType.FILE,
                        "dev:77",
                        STAT,
                    ),
                )
            },
        ),
        admission=_Admission(),
    )

    renamed_source_id = store.source_bindings[renamed].source_entry_id
    assert renamed_source_id != original_source_id
    assert store.work_ids[renamed_source_id] != original_work_id


@pytest.mark.parametrize(
    ("state", "stage", "expected_stage"),
    (
        (ScanState.RUNNING, ScanStage.RECONCILE, ScanStage.DISCOVER),
        (ScanState.FINALIZING, ScanStage.FINALIZE, ScanStage.FINALIZE),
    ),
)
def test_expired_takeover_restarts_nonfinalizing_runs_only(
    state: ScanState,
    stage: ScanStage,
    expected_stage: ScanStage,
) -> None:
    library = _library()
    run = _run(
        library,
        state=state,
        stage=stage,
        root_identity="dev:root",
        expired=True,
    )
    store = _Store(library, run=run, work=_work(run))

    taken = TakeOverFullLibraryScan(
        unit_of_work_factory=_UnitOfWorkFactory(store),
        clock=_Clock(),
    ).execute(
        TakeOverFullLibraryScanCommand(
            "library-1", "scan-1", "worker-2", lease_seconds=60
        )
    )

    assert taken.stage is expected_stage
    assert taken.lease_owner == "worker-2"
    assert store.work is not None and store.work.stage is expected_stage
    assert store.abandoned_scan_count == 1
    assert store.audit.events == []
    assert [event.event_type for event in store.outbox.events] == [
        "LIBRARY_FULL_SCAN_TAKEN_OVER"
    ]
