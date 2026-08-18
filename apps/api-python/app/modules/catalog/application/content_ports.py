"""Application ports for dormant PR6A content processing."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Literal, Protocol, Self, TypeAlias

from app.modules.catalog.application.content_dto import (
    ContentLibrarySnapshot,
    ContentSchedulingOutcome,
    ContentTopologyProjectionBatchOutcome,
    ContentTopologyProjectionRequestOutcome,
    ExplicitSourceModify,
    ObservedContentSource,
    RequiredManifestActivationOutcome,
    RequiredManifestCandidate,
    RequiredManifestHeader,
    RequiredManifestStageBatch,
    RequiredOpeningEvidence,
    RequiredOpeningProgress,
    RequiredOpeningRequest,
    SourceContentFact,
    SourceContentObservationOutcome,
    SourceContentWorkFence,
    SourceDigestClaimOutcome,
    SourceDigestEvidence,
    SourceDigestProgress,
    SourceDigestPublishOutcome,
    SourceDigestRequest,
    VolumeProcessingClaimOutcome,
    VolumeProcessingFact,
    VolumeProcessingWorkFence,
)
from app.modules.catalog.application.ports import OutboxPort
from app.modules.catalog.application.scan_dto import ScanFence, StagingRevision
from app.modules.catalog.application.watcher_dto import ReconcileFence
from app.modules.catalog.domain.content import (
    ContentProcessorKind,
    RevisionImpact,
)

ContentMutationFence: TypeAlias = ScanFence | ReconcileFence


class CatalogContentError(RuntimeError):
    code = "CATALOG_CONTENT_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class ContentConflict(CatalogContentError):
    code = "CONTENT_CONFLICT"


class ContentLeaseLost(CatalogContentError):
    code = "CONTENT_LEASE_LOST"


class ContentStale(CatalogContentError):
    code = "CONTENT_STALE"


class SourceDigestOperationalError(RuntimeError):
    """A stable path-free failure from the secure digest boundary."""

    code = "SOURCE_DIGEST_OPERATIONAL_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class InvalidSourceDigestRelativePath(SourceDigestOperationalError):
    code = "INVALID_SOURCE_DIGEST_RELATIVE_PATH"


class SourceDigestIoError(SourceDigestOperationalError):
    code = "SOURCE_DIGEST_IO_ERROR"


class SourceDigestPermissionDenied(SourceDigestOperationalError):
    code = "SOURCE_DIGEST_PERMISSION_DENIED"


class SourceDigestUnavailable(SourceDigestOperationalError):
    code = "SOURCE_DIGEST_UNAVAILABLE"


class SourceDigestRootIdentityChanged(SourceDigestOperationalError):
    code = "SOURCE_DIGEST_ROOT_IDENTITY_CHANGED"


class SourceChangedDuringDigest(SourceDigestOperationalError):
    code = "SOURCE_CHANGED_DURING_DIGEST"


class SourceDigestPort(Protocol):
    """Stream and hash one original source through a no-follow root binding."""

    def digest(
        self,
        request: SourceDigestRequest,
        checkpoint: SourceDigestCheckpointPort,
    ) -> SourceDigestEvidence:
        """Hash in non-empty chunks of at most 1 MiB.

        After every chunk the adapter calls ``checkpoint`` with cumulative
        bytes.  It makes no synthetic zero-byte/EOF callback and propagates a
        checkpoint exception immediately before attempting another read.
        """


class SourceDigestCheckpointPort(Protocol):
    def checkpoint(self, progress: SourceDigestProgress) -> None:
        """Renew/check the owned lease; may raise ``ContentLeaseLost``."""


class RequiredOpeningOperationalError(RuntimeError):
    code = "REQUIRED_OPENING_OPERATIONAL_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class RequiredOpeningPort(Protocol):
    """Perform stable required-source opening without changing topology."""

    def inspect(
        self,
        request: RequiredOpeningRequest,
        checkpoint: RequiredOpeningCheckpointPort,
    ) -> RequiredOpeningEvidence:
        """Inspect through bounded reads and report monotonic progress.

        The adapter reports each non-empty read chunk of at most 1 MiB and each
        completed source.  It propagates a checkpoint exception immediately,
        closes any open source handle, and does not inspect another source.
        READY is accepted only after every source is reported complete; parser
        reads may be partial/seeked and therefore are not a second full digest.
        This generic boundary checks monotonic progress and the per-callback
        1 MiB bound only: legitimate ZIP/PDF parsers can seek and reread bytes.
        Absolute I/O, seek, archive, and expansion budgets belong to each PR6B
        format-specific secure parser facade and its real-filesystem tests.
        A stable UNREADABLE result may stop at the first proven format failure.
        """


class RequiredOpeningCheckpointPort(Protocol):
    def checkpoint(self, progress: RequiredOpeningProgress) -> None:
        """Renew/check the owned lease; may raise ``ContentLeaseLost``."""


class ContentLibraryRepository(Protocol):
    def get_for_content_for_update(
        self, library_id: str
    ) -> ContentLibrarySnapshot | None: ...


class SourceContentObservationRepository(Protocol):
    def observe_sources(
        self,
        fence: ContentMutationFence,
        observations: tuple[ObservedContentSource, ...],
        *,
        observed_at: datetime,
    ) -> SourceContentObservationOutcome:
        """Upsert one fact per file inside the source-observation transaction.

        Exact input retries do not advance ``input_revision``. The structured
        origin is tracking/idempotency evidence only and is never a content
        equality key or a foreign key to a disposable scan/reconcile row.
        An advanced REQUIRED_ASSET input atomically makes its current
        VolumeAsset and affected Volume readiness PENDING without changing an
        ACTIVE manifest or any business revision; an exact retry changes no
        readiness.  A PENDING exact retry may move a future ``available_at``
        forward to ``observed_at`` and report ``work_available=True`` without
        advancing the input revision.  A first SIDECAR/UNSUPPORTED observation
        creates no SourceContentFact.  INELIGIBLE is retained only when an
        existing required fact becomes non-required, so its old digest/lease is
        invalidated without duplicating every irrelevant SourceEntry.
        """

    def mark_explicit_modify(
        self,
        modification: ExplicitSourceModify,
        *,
        observed_at: datetime,
    ) -> SourceContentObservationOutcome | None:
        """Advance once and project PENDING; an exact sequence returns no new work.

        ``None`` means the exact slot is unknown or is not a regular file.  A
        non-``None`` result with ``work_available=False`` is an idempotent
        repeat and must not produce another worker wake.
        """


class SourceContentWorkRepository(Protocol):
    def claim_next_digest(
        self,
        library_id: str,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
        defer_until: datetime,
    ) -> SourceDigestClaimOutcome:
        """Boundedly defer up to 100 facts with no effective active membership."""

    def heartbeat_digest(
        self,
        fence: SourceContentWorkFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> SourceContentWorkFence | None: ...

    def publish_digest(
        self,
        fence: SourceContentWorkFence,
        evidence: SourceDigestEvidence,
        *,
        published_at: datetime,
    ) -> SourceDigestPublishOutcome | None:
        """Publish with an owned CAS and never overwrite a digest revision.

        If a real full read finds different bytes while identity, size, and
        mtime still match an already-READY input, this CAS advances
        ``input_revision`` and publishes the new digest at that new revision.
        It returns ``INPUT_REVISION_ADVANCED``; a stale owner returns ``None``.
        """

    def release_digest_for_retry(
        self,
        fence: SourceContentWorkFence,
        *,
        diagnostic_code: str,
        retry_at: datetime,
        released_at: datetime,
    ) -> SourceContentFact | None: ...


class ContentTopologyActivationRepository(Protocol):
    def record_topology_activation(
        self,
        fence: ContentMutationFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> ContentTopologyProjectionRequestOutcome:
        """Advance one per-Library projection epoch in the pointer transaction.

        This operation never advances content/manifest business revisions and
        never reads or writes descendant Volumes.  Only an idle-to-pending
        transition requests a new library-level wake; a sweep already in
        progress observes a later requested epoch at its bounded tail.
        """


class ContentTopologyProjectionRepository(Protocol):
    def project_next_batch(
        self,
        library_id: str,
        *,
        limit: int,
        projected_at: datetime,
    ) -> ContentTopologyProjectionBatchOutcome:
        """Project at most ``limit`` current Volume mismatches in one UoW.

        The adapter uses a stable ``volumeId`` keyset and reads at most
        ``limit + 1`` current ACTIVE topology/REQUIRED_MANIFEST mismatches.
        It may set only the first ``limit`` Volumes to PENDING and upsert their
        manifest processing facts.  The same transaction advances the durable
        cursor and epoch state.  A requested successor does not interrupt the
        active sweep: at its tail the old claimed epoch becomes applied and a
        new sweep starts from the beginning.  A stable tail makes all three
        epochs equal and removes the cursor.
        """


class VolumeProcessingRepository(Protocol):
    def claim_next(
        self,
        library_id: str,
        processor_kind: ContentProcessorKind,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
        defer_until: datetime,
    ) -> VolumeProcessingClaimOutcome:
        """Boundedly defer up to 100 blocked/stale processor rows."""

    def heartbeat(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> VolumeProcessingFact | None: ...

    def release_for_retry(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        diagnostic_code: str,
        retry_at: datetime,
        released_at: datetime,
    ) -> VolumeProcessingFact | None: ...

    def schedule_required_manifest_for_digest(
        self,
        outcome: SourceDigestPublishOutcome,
        *,
        scheduled_at: datetime,
    ) -> ContentSchedulingOutcome:
        """Retarget current active memberships and project readiness PENDING."""

    def schedule_required_opening(
        self,
        fence: VolumeProcessingWorkFence,
        outcome: RequiredManifestActivationOutcome,
        *,
        topology_unit_revision_id: str,
        scheduled_at: datetime,
    ) -> ContentSchedulingOutcome | None:
        """Retarget or enqueue opening after the manifest CAS in one transaction."""

    def load_required_opening_request(
        self,
        fence: VolumeProcessingWorkFence,
    ) -> RequiredOpeningRequest | None:
        """Load only a manifest fenced to the owning unit's ACTIVE revision.

        A stale Volume READY flag never makes an old-topology manifest current.
        """

    def complete_required_opening(
        self,
        fence: VolumeProcessingWorkFence,
        evidence: RequiredOpeningEvidence,
        *,
        completed_at: datetime,
    ) -> VolumeProcessingFact | None:
        """CAS the current topology and required revision vector to READY."""


class RequiredManifestRepository(Protocol):
    def load_candidate(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        manifest_id: str,
    ) -> RequiredManifestCandidate | None:
        """Build canonical MIME/assets from current READY source digests only."""

    def get_active_for_update(
        self,
        library_id: str,
        volume_id: str,
    ) -> RequiredManifestHeader | None: ...

    def retarget_active(
        self,
        fence: VolumeProcessingWorkFence,
        candidate: RequiredManifestCandidate,
        impact: RevisionImpact,
        *,
        retargeted_at: datetime,
    ) -> RequiredManifestActivationOutcome | None:
        """Reuse identical canonical facts without changing business revisions.

        An ACTIVE entry's source fact revision/stat/identity are immutable build
        provenance, not a permanent delivery fence.  When current READY facts
        retain the same full digest/canonical facts, retarget processing and
        opening to their current expected stat/identity and update the ACTIVE
        header's topology revision fence in O(1), while keeping immutable
        entries and both business revisions unchanged.
        """

    def abandon_incomplete(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        abandoned_at: datetime,
    ) -> None:
        """Delete this Volume's incomplete STAGING header and entries."""

    def begin_staging(
        self,
        fence: VolumeProcessingWorkFence,
        candidate: RequiredManifestCandidate,
        impact: RevisionImpact,
        *,
        created_at: datetime,
    ) -> RequiredManifestHeader | None: ...

    def append_staging_batch(
        self,
        fence: VolumeProcessingWorkFence,
        staging: RequiredManifestHeader,
        batch: RequiredManifestStageBatch,
        *,
        staged_at: datetime,
    ) -> RequiredManifestHeader | None: ...

    def activate_staging(
        self,
        fence: VolumeProcessingWorkFence,
        staging: RequiredManifestHeader,
        impact: RevisionImpact,
        *,
        activated_at: datetime,
    ) -> RequiredManifestActivationOutcome | None:
        """Atomically replace ACTIVE and advance only the owned revisions.

        The final transaction deletes/flushes the previous ACTIVE header and
        entries before promoting the complete STAGING header.  Readers see the
        old committed snapshot before commit and the new one afterwards;
        rollback restores the old manifest.  Each Volume therefore retains at
        most one ACTIVE and one STAGING header.
        """


class ContentUnitOfWork(Protocol):
    libraries: ContentLibraryRepository
    topology_projection: ContentTopologyProjectionRepository
    source_contents: SourceContentWorkRepository
    processing: VolumeProcessingRepository
    required_manifests: RequiredManifestRepository
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


class ContentUowFactory(Protocol):
    def __call__(self) -> ContentUnitOfWork: ...


__all__ = [
    "CatalogContentError",
    "ContentConflict",
    "ContentLeaseLost",
    "ContentLibraryRepository",
    "ContentMutationFence",
    "ContentStale",
    "ContentTopologyActivationRepository",
    "ContentTopologyProjectionRepository",
    "ContentUnitOfWork",
    "ContentUowFactory",
    "InvalidSourceDigestRelativePath",
    "RequiredManifestRepository",
    "RequiredOpeningCheckpointPort",
    "RequiredOpeningOperationalError",
    "RequiredOpeningPort",
    "SourceChangedDuringDigest",
    "SourceContentObservationRepository",
    "SourceContentWorkRepository",
    "SourceDigestCheckpointPort",
    "SourceDigestIoError",
    "SourceDigestOperationalError",
    "SourceDigestPermissionDenied",
    "SourceDigestPort",
    "SourceDigestRootIdentityChanged",
    "SourceDigestUnavailable",
    "VolumeProcessingRepository",
]
