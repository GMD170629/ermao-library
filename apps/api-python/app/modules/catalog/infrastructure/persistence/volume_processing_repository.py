"""SQLAlchemy volume-processing lease, readiness, and opening repository."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.modules.catalog.application.content_dto import (
    ContentLibrarySnapshot,
    ContentSchedulingOutcome,
    RequiredManifestActivationOutcome,
    RequiredOpeningDisposition,
    RequiredOpeningEvidence,
    RequiredOpeningRequest,
    RequiredOpeningSource,
    RequiredRevisionVector,
    SourceDigestPublishOutcome,
    VolumeProcessingClaimOutcome,
    VolumeProcessingWorkFence,
)
from app.modules.catalog.application.content_dto import (
    VolumeProcessingFact as VolumeProcessingFactDto,
)
from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.content import (
    CanonicalRequiredManifestFacts,
    RequiredContentAsset,
    Sha256Digest,
    canonical_required_mime_type,
)
from app.modules.catalog.domain.content import (
    ContentProcessorKind as DomainContentProcessorKind,
)
from app.modules.catalog.domain.content import (
    ProcessorState as DomainProcessorState,
)
from app.modules.catalog.domain.content import (
    RequiredDeliveryPolicy as DomainRequiredDeliveryPolicy,
)
from app.modules.catalog.domain.content import (
    SourceContentState as DomainSourceContentState,
)
from app.modules.catalog.domain.library import (
    LibraryControlState as DomainLibraryControlState,
)
from app.modules.catalog.domain.model import (
    SourceFormat,
)
from app.modules.catalog.domain.scan import (
    AssetRole as DomainAssetRole,
)
from app.modules.catalog.domain.scan import (
    ReadingMorphology,
)

from .content_persistence_primitives import (
    CLAIM_CANDIDATE_LIMIT,
    DELIVERY_POLICY_VERSION,
    MAX_DEFERRED_CLAIMS,
    MAX_REQUIRED_ASSETS,
    MAX_SOURCE_PATH_DEPTH,
    REQUIRED_OPENING_PROCESSOR_VERSION,
    current_required_memberships_for_sources,
    owned_processing_conditions,
)
from .enums import (
    AssetValidationState,
    ContentProcessorKind,
    LayoutState,
    LibraryControlState,
    ManifestKind,
    ProcessorState,
    RequiredManifestState,
    RevisionState,
    SlotState,
    SourceContentState,
    SourceEntryType,
    VolumeContentState,
)
from .models import (
    CatalogLibrary,
    LibrarySourceEntry,
    LibraryVolume,
    SourceContentFact,
    TopologyAssetMembership,
    TopologyUnit,
    TopologyUnitRevision,
    TopologyVolumeProjection,
    VolumeAsset,
    VolumeManifestEntry,
    VolumeManifestHeader,
    VolumeProcessingFact,
)
from .source_content_repositories import (
    project_source_digest_ready,
    source_path_if_effective,
)
from .source_path_resolution import SOURCE_QUERY_CHUNK


def all_current_required_assets_ready(
    session: Session,
    *,
    library_id: str,
    volume_id: str,
    topology_revision_id: str,
) -> bool:
    required_count = session.scalar(
        select(func.count())
        .select_from(TopologyAssetMembership)
        .where(
            TopologyAssetMembership.library_id == library_id,
            TopologyAssetMembership.volume_id == volume_id,
            TopologyAssetMembership.unit_revision_id == topology_revision_id,
            TopologyAssetMembership.required_for_reading.is_(True),
        )
    )
    if required_count is None or required_count == 0:
        return False
    ready_count = session.scalar(
        select(func.count())
        .select_from(TopologyAssetMembership)
        .join(
            VolumeAsset,
            and_(
                VolumeAsset.library_id == TopologyAssetMembership.library_id,
                VolumeAsset.id == TopologyAssetMembership.asset_id,
                VolumeAsset.validation_state == AssetValidationState.READY,
            ),
        )
        .where(
            TopologyAssetMembership.library_id == library_id,
            TopologyAssetMembership.volume_id == volume_id,
            TopologyAssetMembership.unit_revision_id == topology_revision_id,
            TopologyAssetMembership.required_for_reading.is_(True),
        )
    )
    return ready_count == required_count


def active_volume_context(
    session: Session,
    library_id: str,
    volume_id: str,
) -> (
    tuple[
        CatalogLibrary,
        LibraryVolume,
        TopologyUnitRevision,
        TopologyVolumeProjection,
    ]
    | None
):
    result = session.execute(
        select(
            CatalogLibrary,
            LibraryVolume,
            TopologyUnitRevision,
            TopologyVolumeProjection,
        )
        .join(
            LibraryVolume,
            LibraryVolume.library_id == CatalogLibrary.id,
        )
        .join(
            TopologyVolumeProjection,
            and_(
                TopologyVolumeProjection.library_id == LibraryVolume.library_id,
                TopologyVolumeProjection.volume_id == LibraryVolume.id,
            ),
        )
        .join(
            TopologyUnitRevision,
            and_(
                TopologyUnitRevision.library_id == TopologyVolumeProjection.library_id,
                TopologyUnitRevision.id == TopologyVolumeProjection.unit_revision_id,
                TopologyUnitRevision.state == RevisionState.ACTIVE,
            ),
        )
        .join(
            TopologyUnit,
            and_(
                TopologyUnit.library_id == TopologyUnitRevision.library_id,
                TopologyUnit.id == TopologyUnitRevision.unit_id,
                TopologyUnit.active_revision_id == TopologyUnitRevision.id,
            ),
        )
        .where(
            CatalogLibrary.id == library_id,
            CatalogLibrary.control_state == LibraryControlState.ACTIVE,
            CatalogLibrary.last_successful_generation.is_not(None),
            LibraryVolume.id == volume_id,
        )
    ).one_or_none()
    if result is None:
        return None
    library, volume, revision, projection = result
    return library, volume, revision, projection


def _load_effective_source_graph(
    session: Session,
    library: CatalogLibrary,
    source_ids: tuple[str, ...],
) -> dict[str, LibrarySourceEntry] | None:
    generation = library.last_successful_generation
    if generation is None:
        return None
    loaded: dict[str, LibrarySourceEntry] = {}
    frontier = set(source_ids)
    depth = 0
    while frontier:
        depth += 1
        if depth > MAX_SOURCE_PATH_DEPTH:
            return None
        ordered = tuple(sorted(frontier))
        rows: dict[str, LibrarySourceEntry] = {}
        for offset in range(0, len(ordered), SOURCE_QUERY_CHUNK):
            rows.update(
                (row.id, row)
                for row in session.scalars(
                    select(LibrarySourceEntry).where(
                        LibrarySourceEntry.library_id == library.id,
                        LibrarySourceEntry.id.in_(
                            ordered[offset : offset + SOURCE_QUERY_CHUNK]
                        ),
                    )
                )
            )
        if set(rows) != frontier:
            return None
        if any(
            row.slot_state is not SlotState.ACTIVE
            or row.layout_state is not LayoutState.PRESENT
            or row.absence_confirmed_at is not None
            or row.last_seen_generation != generation
            for row in rows.values()
        ):
            return None
        loaded.update(rows)
        frontier = {
            row.parent_entry_id
            for row in rows.values()
            if row.parent_entry_id is not None and row.parent_entry_id not in loaded
        }
    for row in loaded.values():
        if row.parent_entry_id is None:
            if row.entry_type is not SourceEntryType.SYNTHETIC_ROOT:
                return None
            continue
        parent = loaded.get(row.parent_entry_id)
        if parent is None or parent.entry_type not in {
            SourceEntryType.SYNTHETIC_ROOT,
            SourceEntryType.DIRECTORY,
        }:
            return None
        if (
            row.observed_parent_presence_epoch != parent.children_presence_epoch
            and row.pending_observed_parent_presence_epoch
            != parent.children_presence_epoch
        ):
            return None
    return {source_id: loaded[source_id] for source_id in source_ids}


def canonical_facts_for_processing(
    session: Session,
    processing: VolumeProcessingFact,
) -> tuple[CanonicalRequiredManifestFacts, LibraryVolume] | None:
    context = active_volume_context(
        session,
        processing.library_id,
        processing.volume_id,
    )
    if context is None:
        return None
    library, volume, revision, projection = context
    if (
        revision.id != processing.active_topology_revision_id
        or volume.content_revision != processing.expected_content_revision
        or volume.required_manifest_revision
        != processing.expected_required_manifest_revision
    ):
        return None
    memberships = tuple(
        session.scalars(
            select(TopologyAssetMembership)
            .where(
                TopologyAssetMembership.library_id == processing.library_id,
                TopologyAssetMembership.unit_revision_id == revision.id,
                TopologyAssetMembership.volume_id == processing.volume_id,
                TopologyAssetMembership.required_for_reading.is_(True),
            )
            .order_by(
                TopologyAssetMembership.asset_order,
                TopologyAssetMembership.id,
            )
            .limit(MAX_REQUIRED_ASSETS + 1)
        )
    )
    if not memberships or len(memberships) > MAX_REQUIRED_ASSETS:
        return None
    source_ids = tuple(dict.fromkeys(row.source_entry_id for row in memberships))
    source_rows = _load_effective_source_graph(session, library, source_ids)
    if source_rows is None:
        return None
    facts: dict[str, SourceContentFact] = {}
    for offset in range(0, len(source_ids), SOURCE_QUERY_CHUNK):
        facts.update(
            (row.source_entry_id, row)
            for row in session.scalars(
                select(SourceContentFact).where(
                    SourceContentFact.library_id == processing.library_id,
                    SourceContentFact.source_entry_id.in_(
                        source_ids[offset : offset + SOURCE_QUERY_CHUNK]
                    ),
                )
            )
        )
    if set(facts) != set(source_ids):
        return None
    assets: list[RequiredContentAsset] = []
    for membership in memberships:
        fact = facts[membership.source_entry_id]
        source = source_rows[membership.source_entry_id]
        if (
            fact.state is not SourceContentState.READY
            or fact.content_digest is None
            or fact.digest_input_revision != fact.input_revision
            or fact.source_format != membership.source_format
            or fact.filesystem_identity != source.filesystem_identity
            or fact.size_bytes != source.size_bytes
            or fact.modified_ns != source.modified_ns
        ):
            return None
        source_format = SourceFormat(membership.source_format)
        assets.append(
            RequiredContentAsset(
                asset_id=membership.asset_id,
                role=DomainAssetRole(membership.role.value),
                source_format=source_format,
                size_bytes=fact.size_bytes,
                content_digest=Sha256Digest(fact.content_digest),
                order=membership.asset_order,
                mime_type=canonical_required_mime_type(source_format),
            )
        )
    try:
        facts_value = CanonicalRequiredManifestFacts(
            topology_version=library.topology_version,
            reading_morphology=ReadingMorphology(projection.reading_morphology),
            delivery_policy=DomainRequiredDeliveryPolicy.ORIGINAL_SOURCE,
            delivery_policy_version=DELIVERY_POLICY_VERSION,
            assets=tuple(assets),
        )
    except (TypeError, ValueError):
        return None
    return facts_value, volume


def _processing_fact_from_row(
    row: VolumeProcessingFact,
) -> VolumeProcessingFactDto:
    return VolumeProcessingFactDto(
        library_id=row.library_id,
        volume_id=row.volume_id,
        processor_kind=DomainContentProcessorKind(row.processor_kind.value),
        processor_version=row.processor_version,
        work_revision=row.work_revision,
        active_topology_revision_id=row.active_topology_revision_id,
        target_vector=RequiredRevisionVector(
            row.expected_content_revision,
            row.expected_required_manifest_revision,
        ),
        input_fingerprint=Sha256Digest(row.input_fingerprint),
        state=DomainProcessorState(row.state.value),
        available_at=row.available_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        failure_code=row.failure_code,
    )


class SqlAlchemyContentLibraryRepository:
    """Load the current library control state inside the content writer UoW."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_content_for_update(
        self,
        library_id: str,
    ) -> ContentLibrarySnapshot | None:
        row = self._session.scalar(
            select(CatalogLibrary)
            .where(CatalogLibrary.id == library_id)
            .with_for_update()
        )
        if row is None:
            return None
        return ContentLibrarySnapshot(
            library_id=row.id,
            control_state=DomainLibraryControlState(row.control_state.value),
        )


class SqlAlchemyVolumeProcessingRepository:
    """Lease current per-Volume processor work without hidden commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def claim_next(
        self,
        library_id: str,
        processor_kind: DomainContentProcessorKind,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
        defer_until: datetime,
    ) -> VolumeProcessingClaimOutcome:
        if defer_until <= now:
            raise ValueError("defer_until must be later than now")
        stored_kind = ContentProcessorKind(processor_kind.value)
        candidates = tuple(
            self._session.scalars(
                select(VolumeProcessingFact)
                .where(
                    VolumeProcessingFact.library_id == library_id,
                    VolumeProcessingFact.processor_kind == stored_kind,
                    or_(
                        and_(
                            VolumeProcessingFact.state == ProcessorState.PENDING,
                            VolumeProcessingFact.available_at <= now,
                        ),
                        and_(
                            VolumeProcessingFact.state == ProcessorState.RUNNING,
                            VolumeProcessingFact.lease_expires_at.is_not(None),
                            VolumeProcessingFact.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(
                    VolumeProcessingFact.available_at,
                    VolumeProcessingFact.volume_id,
                )
                .limit(CLAIM_CANDIDATE_LIMIT)
                .with_for_update()
            )
        )
        deferred_count = 0
        for row in candidates:
            context = active_volume_context(self._session, library_id, row.volume_id)
            if context is None:
                input_fingerprint = None
            else:
                _, volume, revision, _ = context
                if stored_kind is ContentProcessorKind.REQUIRED_MANIFEST:
                    facts_result = canonical_facts_for_processing(self._session, row)
                    input_fingerprint = (
                        None
                        if facts_result is None
                        else facts_result[0].fingerprints.delivery_facts_digest.value
                    )
                else:
                    active = self._session.scalar(
                        select(VolumeManifestHeader).where(
                            VolumeManifestHeader.library_id == library_id,
                            VolumeManifestHeader.volume_id == row.volume_id,
                            VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                            VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
                            VolumeManifestHeader.published_content_revision
                            == volume.content_revision,
                            VolumeManifestHeader.published_required_manifest_revision
                            == volume.required_manifest_revision,
                        )
                    )
                    input_fingerprint = (
                        None if active is None else active.content_facts_digest
                    )
                if (
                    row.active_topology_revision_id != revision.id
                    or row.expected_content_revision != volume.content_revision
                    or row.expected_required_manifest_revision
                    != volume.required_manifest_revision
                ):
                    input_fingerprint = None
            if input_fingerprint is None:
                if deferred_count >= MAX_DEFERRED_CLAIMS:
                    break
                result = self._session.execute(
                    update(VolumeProcessingFact)
                    .where(
                        VolumeProcessingFact.library_id == library_id,
                        VolumeProcessingFact.volume_id == row.volume_id,
                        VolumeProcessingFact.processor_kind == stored_kind,
                        VolumeProcessingFact.work_revision == row.work_revision,
                        VolumeProcessingFact.state == row.state,
                        (
                            VolumeProcessingFact.lease_owner.is_(None)
                            if row.lease_owner is None
                            else VolumeProcessingFact.lease_owner == row.lease_owner
                        ),
                        (
                            VolumeProcessingFact.lease_expires_at.is_(None)
                            if row.lease_expires_at is None
                            else VolumeProcessingFact.lease_expires_at
                            == row.lease_expires_at
                        ),
                    )
                    .values(
                        state=ProcessorState.PENDING,
                        available_at=defer_until,
                        failure_code=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                if cast(CursorResult[object], result).rowcount == 1:
                    deferred_count += 1
                continue
            previous_revision = row.work_revision
            previous_state = row.state
            previous_owner = row.lease_owner
            previous_expiry = row.lease_expires_at
            fingerprint_changed = row.input_fingerprint != input_fingerprint
            result = self._session.execute(
                update(VolumeProcessingFact)
                .where(
                    VolumeProcessingFact.library_id == library_id,
                    VolumeProcessingFact.volume_id == row.volume_id,
                    VolumeProcessingFact.processor_kind == stored_kind,
                    VolumeProcessingFact.work_revision == previous_revision,
                    VolumeProcessingFact.state == previous_state,
                    (
                        VolumeProcessingFact.lease_owner.is_(None)
                        if previous_owner is None
                        else VolumeProcessingFact.lease_owner == previous_owner
                    ),
                    (
                        VolumeProcessingFact.lease_expires_at.is_(None)
                        if previous_expiry is None
                        else VolumeProcessingFact.lease_expires_at == previous_expiry
                    ),
                )
                .values(
                    input_fingerprint=input_fingerprint,
                    work_revision=previous_revision + (2 if fingerprint_changed else 1),
                    state=ProcessorState.RUNNING,
                    available_at=now if fingerprint_changed else row.available_at,
                    lease_owner=owner_token,
                    lease_expires_at=lease_expires_at,
                    failure_code=None,
                    updated_at=now,
                )
            )
            if cast(CursorResult[object], result).rowcount != 1:
                continue
            claimed = self._session.get(
                VolumeProcessingFact,
                (library_id, row.volume_id, stored_kind),
                populate_existing=True,
            )
            return VolumeProcessingClaimOutcome(
                None if claimed is None else _processing_fact_from_row(claimed),
                deferred_count,
            )
        return VolumeProcessingClaimOutcome(None, deferred_count)

    def heartbeat(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> VolumeProcessingFactDto | None:
        result = self._session.execute(
            update(VolumeProcessingFact)
            .where(
                *owned_processing_conditions(fence),
                VolumeProcessingFact.lease_expires_at > now,
            )
            .values(lease_expires_at=lease_expires_at, updated_at=now)
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        self._session.flush()
        row = self._session.get(
            VolumeProcessingFact,
            (
                fence.library_id,
                fence.volume_id,
                ContentProcessorKind(fence.processor_kind.value),
            ),
            populate_existing=True,
        )
        return None if row is None else _processing_fact_from_row(row)

    def release_for_retry(
        self,
        fence: VolumeProcessingWorkFence,
        *,
        diagnostic_code: str,
        retry_at: datetime,
        released_at: datetime,
    ) -> VolumeProcessingFactDto | None:
        if not diagnostic_code.strip():
            raise ValueError("diagnostic_code must be non-empty")
        result = self._session.execute(
            update(VolumeProcessingFact)
            .where(
                *owned_processing_conditions(fence),
                VolumeProcessingFact.lease_expires_at > released_at,
            )
            .values(
                state=ProcessorState.PENDING,
                available_at=retry_at,
                failure_code=None,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=released_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        self._session.flush()
        row = self._session.get(
            VolumeProcessingFact,
            (
                fence.library_id,
                fence.volume_id,
                ContentProcessorKind(fence.processor_kind.value),
            ),
            populate_existing=True,
        )
        return None if row is None else _processing_fact_from_row(row)

    def schedule_required_manifest_for_digest(
        self,
        outcome: SourceDigestPublishOutcome,
        *,
        scheduled_at: datetime,
    ) -> ContentSchedulingOutcome:
        current = outcome.current
        if current.state is not DomainSourceContentState.READY:
            return ContentSchedulingOutcome(0, False)
        fact = self._session.scalar(
            select(SourceContentFact)
            .where(
                SourceContentFact.library_id == current.library_id,
                SourceContentFact.source_entry_id == current.source_entry_id,
                SourceContentFact.input_revision == current.input_revision,
                SourceContentFact.digest_input_revision == current.input_revision,
                SourceContentFact.state == SourceContentState.READY,
                SourceContentFact.content_digest
                == (
                    None
                    if current.content_digest is None
                    else current.content_digest.value
                ),
            )
            .with_for_update()
        )
        if fact is None:
            return ContentSchedulingOutcome(0, False)
        memberships = current_required_memberships_for_sources(
            self._session,
            current.library_id,
            (current.source_entry_id,),
        )
        volume_ids = tuple(dict.fromkeys(value[1] for value in memberships))
        project_source_digest_ready(
            self._session,
            fact,
            published_at=scheduled_at,
        )
        self._session.flush()
        return ContentSchedulingOutcome(len(volume_ids), bool(volume_ids))

    def schedule_required_opening(
        self,
        fence: VolumeProcessingWorkFence,
        outcome: RequiredManifestActivationOutcome,
        *,
        topology_unit_revision_id: str,
        scheduled_at: datetime,
    ) -> ContentSchedulingOutcome | None:
        if fence.processor_kind is not DomainContentProcessorKind.REQUIRED_MANIFEST:
            return None
        manifest_processing = self._session.get(
            VolumeProcessingFact,
            (
                fence.library_id,
                fence.volume_id,
                ContentProcessorKind.REQUIRED_MANIFEST,
            ),
        )
        if (
            manifest_processing is None
            or manifest_processing.work_revision != fence.work_revision
            or manifest_processing.state is not ProcessorState.READY
            or manifest_processing.lease_owner is not None
            or manifest_processing.lease_expires_at is not None
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
            revision.id != topology_unit_revision_id
            or outcome.published_revisions.content_revision != volume.content_revision
            or outcome.published_revisions.required_manifest_revision
            != volume.required_manifest_revision
        ):
            return None
        active = self._session.scalar(
            select(VolumeManifestHeader).where(
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.id == outcome.active_manifest_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
                VolumeManifestHeader.topology_unit_revision_id == revision.id,
                VolumeManifestHeader.published_content_revision
                == volume.content_revision,
                VolumeManifestHeader.published_required_manifest_revision
                == volume.required_manifest_revision,
            )
        )
        if active is None:
            return None
        input_fingerprint = active.content_facts_digest
        opening = self._session.get(
            VolumeProcessingFact,
            (
                fence.library_id,
                fence.volume_id,
                ContentProcessorKind.REQUIRED_OPENING,
            ),
        )
        reusable = (
            opening is not None
            and opening.state is ProcessorState.READY
            and opening.processor_version == REQUIRED_OPENING_PROCESSOR_VERSION
            and opening.expected_content_revision == volume.content_revision
            and opening.input_fingerprint == input_fingerprint
            and volume.publication_fingerprint is not None
            and all_current_required_assets_ready(
                self._session,
                library_id=fence.library_id,
                volume_id=fence.volume_id,
                topology_revision_id=topology_unit_revision_id,
            )
        )
        if opening is None:
            opening = VolumeProcessingFact(
                library_id=fence.library_id,
                volume_id=fence.volume_id,
                processor_kind=ContentProcessorKind.REQUIRED_OPENING,
                work_revision=1,
                processor_version=REQUIRED_OPENING_PROCESSOR_VERSION,
                active_topology_revision_id=topology_unit_revision_id,
                expected_content_revision=volume.content_revision,
                expected_required_manifest_revision=volume.required_manifest_revision,
                input_fingerprint=input_fingerprint,
                available_at=scheduled_at,
                state=ProcessorState.PENDING,
                failure_code=None,
                lease_owner=None,
                lease_expires_at=None,
                created_at=scheduled_at,
                updated_at=scheduled_at,
            )
            self._session.add(opening)
        elif reusable:
            opening.active_topology_revision_id = topology_unit_revision_id
            opening.expected_content_revision = volume.content_revision
            opening.expected_required_manifest_revision = (
                volume.required_manifest_revision
            )
            opening.updated_at = scheduled_at
        else:
            opening.work_revision += 1
            opening.processor_version = REQUIRED_OPENING_PROCESSOR_VERSION
            opening.active_topology_revision_id = topology_unit_revision_id
            opening.expected_content_revision = volume.content_revision
            opening.expected_required_manifest_revision = (
                volume.required_manifest_revision
            )
            opening.input_fingerprint = input_fingerprint
            opening.available_at = scheduled_at
            opening.state = ProcessorState.PENDING
            opening.failure_code = None
            opening.lease_owner = None
            opening.lease_expires_at = None
            opening.updated_at = scheduled_at
        if reusable:
            volume.content_state = VolumeContentState.READY
        else:
            volume.content_state = VolumeContentState.PENDING
            if outcome.revision_impact.content_facts_changed:
                volume.publication_fingerprint = None
        volume.updated_at = scheduled_at
        self._session.flush()
        return ContentSchedulingOutcome(0 if reusable else 1, not reusable)

    def load_required_opening_request(
        self,
        fence: VolumeProcessingWorkFence,
    ) -> RequiredOpeningRequest | None:
        if fence.processor_kind is not DomainContentProcessorKind.REQUIRED_OPENING:
            return None
        row = self._session.scalar(
            select(VolumeProcessingFact).where(*owned_processing_conditions(fence))
        )
        if row is None:
            return None
        context = active_volume_context(
            self._session,
            fence.library_id,
            fence.volume_id,
        )
        if context is None:
            return None
        library, volume, revision, _ = context
        if (
            row.active_topology_revision_id != revision.id
            or row.expected_content_revision != volume.content_revision
            or row.expected_required_manifest_revision
            != volume.required_manifest_revision
        ):
            return None
        manifest = self._session.scalar(
            select(VolumeManifestHeader).where(
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
                VolumeManifestHeader.topology_unit_revision_id == revision.id,
                VolumeManifestHeader.published_content_revision
                == volume.content_revision,
                VolumeManifestHeader.published_required_manifest_revision
                == volume.required_manifest_revision,
                VolumeManifestHeader.content_facts_digest == row.input_fingerprint,
            )
        )
        if manifest is None:
            return None
        entries = tuple(
            self._session.scalars(
                select(VolumeManifestEntry)
                .where(
                    VolumeManifestEntry.library_id == fence.library_id,
                    VolumeManifestEntry.volume_id == fence.volume_id,
                    VolumeManifestEntry.manifest_id == manifest.id,
                )
                .order_by(VolumeManifestEntry.asset_order)
                .limit(MAX_REQUIRED_ASSETS + 1)
            )
        )
        if (
            not entries
            or len(entries) > MAX_REQUIRED_ASSETS
            or len(entries) != manifest.expected_entry_count
        ):
            return None
        source_ids = tuple(entry.source_entry_id for entry in entries)
        source_rows = _load_effective_source_graph(self._session, library, source_ids)
        if source_rows is None:
            return None
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
        opening_sources: list[RequiredOpeningSource] = []
        expected_root_identity: str | None = None
        for entry in entries:
            fact = facts.get(entry.source_entry_id)
            source = source_rows[entry.source_entry_id]
            if (
                fact is None
                or fact.state is not SourceContentState.READY
                or fact.digest_input_revision != fact.input_revision
                or fact.content_digest != entry.content_digest
                or fact.source_format != entry.source_format
                or fact.size_bytes != entry.size_bytes
                or source.filesystem_identity != fact.filesystem_identity
                or source.size_bytes != fact.size_bytes
                or source.modified_ns != fact.modified_ns
            ):
                return None
            path = source_path_if_effective(self._session, library, source)
            if path is None:
                return None
            relative_path, root_identity = path
            if expected_root_identity is None:
                expected_root_identity = root_identity
            elif expected_root_identity != root_identity:
                return None
            opening_sources.append(
                RequiredOpeningSource(
                    source_entry_id=entry.source_entry_id,
                    relative_path=relative_path,
                    source_format=SourceFormat(entry.source_format),
                    expected_stat=SourceStatExpectation(
                        device_id=fact.device_id,
                        file_id=fact.file_id,
                        size_bytes=fact.size_bytes,
                        modified_ns=fact.modified_ns,
                    ),
                    content_digest=Sha256Digest(entry.content_digest),
                    order=entry.asset_order,
                )
            )
        if expected_root_identity is None:
            return None
        return RequiredOpeningRequest(
            library_id=fence.library_id,
            volume_id=fence.volume_id,
            topology_unit_revision_id=revision.id,
            target_revisions=RequiredRevisionVector(
                volume.content_revision,
                volume.required_manifest_revision,
            ),
            canonical_root=library.root_path,
            expected_root_identity=expected_root_identity,
            sources=tuple(opening_sources),
        )

    def complete_required_opening(
        self,
        fence: VolumeProcessingWorkFence,
        evidence: RequiredOpeningEvidence,
        *,
        completed_at: datetime,
    ) -> VolumeProcessingFactDto | None:
        if fence.processor_kind is not DomainContentProcessorKind.REQUIRED_OPENING:
            return None
        row = self._session.scalar(
            select(VolumeProcessingFact)
            .where(
                *owned_processing_conditions(fence),
                VolumeProcessingFact.lease_expires_at > completed_at,
            )
            .with_for_update()
        )
        if row is None:
            return None
        context = active_volume_context(
            self._session,
            fence.library_id,
            fence.volume_id,
        )
        if context is None:
            return None
        _, volume, revision, _ = context
        active = self._session.scalar(
            select(VolumeManifestHeader).where(
                VolumeManifestHeader.library_id == fence.library_id,
                VolumeManifestHeader.volume_id == fence.volume_id,
                VolumeManifestHeader.kind == ManifestKind.REQUIRED,
                VolumeManifestHeader.state == RequiredManifestState.ACTIVE,
                VolumeManifestHeader.topology_unit_revision_id == revision.id,
                VolumeManifestHeader.published_content_revision
                == volume.content_revision,
                VolumeManifestHeader.published_required_manifest_revision
                == volume.required_manifest_revision,
                VolumeManifestHeader.content_facts_digest == row.input_fingerprint,
            )
        )
        if (
            active is None
            or row.active_topology_revision_id != revision.id
            or row.expected_content_revision != volume.content_revision
            or row.expected_required_manifest_revision
            != volume.required_manifest_revision
        ):
            return None
        if evidence.disposition is RequiredOpeningDisposition.READY:
            if evidence.publication_fingerprint is None:
                return None
            row.state = ProcessorState.READY
            row.failure_code = None
            volume.content_state = VolumeContentState.READY
            volume.publication_fingerprint = evidence.publication_fingerprint.value
        else:
            if evidence.diagnostic_code is None:
                return None
            row.state = ProcessorState.FAILED
            row.failure_code = evidence.diagnostic_code
            volume.content_state = VolumeContentState.UNREADABLE
            volume.publication_fingerprint = None
        row.available_at = completed_at
        row.lease_owner = None
        row.lease_expires_at = None
        row.updated_at = completed_at
        volume.updated_at = completed_at
        self._session.flush()
        return _processing_fact_from_row(row)


__all__ = [
    "SqlAlchemyContentLibraryRepository",
    "SqlAlchemyVolumeProcessingRepository",
]
