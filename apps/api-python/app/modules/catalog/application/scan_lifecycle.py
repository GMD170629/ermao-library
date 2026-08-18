"""Full-scan lifecycle commands and durable event helpers."""

from __future__ import annotations

import hashlib

from app.modules.catalog.application.ports import (
    AuditEvent,
    Clock,
    IdGenerator,
    OutboxEvent,
)
from app.modules.catalog.application.scan_dto import (
    CancelFullLibraryScanCommand,
    FailFullLibraryScanCommand,
    FinalizeFullLibraryScanCommand,
    FullScanRun,
    FullScanWorkItem,
    HeartbeatFullLibraryScanCommand,
    ScanFailureCode,
    ScanLibrarySnapshot,
    StagingRevision,
    StartFullLibraryScanCommand,
    TakeOverFullLibraryScanCommand,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryDiscoveryPort,
    ScanUnitOfWork,
    ScanUowFactory,
)
from app.modules.catalog.application.scan_runtime_policy import (
    SCANNABLE_LIBRARY_STATES,
    scan_lease_deadline,
)
from app.modules.catalog.application.watcher_dto import (
    WatcherFinalizeOutcome,
    WatcherResumeOutcome,
)
from app.modules.catalog.domain.access import GrantLevel, grant_allows
from app.modules.catalog.domain.library import LibraryHealth
from app.modules.catalog.domain.scan import (
    ScanAuthorizationDenied,
    ScanConflict,
    ScanLeaseLost,
    ScanNotFound,
    ScanRootIdentityChanged,
    ScanStage,
    ScanStale,
    ScanState,
)


def _require_value(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_admin(uow: ScanUnitOfWork, actor_id: str, library_id: str) -> None:
    if not grant_allows(uow.grants.get(actor_id, library_id), GrantLevel.ADMIN):
        raise ScanAuthorizationDenied()


def _scan_event(
    event_type: str,
    *,
    actor_id: str,
    run: FullScanRun,
) -> tuple[AuditEvent, OutboxEvent]:
    payload = (("scanId", run.scan_id), ("generation", run.generation))
    return (
        AuditEvent(event_type, actor_id, run.library_id, payload),
        OutboxEvent(event_type, run.library_id, actor_id, payload),
    )


def _append_events(
    uow: ScanUnitOfWork,
    event_type: str,
    *,
    actor_id: str,
    run: FullScanRun,
) -> None:
    audit, outbox = _scan_event(event_type, actor_id=actor_id, run=run)
    uow.audit.append(audit)
    uow.outbox.append(outbox)


def _append_system_scan_outbox(
    uow: ScanUnitOfWork, event_type: str, *, run: FullScanRun
) -> None:
    uow.outbox.append(
        OutboxEvent(
            event_type,
            run.library_id,
            "SYSTEM",
            (("scanId", run.scan_id), ("generation", run.generation)),
        )
    )


def _append_watcher_follow_up_outbox(
    uow: ScanUnitOfWork,
    *,
    run: FullScanRun,
    outcome: WatcherFinalizeOutcome | WatcherResumeOutcome,
) -> None:
    reason = outcome.state.full_rescan_reason
    if reason is not None:
        uow.outbox.append(
            OutboxEvent(
                "LIBRARY_FULL_SCAN_REQUIRED",
                run.library_id,
                "SYSTEM",
                (
                    ("scanId", run.scan_id),
                    ("generation", run.generation),
                    ("reason", reason.value),
                    (
                        "throughSequence",
                        outcome.state.overflow_through_sequence or 0,
                    ),
                ),
            )
        )
    elif outcome.replay_available:
        uow.outbox.append(
            OutboxEvent(
                "LIBRARY_RECONCILE_AVAILABLE",
                run.library_id,
                "SYSTEM",
                (
                    ("scanId", run.scan_id),
                    ("generation", run.generation),
                    ("latestSequence", outcome.state.latest_sequence),
                ),
            )
        )


def append_activation_outboxes(
    uow: ScanUnitOfWork,
    *,
    run: FullScanRun,
    staging: tuple[StagingRevision, ...],
) -> None:
    for revision in staging:
        uow.outbox.append(
            OutboxEvent(
                "CATALOG_TOPOLOGY_UNIT_ACTIVATED",
                run.library_id,
                "SYSTEM",
                (
                    ("scanId", run.scan_id),
                    ("generation", run.generation),
                    ("unitId", revision.unit_id),
                    ("unitRevisionId", revision.revision_id),
                ),
            )
        )


def _root_work_idempotency_key(library_id: str, generation: int) -> str:
    return hashlib.sha256(f"{library_id}\x00{generation}\x00root".encode()).hexdigest()


def _is_invalidated(
    run: FullScanRun,
    library: ScanLibrarySnapshot,
) -> bool:
    return (
        run.library_id != library.library_id
        or run.canonical_root != library.canonical_root
        or run.config_revision != library.config_revision
        or run.organization_mode is not library.organization_mode
        or run.topology_version != library.topology_version
        or run.path_comparison is not library.path_comparison
        or run.topology_writer_fence != library.topology_writer_fence
        or library.control_state not in SCANNABLE_LIBRARY_STATES
    )


class StartFullLibraryScan:
    def __init__(
        self,
        *,
        unit_of_work_factory: ScanUowFactory,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._id_generator = id_generator
        self._clock = clock

    def execute(self, command: StartFullLibraryScanCommand) -> FullScanRun:
        _require_value(command.actor_id, "actor_id")
        _require_value(command.library_id, "library_id")
        _require_value(command.owner_token, "owner_token")
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            library = uow.libraries.get_for_scan_for_update(command.library_id)
            if library is None:
                raise ScanAuthorizationDenied()
            _require_admin(uow, command.actor_id, command.library_id)
            if library.control_state not in SCANNABLE_LIBRARY_STATES:
                raise ScanConflict()
            active = uow.scans.get_active_for_update(command.library_id)
            if active is not None:
                if not _is_invalidated(active, library):
                    raise ScanConflict()
                cancelled = uow.scans.cancel_invalidated(
                    active,
                    current_library=library,
                    cancelled_at=now,
                )
                if cancelled is None or not uow.topology.abandon_cancelled_scan_staging(
                    active.library_id,
                    active.scan_id,
                    abandoned_at=now,
                ):
                    raise ScanStale()
                if not uow.work_items.delete_for_terminal(
                    active.library_id, active.scan_id
                ):
                    raise ScanStale()
                _append_system_scan_outbox(
                    uow,
                    "LIBRARY_FULL_SCAN_INVALIDATED",
                    run=cancelled,
                )
            watcher_start = uow.watcher.prepare_full_scan_start(library, now=now)
            if watcher_start is None:
                raise ScanConflict()
            reservation = uow.libraries.reserve_topology_writer(
                command.library_id,
                expected_topology_writer_fence=watcher_start.topology_writer_fence,
                expected_next_generation=library.next_scan_generation,
            )
            if reservation is None:
                raise ScanConflict()
            run = FullScanRun(
                scan_id=self._id_generator.new_id(),
                library_id=library.library_id,
                canonical_root=library.canonical_root,
                generation=reservation.generation,
                config_revision=library.config_revision,
                organization_mode=library.organization_mode,
                topology_version=library.topology_version,
                path_comparison=library.path_comparison,
                root_identity=None,
                topology_writer_fence=reservation.topology_writer_fence,
                state=ScanState.PENDING,
                failure_code=None,
                stage=ScanStage.DISCOVER,
                lease_owner=command.owner_token,
                lease_expires_at=lease_expires_at,
                heartbeat_at=now,
                discovered_count=0,
                diagnostic_count=0,
                created_by_actor_id=command.actor_id,
                started_at=None,
                finished_at=None,
                watcher_sequence_watermark=(watcher_start.watcher_sequence_watermark),
            )
            uow.scans.insert(run)
            uow.work_items.insert_root(
                FullScanWorkItem(
                    work_item_id=self._id_generator.new_id(),
                    library_id=run.library_id,
                    scan_id=run.scan_id,
                    root_path_snapshot=run.root_path_snapshot,
                    scope_relative_path=(),
                    state=ScanState.PENDING,
                    stage=ScanStage.DISCOVER,
                    lease_owner=None,
                    lease_expires_at=None,
                    attempt=0,
                    available_at=now,
                    idempotency_key=_root_work_idempotency_key(
                        run.library_id, run.generation
                    ),
                    discovered_count=0,
                )
            )
            _append_events(
                uow, "LIBRARY_FULL_SCAN_STARTED", actor_id=command.actor_id, run=run
            )
            uow.commit()
            return run


class TakeOverFullLibraryScan:
    def __init__(self, *, unit_of_work_factory: ScanUowFactory, clock: Clock) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, command: TakeOverFullLibraryScanCommand) -> FullScanRun:
        _require_value(command.new_owner_token, "new_owner_token")
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            library = uow.libraries.get_for_scan_for_update(command.library_id)
            run = uow.scans.get_for_update(command.library_id, command.scan_id)
            if library is None or run is None:
                raise ScanNotFound()
            if (
                run.state
                not in {ScanState.PENDING, ScanState.RUNNING, ScanState.FINALIZING}
                or run.lease_expires_at is None
                or run.lease_expires_at > now
                or library.control_state not in SCANNABLE_LIBRARY_STATES
            ):
                raise ScanConflict()
            next_fence = uow.libraries.take_over_topology_writer(
                command.library_id,
                expected_topology_writer_fence=run.topology_writer_fence,
            )
            if next_fence is None:
                raise ScanStale()
            taken = uow.scans.take_over_expired(
                run.fence(),
                new_owner_token=command.new_owner_token,
                new_topology_writer_fence=next_fence,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            if taken is None:
                raise ScanConflict()
            work_item = uow.work_items.take_over_expired_root(
                run.fence(),
                new_owner_token=command.new_owner_token,
                new_topology_writer_fence=next_fence,
                now=now,
                lease_expires_at=lease_expires_at,
                restart_from_root=run.state is not ScanState.FINALIZING,
            )
            if work_item is None:
                raise ScanConflict()
            uow.topology.abandon_scan_staging(taken.fence(), abandoned_at=now)
            _append_system_scan_outbox(uow, "LIBRARY_FULL_SCAN_TAKEN_OVER", run=taken)
            uow.commit()
            return taken


class HeartbeatFullLibraryScan:
    def __init__(self, *, unit_of_work_factory: ScanUowFactory, clock: Clock) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, command: HeartbeatFullLibraryScanCommand) -> FullScanRun:
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            run = uow.scans.get_for_update(command.library_id, command.scan_id)
            if run is None:
                raise ScanNotFound()
            if run.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            updated = uow.scans.heartbeat(
                run.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
            )
            if updated is None:
                raise ScanLeaseLost()
            if not uow.work_items.heartbeat_root(
                run.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
                discovered_increment=0,
            ):
                raise ScanLeaseLost()
            uow.commit()
            return updated


class FailFullLibraryScan:
    def __init__(self, *, unit_of_work_factory: ScanUowFactory, clock: Clock) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, command: FailFullLibraryScanCommand) -> FullScanRun:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            run = uow.scans.get_for_update(command.library_id, command.scan_id)
            if run is None:
                raise ScanNotFound()
            if run.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            if run.state not in {
                ScanState.PENDING,
                ScanState.RUNNING,
                ScanState.FINALIZING,
            }:
                raise ScanConflict()
            uow.topology.abandon_scan_staging(run.fence(), abandoned_at=now)
            health = (
                LibraryHealth.UNAVAILABLE
                if command.failure_code
                in {
                    ScanFailureCode.ROOT_UNAVAILABLE,
                    ScanFailureCode.PERMISSION_DENIED,
                    ScanFailureCode.ROOT_IDENTITY_CHANGED,
                }
                else LibraryHealth.ERROR
            )
            if not uow.libraries.set_health_if_fence(
                run.fence(), health=health, observed_at=now
            ):
                raise ScanStale()
            failed = uow.scans.fail(
                run.fence(), failure_code=command.failure_code, failed_at=now
            )
            if failed is None:
                raise ScanStale()
            if not uow.work_items.delete_for_terminal(
                command.library_id, command.scan_id
            ):
                raise ScanStale()
            _append_system_scan_outbox(uow, "LIBRARY_FULL_SCAN_FAILED", run=failed)
            watcher_outcome = uow.watcher.resume_after_full_scan_terminal(
                failed.library_id,
                observed_at=now,
            )
            _append_watcher_follow_up_outbox(
                uow,
                run=failed,
                outcome=watcher_outcome,
            )
            uow.commit()
            return failed


class CancelFullLibraryScan:
    def __init__(self, *, unit_of_work_factory: ScanUowFactory, clock: Clock) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, command: CancelFullLibraryScanCommand) -> FullScanRun:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            library = uow.libraries.get_for_scan_for_update(command.library_id)
            if library is None:
                raise ScanAuthorizationDenied()
            _require_admin(uow, command.actor_id, command.library_id)
            run = uow.scans.get_for_update(command.library_id, command.scan_id)
            if run is None:
                raise ScanNotFound()
            if run.state not in {
                ScanState.PENDING,
                ScanState.RUNNING,
                ScanState.FINALIZING,
            }:
                raise ScanConflict()
            if _is_invalidated(run, library):
                cancelled = uow.scans.cancel_invalidated(
                    run,
                    current_library=library,
                    cancelled_at=now,
                )
            else:
                next_fence = uow.libraries.take_over_topology_writer(
                    command.library_id,
                    expected_topology_writer_fence=run.topology_writer_fence,
                )
                if next_fence is None:
                    raise ScanStale()
                cancelled = uow.scans.cancel(
                    run,
                    cancelled_at=now,
                    next_topology_writer_fence=next_fence,
                )
            if cancelled is None:
                raise ScanStale()
            if not uow.topology.abandon_cancelled_scan_staging(
                command.library_id,
                command.scan_id,
                abandoned_at=now,
            ):
                raise ScanStale()
            if not uow.work_items.delete_for_terminal(
                command.library_id, command.scan_id
            ):
                raise ScanStale()
            _append_events(
                uow,
                "LIBRARY_FULL_SCAN_CANCELLED",
                actor_id=command.actor_id,
                run=cancelled,
            )
            watcher_outcome = uow.watcher.resume_after_full_scan_terminal(
                cancelled.library_id,
                observed_at=now,
            )
            _append_watcher_follow_up_outbox(
                uow,
                run=cancelled,
                outcome=watcher_outcome,
            )
            uow.commit()
            return cancelled


class FinalizeFullLibraryScan:
    def __init__(
        self,
        *,
        unit_of_work_factory: ScanUowFactory,
        discovery: DirectoryDiscoveryPort,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._discovery = discovery
        self._clock = clock

    def execute(self, command: FinalizeFullLibraryScanCommand) -> FullScanRun:
        run = self._load_owned_run(command)
        if run.state is not ScanState.FINALIZING or run.stage is not ScanStage.FINALIZE:
            raise ScanConflict()
        if run.root_identity is None:
            raise ScanStale()
        with self._discovery.open(canonical_root=run.canonical_root) as session:
            if session.root_identity != run.root_identity:
                raise ScanRootIdentityChanged()
            if session.revalidate_root_identity() != run.root_identity:
                raise ScanRootIdentityChanged()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            current = uow.scans.get_for_update(command.library_id, command.scan_id)
            if current is None or current.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            fence = current.fence()
            if current.stage is not ScanStage.FINALIZE:
                raise ScanConflict()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanStale()
            uow.topology.abandon_scan_staging(fence, abandoned_at=now)
            if not uow.libraries.finalize_generation(fence, completed_at=now):
                raise ScanStale()
            watcher_outcome = uow.watcher.finalize_full_scan(
                current.library_id,
                watcher_sequence_watermark=current.watcher_sequence_watermark,
                completed_at=now,
            )
            completed = uow.scans.complete(fence, completed_at=now)
            if completed is None:
                raise ScanStale()
            if not uow.work_items.delete_for_terminal(
                command.library_id, command.scan_id
            ):
                raise ScanStale()
            _append_system_scan_outbox(
                uow, "LIBRARY_FULL_SCAN_COMPLETED", run=completed
            )
            _append_watcher_follow_up_outbox(
                uow,
                run=completed,
                outcome=watcher_outcome,
            )
            uow.commit()
            return completed

    def _load_owned_run(self, command: FinalizeFullLibraryScanCommand) -> FullScanRun:
        with self._unit_of_work_factory() as uow:
            run = uow.scans.get_for_update(command.library_id, command.scan_id)
            if run is None:
                raise ScanNotFound()
            if run.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            return run


__all__ = [
    "CancelFullLibraryScan",
    "FailFullLibraryScan",
    "FinalizeFullLibraryScan",
    "HeartbeatFullLibraryScan",
    "StartFullLibraryScan",
    "TakeOverFullLibraryScan",
    "append_activation_outboxes",
]
