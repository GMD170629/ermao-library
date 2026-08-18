"""SQLAlchemy immutable required-manifest staging and activation repository."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.catalog.application.content_dto import (
    RequiredManifestActivationDisposition,
    RequiredManifestActivationOutcome,
    RequiredManifestCandidate,
    RequiredManifestStageBatch,
    RequiredRevisionVector,
    VolumeProcessingWorkFence,
)
from app.modules.catalog.application.content_dto import (
    RequiredManifestHeader as RequiredManifestHeaderDto,
)
from app.modules.catalog.application.content_dto import (
    RequiredManifestState as RequiredManifestStateDto,
)
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    RequiredManifestFingerprints,
    RevisionImpact,
    Sha256Digest,
    required_manifest_revision_impact,
)
from app.modules.catalog.domain.content import (
    ContentProcessorKind as DomainContentProcessorKind,
)

from .content_persistence_primitives import (
    owned_processing_conditions,
)
from .enums import (
    AssetRole,
    AssetValidationState,
    ManifestKind,
    ProcessorState,
    RequiredDeliveryPolicy,
    RequiredManifestState,
    SourceContentState,
    VolumeContentState,
)
from .models import (
    LibraryVolume,
    SourceContentFact,
    TopologyAssetMembership,
    VolumeAsset,
    VolumeManifestEntry,
    VolumeManifestHeader,
    VolumeProcessingFact,
)
from .scan_fencing import stable_id
from .source_path_resolution import SOURCE_QUERY_CHUNK
from .volume_processing_repository import (
    active_volume_context,
    all_current_required_assets_ready,
    canonical_facts_for_processing,
)


def _manifest_candidate(
    processing: VolumeProcessingFact,
    facts: CanonicalRequiredManifestFacts,
    volume: LibraryVolume,
    *,
    manifest_id: str,
) -> RequiredManifestCandidate:
    return RequiredManifestCandidate(
        manifest_id=manifest_id,
        library_id=processing.library_id,
        volume_id=processing.volume_id,
        topology_unit_revision_id=processing.active_topology_revision_id,
        base_revisions=RequiredRevisionVector(
            volume.content_revision,
            volume.required_manifest_revision,
        ),
        facts=facts,
    )


def _manifest_fingerprints(row: VolumeManifestHeader) -> RequiredManifestFingerprints:
    return RequiredManifestFingerprints(
        source_bytes_digest=Sha256Digest(row.source_bytes_digest),
        content_facts_digest=Sha256Digest(row.content_facts_digest),
        delivery_facts_digest=Sha256Digest(row.delivery_facts_digest),
    )


def _manifest_header_from_row(
    row: VolumeManifestHeader,
) -> RequiredManifestHeaderDto:
    published = (
        None
        if row.published_content_revision is None
        else RequiredRevisionVector(
            row.published_content_revision,
            cast(int, row.published_required_manifest_revision),
        )
    )
    return RequiredManifestHeaderDto(
        manifest_id=row.id,
        library_id=row.library_id,
        volume_id=row.volume_id,
        topology_unit_revision_id=row.topology_unit_revision_id,
        state=RequiredManifestStateDto(row.state.value),
        base_revisions=RequiredRevisionVector(
            row.base_content_revision,
            row.base_required_manifest_revision,
        ),
        published_revisions=published,
        fingerprints=_manifest_fingerprints(row),
        expected_entry_count=row.expected_entry_count,
        staged_entry_count=row.staged_entry_count,
    )


def _manifest_processing_row(
    session: Session,
    fence: VolumeProcessingWorkFence,
    *,
    at: datetime | None = None,
) -> VolumeProcessingFact | None:
    if fence.processor_kind is not DomainContentProcessorKind.REQUIRED_MANIFEST:
        return None
    conditions = owned_processing_conditions(fence)
    if at is not None:
        conditions = (*conditions, VolumeProcessingFact.lease_expires_at > at)
    row = session.scalar(
        select(VolumeProcessingFact).where(*conditions).with_for_update()
    )
    return row


def _delete_staging_required_manifests(
    session: Session,
    *,
    library_id: str,
    volume_id: str,
) -> None:
    session.execute(
        delete(VolumeManifestHeader).where(
            VolumeManifestHeader.library_id == library_id,
            VolumeManifestHeader.volume_id == volume_id,
            VolumeManifestHeader.kind == ManifestKind.REQUIRED,
            VolumeManifestHeader.state == RequiredManifestState.STAGING,
        )
    )
    session.flush()


class SqlAlchemyRequiredManifestRepository:
    """Stage immutable required manifests and publish them with one final CAS."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load_candidate(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        manifest_id: str,
    ) -> RequiredManifestCandidate | None:
        processing = _manifest_processing_row(self._session, fence)
        if processing is None:
            return None
        facts_result = canonical_facts_for_processing(self._session, processing)
        if facts_result is None:
            return None
        facts, volume = facts_result
        return _manifest_candidate(
            processing,
            facts,
            volume,
            manifest_id=manifest_id,
        )

    def get_active_for_update(
        self,
        library_id: str,
        volume_id: str,
    ) -> RequiredManifestHeaderDto | None:
        row = self._session.scalar(
            select(VolumeManifestHeader)
            .where(
                VolumeManifestHeader.library_id == library_id,
                VolumeManifestHeader.volume_id == volume_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
            )
            .with_for_update()
        )
        return None if row is None else _manifest_header_from_row(row)

    def retarget_active(
        self,
        fence: VolumeProcessingWorkFence,
        candidate: RequiredManifestCandidate,
        impact: RevisionImpact,
        *,
        retargeted_at: datetime,
    ) -> RequiredManifestActivationOutcome | None:
        if not impact.reuse_active_manifest:
            return None
        processing = _manifest_processing_row(
            self._session,
            fence,
            at=retargeted_at,
        )
        if processing is None or not self._candidate_matches_processing(
            processing, candidate
        ):
            return None
        _delete_staging_required_manifests(
            self._session,
            library_id=fence.library_id,
            volume_id=fence.volume_id,
        )
        context = active_volume_context(
            self._session,
            fence.library_id,
            fence.volume_id,
        )
        if context is None:
            return None
        _, volume, revision, _ = context
        active = self._session.scalar(
            select(VolumeManifestHeader)
            .where(
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
            )
            .with_for_update()
        )
        fingerprints = candidate.facts.fingerprints
        if (
            active is None
            or revision.id != candidate.topology_unit_revision_id
            or candidate.base_revisions
            != RequiredRevisionVector(
                volume.content_revision,
                volume.required_manifest_revision,
            )
            or _manifest_fingerprints(active) != fingerprints
            or active.published_content_revision != volume.content_revision
            or active.published_required_manifest_revision
            != volume.required_manifest_revision
        ):
            return None
        if not all_current_required_assets_ready(
            self._session,
            library_id=fence.library_id,
            volume_id=fence.volume_id,
            topology_revision_id=candidate.topology_unit_revision_id,
        ):
            return None
        # The immutable entries remain valid when canonical content is
        # unchanged, but the Reader fence must follow the newly ACTIVE
        # topology revision before this manifest is current again.
        active.topology_unit_revision_id = candidate.topology_unit_revision_id
        processing.state = ProcessorState.READY
        processing.available_at = retargeted_at
        processing.failure_code = None
        processing.lease_owner = None
        processing.lease_expires_at = None
        processing.updated_at = retargeted_at
        self._session.flush()
        return RequiredManifestActivationOutcome(
            disposition=RequiredManifestActivationDisposition.REUSED_ACTIVE,
            active_manifest_id=active.id,
            published_revisions=RequiredRevisionVector(
                volume.content_revision,
                volume.required_manifest_revision,
            ),
            fingerprints=fingerprints,
            revision_impact=impact,
        )

    def abandon_incomplete(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        abandoned_at: datetime,
    ) -> None:
        if _manifest_processing_row(self._session, fence, at=abandoned_at) is None:
            return
        _delete_staging_required_manifests(
            self._session,
            library_id=fence.library_id,
            volume_id=fence.volume_id,
        )

    def begin_staging(
        self,
        fence: VolumeProcessingWorkFence,
        candidate: RequiredManifestCandidate,
        impact: RevisionImpact,
        *,
        created_at: datetime,
    ) -> RequiredManifestHeaderDto | None:
        if impact.reuse_active_manifest:
            return None
        processing = _manifest_processing_row(self._session, fence, at=created_at)
        if processing is None or not self._candidate_matches_processing(
            processing, candidate
        ):
            return None
        context = active_volume_context(
            self._session,
            fence.library_id,
            fence.volume_id,
        )
        if context is None:
            return None
        _, volume, revision, _ = context
        if (
            revision.id != candidate.topology_unit_revision_id
            or candidate.base_revisions
            != RequiredRevisionVector(
                volume.content_revision,
                volume.required_manifest_revision,
            )
            or self._session.get(VolumeManifestHeader, candidate.manifest_id)
            is not None
        ):
            return None
        fingerprints = candidate.facts.fingerprints
        row = VolumeManifestHeader(
            id=candidate.manifest_id,
            library_id=fence.library_id,
            volume_id=fence.volume_id,
            kind=ManifestKind.REQUIRED,
            state=RequiredManifestState.STAGING,
            topology_unit_revision_id=candidate.topology_unit_revision_id,
            processor_version=processing.processor_version,
            processing_revision=fence.work_revision,
            topology_version=candidate.facts.topology_version,
            reading_morphology=candidate.facts.reading_morphology.value,
            delivery_policy=RequiredDeliveryPolicy(
                candidate.facts.delivery_policy.value
            ),
            delivery_policy_version=candidate.facts.delivery_policy_version,
            base_content_revision=candidate.base_revisions.content_revision,
            base_required_manifest_revision=(
                candidate.base_revisions.required_manifest_revision
            ),
            published_content_revision=None,
            published_required_manifest_revision=None,
            expected_entry_count=len(candidate.facts.assets),
            staged_entry_count=0,
            source_bytes_digest=fingerprints.source_bytes_digest.value,
            content_facts_digest=fingerprints.content_facts_digest.value,
            delivery_facts_digest=fingerprints.delivery_facts_digest.value,
            activated_at=None,
            created_at=created_at,
        )
        self._session.add(row)
        self._session.flush()
        return _manifest_header_from_row(row)

    def append_staging_batch(
        self,
        fence: VolumeProcessingWorkFence,
        staging: RequiredManifestHeaderDto,
        batch: RequiredManifestStageBatch,
        *,
        staged_at: datetime,
    ) -> RequiredManifestHeaderDto | None:
        processing = _manifest_processing_row(self._session, fence, at=staged_at)
        if processing is None:
            return None
        row = self._session.scalar(
            select(VolumeManifestHeader)
            .where(
                VolumeManifestHeader.id == staging.manifest_id,
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.STAGING,
                VolumeManifestHeader.processing_revision == fence.work_revision,
                VolumeManifestHeader.processor_version == processing.processor_version,
                VolumeManifestHeader.staged_entry_count == batch.start_order,
            )
            .with_for_update()
        )
        if row is None or _manifest_header_from_row(row) != staging:
            return None
        target_count = batch.start_order + len(batch.assets)
        if target_count > row.expected_entry_count or batch.complete != (
            target_count == row.expected_entry_count
        ):
            return None
        asset_ids = tuple(asset.asset_id for asset in batch.assets)
        memberships = {
            membership.asset_id: membership
            for membership in self._session.scalars(
                select(TopologyAssetMembership).where(
                    TopologyAssetMembership.library_id == fence.library_id,
                    TopologyAssetMembership.unit_revision_id
                    == row.topology_unit_revision_id,
                    TopologyAssetMembership.volume_id == fence.volume_id,
                    TopologyAssetMembership.asset_id.in_(asset_ids),
                    TopologyAssetMembership.required_for_reading.is_(True),
                )
            )
        }
        if set(memberships) != set(asset_ids):
            return None
        asset_rows = {
            asset.id: asset
            for asset in self._session.scalars(
                select(VolumeAsset)
                .where(
                    VolumeAsset.library_id == fence.library_id,
                    VolumeAsset.id.in_(asset_ids),
                )
                .with_for_update()
            )
        }
        if set(asset_rows) != set(asset_ids):
            return None
        source_ids = tuple(
            memberships[asset.asset_id].source_entry_id for asset in batch.assets
        )
        facts: dict[str, SourceContentFact] = {}
        for offset in range(0, len(source_ids), SOURCE_QUERY_CHUNK):
            facts.update(
                (fact.source_entry_id, fact)
                for fact in self._session.scalars(
                    select(SourceContentFact).where(
                        SourceContentFact.library_id == fence.library_id,
                        SourceContentFact.source_entry_id.in_(
                            source_ids[offset : offset + SOURCE_QUERY_CHUNK]
                        ),
                    )
                )
            )
        entries: list[VolumeManifestEntry] = []
        for asset in batch.assets:
            membership = memberships[asset.asset_id]
            fact = facts.get(membership.source_entry_id)
            if (
                fact is None
                or fact.state is not SourceContentState.READY
                or fact.digest_input_revision != fact.input_revision
                or fact.content_digest != asset.content_digest.value
                or fact.source_format != asset.source_format.value
                or fact.size_bytes != asset.size_bytes
                or membership.role.value != asset.role.value
                or membership.source_format != asset.source_format.value
                or membership.asset_order != asset.order
            ):
                return None
            entries.append(
                VolumeManifestEntry(
                    id=stable_id("manifest_entry", row.id, asset.asset_id),
                    library_id=fence.library_id,
                    volume_id=fence.volume_id,
                    manifest_id=row.id,
                    asset_id=asset.asset_id,
                    source_entry_id=fact.source_entry_id,
                    source_fact_revision=fact.input_revision,
                    role=AssetRole(asset.role.value),
                    source_format=asset.source_format.value,
                    mime_type=asset.mime_type,
                    size_bytes=asset.size_bytes,
                    content_digest=asset.content_digest.value,
                    filesystem_identity=fact.filesystem_identity,
                    modified_ns=fact.modified_ns,
                    asset_order=asset.order,
                    created_at=staged_at,
                )
            )
            asset_row = asset_rows[asset.asset_id]
            asset_row.mime_type = asset.mime_type
            asset_row.size_bytes = asset.size_bytes
            asset_row.content_digest = asset.content_digest.value
            asset_row.validation_state = AssetValidationState.READY
            asset_row.updated_at = staged_at
        self._session.add_all(entries)
        self._session.flush()
        row.staged_entry_count = target_count
        self._session.flush()
        return _manifest_header_from_row(row)

    def activate_staging(
        self,
        fence: VolumeProcessingWorkFence,
        staging: RequiredManifestHeaderDto,
        impact: RevisionImpact,
        *,
        activated_at: datetime,
    ) -> RequiredManifestActivationOutcome | None:
        processing = _manifest_processing_row(
            self._session,
            fence,
            at=activated_at,
        )
        if processing is None or impact.reuse_active_manifest:
            return None
        row = self._session.scalar(
            select(VolumeManifestHeader)
            .where(
                VolumeManifestHeader.id == staging.manifest_id,
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.state == RequiredManifestState.STAGING,
                VolumeManifestHeader.processing_revision == fence.work_revision,
                VolumeManifestHeader.staged_entry_count
                == VolumeManifestHeader.expected_entry_count,
            )
            .with_for_update()
        )
        if row is None or _manifest_header_from_row(row) != staging:
            return None
        context = active_volume_context(
            self._session,
            fence.library_id,
            fence.volume_id,
        )
        if context is None:
            return None
        _, volume, revision, _ = context
        base = RequiredRevisionVector(
            row.base_content_revision,
            row.base_required_manifest_revision,
        )
        if (
            revision.id != row.topology_unit_revision_id
            or base
            != RequiredRevisionVector(
                volume.content_revision,
                volume.required_manifest_revision,
            )
        ):
            return None
        active = self._session.scalar(
            select(VolumeManifestHeader)
            .where(
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
            )
            .with_for_update()
        )
        if active is None:
            if volume.content_revision != 0 or volume.required_manifest_revision != 0:
                return None
            previous = None
        else:
            if (
                active.published_content_revision != volume.content_revision
                or active.published_required_manifest_revision
                != volume.required_manifest_revision
            ):
                return None
            previous = _manifest_fingerprints(active)
        candidate_fingerprints = _manifest_fingerprints(row)
        try:
            actual_impact = required_manifest_revision_impact(
                previous,
                candidate_fingerprints,
                base_content_revision=base.content_revision,
                base_required_manifest_revision=base.required_manifest_revision,
            )
        except (TypeError, ValueError):
            return None
        if actual_impact != impact:
            return None
        if (
            processing.input_fingerprint
            != candidate_fingerprints.delivery_facts_digest.value
        ):
            return None
        target = base.apply(impact)
        if active is not None:
            self._session.execute(
                delete(VolumeManifestHeader).where(
                    VolumeManifestHeader.id == active.id,
                    VolumeManifestHeader.library_id == fence.library_id,
                    VolumeManifestHeader.volume_id == fence.volume_id,
                    VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
                )
            )
            self._session.flush()
        row.state = RequiredManifestState.ACTIVE
        row.published_content_revision = target.content_revision
        row.published_required_manifest_revision = target.required_manifest_revision
        row.activated_at = activated_at
        volume.content_revision = target.content_revision
        volume.required_manifest_revision = target.required_manifest_revision
        volume.required_manifest_digest = row.source_bytes_digest
        volume.content_state = VolumeContentState.PENDING
        if impact.content_facts_changed:
            volume.publication_fingerprint = None
        volume.updated_at = activated_at
        processing.state = ProcessorState.READY
        processing.available_at = activated_at
        processing.failure_code = None
        processing.lease_owner = None
        processing.lease_expires_at = None
        processing.updated_at = activated_at
        self._session.flush()
        return RequiredManifestActivationOutcome(
            disposition=RequiredManifestActivationDisposition.ACTIVATED_NEW,
            active_manifest_id=row.id,
            published_revisions=target,
            fingerprints=candidate_fingerprints,
            revision_impact=impact,
        )

    @staticmethod
    def _candidate_matches_processing(
        processing: VolumeProcessingFact,
        candidate: RequiredManifestCandidate,
    ) -> bool:
        return (
            candidate.library_id == processing.library_id
            and candidate.volume_id == processing.volume_id
            and candidate.topology_unit_revision_id
            == processing.active_topology_revision_id
            and candidate.base_revisions
            == RequiredRevisionVector(
                processing.expected_content_revision,
                processing.expected_required_manifest_revision,
            )
            and candidate.facts.fingerprints.delivery_facts_digest.value
            == processing.input_fingerprint
        )


__all__ = ["SqlAlchemyRequiredManifestRepository"]
