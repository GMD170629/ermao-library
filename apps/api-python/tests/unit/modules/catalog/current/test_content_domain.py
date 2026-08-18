from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.catalog.domain.content import (
    AssetReadiness,
    CanonicalRequiredManifestFacts,
    ContentProcessorKind,
    ProcessorState,
    RequiredContentAsset,
    RequiredDeliveryPolicy,
    RequiredManifestFingerprints,
    Sha256Digest,
    VolumeReadiness,
    canonical_required_mime_type,
    required_manifest_revision_impact,
    required_volume_readiness,
    source_input_revision_impact,
)
from app.modules.catalog.domain.model import AdmissionKind, SourceFormat
from app.modules.catalog.domain.scan import AssetRole, ReadingMorphology


def digest(character: str) -> Sha256Digest:
    return Sha256Digest(f"sha256:{character * 64}")


def asset(
    *,
    asset_id: str = "asset-1",
    mime_type: str = "application/epub+zip",
    content_digest: Sha256Digest | None = None,
    role: AssetRole = AssetRole.PRIMARY,
    source_format: SourceFormat = SourceFormat.EPUB,
    order: int = 0,
) -> RequiredContentAsset:
    return RequiredContentAsset(
        asset_id=asset_id,
        role=role,
        source_format=source_format,
        size_bytes=123,
        content_digest=content_digest or digest("a"),
        order=order,
        mime_type=mime_type,
    )


def manifest(
    *,
    asset_id: str = "asset-1",
    mime_type: str = "application/epub+zip",
    content_digest: Sha256Digest | None = None,
    delivery_policy_version: int = 1,
) -> CanonicalRequiredManifestFacts:
    return CanonicalRequiredManifestFacts(
        topology_version=1,
        reading_morphology=ReadingMorphology.REFLOWABLE,
        delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
        delivery_policy_version=delivery_policy_version,
        assets=(
            asset(
                asset_id=asset_id,
                mime_type=mime_type,
                content_digest=content_digest,
            ),
        ),
    )


def test_required_manifest_has_three_canonical_fingerprints() -> None:
    value = manifest()

    assert value.source_bytes_json == (
        b'{"topologyVersion":1,"assets":[{"order":0,'
        b'"sourceFormat":"EPUB","sizeBytes":123,'
        b'"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        b'aaaaaaaaaaaaaaaa"}]}'
    )
    assert value.fingerprints == RequiredManifestFingerprints(
        source_bytes_digest=Sha256Digest.from_bytes(value.source_bytes_json),
        content_facts_digest=Sha256Digest.from_bytes(value.content_facts_json),
        delivery_facts_digest=Sha256Digest.from_bytes(value.delivery_facts_json),
    )


def test_first_manifest_can_only_activate_from_zero() -> None:
    candidate = manifest().fingerprints

    impact = required_manifest_revision_impact(
        None,
        candidate,
        base_content_revision=0,
        base_required_manifest_revision=0,
    )
    assert impact.content_revision_delta == 1
    assert impact.required_manifest_revision_delta == 1

    with pytest.raises(ValueError, match="from revision zero"):
        required_manifest_revision_impact(
            None,
            candidate,
            base_content_revision=7,
            base_required_manifest_revision=11,
        )


def test_manifest_revision_matrix_distinguishes_identity_and_delivery() -> None:
    current = manifest()
    same = required_manifest_revision_impact(
        current.fingerprints,
        current.fingerprints,
        base_content_revision=7,
        base_required_manifest_revision=11,
    )
    assert same.content_revision_delta == 0
    assert same.required_manifest_revision_delta == 0
    assert same.reuse_active_manifest is True

    different_asset_id = manifest(asset_id="asset-2")
    assert different_asset_id.fingerprints.source_bytes_digest == (
        current.fingerprints.source_bytes_digest
    )
    identity_change = required_manifest_revision_impact(
        current.fingerprints,
        different_asset_id.fingerprints,
        base_content_revision=7,
        base_required_manifest_revision=11,
    )
    assert identity_change.content_revision_delta == 1
    assert identity_change.required_manifest_revision_delta == 1

    delivery_policy_only = manifest(delivery_policy_version=2)
    assert delivery_policy_only.fingerprints.source_bytes_digest == (
        current.fingerprints.source_bytes_digest
    )
    assert delivery_policy_only.fingerprints.content_facts_digest == (
        current.fingerprints.content_facts_digest
    )
    delivery_change = required_manifest_revision_impact(
        current.fingerprints,
        delivery_policy_only.fingerprints,
        base_content_revision=7,
        base_required_manifest_revision=11,
    )
    assert delivery_change.content_revision_delta == 0
    assert delivery_change.required_manifest_revision_delta == 1


def test_manifest_rejects_impossible_fingerprint_implication() -> None:
    previous = manifest().fingerprints
    fabricated = replace(previous, source_bytes_digest=digest("b"))

    with pytest.raises(ValueError, match="source-byte changes"):
        required_manifest_revision_impact(
            previous,
            fabricated,
            base_content_revision=1,
            base_required_manifest_revision=1,
        )


def test_manifest_enforces_required_asset_shape_and_bounds() -> None:
    base = manifest()
    with pytest.raises(ValueError, match="at least one required asset"):
        replace(base, assets=())
    with pytest.raises(ValueError, match="orders must be contiguous"):
        replace(base, assets=(replace(asset(), order=1),))
    with pytest.raises(ValueError, match="repeat an asset_id"):
        replace(base, assets=(asset(), replace(asset(), order=1)))
    with pytest.raises(ValueError, match="one PRIMARY or only AUDIO_TRACK"):
        replace(
            base,
            assets=(
                asset(),
                asset(
                    asset_id="track",
                    role=AssetRole.AUDIO_TRACK,
                    source_format=SourceFormat.MP3,
                    order=1,
                    mime_type="audio/mpeg",
                ),
            ),
        )
    invalid_track = replace(asset(), role=AssetRole.AUDIO_TRACK)
    with pytest.raises(ValueError, match="audio source format"):
        replace(base, assets=(invalid_track,))
    with pytest.raises(ValueError, match="audio source format"):
        replace(
            base,
            assets=(
                invalid_track,
                replace(invalid_track, asset_id="track-2", order=1),
            ),
        )

    too_many = tuple(
        asset(
            asset_id=f"track-{index}",
            role=AssetRole.AUDIO_TRACK,
            source_format=SourceFormat.MP3,
            order=index,
            mime_type="audio/mpeg",
        )
        for index in range(10_001)
    )
    with pytest.raises(ValueError, match="10,000"):
        CanonicalRequiredManifestFacts(
            topology_version=1,
            reading_morphology=ReadingMorphology.AUDIO,
            delivery_policy=RequiredDeliveryPolicy.ORIGINAL_SOURCE,
            delivery_policy_version=1,
            assets=too_many,
        )


def test_required_asset_rejects_noncanonical_digest_size_and_mime() -> None:
    with pytest.raises(ValueError, match="lower-case"):
        Sha256Digest(f"sha256:{'A' * 64}")
    with pytest.raises(ValueError, match="at least 0"):
        replace(asset(), size_bytes=-1)
    with pytest.raises(ValueError, match="canonical lower-case"):
        replace(asset(), mime_type="Application/EPUB+ZIP")
    with pytest.raises(ValueError, match="source-format policy"):
        replace(asset(), mime_type="application/octet-stream")


@pytest.mark.parametrize("source_format", tuple(SourceFormat))
def test_required_mime_policy_covers_every_v1_format(
    source_format: SourceFormat,
) -> None:
    mime_type = canonical_required_mime_type(source_format)
    assert mime_type == mime_type.lower()
    assert "/" in mime_type


def test_source_revision_origin_is_idempotency_not_content_equality() -> None:
    retry = source_input_revision_impact(
        input_facts_changed=False,
        explicit_modify=False,
        repeated_origin=False,
        admission=AdmissionKind.PRIMARY,
    )
    assert retry.input_revision_delta == 0

    modify = source_input_revision_impact(
        input_facts_changed=False,
        explicit_modify=True,
        repeated_origin=False,
        admission=AdmissionKind.PRIMARY,
    )
    assert modify.input_revision_delta == 1
    assert modify.digest_requeue_required is True

    repeated_modify = source_input_revision_impact(
        input_facts_changed=False,
        explicit_modify=True,
        repeated_origin=True,
        admission=AdmissionKind.PRIMARY,
    )
    assert repeated_modify.input_revision_delta == 0

    changed_during_retry = source_input_revision_impact(
        input_facts_changed=True,
        explicit_modify=False,
        repeated_origin=True,
        admission=AdmissionKind.PRIMARY,
    )
    assert changed_during_retry.input_revision_delta == 1

    became_unsupported = source_input_revision_impact(
        input_facts_changed=True,
        explicit_modify=False,
        repeated_origin=False,
        admission=AdmissionKind.UNSUPPORTED,
    )
    assert became_unsupported.input_revision_delta == 1
    assert became_unsupported.digest_requeue_required is False

    became_required_again = source_input_revision_impact(
        input_facts_changed=True,
        explicit_modify=False,
        repeated_origin=False,
        admission=AdmissionKind.PRIMARY,
    )
    assert became_required_again.input_revision_delta == 1
    assert became_required_again.digest_requeue_required is True


def test_required_readiness_only_depends_on_required_opening() -> None:
    assert (
        required_volume_readiness(
            asset_states=(AssetReadiness.READY,),
            required_manifest_state=ProcessorState.READY,
            required_opening_state=ProcessorState.READY,
        )
        is VolumeReadiness.READY
    )
    assert (
        required_volume_readiness(
            asset_states=(AssetReadiness.READY,),
            required_manifest_state=ProcessorState.FAILED,
            required_opening_state=ProcessorState.PENDING,
        )
        is VolumeReadiness.PENDING
    )
    assert (
        required_volume_readiness(
            asset_states=(AssetReadiness.READY,),
            required_manifest_state=ProcessorState.READY,
            required_opening_state=ProcessorState.FAILED,
        )
        is VolumeReadiness.UNREADABLE
    )
    assert tuple(ContentProcessorKind) == (
        ContentProcessorKind.REQUIRED_MANIFEST,
        ContentProcessorKind.REQUIRED_OPENING,
    )
