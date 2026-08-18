from __future__ import annotations

import unicodedata
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from app.modules.catalog.application.content_dto import (
    ContentTopologyProjectionBatchOutcome,
    ContentTopologyProjectionRequestOutcome,
    ContentTopologyProjectionState,
    FullScanContentOrigin,
    ObservedContentSource,
    ReconcileContentOrigin,
    RequiredManifestActivationDisposition,
    RequiredManifestActivationOutcome,
    RequiredManifestCandidate,
    RequiredManifestHeader,
    RequiredManifestStageBatch,
    RequiredManifestState,
    RequiredOpeningProgress,
    RequiredRevisionVector,
    SourceContentFact,
    SourceContentObservationOutcome,
    SourceContentWorkFence,
    SourceDigestEvidence,
    SourceDigestProgress,
    SourceDigestPublishDisposition,
    SourceDigestPublishOutcome,
    SourceDigestRequest,
    SourceDigestWork,
    VolumeContentVector,
    VolumeProcessingFact,
    VolumeProcessingWorkFence,
    WatcherContentOrigin,
)
from app.modules.catalog.application.content_observations import (
    observed_content_sources,
)
from app.modules.catalog.application.content_ports import (
    SourceDigestCheckpointPort,
    SourceDigestPort,
    SourceDigestRootIdentityChanged,
)
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    PathCollision,
    SourceObservation,
    SourceObservationOutcome,
)
from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.admission import (
    DirectFileEvidence,
    SourceAdmissionEvidence,
)
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    ContentProcessorKind,
    ProcessorState,
    RequiredContentAsset,
    RequiredDeliveryPolicy,
    RevisionImpact,
    Sha256Digest,
    SourceContentState,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    SidecarRole,
    SourceFormat,
)
from app.modules.catalog.domain.scan import AssetRole, ReadingMorphology

NOW = datetime(2026, 8, 18, tzinfo=UTC)
STAT = SourceStatExpectation(1, 2, 3, 4)
DIGEST = Sha256Digest(f"sha256:{'a' * 64}")


def test_required_opening_progress_requires_real_monotonic_work() -> None:
    with pytest.raises(ValueError, match="must advance"):
        RequiredOpeningProgress("volume-1", "revision-1", 0, 0)

    assert (
        RequiredOpeningProgress(
            "volume-1", "revision-1", 1_048_576, 1
        ).sources_completed
        == 1
    )


def test_required_manifest_has_only_active_and_staging_states() -> None:
    assert set(RequiredManifestState) == {
        RequiredManifestState.STAGING,
        RequiredManifestState.ACTIVE,
    }


def test_content_topology_projection_state_models_bounded_successor_sweeps() -> None:
    idle = ContentTopologyProjectionState("library-1", 0, 0, 0, None)
    pending = ContentTopologyProjectionState("library-1", 1, 0, 0, None)
    active = ContentTopologyProjectionState("library-1", 1, 1, 0, "volume-500")
    successor = ContentTopologyProjectionState("library-1", 2, 1, 0, "volume-500")
    restarted = ContentTopologyProjectionState("library-1", 2, 2, 1, None)

    assert idle.work_remaining is False
    assert pending.work_remaining is True
    assert active.work_remaining is True
    assert successor.work_remaining is True
    assert restarted.work_remaining is True
    with pytest.raises(ValueError, match="epoch order"):
        ContentTopologyProjectionState("library-1", 1, 0, 1, None)
    with pytest.raises(ValueError, match="active sweep"):
        ContentTopologyProjectionState("library-1", 1, 1, 1, "volume-1")


def test_content_topology_projection_outcomes_are_bounded_and_explicit() -> None:
    idle = ContentTopologyProjectionState("library-1", 1, 1, 1, None)
    active = ContentTopologyProjectionState("library-1", 1, 1, 0, "volume-500")

    assert ContentTopologyProjectionRequestOutcome(active, True).wake_required is True
    projected = ContentTopologyProjectionBatchOutcome(active, True, 500)
    assert projected.work_remaining is True
    assert ContentTopologyProjectionBatchOutcome(idle, True, 0).work_remaining is False
    with pytest.raises(ValueError, match="at most 500"):
        ContentTopologyProjectionBatchOutcome(active, True, 501)
    with pytest.raises(ValueError, match="NO_WORK"):
        ContentTopologyProjectionBatchOutcome(active, False, 0)


def facts() -> CanonicalRequiredManifestFacts:
    return CanonicalRequiredManifestFacts(
        topology_version=1,
        reading_morphology=ReadingMorphology.REFLOWABLE,
        delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
        delivery_policy_version=1,
        assets=(
            RequiredContentAsset(
                asset_id="asset-1",
                role=AssetRole.PRIMARY,
                source_format=SourceFormat.EPUB,
                size_bytes=3,
                content_digest=DIGEST,
                order=0,
                mime_type="application/epub+zip",
            ),
        ),
    )


def ready_fact(*, input_revision: int = 1) -> SourceContentFact:
    return SourceContentFact(
        library_id="library-1",
        source_entry_id="source-1",
        input_revision=input_revision,
        work_revision=2,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.EPUB,
        filesystem_identity="1:2",
        expected_stat=STAT,
        policy_version=1,
        state=SourceContentState.READY,
        content_digest=DIGEST,
        digest_input_revision=input_revision,
        last_origin=WatcherContentOrigin(9),
        available_at=NOW,
    )


def observed_pdf(name: str) -> SourceObservation:
    path = (name,)
    return SourceObservation(
        DiscoveredSource(path, DiscoveryEntryType.FILE, f"id:{name}", STAT),
        1,
        SourceAdmissionEvidence(
            path,
            EntryType.FILE,
            AdmissionKind.PRIMARY,
            SourceFormat.PDF,
            evidence=DirectFileEvidence(SourceFormat.PDF, 1, 1),
        ),
    )


def test_origins_are_structured_and_never_include_a_source_path() -> None:
    assert FullScanContentOrigin("scan-1", 4).token == "FULL_SCAN:scan-1:4"
    assert ReconcileContentOrigin("intent-1", 7).token == ("RECONCILE:intent-1:7")
    assert WatcherContentOrigin(9).token == "WATCHER:9"
    assert WatcherContentOrigin(9) == WatcherContentOrigin(9)


def test_observed_content_preserves_nfd_and_keeps_sidecar_transient() -> None:
    nfd_name = unicodedata.normalize("NFD", "é") + ".opf"
    observed = ObservedContentSource(
        source_entry_id="source-1",
        relative_path=(nfd_name,),
        filesystem_identity="1:2",
        expected_stat=STAT,
        admission=AdmissionKind.SIDECAR,
        source_format=None,
        sidecar_role=SidecarRole.OPF,
        policy_version=1,
        origin=FullScanContentOrigin("scan-1", 1),
    )

    assert observed.relative_path == (nfd_name,)
    with pytest.raises(ValueError, match="strict UTF-8"):
        ObservedContentSource(
            source_entry_id="source-1",
            relative_path=("bad\ud800.epub",),
            filesystem_identity="1:2",
            expected_stat=STAT,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.EPUB,
            sidecar_role=None,
            policy_version=1,
            origin=FullScanContentOrigin("scan-1", 1),
        )
    with pytest.raises(ValueError, match="AUDIO_TRACK"):
        ObservedContentSource(
            source_entry_id="source-1",
            relative_path=("track.mp3",),
            filesystem_identity="1:2",
            expected_stat=STAT,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.MP3,
            sidecar_role=None,
            policy_version=1,
            origin=FullScanContentOrigin("scan-1", 1),
        )


def test_content_mapper_skips_both_collision_paths_but_not_missing_bindings() -> None:
    observations = (observed_pdf("A.pdf"), observed_pdf("a.pdf"))
    collision = PathCollision((), "a.pdf", (("A.pdf",), ("a.pdf",)))

    assert (
        observed_content_sources(
            observations,
            SourceObservationOutcome(collisions=(collision,)),
            origin=FullScanContentOrigin("scan-1", 1),
        )
        == ()
    )

    with pytest.raises(ValueError, match="exact source binding"):
        observed_content_sources(
            (observed_pdf("Book.pdf"),),
            SourceObservationOutcome(),
            origin=FullScanContentOrigin("scan-1", 1),
        )


def test_content_observation_outcome_exposes_only_new_required_work() -> None:
    fact = ready_fact()
    assert SourceContentObservationOutcome((fact,), 1, True).work_available is True
    assert SourceContentObservationOutcome((fact,), 0, False).work_available is False
    assert SourceContentObservationOutcome((fact,), 0, True).work_available is True


def test_source_fact_requires_current_digest_for_ready() -> None:
    with pytest.raises(ValueError, match="current input revision"):
        SourceContentFact(
            library_id="library-1",
            source_entry_id="source-1",
            input_revision=2,
            work_revision=1,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.EPUB,
            filesystem_identity="1:2",
            expected_stat=STAT,
            policy_version=1,
            state=SourceContentState.READY,
            content_digest=DIGEST,
            digest_input_revision=1,
            last_origin=WatcherContentOrigin(9),
            available_at=NOW,
        )

    with pytest.raises(ValueError, match="complete lease"):
        replace(
            ready_fact(),
            state=SourceContentState.RUNNING,
            lease_owner="worker-1",
            lease_expires_at=None,
        )
    with pytest.raises(ValueError, match="complete lease"):
        replace(
            ready_fact(),
            state=SourceContentState.RUNNING,
            lease_owner=None,
            lease_expires_at=NOW,
        )


def test_digest_contract_carries_root_stat_and_owned_revision() -> None:
    fence = SourceContentWorkFence(
        library_id="library-1",
        source_entry_id="source-1",
        input_revision=1,
        work_revision=2,
        owner_token="worker-1",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    request = SourceDigestRequest(
        library_id="library-1",
        source_entry_id="source-1",
        input_revision=1,
        canonical_root="/raw/root",
        expected_root_identity="1:99",
        relative_path=("Book.epub",),
        expected_stat=STAT,
    )
    evidence = SourceDigestEvidence(
        source_entry_id="source-1",
        input_revision=1,
        observed_stat=STAT,
        bytes_hashed=3,
        content_digest=DIGEST,
    )

    assert SourceDigestWork(fence, request).request == request
    assert evidence.bytes_hashed == request.expected_stat.size_bytes
    assert SourceDigestRootIdentityChanged.code == (
        "SOURCE_DIGEST_ROOT_IDENTITY_CHANGED"
    )
    with pytest.raises(ValueError, match="invalid component"):
        SourceDigestRequest(
            library_id="library-1",
            source_entry_id="source-1",
            input_revision=1,
            canonical_root="/raw/root",
            expected_root_identity="1:99",
            relative_path=("C:drive.epub",),
            expected_stat=STAT,
        )


def test_same_stat_different_digest_outcome_must_advance_input_revision() -> None:
    advanced = SourceDigestPublishOutcome(
        disposition=SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED,
        claimed_input_revision=1,
        current=ready_fact(input_revision=2),
    )
    assert advanced.current.input_revision == 2

    with pytest.raises(ValueError, match="invalid input revision"):
        SourceDigestPublishOutcome(
            disposition=SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED,
            claimed_input_revision=1,
            current=ready_fact(input_revision=1),
        )


def test_processing_vector_excludes_optional_and_metadata_axes() -> None:
    vector = VolumeContentVector(3, 5, 7, 11)
    target = RequiredRevisionVector.from_volume(vector)
    processing = VolumeProcessingFact(
        library_id="library-1",
        volume_id="volume-1",
        processor_kind=ContentProcessorKind.REQUIRED_OPENING,
        processor_version="required-opening-v1",
        work_revision=1,
        active_topology_revision_id="topology-revision-1",
        target_vector=target,
        input_fingerprint=DIGEST,
        state=ProcessorState.PENDING,
        available_at=NOW,
    )

    assert processing.target_vector == RequiredRevisionVector(3, 5)

    with pytest.raises(ValueError, match="complete lease"):
        replace(
            processing,
            state=ProcessorState.RUNNING,
            lease_owner="worker-1",
            lease_expires_at=None,
        )
    with pytest.raises(ValueError, match="complete lease"):
        replace(
            processing,
            state=ProcessorState.RUNNING,
            lease_owner=None,
            lease_expires_at=NOW,
        )


def test_content_work_fences_require_typed_lease_deadlines() -> None:
    with pytest.raises(TypeError, match="lease_expires_at"):
        SourceContentWorkFence(
            "library-1",
            "source-1",
            1,
            1,
            "worker-1",
            cast(datetime, None),
        )
    with pytest.raises(TypeError, match="lease_expires_at"):
        VolumeProcessingWorkFence(
            "library-1",
            "volume-1",
            ContentProcessorKind.REQUIRED_MANIFEST,
            1,
            "worker-1",
            cast(datetime, None),
        )


def test_manifest_staging_and_reuse_outcome_are_typed() -> None:
    candidate = RequiredManifestCandidate(
        manifest_id="manifest-1",
        library_id="library-1",
        volume_id="volume-1",
        topology_unit_revision_id="topology-revision-1",
        base_revisions=RequiredRevisionVector(1, 1),
        facts=facts(),
    )
    header = RequiredManifestHeader(
        manifest_id=candidate.manifest_id,
        library_id=candidate.library_id,
        volume_id=candidate.volume_id,
        topology_unit_revision_id=candidate.topology_unit_revision_id,
        state=RequiredManifestState.STAGING,
        base_revisions=candidate.base_revisions,
        published_revisions=None,
        fingerprints=candidate.facts.fingerprints,
        expected_entry_count=1,
        staged_entry_count=0,
    )
    batch = RequiredManifestStageBatch(
        start_order=0,
        assets=candidate.facts.assets,
        complete=True,
    )
    no_change = RevisionImpact(0, 0, False, False, False, True)
    outcome = RequiredManifestActivationOutcome(
        disposition=RequiredManifestActivationDisposition.REUSED_ACTIVE,
        active_manifest_id="manifest-active",
        published_revisions=candidate.base_revisions,
        fingerprints=candidate.facts.fingerprints,
        revision_impact=no_change,
    )

    assert header.state is RequiredManifestState.STAGING
    assert batch.complete is True
    assert outcome.published_revisions == candidate.base_revisions


def test_source_digest_port_is_a_small_sync_boundary() -> None:
    class FakeDigest:
        def digest(
            self,
            request: SourceDigestRequest,
            checkpoint: SourceDigestCheckpointPort,
        ) -> SourceDigestEvidence:
            return SourceDigestEvidence(
                source_entry_id=request.source_entry_id,
                input_revision=request.input_revision,
                observed_stat=request.expected_stat,
                bytes_hashed=request.expected_stat.size_bytes,
                content_digest=DIGEST,
            )

    port = cast(SourceDigestPort, FakeDigest())
    request = SourceDigestRequest(
        library_id="library-1",
        source_entry_id="source-1",
        input_revision=1,
        canonical_root="/root",
        expected_root_identity="1:2",
        relative_path=("Book.epub",),
        expected_stat=STAT,
    )

    class Checkpoint:
        def checkpoint(self, progress: SourceDigestProgress) -> None:
            return None

    assert port.digest(request, Checkpoint()).content_digest == DIGEST
