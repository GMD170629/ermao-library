"""Application ports for watcher journaling and targeted reconciliation."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Literal, Protocol, Self, TypeAlias

from app.modules.catalog.application.content_ports import (
    ContentTopologyActivationRepository,
    SourceContentObservationRepository,
)
from app.modules.catalog.application.ports import OutboxPort
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    ScanFence,
    ScanLibrarySnapshot,
    SourceObservationOutcome,
    SourcePathBinding,
    StagingRevision,
)
from app.modules.catalog.application.scan_ports import DirectoryDiscoveryPort
from app.modules.catalog.application.watcher_dto import (
    BoundTopologyStageBatch,
    BoundTopologyUnitPlan,
    DirectoryPresenceEpoch,
    FullRescanTransition,
    PendingSourceObservation,
    PresenceFoldPage,
    ProvenMoveEvidence,
    ReconcileFence,
    ReconcileIntent,
    SourceRebindResult,
    WatcherFinalizeOutcome,
    WatcherState,
)
from app.modules.catalog.domain.scan import ScanDiagnostic, TopologyUnitPlan
from app.modules.catalog.domain.watcher import (
    FullRescanReason,
    ReconcileScope,
)

TopologyMutationFence: TypeAlias = ScanFence | ReconcileFence


class ReconcileLibraryRepository(Protocol):
    def get_for_reconcile_for_update(
        self, library_id: str
    ) -> ScanLibrarySnapshot | None: ...

    def reserve_reconcile_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
    ) -> int | None: ...


class WatcherJournalRepository(Protocol):
    """Own sequence allocation, coalesced journal rows, and rescan fencing."""

    def get_state_for_update(self, library_id: str) -> WatcherState | None: ...

    def find_overlapping_pending(
        self,
        library_id: str,
        scopes: tuple[ReconcileScope, ...],
        *,
        limit: int,
    ) -> tuple[ReconcileIntent, ...]: ...

    def pending_ids_up_to(self, library_id: str, *, limit: int) -> tuple[str, ...]:
        """Return only IDs; callers use ``limit=2001`` for the hard cap."""

    def append_or_replace(
        self,
        *,
        expected_latest_sequence: int,
        intent: ReconcileIntent,
        replaced_intent_ids: tuple[str, ...],
    ) -> ReconcileIntent | None:
        """CAS the sequence and coalesced PENDING rows without committing."""

    def force_full_rescan(
        self,
        library_id: str,
        *,
        expected_latest_sequence: int,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        """Atomically fence a writer, abandon staging, and delete all intents.

        The operation intentionally leaves orphan pending presence epochs in
        place; a later full scan or bounded fold makes them harmless/clean.
        """

    def force_full_rescan_from_running(
        self,
        fence: ReconcileFence,
        *,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        """Fence and delete the current owned intent without self-staling."""

    def force_full_rescan_from_invalidated(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        """Fence structurally invalidated RUNNING work against current facts.

        Unlike the owned-fence operation, this CAS intentionally proves the
        old running row and the current library snapshot because their frozen
        structural facts no longer match.
        """

    def force_full_rescan_from_pending(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        """Fence structurally stale pending work without allocating a sequence."""

    def get_running_for_update(self, library_id: str) -> ReconcileIntent | None: ...

    def get_next_pending_for_update(
        self, library_id: str, *, now: datetime
    ) -> ReconcileIntent | None:
        """Return the first available row ordered by ``firstSequence,id``."""

    def claim(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None: ...

    def take_over_expired(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        """Fence expired work without leaving unpublished topology behind.

        An expired EXECUTE attempt is restarted from the scope roots and every
        STAGING revision owned by the intent is abandoned in this same CAS.
        An expired FOLD attempt preserves its cursor; reaching FOLD proves that
        the intent owns no STAGING revision.
        """

    def restart_invalidated(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        """Fence invalidated work and restart its scopes from EXECUTE.

        The operation is one CAS that increments the library topology writer
        fence, abandons the old reconcile-origin STAGING revisions, refreshes
        the non-structural snapshot, and invalidates the previous worker.
        """

    def heartbeat(
        self,
        fence: ReconcileFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None: ...

    def has_overlapping_successor(
        self, fence: ReconcileFence, scopes: tuple[ReconcileScope, ...]
    ) -> bool:
        """Return whether overlapping work extends past this intent's through sequence.

        ``firstSequence`` orders claims only. Coalescing may retain an older
        first sequence while advancing ``throughSequence``; therefore a newer
        successor is any overlapping row with ``throughSequence`` greater than
        ``fence.through_sequence``.
        """

    def begin_fold(
        self, fence: ReconcileFence, *, now: datetime
    ) -> ReconcileIntent | None: ...

    def advance_fold_cursor(
        self,
        fence: ReconcileFence,
        *,
        after_source_entry_id: str | None,
        now: datetime,
    ) -> ReconcileIntent | None: ...

    def complete_delete(self, fence: ReconcileFence, *, completed_at: datetime) -> bool:
        """Delete terminal work; history remains in outbox/audit evidence."""

    def invalidate_expired_for_full_scan(
        self,
        library: ScanLibrarySnapshot,
        *,
        now: datetime,
    ) -> FullRescanTransition | None:
        """Fence and delete an expired RUNNING intent before scan start."""

    def finalize_full_scan(
        self,
        library_id: str,
        *,
        watcher_sequence_watermark: int,
        completed_at: datetime,
    ) -> WatcherFinalizeOutcome:
        """Delete covered rows and clear only a fully covered rescan fence."""


class ReconcileSourceRepository(Protocol):
    def get_synthetic_root_identity(self, library_id: str) -> str | None: ...

    def resolve_path_bindings(
        self,
        fence: TopologyMutationFence,
        relative_paths: tuple[tuple[str, ...], ...],
    ) -> tuple[SourcePathBinding, ...]: ...

    def apply_proven_move(
        self,
        fence: ReconcileFence,
        evidence: ProvenMoveEvidence,
        *,
        observed_at: datetime,
    ) -> SourceRebindResult:
        """Preserve IDs only from one current ACTIVE+PRESENT source.

        Hidden, stale, retired, invalid/colliding, absent, ambiguous-identity,
        or destination-colliding sources return ``NOT_PROVEN`` and are handled
        by ordinary scoped reconciliation.
        """

    def begin_directory_presence(
        self,
        fence: ReconcileFence,
        directory: SourcePathBinding,
        *,
        observed_at: datetime,
    ) -> DirectoryPresenceEpoch:
        """Allocate one monotonic proposed epoch for this attempt.

        The directory itself must be effective at its parent's current epoch,
        be top-level, or carry an explicit binding proof equal to its own row's
        pending epoch and the parent's current ``next`` epoch.
        """

    def upsert_reconcile_observations(
        self,
        fence: ReconcileFence,
        observations: tuple[PendingSourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome:
        """Upsert top-level observations without an epoch and nested ones at
        the exact parent ``next`` epoch supplied by the current attempt."""

    def flip_directory_presence(
        self,
        fence: ReconcileFence,
        epoch: DirectoryPresenceEpoch,
        *,
        completed_at: datetime,
    ) -> bool:
        """O(1) CAS current epoch to the attempt's unique proposed epoch."""

    def confirm_top_level_absent(
        self,
        fence: ReconcileFence,
        relative_path: tuple[str, ...],
        *,
        confirmed_at: datetime,
    ) -> None:
        """Idempotently mark a known top-level slot absent.

        A path that has never had a SourceEntry is a successful no-op. Fence
        loss is reported with the typed repository exception, not a boolean.
        """

    def exclude_observed_top_level(
        self,
        fence: ReconcileFence,
        source: DiscoveredSource,
        *,
        excluded_at: datetime,
    ) -> None:
        """Exclude a physically present ignored/noise top-level slot.

        Existing exact rows refresh their physical facts, clear absence, and
        become layout-invalid. An unknown ignored slot remains unmaterialized.
        """

    def fold_effective_presence(
        self,
        fence: ReconcileFence,
        *,
        after_source_entry_id: str | None,
        limit: int,
        folded_at: datetime,
    ) -> PresenceFoldPage:
        """Fold at most 5,000 pending epochs that equal their parent current epoch."""


class ReconcileTopologyRepository(Protocol):
    def bind_plan(
        self,
        fence: TopologyMutationFence,
        plan: TopologyUnitPlan,
        source_bindings: tuple[SourcePathBinding, ...],
    ) -> BoundTopologyUnitPlan | None:
        """Resolve stable IDs from immutable SourceEntry/owner identities.

        Under a live ``ReconcileFence``, a referenced child may either be
        effective at its parent's current epoch or carry the exact pending
        epoch equal to that parent's monotonic ``next`` epoch, and the supplied
        ``SourcePathBinding.pending_parent_presence_epoch`` must carry that
        exact value. The latter is the current directory-attempt proof before
        its O(1) presence flip; older crash-orphan epochs are never accepted.
        This binder-only proof does not broaden query visibility.
        """

    def abandon_incomplete(
        self,
        fence: TopologyMutationFence,
        *,
        unit_id: str,
        abandoned_at: datetime,
    ) -> None: ...

    def get_active_revision_id(
        self, library_id: str, *, unit_id: str
    ) -> str | None: ...

    def begin_staging(
        self,
        fence: TopologyMutationFence,
        plan: BoundTopologyUnitPlan,
        *,
        expected_active_revision_id: str | None,
        created_at: datetime,
    ) -> StagingRevision | None: ...

    def append_staging_batch(
        self,
        fence: TopologyMutationFence,
        staging: StagingRevision,
        batch: BoundTopologyStageBatch,
        *,
        staged_at: datetime,
    ) -> StagingRevision: ...

    def activate_staging_group(
        self,
        fence: TopologyMutationFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> bool: ...


class ReconcileDiagnosticRepository(Protocol):
    def record(
        self,
        fence: ReconcileFence,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None: ...


class WatcherUnitOfWork(Protocol):
    libraries: ReconcileLibraryRepository
    watcher: WatcherJournalRepository
    sources: ReconcileSourceRepository
    content_observations: SourceContentObservationRepository
    content_topology: ContentTopologyActivationRepository
    topology: ReconcileTopologyRepository
    diagnostics: ReconcileDiagnosticRepository
    outbox: OutboxPort

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class WatcherUowFactory(Protocol):
    def __call__(self) -> WatcherUnitOfWork: ...


__all__ = [
    "DirectoryDiscoveryPort",
    "ReconcileDiagnosticRepository",
    "ReconcileLibraryRepository",
    "ReconcileSourceRepository",
    "ReconcileTopologyRepository",
    "TopologyMutationFence",
    "WatcherJournalRepository",
    "WatcherUnitOfWork",
    "WatcherUowFactory",
]
