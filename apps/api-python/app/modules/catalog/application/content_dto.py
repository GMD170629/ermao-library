"""Typed PR6A application contracts for source content and required manifests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.admission import AUDIO_SOURCE_FORMATS
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    ContentProcessorKind,
    ProcessorState,
    RequiredContentAsset,
    RequiredManifestFingerprints,
    RevisionImpact,
    Sha256Digest,
    SourceContentState,
    source_admission_requires_digest,
)
from app.modules.catalog.domain.library import LibraryControlState
from app.modules.catalog.domain.model import (
    AdmissionKind,
    SidecarRole,
    SourceFormat,
)


def _identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _integer(value: int, field_name: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")


def _lease_seconds(value: int) -> None:
    _integer(value, "lease_seconds", minimum=1)
    if value > 3_600:
        raise ValueError("lease_seconds cannot exceed 3600")


def _retry_seconds(value: int) -> None:
    _integer(value, "retry_seconds", minimum=1)
    if value > 86_400:
        raise ValueError("retry_seconds cannot exceed 86400")


def _strict_relative_path(value: tuple[str, ...], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    for component in value:
        if not isinstance(component, str):
            raise TypeError(f"{field_name} components must be strings")
        if (
            not component
            or component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\x00" in component
            or (
                len(component) >= 2
                and component[0]
                in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                and component[1] == ":"
            )
        ):
            raise ValueError(f"{field_name} contains an invalid component")
        try:
            component.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError(f"{field_name} components must be strict UTF-8") from error


def _typed_origin(value: object) -> None:
    if not isinstance(
        value,
        (FullScanContentOrigin, ReconcileContentOrigin, WatcherContentOrigin),
    ):
        raise TypeError("origin must be a typed content observation origin")


def _validate_admission_shape(
    admission: AdmissionKind,
    source_format: SourceFormat | None,
    sidecar_role: SidecarRole | None,
) -> None:
    if not isinstance(admission, AdmissionKind):
        raise TypeError("admission must be an AdmissionKind")
    if source_format is not None and not isinstance(source_format, SourceFormat):
        raise TypeError("source_format must be a SourceFormat")
    if sidecar_role is not None and not isinstance(sidecar_role, SidecarRole):
        raise TypeError("sidecar_role must be a SidecarRole")
    if admission in {AdmissionKind.PRIMARY, AdmissionKind.AUDIO_TRACK}:
        if source_format is None or sidecar_role is not None:
            raise ValueError("required admissions need only a source format")
        if (admission is AdmissionKind.AUDIO_TRACK) != (
            source_format in AUDIO_SOURCE_FORMATS
        ):
            raise ValueError("audio formats require AUDIO_TRACK admission")
    elif admission is AdmissionKind.SIDECAR:
        if source_format is not None or sidecar_role is None:
            raise ValueError("sidecar admissions need only a typed sidecar role")
    elif source_format is not None or sidecar_role is not None:
        raise ValueError("ineligible admissions carry no format or sidecar role")


def _validate_fact_admission_shape(
    admission: AdmissionKind,
    source_format: SourceFormat | None,
) -> None:
    if not isinstance(admission, AdmissionKind):
        raise TypeError("admission must be an AdmissionKind")
    if source_format is not None and not isinstance(source_format, SourceFormat):
        raise TypeError("source_format must be a SourceFormat")
    required = admission in {AdmissionKind.PRIMARY, AdmissionKind.AUDIO_TRACK}
    if required != (source_format is not None):
        raise ValueError("only required admissions persist a source format")
    if source_format is not None and (
        (admission is AdmissionKind.AUDIO_TRACK)
        != (source_format in AUDIO_SOURCE_FORMATS)
    ):
        raise ValueError("audio formats require AUDIO_TRACK admission")


@dataclass(frozen=True, slots=True)
class FullScanContentOrigin:
    scan_id: str
    generation: int

    def __post_init__(self) -> None:
        _identifier(self.scan_id, "scan_id")
        _integer(self.generation, "generation", minimum=1)

    @property
    def token(self) -> str:
        return f"FULL_SCAN:{self.scan_id}:{self.generation}"


@dataclass(frozen=True, slots=True)
class ReconcileContentOrigin:
    reconcile_intent_id: str
    through_sequence: int

    def __post_init__(self) -> None:
        _identifier(self.reconcile_intent_id, "reconcile_intent_id")
        _integer(self.through_sequence, "through_sequence", minimum=1)

    @property
    def token(self) -> str:
        return f"RECONCILE:{self.reconcile_intent_id}:{self.through_sequence}"


@dataclass(frozen=True, slots=True)
class WatcherContentOrigin:
    watcher_sequence: int

    def __post_init__(self) -> None:
        _integer(self.watcher_sequence, "watcher_sequence", minimum=1)

    @property
    def token(self) -> str:
        return f"WATCHER:{self.watcher_sequence}"


ContentObservationOrigin: TypeAlias = (
    FullScanContentOrigin | ReconcileContentOrigin | WatcherContentOrigin
)


@dataclass(frozen=True, slots=True)
class ContentLibrarySnapshot:
    library_id: str
    control_state: LibraryControlState

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        if not isinstance(self.control_state, LibraryControlState):
            raise TypeError("control_state must be a LibraryControlState")


@dataclass(frozen=True, slots=True)
class ObservedContentSource:
    """One regular-file observation bound to an opaque SourceEntry identity."""

    source_entry_id: str
    relative_path: tuple[str, ...]
    filesystem_identity: str
    expected_stat: SourceStatExpectation
    admission: AdmissionKind
    source_format: SourceFormat | None
    sidecar_role: SidecarRole | None
    policy_version: int
    origin: ContentObservationOrigin

    def __post_init__(self) -> None:
        _identifier(self.source_entry_id, "source_entry_id")
        _strict_relative_path(self.relative_path, "relative_path")
        _identifier(self.filesystem_identity, "filesystem_identity")
        if not isinstance(self.expected_stat, SourceStatExpectation):
            raise TypeError("expected_stat must be a SourceStatExpectation")
        _validate_admission_shape(
            self.admission,
            self.source_format,
            self.sidecar_role,
        )
        _integer(self.policy_version, "policy_version", minimum=1)
        _typed_origin(self.origin)


@dataclass(frozen=True, slots=True)
class ExplicitSourceModify:
    """A watcher MODIFY signal; its sequence is the idempotency identity."""

    library_id: str
    relative_path: tuple[str, ...]
    origin: WatcherContentOrigin

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _strict_relative_path(self.relative_path, "relative_path")
        if not isinstance(self.origin, WatcherContentOrigin):
            raise TypeError("origin must be a WatcherContentOrigin")


@dataclass(frozen=True, slots=True)
class SourceContentFact:
    """Current one-row content truth for a regular SourceEntry."""

    library_id: str
    source_entry_id: str
    input_revision: int
    work_revision: int
    admission: AdmissionKind
    source_format: SourceFormat | None
    filesystem_identity: str
    expected_stat: SourceStatExpectation
    policy_version: int
    state: SourceContentState
    content_digest: Sha256Digest | None
    digest_input_revision: int | None
    last_origin: ContentObservationOrigin
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.source_entry_id, "source_entry_id")
        _integer(self.input_revision, "input_revision", minimum=1)
        _integer(self.work_revision, "work_revision")
        _validate_fact_admission_shape(self.admission, self.source_format)
        _identifier(self.filesystem_identity, "filesystem_identity")
        if not isinstance(self.expected_stat, SourceStatExpectation):
            raise TypeError("expected_stat must be a SourceStatExpectation")
        _integer(self.policy_version, "policy_version", minimum=1)
        if not isinstance(self.state, SourceContentState):
            raise TypeError("state must be a SourceContentState")
        if self.content_digest is not None and not isinstance(
            self.content_digest, Sha256Digest
        ):
            raise TypeError("content_digest must be a Sha256Digest")
        if (self.content_digest is None) != (self.digest_input_revision is None):
            raise ValueError("content_digest and digest_input_revision must be paired")
        if self.digest_input_revision is not None:
            _integer(
                self.digest_input_revision,
                "digest_input_revision",
                minimum=1,
            )
            if self.digest_input_revision > self.input_revision:
                raise ValueError("digest_input_revision cannot exceed input_revision")
        _typed_origin(self.last_origin)
        if not isinstance(self.available_at, datetime):
            raise TypeError("available_at must be a datetime")
        leased = self.lease_owner is not None or self.lease_expires_at is not None
        if leased != (self.state is SourceContentState.RUNNING):
            raise ValueError("only RUNNING source facts carry a complete lease")
        if leased:
            if self.lease_owner is None or not isinstance(
                self.lease_expires_at, datetime
            ):
                raise ValueError("RUNNING source facts require a complete lease")
            _identifier(self.lease_owner, "lease_owner")
        if self.state is SourceContentState.INELIGIBLE:
            if source_admission_requires_digest(self.admission) or self.content_digest:
                raise ValueError("INELIGIBLE source facts cannot carry content")
        elif not source_admission_requires_digest(self.admission):
            raise ValueError("ineligible admission requires INELIGIBLE state")
        if self.state is SourceContentState.READY and (
            self.content_digest is None
            or self.digest_input_revision != self.input_revision
        ):
            raise ValueError("READY requires a digest for the current input revision")


@dataclass(frozen=True, slots=True)
class SourceContentObservationOutcome:
    """Bounded result that distinguishes new digest work from an exact retry."""

    facts: tuple[SourceContentFact, ...]
    advanced_required_count: int
    work_available: bool

    def __post_init__(self) -> None:
        if not isinstance(self.facts, tuple):
            raise TypeError("facts must be a tuple")
        if any(not isinstance(value, SourceContentFact) for value in self.facts):
            raise TypeError("facts must contain SourceContentFact values")
        _integer(self.advanced_required_count, "advanced_required_count")
        required_count = sum(
            source_admission_requires_digest(value.admission) for value in self.facts
        )
        if self.advanced_required_count > required_count:
            raise ValueError("advanced required count cannot exceed required facts")
        if not isinstance(self.work_available, bool):
            raise TypeError("work_available must be a bool")
        if self.advanced_required_count and not self.work_available:
            raise ValueError("advanced required input must expose available work")


@dataclass(frozen=True, slots=True)
class SourceContentWorkFence:
    library_id: str
    source_entry_id: str
    input_revision: int
    work_revision: int
    owner_token: str
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("library_id", "source_entry_id", "owner_token"):
            _identifier(getattr(self, field_name), field_name)
        _integer(self.input_revision, "input_revision", minimum=1)
        _integer(self.work_revision, "work_revision", minimum=1)
        if not isinstance(self.lease_expires_at, datetime):
            raise TypeError("lease_expires_at must be a datetime")


@dataclass(frozen=True, slots=True)
class SourceDigestRequest:
    library_id: str
    source_entry_id: str
    input_revision: int
    canonical_root: str
    expected_root_identity: str
    relative_path: tuple[str, ...]
    expected_stat: SourceStatExpectation

    def __post_init__(self) -> None:
        for field_name in (
            "library_id",
            "source_entry_id",
            "canonical_root",
            "expected_root_identity",
        ):
            _identifier(getattr(self, field_name), field_name)
        _integer(self.input_revision, "input_revision", minimum=1)
        _strict_relative_path(self.relative_path, "relative_path")
        if not isinstance(self.expected_stat, SourceStatExpectation):
            raise TypeError("expected_stat must be a SourceStatExpectation")


@dataclass(frozen=True, slots=True)
class SourceDigestEvidence:
    source_entry_id: str
    input_revision: int
    observed_stat: SourceStatExpectation
    bytes_hashed: int
    content_digest: Sha256Digest

    def __post_init__(self) -> None:
        _identifier(self.source_entry_id, "source_entry_id")
        _integer(self.input_revision, "input_revision", minimum=1)
        if not isinstance(self.observed_stat, SourceStatExpectation):
            raise TypeError("observed_stat must be a SourceStatExpectation")
        _integer(self.bytes_hashed, "bytes_hashed")
        if self.bytes_hashed != self.observed_stat.size_bytes:
            raise ValueError("bytes_hashed must equal the complete observed size")
        if not isinstance(self.content_digest, Sha256Digest):
            raise TypeError("content_digest must be a Sha256Digest")


@dataclass(frozen=True, slots=True)
class SourceDigestProgress:
    source_entry_id: str
    input_revision: int
    bytes_hashed: int

    def __post_init__(self) -> None:
        _identifier(self.source_entry_id, "source_entry_id")
        _integer(self.input_revision, "input_revision", minimum=1)
        _integer(self.bytes_hashed, "bytes_hashed", minimum=1)


@dataclass(frozen=True, slots=True)
class SourceDigestWork:
    fence: SourceContentWorkFence
    request: SourceDigestRequest

    def __post_init__(self) -> None:
        if not isinstance(self.fence, SourceContentWorkFence):
            raise TypeError("fence must be a SourceContentWorkFence")
        if not isinstance(self.request, SourceDigestRequest):
            raise TypeError("request must be a SourceDigestRequest")
        if (
            self.fence.library_id != self.request.library_id
            or self.fence.source_entry_id != self.request.source_entry_id
            or self.fence.input_revision != self.request.input_revision
        ):
            raise ValueError("digest work fence and request must describe one input")


@dataclass(frozen=True, slots=True)
class SourceDigestClaimOutcome:
    work: SourceDigestWork | None
    deferred_count: int

    def __post_init__(self) -> None:
        if self.work is not None and not isinstance(self.work, SourceDigestWork):
            raise TypeError("work must be a SourceDigestWork")
        _integer(self.deferred_count, "deferred_count")
        if self.deferred_count > 100:
            raise ValueError("one claim may defer at most 100 ineligible rows")


class SourceDigestPublishDisposition(StrEnum):
    READY_UNCHANGED = "READY_UNCHANGED"
    READY_CHANGED = "READY_CHANGED"
    INPUT_REVISION_ADVANCED = "INPUT_REVISION_ADVANCED"


@dataclass(frozen=True, slots=True)
class SourceDigestPublishOutcome:
    disposition: SourceDigestPublishDisposition
    claimed_input_revision: int
    current: SourceContentFact

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, SourceDigestPublishDisposition):
            raise TypeError("disposition must be a SourceDigestPublishDisposition")
        _integer(
            self.claimed_input_revision,
            "claimed_input_revision",
            minimum=1,
        )
        if not isinstance(self.current, SourceContentFact):
            raise TypeError("current must be a SourceContentFact")
        advanced = (
            self.disposition is SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED
        )
        expected_revision = self.claimed_input_revision + int(advanced)
        if self.current.input_revision != expected_revision:
            raise ValueError("digest publication has an invalid input revision")
        if self.current.state is not SourceContentState.READY:
            raise ValueError("a digest publication must return a READY source fact")


@dataclass(frozen=True, slots=True)
class ContentSchedulingOutcome:
    affected_volume_count: int
    wake_required: bool

    def __post_init__(self) -> None:
        _integer(self.affected_volume_count, "affected_volume_count")
        if not isinstance(self.wake_required, bool):
            raise TypeError("wake_required must be a bool")
        if self.wake_required != (self.affected_volume_count > 0):
            raise ValueError("content wake and affected volume count must agree")


@dataclass(frozen=True, slots=True)
class ContentTopologyProjectionState:
    library_id: str
    requested_epoch: int
    claimed_epoch: int
    applied_epoch: int
    cursor_volume_id: str | None

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        for field_name in ("requested_epoch", "claimed_epoch", "applied_epoch"):
            _integer(getattr(self, field_name), field_name)
        if not (self.applied_epoch <= self.claimed_epoch <= self.requested_epoch):
            raise ValueError(
                "projection epochs must preserve applied/claimed/requested epoch order"
            )
        if self.cursor_volume_id is not None:
            _identifier(self.cursor_volume_id, "cursor_volume_id")
            if self.claimed_epoch == self.applied_epoch:
                raise ValueError("a projection cursor requires an active sweep")

    @property
    def work_remaining(self) -> bool:
        return self.applied_epoch < self.requested_epoch


@dataclass(frozen=True, slots=True)
class ContentTopologyProjectionRequestOutcome:
    state: ContentTopologyProjectionState
    wake_required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, ContentTopologyProjectionState):
            raise TypeError("state must be a ContentTopologyProjectionState")
        if not self.state.work_remaining:
            raise ValueError("a topology activation must leave projection work")
        if not isinstance(self.wake_required, bool):
            raise TypeError("wake_required must be a bool")


@dataclass(frozen=True, slots=True)
class ContentTopologyProjectionBatchOutcome:
    state: ContentTopologyProjectionState
    projection_performed: bool
    processed_volume_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.state, ContentTopologyProjectionState):
            raise TypeError("state must be a ContentTopologyProjectionState")
        if not isinstance(self.projection_performed, bool):
            raise TypeError("projection_performed must be a bool")
        _integer(self.processed_volume_count, "processed_volume_count")
        if self.processed_volume_count > 500:
            raise ValueError("a projection batch may process at most 500 Volumes")
        if not self.projection_performed and (
            self.processed_volume_count != 0 or self.state.work_remaining
        ):
            raise ValueError("a NO_WORK projection outcome must be idle and empty")

    @property
    def work_remaining(self) -> bool:
        return self.state.work_remaining


@dataclass(frozen=True, slots=True)
class VolumeContentVector:
    content_revision: int
    required_manifest_revision: int
    optional_manifest_revision: int
    metadata_revision: int

    def __post_init__(self) -> None:
        for field_name in (
            "content_revision",
            "required_manifest_revision",
            "optional_manifest_revision",
            "metadata_revision",
        ):
            _integer(getattr(self, field_name), field_name)

    def apply(self, impact: RevisionImpact) -> VolumeContentVector:
        if not isinstance(impact, RevisionImpact):
            raise TypeError("impact must be a RevisionImpact")
        return VolumeContentVector(
            self.content_revision + impact.content_revision_delta,
            self.required_manifest_revision + impact.required_manifest_revision_delta,
            self.optional_manifest_revision,
            self.metadata_revision,
        )

    @property
    def required_revisions(self) -> RequiredRevisionVector:
        return RequiredRevisionVector(
            self.content_revision,
            self.required_manifest_revision,
        )


@dataclass(frozen=True, slots=True)
class RequiredRevisionVector:
    """The two revision axes owned by required-content processing."""

    content_revision: int
    required_manifest_revision: int

    def __post_init__(self) -> None:
        _integer(self.content_revision, "content_revision")
        _integer(self.required_manifest_revision, "required_manifest_revision")

    @classmethod
    def from_volume(cls, vector: VolumeContentVector) -> RequiredRevisionVector:
        if not isinstance(vector, VolumeContentVector):
            raise TypeError("vector must be a VolumeContentVector")
        return cls(vector.content_revision, vector.required_manifest_revision)

    def apply(self, impact: RevisionImpact) -> RequiredRevisionVector:
        if not isinstance(impact, RevisionImpact):
            raise TypeError("impact must be a RevisionImpact")
        return RequiredRevisionVector(
            self.content_revision + impact.content_revision_delta,
            self.required_manifest_revision + impact.required_manifest_revision_delta,
        )


@dataclass(frozen=True, slots=True)
class VolumeProcessingFact:
    library_id: str
    volume_id: str
    processor_kind: ContentProcessorKind
    processor_version: str
    work_revision: int
    active_topology_revision_id: str
    target_vector: RequiredRevisionVector
    input_fingerprint: Sha256Digest
    state: ProcessorState
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "library_id",
            "volume_id",
            "active_topology_revision_id",
        ):
            _identifier(getattr(self, field_name), field_name)
        if not isinstance(self.processor_kind, ContentProcessorKind):
            raise TypeError("processor_kind must be a ContentProcessorKind")
        _identifier(self.processor_version, "processor_version")
        _integer(self.work_revision, "work_revision", minimum=1)
        if not isinstance(self.target_vector, RequiredRevisionVector):
            raise TypeError("target_vector must be a RequiredRevisionVector")
        if not isinstance(self.input_fingerprint, Sha256Digest):
            raise TypeError("input_fingerprint must be a Sha256Digest")
        if not isinstance(self.state, ProcessorState):
            raise TypeError("state must be a ProcessorState")
        if not isinstance(self.available_at, datetime):
            raise TypeError("available_at must be a datetime")
        leased = self.lease_owner is not None or self.lease_expires_at is not None
        if leased != (self.state is ProcessorState.RUNNING):
            raise ValueError("only RUNNING processing facts carry a complete lease")
        if leased:
            if self.lease_owner is None or not isinstance(
                self.lease_expires_at, datetime
            ):
                raise ValueError("RUNNING processing facts require a complete lease")
            _identifier(self.lease_owner, "lease_owner")
        failed = self.state is ProcessorState.FAILED
        if failed != (self.failure_code is not None):
            raise ValueError("FAILED and failure_code must be paired")
        if self.failure_code is not None:
            _identifier(self.failure_code, "failure_code")

    def fence(self) -> VolumeProcessingWorkFence:
        if (
            self.state is not ProcessorState.RUNNING
            or self.lease_owner is None
            or self.lease_expires_at is None
        ):
            raise ValueError("only RUNNING processing facts have a work fence")
        return VolumeProcessingWorkFence(
            self.library_id,
            self.volume_id,
            self.processor_kind,
            self.work_revision,
            self.lease_owner,
            self.lease_expires_at,
        )


@dataclass(frozen=True, slots=True)
class VolumeProcessingWorkFence:
    library_id: str
    volume_id: str
    processor_kind: ContentProcessorKind
    work_revision: int
    owner_token: str
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("library_id", "volume_id", "owner_token"):
            _identifier(getattr(self, field_name), field_name)
        if not isinstance(self.processor_kind, ContentProcessorKind):
            raise TypeError("processor_kind must be a ContentProcessorKind")
        _integer(self.work_revision, "work_revision", minimum=1)
        if not isinstance(self.lease_expires_at, datetime):
            raise TypeError("lease_expires_at must be a datetime")


@dataclass(frozen=True, slots=True)
class VolumeProcessingClaimOutcome:
    work: VolumeProcessingFact | None
    deferred_count: int

    def __post_init__(self) -> None:
        if self.work is not None and not isinstance(self.work, VolumeProcessingFact):
            raise TypeError("work must be a VolumeProcessingFact")
        _integer(self.deferred_count, "deferred_count")
        if self.deferred_count > 100:
            raise ValueError("one claim may defer at most 100 blocked rows")


class RequiredManifestState(StrEnum):
    STAGING = "STAGING"
    ACTIVE = "ACTIVE"


@dataclass(frozen=True, slots=True)
class RequiredManifestCandidate:
    manifest_id: str
    library_id: str
    volume_id: str
    topology_unit_revision_id: str
    base_revisions: RequiredRevisionVector
    facts: CanonicalRequiredManifestFacts

    def __post_init__(self) -> None:
        for field_name in (
            "manifest_id",
            "library_id",
            "volume_id",
            "topology_unit_revision_id",
        ):
            _identifier(getattr(self, field_name), field_name)
        if not isinstance(self.base_revisions, RequiredRevisionVector):
            raise TypeError("base_revisions must be a RequiredRevisionVector")
        if not isinstance(self.facts, CanonicalRequiredManifestFacts):
            raise TypeError("facts must be CanonicalRequiredManifestFacts")


@dataclass(frozen=True, slots=True)
class RequiredManifestHeader:
    manifest_id: str
    library_id: str
    volume_id: str
    topology_unit_revision_id: str
    state: RequiredManifestState
    base_revisions: RequiredRevisionVector
    published_revisions: RequiredRevisionVector | None
    fingerprints: RequiredManifestFingerprints
    expected_entry_count: int
    staged_entry_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "manifest_id",
            "library_id",
            "volume_id",
            "topology_unit_revision_id",
        ):
            _identifier(getattr(self, field_name), field_name)
        if not isinstance(self.state, RequiredManifestState):
            raise TypeError("state must be a RequiredManifestState")
        if not isinstance(self.base_revisions, RequiredRevisionVector):
            raise TypeError("base_revisions must be a RequiredRevisionVector")
        if self.published_revisions is not None and not isinstance(
            self.published_revisions, RequiredRevisionVector
        ):
            raise TypeError("published_revisions must be a RequiredRevisionVector")
        if not isinstance(self.fingerprints, RequiredManifestFingerprints):
            raise TypeError("fingerprints must be RequiredManifestFingerprints")
        _integer(self.expected_entry_count, "expected_entry_count", minimum=1)
        _integer(self.staged_entry_count, "staged_entry_count")
        if self.staged_entry_count > self.expected_entry_count:
            raise ValueError("staged_entry_count cannot exceed expected_entry_count")
        if self.state is RequiredManifestState.ACTIVE:
            if (
                self.published_revisions is None
                or self.staged_entry_count != self.expected_entry_count
            ):
                raise ValueError("ACTIVE manifests must be complete and published")
        elif self.published_revisions is not None:
            raise ValueError("only ACTIVE manifests carry published revisions")


@dataclass(frozen=True, slots=True)
class RequiredManifestStageBatch:
    start_order: int
    assets: tuple[RequiredContentAsset, ...]
    complete: bool

    def __post_init__(self) -> None:
        _integer(self.start_order, "start_order")
        if not isinstance(self.assets, tuple):
            raise TypeError("assets must be a tuple")
        if not self.assets:
            raise ValueError("a manifest batch must not be empty")
        if len(self.assets) > 500:
            raise ValueError("a manifest batch cannot exceed 500 assets")
        if any(not isinstance(asset, RequiredContentAsset) for asset in self.assets):
            raise TypeError("assets must contain RequiredContentAsset values")
        if tuple(asset.order for asset in self.assets) != tuple(
            range(self.start_order, self.start_order + len(self.assets))
        ):
            raise ValueError("manifest batch orders must match start_order")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be a bool")


class RequiredManifestActivationDisposition(StrEnum):
    ACTIVATED_NEW = "ACTIVATED_NEW"
    REUSED_ACTIVE = "REUSED_ACTIVE"


@dataclass(frozen=True, slots=True)
class RequiredManifestActivationOutcome:
    disposition: RequiredManifestActivationDisposition
    active_manifest_id: str
    published_revisions: RequiredRevisionVector
    fingerprints: RequiredManifestFingerprints
    revision_impact: RevisionImpact

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, RequiredManifestActivationDisposition):
            raise TypeError(
                "disposition must be a RequiredManifestActivationDisposition"
            )
        _identifier(self.active_manifest_id, "active_manifest_id")
        if not isinstance(self.published_revisions, RequiredRevisionVector):
            raise TypeError("published_revisions must be a RequiredRevisionVector")
        if not isinstance(self.fingerprints, RequiredManifestFingerprints):
            raise TypeError("fingerprints must be RequiredManifestFingerprints")
        if not isinstance(self.revision_impact, RevisionImpact):
            raise TypeError("revision_impact must be a RevisionImpact")
        reused = self.disposition is RequiredManifestActivationDisposition.REUSED_ACTIVE
        if reused != self.revision_impact.reuse_active_manifest:
            raise ValueError("manifest disposition must match its revision impact")


class ContentRunDisposition(StrEnum):
    NO_WORK = "NO_WORK"
    COMPLETED = "COMPLETED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    STALE = "STALE"
    LIBRARY_NOT_ACTIVE = "LIBRARY_NOT_ACTIVE"


@dataclass(frozen=True, slots=True)
class RunNextContentTopologyProjectionCommand:
    library_id: str

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")


@dataclass(frozen=True, slots=True)
class RunContentTopologyProjectionResult:
    disposition: ContentRunDisposition
    processed_volume_count: int
    work_remaining: bool

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ContentRunDisposition):
            raise TypeError("disposition must be a ContentRunDisposition")
        if self.disposition not in {
            ContentRunDisposition.NO_WORK,
            ContentRunDisposition.COMPLETED,
            ContentRunDisposition.LIBRARY_NOT_ACTIVE,
        }:
            raise ValueError("topology projection has an invalid disposition")
        _integer(self.processed_volume_count, "processed_volume_count")
        if self.processed_volume_count > 500:
            raise ValueError("one projection result may contain at most 500 Volumes")
        if not isinstance(self.work_remaining, bool):
            raise TypeError("work_remaining must be a bool")
        if self.disposition is not ContentRunDisposition.COMPLETED and (
            self.processed_volume_count != 0 or self.work_remaining
        ):
            raise ValueError("an idle projection result must be empty")


@dataclass(frozen=True, slots=True)
class RunNextSourceDigestCommand:
    library_id: str
    owner_token: str
    lease_seconds: int = 60
    retry_seconds: int = 30

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.owner_token, "owner_token")
        _lease_seconds(self.lease_seconds)
        _retry_seconds(self.retry_seconds)


@dataclass(frozen=True, slots=True)
class RunSourceDigestResult:
    disposition: ContentRunDisposition
    source_entry_id: str | None
    publication: SourceDigestPublishDisposition | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ContentRunDisposition):
            raise TypeError("disposition must be a ContentRunDisposition")
        if self.source_entry_id is not None:
            _identifier(self.source_entry_id, "source_entry_id")
        if self.publication is not None and not isinstance(
            self.publication, SourceDigestPublishDisposition
        ):
            raise TypeError("publication must be a SourceDigestPublishDisposition")
        completed = self.disposition is ContentRunDisposition.COMPLETED
        if completed != (self.publication is not None):
            raise ValueError("only a completed digest carries a publication")
        if (self.source_entry_id is None) != (
            self.disposition
            in {
                ContentRunDisposition.NO_WORK,
                ContentRunDisposition.LIBRARY_NOT_ACTIVE,
            }
        ):
            raise ValueError("digest result source shape is invalid")


@dataclass(frozen=True, slots=True)
class RunNextRequiredManifestCommand:
    library_id: str
    owner_token: str
    lease_seconds: int = 60
    retry_seconds: int = 30

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.owner_token, "owner_token")
        _lease_seconds(self.lease_seconds)
        _retry_seconds(self.retry_seconds)


@dataclass(frozen=True, slots=True)
class RunRequiredManifestResult:
    disposition: ContentRunDisposition
    volume_id: str | None
    activation: RequiredManifestActivationDisposition | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ContentRunDisposition):
            raise TypeError("disposition must be a ContentRunDisposition")
        if self.volume_id is not None:
            _identifier(self.volume_id, "volume_id")
        if self.activation is not None and not isinstance(
            self.activation, RequiredManifestActivationDisposition
        ):
            raise TypeError(
                "activation must be a RequiredManifestActivationDisposition"
            )
        completed = self.disposition is ContentRunDisposition.COMPLETED
        if completed != (self.activation is not None):
            raise ValueError("only a completed manifest carries an activation")
        if (self.volume_id is None) != (
            self.disposition
            in {
                ContentRunDisposition.NO_WORK,
                ContentRunDisposition.LIBRARY_NOT_ACTIVE,
            }
        ):
            raise ValueError("manifest result volume shape is invalid")


class RequiredOpeningDisposition(StrEnum):
    READY = "READY"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True, slots=True)
class RequiredOpeningSource:
    source_entry_id: str
    relative_path: tuple[str, ...]
    source_format: SourceFormat
    expected_stat: SourceStatExpectation
    content_digest: Sha256Digest
    order: int

    def __post_init__(self) -> None:
        _identifier(self.source_entry_id, "source_entry_id")
        _strict_relative_path(self.relative_path, "relative_path")
        if not isinstance(self.source_format, SourceFormat):
            raise TypeError("source_format must be a SourceFormat")
        if not isinstance(self.expected_stat, SourceStatExpectation):
            raise TypeError("expected_stat must be a SourceStatExpectation")
        if not isinstance(self.content_digest, Sha256Digest):
            raise TypeError("content_digest must be a Sha256Digest")
        _integer(self.order, "order")


@dataclass(frozen=True, slots=True)
class RequiredOpeningRequest:
    library_id: str
    volume_id: str
    topology_unit_revision_id: str
    target_revisions: RequiredRevisionVector
    canonical_root: str
    expected_root_identity: str
    sources: tuple[RequiredOpeningSource, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "library_id",
            "volume_id",
            "topology_unit_revision_id",
            "canonical_root",
            "expected_root_identity",
        ):
            _identifier(getattr(self, field_name), field_name)
        if not isinstance(self.target_revisions, RequiredRevisionVector):
            raise TypeError("target_revisions must be a RequiredRevisionVector")
        if not isinstance(self.sources, tuple):
            raise TypeError("sources must be a tuple")
        if not self.sources or len(self.sources) > 10_000:
            raise ValueError("required opening needs between 1 and 10000 sources")
        if any(not isinstance(value, RequiredOpeningSource) for value in self.sources):
            raise TypeError("sources must contain RequiredOpeningSource values")
        if tuple(value.order for value in self.sources) != tuple(
            range(len(self.sources))
        ):
            raise ValueError("opening source order must be contiguous")


@dataclass(frozen=True, slots=True)
class RequiredOpeningProgress:
    """Monotonic progress from one bounded required-opening attempt."""

    volume_id: str
    topology_unit_revision_id: str
    bytes_read: int
    sources_completed: int

    def __post_init__(self) -> None:
        _identifier(self.volume_id, "volume_id")
        _identifier(
            self.topology_unit_revision_id,
            "topology_unit_revision_id",
        )
        _integer(self.bytes_read, "bytes_read")
        _integer(self.sources_completed, "sources_completed")
        if self.bytes_read == 0 and self.sources_completed == 0:
            raise ValueError("opening progress must advance bytes or sources")


@dataclass(frozen=True, slots=True)
class RequiredOpeningEvidence:
    disposition: RequiredOpeningDisposition
    publication_fingerprint: Sha256Digest | None = None
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, RequiredOpeningDisposition):
            raise TypeError("disposition must be a RequiredOpeningDisposition")
        unreadable = self.disposition is RequiredOpeningDisposition.UNREADABLE
        if unreadable != (self.diagnostic_code is not None):
            raise ValueError("UNREADABLE and diagnostic_code must be paired")
        if unreadable == (self.publication_fingerprint is not None):
            raise ValueError(
                "READY requires only a publication fingerprint; "
                "UNREADABLE requires only a diagnostic"
            )
        if self.publication_fingerprint is not None and not isinstance(
            self.publication_fingerprint, Sha256Digest
        ):
            raise TypeError("publication_fingerprint must be a Sha256Digest")
        if self.diagnostic_code is not None:
            _identifier(self.diagnostic_code, "diagnostic_code")


@dataclass(frozen=True, slots=True)
class RunNextRequiredOpeningCommand:
    library_id: str
    owner_token: str
    lease_seconds: int = 60
    retry_seconds: int = 30

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.owner_token, "owner_token")
        _lease_seconds(self.lease_seconds)
        _retry_seconds(self.retry_seconds)


@dataclass(frozen=True, slots=True)
class RunRequiredOpeningResult:
    disposition: ContentRunDisposition
    volume_id: str | None
    opening: RequiredOpeningDisposition | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ContentRunDisposition):
            raise TypeError("disposition must be a ContentRunDisposition")
        if self.volume_id is not None:
            _identifier(self.volume_id, "volume_id")
        if self.opening is not None and not isinstance(
            self.opening, RequiredOpeningDisposition
        ):
            raise TypeError("opening must be a RequiredOpeningDisposition")
        completed = self.disposition is ContentRunDisposition.COMPLETED
        if completed != (self.opening is not None):
            raise ValueError("only a completed opening carries an outcome")
        if (self.volume_id is None) != (
            self.disposition
            in {
                ContentRunDisposition.NO_WORK,
                ContentRunDisposition.LIBRARY_NOT_ACTIVE,
            }
        ):
            raise ValueError("opening result volume shape is invalid")


__all__ = [
    "ContentLibrarySnapshot",
    "ContentObservationOrigin",
    "ContentRunDisposition",
    "ContentSchedulingOutcome",
    "ContentTopologyProjectionBatchOutcome",
    "ContentTopologyProjectionRequestOutcome",
    "ContentTopologyProjectionState",
    "ExplicitSourceModify",
    "FullScanContentOrigin",
    "ObservedContentSource",
    "ReconcileContentOrigin",
    "RequiredManifestActivationDisposition",
    "RequiredManifestActivationOutcome",
    "RequiredManifestCandidate",
    "RequiredManifestHeader",
    "RequiredManifestStageBatch",
    "RequiredManifestState",
    "RequiredOpeningDisposition",
    "RequiredOpeningEvidence",
    "RequiredOpeningProgress",
    "RequiredOpeningRequest",
    "RequiredOpeningSource",
    "RequiredRevisionVector",
    "RunContentTopologyProjectionResult",
    "RunNextContentTopologyProjectionCommand",
    "RunNextRequiredManifestCommand",
    "RunNextRequiredOpeningCommand",
    "RunNextSourceDigestCommand",
    "RunRequiredManifestResult",
    "RunRequiredOpeningResult",
    "RunSourceDigestResult",
    "SourceContentFact",
    "SourceContentObservationOutcome",
    "SourceContentWorkFence",
    "SourceDigestClaimOutcome",
    "SourceDigestEvidence",
    "SourceDigestProgress",
    "SourceDigestPublishDisposition",
    "SourceDigestPublishOutcome",
    "SourceDigestRequest",
    "SourceDigestWork",
    "VolumeContentVector",
    "VolumeProcessingClaimOutcome",
    "VolumeProcessingFact",
    "VolumeProcessingWorkFence",
    "WatcherContentOrigin",
]
