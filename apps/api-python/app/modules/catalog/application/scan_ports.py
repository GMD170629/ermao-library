"""Ports owned by the full-scan application workflow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import Literal, Protocol, Self

from app.modules.catalog.application.ports import (
    AuditPort,
    LibraryGrantRepository,
    OutboxPort,
)
from app.modules.catalog.application.scan_dto import (
    DiscoveryObservation,
    FullScanRun,
    FullScanWorkItem,
    PathCollision,
    ScanFailureCode,
    ScanFence,
    ScanLibrarySnapshot,
    SourceObservation,
    SourceObservationOutcome,
    StagingRevision,
    WriterReservation,
)
from app.modules.catalog.domain.library import LibraryHealth
from app.modules.catalog.domain.scan import (
    ScanDiagnostic,
    ScanStage,
    TopologyStageBatch,
    TopologyUnitPlan,
)


class DirectoryDiscoveryOperationalError(RuntimeError):
    """Path-free operational error raised by a read-only discovery adapter."""

    code = "DIRECTORY_DISCOVERY_OPERATIONAL_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class DirectoryRootUnavailable(DirectoryDiscoveryOperationalError):
    code = "DIRECTORY_ROOT_UNAVAILABLE"


class DirectoryPermissionDenied(DirectoryDiscoveryOperationalError):
    code = "DIRECTORY_PERMISSION_DENIED"


class DirectoryIoError(DirectoryDiscoveryOperationalError):
    code = "DIRECTORY_IO_ERROR"


class DirectoryChangedDuringDiscovery(DirectoryDiscoveryOperationalError):
    code = "DIRECTORY_CHANGED_DURING_DISCOVERY"


class InvalidDiscoveryRelativePath(DirectoryDiscoveryOperationalError):
    code = "INVALID_DISCOVERY_RELATIVE_PATH"


class DirectoryDiscoverySession(
    AbstractContextManager["DirectoryDiscoverySession"], Protocol
):
    """One no-follow root binding with lazy direct-directory iterators.

    A session may enumerate several directories. Each returned iterator is
    single-use and must release its directory handle on exhaustion, error, or
    session exit.
    """

    @property
    def root_identity(self) -> str: ...

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]: ...

    def revalidate_root_identity(self) -> str:
        """Freshly walk the canonical binding and return its current identity."""


class DirectoryDiscoveryPort(Protocol):
    def open(self, *, canonical_root: str) -> DirectoryDiscoverySession: ...


class MonotonicClock(Protocol):
    def seconds(self) -> float: ...


class ScanLibraryRepository(Protocol):
    def get_for_scan_for_update(
        self, library_id: str
    ) -> ScanLibrarySnapshot | None: ...

    def reserve_topology_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
        expected_next_generation: int,
    ) -> WriterReservation | None: ...

    def take_over_topology_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
    ) -> int | None: ...

    def finalize_generation(self, fence: ScanFence, *, completed_at: datetime) -> bool:
        """Advance last-success and ACTIVATING -> ACTIVE under the full fence."""

    def set_health_if_fence(
        self,
        fence: ScanFence,
        *,
        health: LibraryHealth,
        observed_at: datetime,
    ) -> bool: ...


class FullScanRepository(Protocol):
    def get_active_for_update(self, library_id: str) -> FullScanRun | None: ...

    def get_for_update(self, library_id: str, scan_id: str) -> FullScanRun | None: ...

    def insert(self, run: FullScanRun) -> None: ...

    def start_running(
        self,
        fence: ScanFence,
        *,
        root_identity: str,
        started_at: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None: ...

    def take_over_expired(
        self,
        fence: ScanFence,
        *,
        new_owner_token: str,
        new_topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        """Restart PENDING/RUNNING at root; retain FINALIZING for final CAS."""

        ...

    def guard_mutation(self, fence: ScanFence, *, now: datetime) -> bool:
        """CAS snapshot, legal live state/stage, owner, fence and live lease."""

    def heartbeat(
        self,
        fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int = 0,
        diagnostic_increment: int = 0,
    ) -> FullScanRun | None: ...

    def set_stage(
        self,
        fence: ScanFence,
        *,
        expected_stage: ScanStage,
        next_stage: ScanStage,
        now: datetime,
    ) -> bool: ...

    def begin_finalizing(
        self,
        fence: ScanFence,
        *,
        expected_stage: ScanStage,
        now: datetime,
    ) -> FullScanRun | None:
        """CAS RUNNING/RECONCILE to FINALIZING/FINALIZE."""

    def complete(
        self, fence: ScanFence, *, completed_at: datetime
    ) -> FullScanRun | None: ...

    def fail(
        self,
        fence: ScanFence,
        *,
        failure_code: ScanFailureCode,
        failed_at: datetime,
    ) -> FullScanRun | None: ...

    def cancel(
        self,
        run: FullScanRun,
        *,
        cancelled_at: datetime,
        next_topology_writer_fence: int,
    ) -> FullScanRun | None: ...

    def cancel_invalidated(
        self,
        run: FullScanRun,
        *,
        current_library: ScanLibrarySnapshot,
        cancelled_at: datetime,
    ) -> FullScanRun | None:
        """CAS-cancel a live run whose frozen library snapshot is no longer current."""

    def restart_from_root(
        self,
        fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        """Reset a non-finalizing live run to RUNNING/DISCOVER."""


class RootScanWorkRepository(Protocol):
    def insert_root(self, work_item: FullScanWorkItem) -> None: ...

    def get_root_for_update(
        self, library_id: str, scan_id: str
    ) -> FullScanWorkItem | None: ...

    def claim_pending_root(
        self,
        fence: ScanFence,
        *,
        work_item_id: str,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanWorkItem | None: ...

    def take_over_expired_root(
        self,
        fence: ScanFence,
        *,
        new_owner_token: str,
        new_topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
        restart_from_root: bool,
    ) -> FullScanWorkItem | None: ...

    def heartbeat_root(
        self,
        fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int,
    ) -> bool: ...

    def set_stage(
        self,
        fence: ScanFence,
        *,
        expected_stage: ScanStage,
        next_stage: ScanStage,
    ) -> bool: ...

    def delete_for_terminal(self, library_id: str, scan_id: str) -> bool: ...


class SourceObservationRepository(Protocol):
    def bind_synthetic_root(
        self,
        fence: ScanFence,
        *,
        observed_identity: str,
        observed_at: datetime,
    ) -> bool:
        """Create the first root evidence or stamp an exactly matching identity."""

    def upsert_observations(
        self,
        fence: ScanFence,
        observations: tuple[SourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome: ...


class PathCollisionRepository(Protocol):
    def record(
        self,
        fence: ScanFence,
        collisions: tuple[PathCollision, ...],
        *,
        observed_at: datetime,
    ) -> None: ...


class ScanDiagnosticRepository(Protocol):
    def record(
        self,
        fence: ScanFence,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None: ...


class TopologyRepository(Protocol):
    def abandon_scan_staging(self, fence: ScanFence, *, abandoned_at: datetime) -> None:
        """Boundedly mark every STAGING revision owned by this scan ABANDONED."""

    def abandon_cancelled_scan_staging(
        self,
        library_id: str,
        scan_id: str,
        *,
        abandoned_at: datetime,
    ) -> bool:
        """Clean staging only after proving the named run is already CANCELLED."""

    def abandon_incomplete(
        self, fence: ScanFence, *, unit_key: str, abandoned_at: datetime
    ) -> None: ...

    def get_active_revision_id(
        self, library_id: str, *, unit_key: str
    ) -> str | None: ...

    def begin_staging(
        self,
        fence: ScanFence,
        plan: TopologyUnitPlan,
        *,
        expected_active_revision_id: str | None,
        created_at: datetime,
    ) -> StagingRevision | None:
        """Return None when the active projection is structurally unchanged."""

    def append_staging_batch(
        self,
        fence: ScanFence,
        staging: StagingRevision,
        batch: TopologyStageBatch,
        *,
        staged_at: datetime,
    ) -> StagingRevision: ...

    def activate_staging_group(
        self,
        fence: ScanFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> bool:
        """Atomically validate complete revisions and move every group pointer."""


class ScanUnitOfWork(Protocol):
    libraries: ScanLibraryRepository
    scans: FullScanRepository
    work_items: RootScanWorkRepository
    sources: SourceObservationRepository
    topology: TopologyRepository
    diagnostics: ScanDiagnosticRepository
    collisions: PathCollisionRepository
    grants: LibraryGrantRepository
    audit: AuditPort
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


class ScanUowFactory(Protocol):
    def __call__(self) -> ScanUnitOfWork: ...


__all__ = [
    "DirectoryChangedDuringDiscovery",
    "DirectoryDiscoveryOperationalError",
    "DirectoryDiscoveryPort",
    "DirectoryDiscoverySession",
    "DirectoryIoError",
    "DirectoryPermissionDenied",
    "DirectoryRootUnavailable",
    "FullScanRepository",
    "InvalidDiscoveryRelativePath",
    "MonotonicClock",
    "PathCollisionRepository",
    "RootScanWorkRepository",
    "ScanDiagnosticRepository",
    "ScanLibraryRepository",
    "ScanUnitOfWork",
    "ScanUowFactory",
    "SourceObservationRepository",
    "TopologyRepository",
]
