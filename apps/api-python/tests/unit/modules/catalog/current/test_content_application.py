from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self, cast

import pytest

from app.modules.catalog.application.content_dto import (
    ContentLibrarySnapshot,
    ContentRunDisposition,
    ContentSchedulingOutcome,
    ContentTopologyProjectionBatchOutcome,
    ContentTopologyProjectionState,
    RequiredManifestActivationDisposition,
    RequiredManifestActivationOutcome,
    RequiredManifestCandidate,
    RequiredManifestHeader,
    RequiredManifestStageBatch,
    RequiredManifestState,
    RequiredOpeningDisposition,
    RequiredOpeningEvidence,
    RequiredOpeningProgress,
    RequiredOpeningRequest,
    RequiredOpeningSource,
    RequiredRevisionVector,
    RunNextContentTopologyProjectionCommand,
    RunNextRequiredManifestCommand,
    RunNextRequiredOpeningCommand,
    RunNextSourceDigestCommand,
    SourceContentFact,
    SourceContentState,
    SourceContentWorkFence,
    SourceDigestClaimOutcome,
    SourceDigestEvidence,
    SourceDigestProgress,
    SourceDigestPublishDisposition,
    SourceDigestPublishOutcome,
    SourceDigestRequest,
    SourceDigestWork,
    VolumeProcessingClaimOutcome,
    VolumeProcessingFact,
    VolumeProcessingWorkFence,
    WatcherContentOrigin,
)
from app.modules.catalog.application.content_events import ContentWakeReason
from app.modules.catalog.application.content_ports import (
    ContentLeaseLost,
    ContentUnitOfWork,
    RequiredOpeningCheckpointPort,
    RequiredOpeningOperationalError,
    SourceDigestCheckpointPort,
    SourceDigestIoError,
)
from app.modules.catalog.application.content_processing import (
    RunNextContentTopologyProjection,
    RunNextRequiredManifest,
    RunNextRequiredOpening,
    RunNextSourceDigest,
)
from app.modules.catalog.application.ports import OutboxEvent
from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    ContentProcessorKind,
    ProcessorState,
    RequiredContentAsset,
    RequiredDeliveryPolicy,
    RevisionImpact,
    Sha256Digest,
)
from app.modules.catalog.domain.library import LibraryControlState
from app.modules.catalog.domain.model import AdmissionKind, SourceFormat
from app.modules.catalog.domain.scan import AssetRole, ReadingMorphology

NOW = datetime(2026, 8, 18, tzinfo=UTC)
DIGEST_A = Sha256Digest(f"sha256:{'a' * 64}")
DIGEST_B = Sha256Digest(f"sha256:{'b' * 64}")
STAT = SourceStatExpectation(1, 2, 2_097_152, 4)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Monotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def seconds(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _Ids:
    def new_id(self) -> str:
        return "manifest-new"


class _Outbox:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []
        self.fail = False

    def append(self, event: OutboxEvent) -> None:
        if self.fail:
            raise RuntimeError("outbox failed")
        self.events.append(event)


def _source_fact(
    *,
    input_revision: int = 1,
    state: SourceContentState = SourceContentState.PENDING,
    digest: Sha256Digest | None = None,
) -> SourceContentFact:
    return SourceContentFact(
        library_id="library-1",
        source_entry_id="source-1",
        input_revision=input_revision,
        work_revision=1,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.EPUB,
        filesystem_identity="1:2",
        expected_stat=STAT,
        policy_version=1,
        state=state,
        content_digest=digest,
        digest_input_revision=input_revision if digest is not None else None,
        last_origin=WatcherContentOrigin(1),
        available_at=NOW,
    )


def _digest_work() -> SourceDigestWork:
    fence = SourceContentWorkFence(
        "library-1",
        "source-1",
        1,
        1,
        "worker-1",
        NOW + timedelta(seconds=1),
    )
    return SourceDigestWork(
        fence,
        SourceDigestRequest(
            "library-1",
            "source-1",
            1,
            "/library",
            "dev:root",
            ("Book.epub",),
            STAT,
        ),
    )


def _manifest_facts() -> CanonicalRequiredManifestFacts:
    return CanonicalRequiredManifestFacts(
        topology_version=1,
        reading_morphology=ReadingMorphology.REFLOWABLE,
        delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
        delivery_policy_version=1,
        assets=(
            RequiredContentAsset(
                "asset-1",
                AssetRole.PRIMARY,
                SourceFormat.EPUB,
                STAT.size_bytes,
                DIGEST_A,
                0,
                "application/epub+zip",
            ),
        ),
    )


def _audio_manifest_facts(count: int) -> CanonicalRequiredManifestFacts:
    return CanonicalRequiredManifestFacts(
        topology_version=1,
        reading_morphology=ReadingMorphology.AUDIO,
        delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
        delivery_policy_version=1,
        assets=tuple(
            RequiredContentAsset(
                f"asset-{index}",
                AssetRole.AUDIO_TRACK,
                SourceFormat.MP3,
                10,
                DIGEST_A,
                index,
                "audio/mpeg",
            )
            for index in range(count)
        ),
    )


def _processing(kind: ContentProcessorKind) -> VolumeProcessingFact:
    return VolumeProcessingFact(
        library_id="library-1",
        volume_id="volume-1",
        processor_kind=kind,
        processor_version=f"{kind.value.lower()}-v1",
        work_revision=1,
        active_topology_revision_id="topology-revision-1",
        target_vector=RequiredRevisionVector(0, 0),
        input_fingerprint=DIGEST_A,
        state=ProcessorState.PENDING,
        available_at=NOW,
    )


def _opening_request(count: int = 1) -> RequiredOpeningRequest:
    return RequiredOpeningRequest(
        "library-1",
        "volume-1",
        "topology-revision-1",
        RequiredRevisionVector(1, 1),
        "/library",
        "dev:root",
        tuple(
            RequiredOpeningSource(
                f"source-{index}",
                (f"Book-{index}.epub",),
                SourceFormat.EPUB,
                STAT,
                DIGEST_A,
                index,
            )
            for index in range(count)
        ),
    )


class _Store:
    def __init__(self) -> None:
        self.library_state = LibraryControlState.ACTIVE
        self.source_work: SourceDigestWork | None = _digest_work()
        self.deferred_digest_count = 0
        self.source_fact = _source_fact()
        self.publish_disposition = SourceDigestPublishDisposition.READY_CHANGED
        self.processing_fact: VolumeProcessingFact | None = None
        self.deferred_processing_count = 0
        self.candidate = RequiredManifestCandidate(
            "manifest-template",
            "library-1",
            "volume-1",
            "topology-revision-1",
            RequiredRevisionVector(0, 0),
            _manifest_facts(),
        )
        self.active_manifest: RequiredManifestHeader | None = None
        self.staging: RequiredManifestHeader | None = None
        self.opening_request = _opening_request()
        self.completed_opening: RequiredOpeningEvidence | None = None
        self.scheduled_manifest_count = 0
        self.scheduled_opening_count = 0
        self.digest_heartbeat_count = 0
        self.processing_heartbeat_count = 0
        self.fail_processing_heartbeat_at: int | None = None
        self.required_assets_ready = True
        self.topology_projection_outcome = ContentTopologyProjectionBatchOutcome(
            ContentTopologyProjectionState("library-1", 0, 0, 0, None),
            False,
            0,
        )
        self.topology_projection_limits: list[int] = []
        self.manifest_calls: list[str] = []
        self.outbox = _Outbox()
        self.libraries = self
        self.source_contents = self
        self.processing = self
        self.required_manifests = self
        self.topology_projection = self
        self.commits = 0
        self.rollbacks = 0

    def get_for_content_for_update(
        self, library_id: str
    ) -> ContentLibrarySnapshot | None:
        if library_id != "library-1":
            return None
        return ContentLibrarySnapshot(library_id, self.library_state)

    def project_next_batch(
        self,
        library_id: str,
        *,
        limit: int,
        projected_at: datetime,
    ) -> ContentTopologyProjectionBatchOutcome:
        assert library_id == "library-1"
        assert projected_at == NOW
        self.topology_projection_limits.append(limit)
        return self.topology_projection_outcome

    def claim_next_digest(
        self,
        library_id: str,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
        defer_until: datetime,
    ) -> SourceDigestClaimOutcome:
        assert library_id == "library-1" and owner_token == "worker-1" and now == NOW
        work = self.source_work
        self.source_work = None
        return SourceDigestClaimOutcome(work, self.deferred_digest_count)

    def heartbeat_digest(
        self,
        fence: SourceContentWorkFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> SourceContentWorkFence | None:
        self.digest_heartbeat_count += 1
        return replace(fence, lease_expires_at=lease_expires_at)

    def publish_digest(
        self,
        fence: SourceContentWorkFence,
        evidence: SourceDigestEvidence,
        *,
        published_at: datetime,
    ) -> SourceDigestPublishOutcome | None:
        input_revision = fence.input_revision + int(
            self.publish_disposition
            is SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED
        )
        self.source_fact = _source_fact(
            input_revision=input_revision,
            state=SourceContentState.READY,
            digest=evidence.content_digest,
        )
        return SourceDigestPublishOutcome(
            self.publish_disposition,
            fence.input_revision,
            self.source_fact,
        )

    def release_digest_for_retry(
        self,
        fence: SourceContentWorkFence,
        *,
        diagnostic_code: str,
        retry_at: datetime,
        released_at: datetime,
    ) -> SourceContentFact | None:
        self.source_fact = replace(
            self.source_fact,
            state=SourceContentState.PENDING,
            available_at=retry_at,
            lease_owner=None,
            lease_expires_at=None,
        )
        return self.source_fact

    def schedule_required_manifest_for_digest(
        self,
        outcome: SourceDigestPublishOutcome,
        *,
        scheduled_at: datetime,
    ) -> ContentSchedulingOutcome:
        self.scheduled_manifest_count += 1
        return ContentSchedulingOutcome(1, True)

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
        fact = self.processing_fact
        if fact is None or fact.processor_kind is not processor_kind:
            return VolumeProcessingClaimOutcome(None, self.deferred_processing_count)
        self.processing_fact = replace(
            fact,
            state=ProcessorState.RUNNING,
            lease_owner=owner_token,
            lease_expires_at=lease_expires_at,
            failure_code=None,
        )
        return VolumeProcessingClaimOutcome(
            self.processing_fact,
            self.deferred_processing_count,
        )

    def heartbeat(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> VolumeProcessingFact | None:
        if self.processing_fact is None:
            return None
        self.processing_heartbeat_count += 1
        self.manifest_calls.append("heartbeat")
        if self.processing_heartbeat_count == self.fail_processing_heartbeat_at:
            return None
        self.processing_fact = replace(
            self.processing_fact,
            lease_expires_at=lease_expires_at,
        )
        return self.processing_fact

    def release_for_retry(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        diagnostic_code: str,
        retry_at: datetime,
        released_at: datetime,
    ) -> VolumeProcessingFact | None:
        if self.processing_fact is None:
            return None
        self.processing_fact = replace(
            self.processing_fact,
            state=ProcessorState.PENDING,
            available_at=retry_at,
            lease_owner=None,
            lease_expires_at=None,
            failure_code=None,
        )
        return self.processing_fact

    def load_candidate(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        manifest_id: str,
    ) -> RequiredManifestCandidate | None:
        return replace(self.candidate, manifest_id=manifest_id)

    def get_active_for_update(
        self, library_id: str, volume_id: str
    ) -> RequiredManifestHeader | None:
        return self.active_manifest

    def retarget_active(
        self,
        fence: VolumeProcessingWorkFence,
        candidate: RequiredManifestCandidate,
        impact: RevisionImpact,
        *,
        retargeted_at: datetime,
    ) -> RequiredManifestActivationOutcome | None:
        self.manifest_calls.append("retarget")
        assert self.active_manifest is not None
        if not self.required_assets_ready:
            return None
        self.active_manifest = replace(
            self.active_manifest,
            topology_unit_revision_id=candidate.topology_unit_revision_id,
        )
        return RequiredManifestActivationOutcome(
            RequiredManifestActivationDisposition.REUSED_ACTIVE,
            self.active_manifest.manifest_id,
            candidate.base_revisions,
            candidate.facts.fingerprints,
            impact,
        )

    def abandon_incomplete(
        self, fence: VolumeProcessingWorkFence, *, abandoned_at: datetime
    ) -> None:
        self.staging = None

    def begin_staging(
        self,
        fence: VolumeProcessingWorkFence,
        candidate: RequiredManifestCandidate,
        impact: RevisionImpact,
        *,
        created_at: datetime,
    ) -> RequiredManifestHeader | None:
        self.staging = RequiredManifestHeader(
            candidate.manifest_id,
            candidate.library_id,
            candidate.volume_id,
            candidate.topology_unit_revision_id,
            RequiredManifestState.STAGING,
            candidate.base_revisions,
            None,
            candidate.facts.fingerprints,
            len(candidate.facts.assets),
            0,
        )
        return self.staging

    def append_staging_batch(
        self,
        fence: VolumeProcessingWorkFence,
        staging: RequiredManifestHeader,
        batch: RequiredManifestStageBatch,
        *,
        staged_at: datetime,
    ) -> RequiredManifestHeader | None:
        self.manifest_calls.append("append")
        self.staging = replace(
            staging,
            staged_entry_count=staging.staged_entry_count + len(batch.assets),
        )
        return self.staging

    def activate_staging(
        self,
        fence: VolumeProcessingWorkFence,
        staging: RequiredManifestHeader,
        impact: RevisionImpact,
        *,
        activated_at: datetime,
    ) -> RequiredManifestActivationOutcome | None:
        self.manifest_calls.append("activate")
        published = staging.base_revisions.apply(impact)
        self.active_manifest = replace(
            staging,
            state=RequiredManifestState.ACTIVE,
            published_revisions=published,
        )
        return RequiredManifestActivationOutcome(
            RequiredManifestActivationDisposition.ACTIVATED_NEW,
            staging.manifest_id,
            published,
            staging.fingerprints,
            impact,
        )

    def schedule_required_opening(
        self,
        fence: VolumeProcessingWorkFence,
        outcome: RequiredManifestActivationOutcome,
        *,
        topology_unit_revision_id: str,
        scheduled_at: datetime,
    ) -> ContentSchedulingOutcome | None:
        self.scheduled_opening_count += 1
        return ContentSchedulingOutcome(1, True)

    def load_required_opening_request(
        self, fence: VolumeProcessingWorkFence
    ) -> RequiredOpeningRequest | None:
        return self.opening_request

    def complete_required_opening(
        self,
        fence: VolumeProcessingWorkFence,
        evidence: RequiredOpeningEvidence,
        *,
        completed_at: datetime,
    ) -> VolumeProcessingFact | None:
        assert self.processing_fact is not None
        self.completed_opening = evidence
        self.processing_fact = replace(
            self.processing_fact,
            state=(
                ProcessorState.READY
                if evidence.disposition is RequiredOpeningDisposition.READY
                else ProcessorState.FAILED
            ),
            lease_owner=None,
            lease_expires_at=None,
            failure_code=evidence.diagnostic_code,
        )
        return self.processing_fact

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is not None:
            self.rollbacks += 1
        return False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _Digest:
    def __init__(
        self,
        monotonic: _Monotonic,
        *,
        digest: Sha256Digest = DIGEST_A,
        fail: bool = False,
        pause_after_first_chunk: _Store | None = None,
    ) -> None:
        self.monotonic = monotonic
        self.digest_value = digest
        self.fail = fail
        self.pause_after_first_chunk = pause_after_first_chunk
        self.chunks = 0

    def digest(
        self,
        request: SourceDigestRequest,
        checkpoint: SourceDigestCheckpointPort,
    ) -> SourceDigestEvidence:
        if self.fail:
            raise SourceDigestIoError()
        for cumulative in (1_048_576, request.expected_stat.size_bytes):
            self.chunks += 1
            if self.pause_after_first_chunk is not None and self.chunks == 1:
                self.pause_after_first_chunk.library_state = LibraryControlState.PAUSED
            self.monotonic.advance(0.3)
            checkpoint.checkpoint(
                SourceDigestProgress(
                    request.source_entry_id,
                    request.input_revision,
                    cumulative,
                )
            )
        return SourceDigestEvidence(
            request.source_entry_id,
            request.input_revision,
            request.expected_stat,
            request.expected_stat.size_bytes,
            self.digest_value,
        )


class _Opening:
    def __init__(self, evidence: RequiredOpeningEvidence) -> None:
        self.evidence = evidence

    def inspect(
        self,
        request: RequiredOpeningRequest,
        checkpoint: RequiredOpeningCheckpointPort,
    ) -> RequiredOpeningEvidence:
        bytes_read = 0
        for index, source in enumerate(request.sources, start=1):
            if source.expected_stat.size_bytes:
                bytes_read += 1
                checkpoint.checkpoint(
                    RequiredOpeningProgress(
                        request.volume_id,
                        request.topology_unit_revision_id,
                        bytes_read,
                        index - 1,
                    )
                )
            checkpoint.checkpoint(
                RequiredOpeningProgress(
                    request.volume_id,
                    request.topology_unit_revision_id,
                    bytes_read,
                    index,
                )
            )
        return self.evidence


class _LongOpening:
    def __init__(
        self,
        monotonic: _Monotonic,
        store: _Store,
        *,
        pause_after_sources: int | None = None,
    ) -> None:
        self.monotonic = monotonic
        self.store = store
        self.pause_after_sources = pause_after_sources
        self.sources_inspected = 0

    def inspect(
        self,
        request: RequiredOpeningRequest,
        checkpoint: RequiredOpeningCheckpointPort,
    ) -> RequiredOpeningEvidence:
        for _source in request.sources:
            self.sources_inspected += 1
            self.monotonic.advance(0.3)
            checkpoint.checkpoint(
                RequiredOpeningProgress(
                    request.volume_id,
                    request.topology_unit_revision_id,
                    self.sources_inspected,
                    self.sources_inspected,
                )
            )
            if self.sources_inspected == self.pause_after_sources:
                self.store.library_state = LibraryControlState.PAUSED
        return RequiredOpeningEvidence(
            RequiredOpeningDisposition.READY,
            publication_fingerprint=DIGEST_B,
        )


class _Factory:
    def __init__(self, store: _Store) -> None:
        self.store = store

    def __call__(self) -> ContentUnitOfWork:
        return cast(ContentUnitOfWork, self.store)


def _digest_use_case(store: _Store, digest: _Digest) -> RunNextSourceDigest:
    return RunNextSourceDigest(
        unit_of_work_factory=_Factory(store),
        digest_port=digest,
        clock=_Clock(),
        monotonic_clock=digest.monotonic,
    )


@pytest.mark.parametrize(
    "state",
    (LibraryControlState.PAUSED, LibraryControlState.REMOVING),
)
def test_content_workers_do_not_claim_in_non_active_libraries(
    state: LibraryControlState,
) -> None:
    store = _Store()
    store.library_state = state
    digest = _Digest(_Monotonic())

    result = _digest_use_case(store, digest).execute(
        RunNextSourceDigestCommand("library-1", "worker-1")
    )

    assert result.disposition is ContentRunDisposition.LIBRARY_NOT_ACTIVE
    assert digest.chunks == 0


def test_digest_claim_commits_bounded_deferrals_without_starving_queue() -> None:
    store = _Store()
    store.source_work = None
    store.deferred_digest_count = 3

    result = _digest_use_case(store, _Digest(_Monotonic())).execute(
        RunNextSourceDigestCommand("library-1", "worker-1")
    )

    assert result.disposition is ContentRunDisposition.NO_WORK
    assert store.commits == 1


def test_processing_claim_commits_bounded_deferrals_without_starving_queue() -> None:
    store = _Store()
    store.processing_fact = None
    store.deferred_processing_count = 4

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.NO_WORK
    assert store.commits == 1


def test_digest_checkpoint_stops_after_pause_without_reading_remaining_chunks() -> None:
    store = _Store()
    digest = _Digest(_Monotonic(), pause_after_first_chunk=store)

    result = _digest_use_case(store, digest).execute(
        RunNextSourceDigestCommand("library-1", "worker-1", lease_seconds=1)
    )

    assert result.disposition is ContentRunDisposition.STALE
    assert digest.chunks == 1
    assert store.source_fact.state is SourceContentState.PENDING


def test_swallowed_digest_checkpoint_failure_cannot_publish_after_resume() -> None:
    store = _Store()
    monotonic = _Monotonic()

    class SwallowsLeaseLoss:
        def digest(
            self,
            request: SourceDigestRequest,
            checkpoint: SourceDigestCheckpointPort,
        ) -> SourceDigestEvidence:
            store.library_state = LibraryControlState.PAUSED
            monotonic.advance(0.3)
            with pytest.raises(ContentLeaseLost):
                checkpoint.checkpoint(
                    SourceDigestProgress(
                        request.source_entry_id,
                        request.input_revision,
                        1_048_576,
                    )
                )
            store.library_state = LibraryControlState.ACTIVE
            return SourceDigestEvidence(
                request.source_entry_id,
                request.input_revision,
                request.expected_stat,
                request.expected_stat.size_bytes,
                DIGEST_B,
            )

    result = RunNextSourceDigest(
        unit_of_work_factory=_Factory(store),
        digest_port=SwallowsLeaseLoss(),
        clock=_Clock(),
        monotonic_clock=monotonic,
    ).execute(RunNextSourceDigestCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert store.scheduled_manifest_count == 0
    assert store.source_fact.state is SourceContentState.PENDING


@pytest.mark.parametrize(
    "publication",
    (
        SourceDigestPublishDisposition.READY_UNCHANGED,
        SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED,
    ),
)
def test_every_digest_publication_schedules_manifest_work(
    publication: SourceDigestPublishDisposition,
) -> None:
    store = _Store()
    store.publish_disposition = publication
    digest = _Digest(_Monotonic(), digest=DIGEST_B)

    result = _digest_use_case(store, digest).execute(
        RunNextSourceDigestCommand("library-1", "worker-1")
    )

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert result.publication is publication
    assert store.scheduled_manifest_count == 1
    assert "CATALOG_CONTENT_AVAILABLE" in {
        event.event_type for event in store.outbox.events
    }


def test_digest_operational_error_requeues_without_unreadable_state() -> None:
    store = _Store()
    digest = _Digest(_Monotonic(), fail=True)

    result = _digest_use_case(store, digest).execute(
        RunNextSourceDigestCommand("library-1", "worker-1")
    )

    assert result.disposition is ContentRunDisposition.RETRY_SCHEDULED
    assert store.source_fact.state is SourceContentState.PENDING
    assert store.source_fact.content_digest is None


def test_old_digest_worker_cannot_publish_or_emit_outbox() -> None:
    class StaleStore(_Store):
        def publish_digest(
            self,
            fence: SourceContentWorkFence,
            evidence: SourceDigestEvidence,
            *,
            published_at: datetime,
        ) -> SourceDigestPublishOutcome | None:
            return None

    store = StaleStore()
    result = _digest_use_case(store, _Digest(_Monotonic())).execute(
        RunNextSourceDigestCommand("library-1", "worker-1")
    )

    assert result.disposition is ContentRunDisposition.STALE
    assert store.outbox.events == []


def test_manifest_activation_is_batched_then_opening_is_scheduled() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_MANIFEST)

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert result.activation is RequiredManifestActivationDisposition.ACTIVATED_NEW
    assert store.active_manifest is not None
    assert store.active_manifest.published_revisions == RequiredRevisionVector(1, 1)
    assert store.scheduled_opening_count == 1


def test_topology_projection_processes_one_bounded_batch_and_requeues() -> None:
    store = _Store()
    store.topology_projection_outcome = ContentTopologyProjectionBatchOutcome(
        ContentTopologyProjectionState("library-1", 2, 1, 0, "volume-500"),
        True,
        500,
    )

    result = RunNextContentTopologyProjection(
        unit_of_work_factory=_Factory(store),
        clock=_Clock(),
    ).execute(RunNextContentTopologyProjectionCommand("library-1"))

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert result.processed_volume_count == 500
    assert result.work_remaining is True
    assert store.topology_projection_limits == [500]
    assert store.commits == 1
    assert store.outbox.events[-1].payload == (
        ("reason", ContentWakeReason.TOPOLOGY_ACTIVATED.value),
    )


def test_topology_projection_stable_tail_commits_without_another_wake() -> None:
    store = _Store()
    store.topology_projection_outcome = ContentTopologyProjectionBatchOutcome(
        ContentTopologyProjectionState("library-1", 1, 1, 1, None),
        True,
        500,
    )

    result = RunNextContentTopologyProjection(
        unit_of_work_factory=_Factory(store),
        clock=_Clock(),
    ).execute(RunNextContentTopologyProjectionCommand("library-1"))

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert result.work_remaining is False
    assert store.commits == 1
    assert store.outbox.events == []


def test_topology_projection_empty_old_tail_requeues_successor_epoch() -> None:
    store = _Store()
    store.topology_projection_outcome = ContentTopologyProjectionBatchOutcome(
        ContentTopologyProjectionState("library-1", 2, 2, 1, None),
        True,
        0,
    )

    result = RunNextContentTopologyProjection(
        unit_of_work_factory=_Factory(store),
        clock=_Clock(),
    ).execute(RunNextContentTopologyProjectionCommand("library-1"))

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert result.processed_volume_count == 0
    assert result.work_remaining is True
    assert store.commits == 1
    assert store.outbox.events[-1].payload == (
        ("reason", ContentWakeReason.TOPOLOGY_ACTIVATED.value),
    )


def test_topology_projection_no_work_and_inactive_library_do_not_write() -> None:
    idle = _Store()
    idle_result = RunNextContentTopologyProjection(
        unit_of_work_factory=_Factory(idle),
        clock=_Clock(),
    ).execute(RunNextContentTopologyProjectionCommand("library-1"))

    paused = _Store()
    paused.library_state = LibraryControlState.PAUSED
    paused_result = RunNextContentTopologyProjection(
        unit_of_work_factory=_Factory(paused),
        clock=_Clock(),
    ).execute(RunNextContentTopologyProjectionCommand("library-1"))

    assert idle_result.disposition is ContentRunDisposition.NO_WORK
    assert idle.commits == 0
    assert paused_result.disposition is ContentRunDisposition.LIBRARY_NOT_ACTIVE
    assert paused.topology_projection_limits == []
    assert paused.commits == 0


def test_topology_projection_wake_failure_rolls_back_cursor_batch() -> None:
    store = _Store()
    store.topology_projection_outcome = ContentTopologyProjectionBatchOutcome(
        ContentTopologyProjectionState("library-1", 1, 1, 0, "volume-500"),
        True,
        500,
    )
    store.outbox.fail = True

    with pytest.raises(RuntimeError, match="outbox failed"):
        RunNextContentTopologyProjection(
            unit_of_work_factory=_Factory(store),
            clock=_Clock(),
        ).execute(RunNextContentTopologyProjectionCommand("library-1"))

    assert store.commits == 0
    assert store.rollbacks == 1


def test_manifest_1001_assets_heartbeats_before_three_bounded_batches() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_MANIFEST)
    store.candidate = replace(store.candidate, facts=_audio_manifest_facts(1_001))

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert store.manifest_calls == [
        "heartbeat",
        "heartbeat",
        "append",
        "heartbeat",
        "append",
        "heartbeat",
        "append",
        "heartbeat",
        "activate",
    ]


def test_manifest_lease_loss_mid_staging_never_activates() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_MANIFEST)
    store.candidate = replace(store.candidate, facts=_audio_manifest_facts(1_001))
    store.fail_processing_heartbeat_at = 3

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert store.manifest_calls == [
        "heartbeat",
        "heartbeat",
        "append",
        "heartbeat",
    ]
    assert store.active_manifest is None


def test_same_manifest_retargets_without_incrementing_business_revisions() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_MANIFEST)
    store.candidate = replace(
        store.candidate, base_revisions=RequiredRevisionVector(1, 1)
    )
    store.active_manifest = RequiredManifestHeader(
        "manifest-active",
        "library-1",
        "volume-1",
        "old-topology-revision",
        RequiredManifestState.ACTIVE,
        RequiredRevisionVector(0, 0),
        RequiredRevisionVector(1, 1),
        store.candidate.facts.fingerprints,
        1,
        1,
    )

    assert store.active_manifest.topology_unit_revision_id == "old-topology-revision"

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.activation is RequiredManifestActivationDisposition.REUSED_ACTIVE
    assert store.active_manifest.topology_unit_revision_id == (
        store.candidate.topology_unit_revision_id
    )
    assert store.active_manifest.published_revisions == RequiredRevisionVector(1, 1)
    assert store.scheduled_opening_count == 1


def test_reusing_large_active_manifest_never_batches_asset_restoration() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_MANIFEST)
    store.candidate = replace(
        store.candidate,
        base_revisions=RequiredRevisionVector(1, 1),
        facts=_audio_manifest_facts(10_000),
    )
    store.active_manifest = RequiredManifestHeader(
        "manifest-active",
        "library-1",
        "volume-1",
        "old-topology-revision",
        RequiredManifestState.ACTIVE,
        RequiredRevisionVector(0, 0),
        RequiredRevisionVector(1, 1),
        store.candidate.facts.fingerprints,
        10_000,
        10_000,
    )

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.activation is RequiredManifestActivationDisposition.REUSED_ACTIVE
    assert store.manifest_calls == ["heartbeat", "retarget"]
    assert store.staging is None


def test_active_manifest_with_pending_required_asset_is_not_retargeted() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_MANIFEST)
    store.candidate = replace(
        store.candidate,
        base_revisions=RequiredRevisionVector(1, 1),
        facts=_audio_manifest_facts(10_000),
    )
    store.active_manifest = RequiredManifestHeader(
        "manifest-active",
        "library-1",
        "volume-1",
        "old-topology-revision",
        RequiredManifestState.ACTIVE,
        RequiredRevisionVector(0, 0),
        RequiredRevisionVector(1, 1),
        store.candidate.facts.fingerprints,
        10_000,
        10_000,
    )
    store.required_assets_ready = False

    result = RunNextRequiredManifest(
        unit_of_work_factory=_Factory(store),
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RunNextRequiredManifestCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert store.manifest_calls == ["heartbeat", "retarget"]
    assert store.scheduled_opening_count == 0
    assert store.outbox.events == []


def test_opening_ready_accepts_partial_reads_after_all_sources_complete() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)
    evidence = RequiredOpeningEvidence(
        RequiredOpeningDisposition.READY,
        publication_fingerprint=DIGEST_B,
    )

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=_Opening(evidence),
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.opening is RequiredOpeningDisposition.READY
    assert store.completed_opening == evidence
    assert store.processing_fact is not None
    assert store.processing_fact.state is ProcessorState.READY


def test_opening_progress_allows_format_parser_seek_rereads() -> None:
    class SeekAndReread:
        def inspect(
            self,
            request: RequiredOpeningRequest,
            checkpoint: RequiredOpeningCheckpointPort,
        ) -> RequiredOpeningEvidence:
            for bytes_read in (1_048_576, 2_097_152, 3_145_728):
                checkpoint.checkpoint(
                    RequiredOpeningProgress(
                        request.volume_id,
                        request.topology_unit_revision_id,
                        bytes_read,
                        0,
                    )
                )
            checkpoint.checkpoint(
                RequiredOpeningProgress(
                    request.volume_id,
                    request.topology_unit_revision_id,
                    3_145_728,
                    1,
                )
            )
            return RequiredOpeningEvidence(
                RequiredOpeningDisposition.READY,
                publication_fingerprint=DIGEST_B,
            )

    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=SeekAndReread(),
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.COMPLETED
    assert store.completed_opening is not None


def test_opening_stable_failure_is_the_only_unreadable_completion() -> None:
    class EarlyUnreadable:
        def inspect(
            self,
            request: RequiredOpeningRequest,
            checkpoint: RequiredOpeningCheckpointPort,
        ) -> RequiredOpeningEvidence:
            checkpoint.checkpoint(
                RequiredOpeningProgress(
                    request.volume_id,
                    request.topology_unit_revision_id,
                    1,
                    0,
                )
            )
            return evidence

    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)
    evidence = RequiredOpeningEvidence(
        RequiredOpeningDisposition.UNREADABLE,
        diagnostic_code="FORMAT_INVALID",
    )

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=EarlyUnreadable(),
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.opening is RequiredOpeningDisposition.UNREADABLE
    assert store.processing_fact is not None
    assert store.processing_fact.state is ProcessorState.FAILED


def test_long_opening_stops_after_pause_without_consuming_remaining_sources() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)
    store.opening_request = _opening_request(10_000)
    monotonic = _Monotonic()
    opening = _LongOpening(monotonic, store, pause_after_sources=1)

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=opening,
        clock=_Clock(),
        monotonic_clock=monotonic,
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert opening.sources_inspected == 2
    assert store.completed_opening is None
    assert store.processing_fact is not None
    assert store.processing_fact.state is ProcessorState.PENDING


def test_long_opening_stops_on_lease_loss_before_reading_next_source() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)
    store.opening_request = _opening_request(10_000)
    store.fail_processing_heartbeat_at = 2
    monotonic = _Monotonic()
    opening = _LongOpening(monotonic, store)

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=opening,
        clock=_Clock(),
        monotonic_clock=monotonic,
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert opening.sources_inspected == 1
    assert store.completed_opening is None


@pytest.mark.parametrize("report_partial_progress", (False, True))
def test_opening_cannot_publish_ready_without_complete_source_progress(
    report_partial_progress: bool,
) -> None:
    class EarlyOpening:
        def inspect(
            self,
            request: RequiredOpeningRequest,
            checkpoint: RequiredOpeningCheckpointPort,
        ) -> RequiredOpeningEvidence:
            if report_partial_progress:
                checkpoint.checkpoint(
                    RequiredOpeningProgress(
                        request.volume_id,
                        request.topology_unit_revision_id,
                        1_048_576,
                        0,
                    )
                )
            return RequiredOpeningEvidence(
                RequiredOpeningDisposition.READY,
                publication_fingerprint=DIGEST_B,
            )

    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=EarlyOpening(),
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert store.completed_opening is None
    assert store.processing_fact is not None
    assert store.processing_fact.state is ProcessorState.PENDING


def test_swallowed_checkpoint_failure_permanently_poisons_opening_attempt() -> None:
    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)
    monotonic = _Monotonic()

    class SwallowsLeaseLoss:
        def inspect(
            self,
            request: RequiredOpeningRequest,
            checkpoint: RequiredOpeningCheckpointPort,
        ) -> RequiredOpeningEvidence:
            checkpoint.checkpoint(
                RequiredOpeningProgress(
                    request.volume_id,
                    request.topology_unit_revision_id,
                    1,
                    0,
                )
            )
            store.library_state = LibraryControlState.PAUSED
            monotonic.advance(0.3)
            with pytest.raises(ContentLeaseLost):
                checkpoint.checkpoint(
                    RequiredOpeningProgress(
                        request.volume_id,
                        request.topology_unit_revision_id,
                        1,
                        1,
                    )
                )
            store.library_state = LibraryControlState.ACTIVE
            return RequiredOpeningEvidence(
                RequiredOpeningDisposition.READY,
                publication_fingerprint=DIGEST_B,
            )

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=SwallowsLeaseLoss(),
        clock=_Clock(),
        monotonic_clock=monotonic,
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.STALE
    assert store.completed_opening is None


def test_outbox_failure_rolls_back_digest_publication_transaction() -> None:
    store = _Store()
    store.outbox.fail = True

    with pytest.raises(RuntimeError, match="outbox failed"):
        _digest_use_case(store, _Digest(_Monotonic())).execute(
            RunNextSourceDigestCommand("library-1", "worker-1")
        )

    assert store.rollbacks == 1


def test_opening_operational_error_is_retryable() -> None:
    class RetryOpening:
        def inspect(
            self,
            request: RequiredOpeningRequest,
            checkpoint: RequiredOpeningCheckpointPort,
        ) -> RequiredOpeningEvidence:
            raise RequiredOpeningOperationalError()

    store = _Store()
    store.processing_fact = _processing(ContentProcessorKind.REQUIRED_OPENING)

    result = RunNextRequiredOpening(
        unit_of_work_factory=_Factory(store),
        opening_port=RetryOpening(),
        clock=_Clock(),
        monotonic_clock=_Monotonic(),
    ).execute(RunNextRequiredOpeningCommand("library-1", "worker-1"))

    assert result.disposition is ContentRunDisposition.RETRY_SCHEDULED
    assert store.processing_fact is not None
    assert store.processing_fact.state is ProcessorState.PENDING
