"""Pure PR6A contracts for source content and required reader manifests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from app.modules.catalog.domain.admission import AUDIO_SOURCE_FORMATS
from app.modules.catalog.domain.model import AdmissionKind, SourceFormat
from app.modules.catalog.domain.scan import (
    MAX_AUDIO_TRACKS,
    AssetRole,
    ReadingMorphology,
    reading_morphology,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$", flags=re.ASCII)
_MEDIA_TYPE = re.compile(
    r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$",
    flags=re.ASCII,
)

SOURCE_CONTENT_POLICY_VERSION = 1

_REQUIRED_MIME_TYPES = {
    SourceFormat.EPUB: "application/epub+zip",
    SourceFormat.MOBI: "application/x-mobipocket-ebook",
    SourceFormat.AZW: "application/x-mobipocket-ebook",
    SourceFormat.AZW3: "application/x-mobipocket-ebook",
    SourceFormat.PRC: "application/x-mobipocket-ebook",
    SourceFormat.TXT: "text/plain",
    SourceFormat.PDF: "application/pdf",
    SourceFormat.CBZ: "application/vnd.comicbook+zip",
    SourceFormat.CBR: "application/vnd.rar",
    SourceFormat.RAR: "application/vnd.rar",
    SourceFormat.ZIP: "application/zip",
    SourceFormat.MP3: "audio/mpeg",
    SourceFormat.M4A: "audio/mp4",
    SourceFormat.M4B: "audio/mp4",
}


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_integer(value: int, field_name: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    """A complete lower-case SHA-256 digest with its algorithm prefix."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("digest value must be a string")
        if _SHA256.fullmatch(self.value) is None:
            raise ValueError(
                "digest must be lower-case sha256 followed by 64 hex digits"
            )

    @classmethod
    def from_bytes(cls, value: bytes) -> Sha256Digest:
        if not isinstance(value, bytes):
            raise TypeError("value must be bytes")
        return cls(f"sha256:{hashlib.sha256(value).hexdigest()}")

    def __str__(self) -> str:
        return self.value


class SourceContentState(StrEnum):
    INELIGIBLE = "INELIGIBLE"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"


class ContentProcessorKind(StrEnum):
    """The complete, deliberately finite PR6A processor set."""

    REQUIRED_MANIFEST = "REQUIRED_MANIFEST"
    REQUIRED_OPENING = "REQUIRED_OPENING"


class ProcessorState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"


class AssetReadiness(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    UNREADABLE = "UNREADABLE"


class VolumeReadiness(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    UNREADABLE = "UNREADABLE"


class RequiredDeliveryPolicy(StrEnum):
    ORIGINAL_SOURCE = "ORIGINAL_SOURCE"


def canonical_required_mime_type(source_format: SourceFormat) -> str:
    """Return topology-v1 delivery MIME without consulting names or metadata."""

    if not isinstance(source_format, SourceFormat):
        raise TypeError("source_format must be a SourceFormat")
    return _REQUIRED_MIME_TYPES[source_format]


def source_admission_requires_digest(admission: AdmissionKind) -> bool:
    if not isinstance(admission, AdmissionKind):
        raise TypeError("admission must be an AdmissionKind")
    return admission in {AdmissionKind.PRIMARY, AdmissionKind.AUDIO_TRACK}


@dataclass(frozen=True, slots=True)
class SourceRevisionImpact:
    input_revision_delta: int
    digest_requeue_required: bool

    def __post_init__(self) -> None:
        if self.input_revision_delta not in {0, 1}:
            raise ValueError("input_revision_delta must be zero or one")
        if not isinstance(self.digest_requeue_required, bool):
            raise TypeError("digest_requeue_required must be a bool")
        if self.digest_requeue_required and self.input_revision_delta == 0:
            raise ValueError("digest work requires an advanced input revision")


def source_input_revision_impact(
    *,
    input_facts_changed: bool,
    explicit_modify: bool,
    repeated_origin: bool,
    admission: AdmissionKind,
) -> SourceRevisionImpact:
    """Decide one monotonic source-input transition.

    Origin identifies a retry only. A different origin never makes equal
    input facts different, while an exact repeated watcher sequence cannot
    advance again even when it carries ``explicit_modify``.
    """

    for value, field_name in (
        (input_facts_changed, "input_facts_changed"),
        (explicit_modify, "explicit_modify"),
        (repeated_origin, "repeated_origin"),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{field_name} must be a bool")
    requires_digest = source_admission_requires_digest(admission)
    advance = input_facts_changed or (explicit_modify and not repeated_origin)
    return SourceRevisionImpact(
        input_revision_delta=int(advance),
        digest_requeue_required=(advance and requires_digest),
    )


@dataclass(frozen=True, slots=True)
class RequiredContentAsset:
    """One required original asset in deterministic reader order."""

    asset_id: str
    role: AssetRole
    source_format: SourceFormat
    size_bytes: int
    content_digest: Sha256Digest
    order: int
    mime_type: str

    def __post_init__(self) -> None:
        _require_identifier(self.asset_id, "asset_id")
        if not isinstance(self.role, AssetRole):
            raise TypeError("role must be an AssetRole")
        if not isinstance(self.source_format, SourceFormat):
            raise TypeError("source_format must be a SourceFormat")
        _require_integer(self.size_bytes, "size_bytes")
        _require_integer(self.order, "order")
        if not isinstance(self.content_digest, Sha256Digest):
            raise TypeError("content_digest must be a Sha256Digest")
        if not isinstance(self.mime_type, str):
            raise TypeError("mime_type must be a string")
        if _MEDIA_TYPE.fullmatch(self.mime_type) is None:
            raise ValueError("mime_type must be a canonical lower-case media type")
        if self.mime_type != canonical_required_mime_type(self.source_format):
            raise ValueError("mime_type must match the canonical source-format policy")


@dataclass(frozen=True, slots=True)
class RequiredManifestFingerprints:
    """The three independent canonical comparisons required by PR6A."""

    source_bytes_digest: Sha256Digest
    content_facts_digest: Sha256Digest
    delivery_facts_digest: Sha256Digest

    def __post_init__(self) -> None:
        for field_name in (
            "source_bytes_digest",
            "content_facts_digest",
            "delivery_facts_digest",
        ):
            if not isinstance(getattr(self, field_name), Sha256Digest):
                raise TypeError(f"{field_name} must be a Sha256Digest")


@dataclass(frozen=True, slots=True)
class CanonicalRequiredManifestFacts:
    """Canonical required-manifest facts, independent of paths and metadata."""

    topology_version: int
    reading_morphology: ReadingMorphology
    delivery_policy: RequiredDeliveryPolicy
    delivery_policy_version: int
    assets: tuple[RequiredContentAsset, ...]

    def __post_init__(self) -> None:
        _require_integer(self.topology_version, "topology_version", minimum=1)
        if not isinstance(self.reading_morphology, ReadingMorphology):
            raise TypeError("reading_morphology must be a ReadingMorphology")
        if not isinstance(self.delivery_policy, RequiredDeliveryPolicy):
            raise TypeError("delivery_policy must be a RequiredDeliveryPolicy")
        _require_integer(
            self.delivery_policy_version,
            "delivery_policy_version",
            minimum=1,
        )
        if not isinstance(self.assets, tuple):
            raise TypeError("assets must be a tuple")
        if not self.assets:
            raise ValueError("a required manifest needs at least one required asset")
        if len(self.assets) > MAX_AUDIO_TRACKS:
            raise ValueError("a required manifest cannot exceed 10,000 assets")
        if any(not isinstance(asset, RequiredContentAsset) for asset in self.assets):
            raise TypeError("assets must contain RequiredContentAsset values")
        if tuple(asset.order for asset in self.assets) != tuple(
            range(len(self.assets))
        ):
            raise ValueError("required asset orders must be contiguous from zero")
        if len({asset.asset_id for asset in self.assets}) != len(self.assets):
            raise ValueError("required assets cannot repeat an asset_id")
        roles = tuple(asset.role for asset in self.assets)
        if roles == (AssetRole.PRIMARY,):
            pass
        elif not roles or any(role is not AssetRole.AUDIO_TRACK for role in roles):
            raise ValueError(
                "required assets must be one PRIMARY or only AUDIO_TRACK values"
            )
        elif any(
            asset.source_format not in AUDIO_SOURCE_FORMATS for asset in self.assets
        ):
            raise ValueError("AUDIO_TRACK assets must use an audio source format")
        observed_morphology = reading_morphology(
            tuple(asset.source_format for asset in self.assets)
        )
        if observed_morphology is not self.reading_morphology:
            raise ValueError("reading_morphology must match required source formats")

    @property
    def source_bytes_json(self) -> bytes:
        return _canonical_json(
            {
                "topologyVersion": self.topology_version,
                "assets": [
                    {
                        "order": asset.order,
                        "sourceFormat": asset.source_format.value,
                        "sizeBytes": asset.size_bytes,
                        "digest": asset.content_digest.value,
                    }
                    for asset in self.assets
                ],
            }
        )

    @property
    def content_facts_json(self) -> bytes:
        return _canonical_json(
            {
                "topologyVersion": self.topology_version,
                "readingMorphology": self.reading_morphology.value,
                "assets": [
                    {
                        "order": asset.order,
                        "assetId": asset.asset_id,
                        "role": asset.role.value,
                        "sourceFormat": asset.source_format.value,
                        "sizeBytes": asset.size_bytes,
                        "digest": asset.content_digest.value,
                    }
                    for asset in self.assets
                ],
            }
        )

    @property
    def delivery_facts_json(self) -> bytes:
        return _canonical_json(
            {
                "topologyVersion": self.topology_version,
                "readingMorphology": self.reading_morphology.value,
                "deliveryPolicy": self.delivery_policy.value,
                "deliveryPolicyVersion": self.delivery_policy_version,
                "assets": [
                    {
                        "order": asset.order,
                        "assetId": asset.asset_id,
                        "role": asset.role.value,
                        "sourceFormat": asset.source_format.value,
                        "sizeBytes": asset.size_bytes,
                        "digest": asset.content_digest.value,
                        "mimeType": asset.mime_type,
                    }
                    for asset in self.assets
                ],
            }
        )

    @property
    def fingerprints(self) -> RequiredManifestFingerprints:
        return RequiredManifestFingerprints(
            source_bytes_digest=Sha256Digest.from_bytes(self.source_bytes_json),
            content_facts_digest=Sha256Digest.from_bytes(self.content_facts_json),
            delivery_facts_digest=Sha256Digest.from_bytes(self.delivery_facts_json),
        )


@dataclass(frozen=True, slots=True)
class RevisionImpact:
    """One manifest activation's bounded monotonic business-revision effect."""

    content_revision_delta: int
    required_manifest_revision_delta: int
    source_bytes_changed: bool
    content_facts_changed: bool
    delivery_facts_changed: bool
    reuse_active_manifest: bool

    def __post_init__(self) -> None:
        for field_name in (
            "content_revision_delta",
            "required_manifest_revision_delta",
        ):
            value = getattr(self, field_name)
            if value not in {0, 1}:
                raise ValueError(f"{field_name} must be zero or one")
        for field_name in (
            "source_bytes_changed",
            "content_facts_changed",
            "delivery_facts_changed",
            "reuse_active_manifest",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        if self.content_revision_delta > self.required_manifest_revision_delta:
            raise ValueError("a content change must also change the required manifest")
        changed = (
            self.source_bytes_changed
            or self.content_facts_changed
            or self.delivery_facts_changed
        )
        if self.reuse_active_manifest == changed:
            raise ValueError(
                "reuse_active_manifest must mean no canonical facts changed"
            )


def required_manifest_revision_impact(
    previous: RequiredManifestFingerprints | None,
    candidate: RequiredManifestFingerprints,
    *,
    base_content_revision: int,
    base_required_manifest_revision: int,
) -> RevisionImpact:
    """Compare one complete candidate only at the final ACTIVE CAS boundary."""

    if previous is not None and not isinstance(previous, RequiredManifestFingerprints):
        raise TypeError("previous must be RequiredManifestFingerprints or None")
    if not isinstance(candidate, RequiredManifestFingerprints):
        raise TypeError("candidate must be RequiredManifestFingerprints")
    _require_integer(base_content_revision, "base_content_revision")
    _require_integer(
        base_required_manifest_revision,
        "base_required_manifest_revision",
    )
    if previous is None:
        if base_content_revision != 0 or base_required_manifest_revision != 0:
            raise ValueError(
                "a first required manifest must activate from revision zero"
            )
        return RevisionImpact(1, 1, True, True, True, False)
    if base_content_revision < 1 or base_required_manifest_revision < 1:
        raise ValueError("an active required manifest requires positive revisions")

    source_bytes_changed = previous.source_bytes_digest != candidate.source_bytes_digest
    content_facts_changed = (
        previous.content_facts_digest != candidate.content_facts_digest
    )
    delivery_facts_changed = (
        previous.delivery_facts_digest != candidate.delivery_facts_digest
    )
    if source_bytes_changed and not content_facts_changed:
        raise ValueError("source-byte changes must also change canonical content facts")
    if content_facts_changed and not delivery_facts_changed:
        raise ValueError(
            "content-fact changes must also change canonical delivery facts"
        )
    content_delta = int(content_facts_changed)
    required_delta = int(content_facts_changed or delivery_facts_changed)
    return RevisionImpact(
        content_revision_delta=content_delta,
        required_manifest_revision_delta=required_delta,
        source_bytes_changed=source_bytes_changed,
        content_facts_changed=content_facts_changed,
        delivery_facts_changed=delivery_facts_changed,
        reuse_active_manifest=not (
            source_bytes_changed or content_facts_changed or delivery_facts_changed
        ),
    )


def required_volume_readiness(
    *,
    asset_states: tuple[AssetReadiness, ...],
    required_manifest_state: ProcessorState,
    required_opening_state: ProcessorState,
) -> VolumeReadiness:
    """Derive readiness without navigation, metadata, or optional sidecars."""

    if not isinstance(asset_states, tuple):
        raise TypeError("asset_states must be a tuple")
    if not asset_states:
        raise ValueError("required readiness needs at least one asset")
    if any(not isinstance(state, AssetReadiness) for state in asset_states):
        raise TypeError("asset_states must contain AssetReadiness values")
    if not isinstance(required_manifest_state, ProcessorState):
        raise TypeError("required_manifest_state must be a ProcessorState")
    if not isinstance(required_opening_state, ProcessorState):
        raise TypeError("required_opening_state must be a ProcessorState")
    if (
        AssetReadiness.UNREADABLE in asset_states
        or required_opening_state is ProcessorState.FAILED
    ):
        return VolumeReadiness.UNREADABLE
    if (
        all(state is AssetReadiness.READY for state in asset_states)
        and required_manifest_state is ProcessorState.READY
        and required_opening_state is ProcessorState.READY
    ):
        return VolumeReadiness.READY
    return VolumeReadiness.PENDING


__all__ = [
    "SOURCE_CONTENT_POLICY_VERSION",
    "AssetReadiness",
    "CanonicalRequiredManifestFacts",
    "ContentProcessorKind",
    "ProcessorState",
    "RequiredContentAsset",
    "RequiredDeliveryPolicy",
    "RequiredManifestFingerprints",
    "RevisionImpact",
    "Sha256Digest",
    "SourceContentState",
    "SourceRevisionImpact",
    "VolumeReadiness",
    "canonical_required_mime_type",
    "required_manifest_revision_impact",
    "required_volume_readiness",
    "source_admission_requires_digest",
    "source_input_revision_impact",
]
