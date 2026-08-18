"""SQLAlchemy source-observation and digest-work repositories."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from typing import cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.content_dto import (
    ContentObservationOrigin,
    ExplicitSourceModify,
    FullScanContentOrigin,
    ObservedContentSource,
    ReconcileContentOrigin,
    SourceContentObservationOutcome,
    SourceContentWorkFence,
    SourceDigestClaimOutcome,
    SourceDigestEvidence,
    SourceDigestPublishDisposition,
    SourceDigestPublishOutcome,
    SourceDigestRequest,
    SourceDigestWork,
    WatcherContentOrigin,
)
from app.modules.catalog.application.content_dto import (
    SourceContentFact as SourceContentFactDto,
)
from app.modules.catalog.application.scan_dto import ScanFence
from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.content import (
    Sha256Digest,
    canonical_required_mime_type,
    source_admission_requires_digest,
    source_input_revision_impact,
)
from app.modules.catalog.domain.content import (
    SourceContentState as DomainSourceContentState,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    SourceFormat,
)
from app.modules.catalog.domain.watcher import ReconcileStale

from .content_persistence_primitives import (
    CLAIM_CANDIDATE_LIMIT,
    MAX_DEFERRED_CLAIMS,
    MAX_OBSERVATIONS,
    MAX_SOURCE_PATH_DEPTH,
    ContentFence,
    current_required_memberships_for_sources,
    is_after,
    mark_current_sources_pending,
    presence_generation,
    raise_content_stale,
    require_content_fence,
)
from .enums import (
    AssetValidationState,
    ContentOriginKind,
    LayoutState,
    LibraryControlState,
    SlotState,
    SourceContentState,
    SourceEntryType,
)
from .models import (
    CatalogLibrary,
    LibrarySourceEntry,
    SourceContentFact,
    TopologyAssetMembership,
    TopologyUnit,
    VolumeAsset,
)
from .source_path_resolution import SOURCE_QUERY_CHUNK, resolve_raw_paths


def _origin_values(
    origin: ContentObservationOrigin,
) -> tuple[ContentOriginKind, str | None, int]:
    if isinstance(origin, FullScanContentOrigin):
        return ContentOriginKind.FULL_SCAN, origin.scan_id, origin.generation
    if isinstance(origin, ReconcileContentOrigin):
        return (
            ContentOriginKind.RECONCILE,
            origin.reconcile_intent_id,
            origin.through_sequence,
        )
    return ContentOriginKind.WATCHER, None, origin.watcher_sequence


def _origin_from_row(row: SourceContentFact) -> ContentObservationOrigin:
    if row.origin_kind is ContentOriginKind.FULL_SCAN:
        if row.origin_id is None:
            raise ValueError("FULL_SCAN content origin is missing its scan id")
        return FullScanContentOrigin(row.origin_id, row.origin_sequence)
    if row.origin_kind is ContentOriginKind.RECONCILE:
        if row.origin_id is None:
            raise ValueError("RECONCILE content origin is missing its intent id")
        return ReconcileContentOrigin(row.origin_id, row.origin_sequence)
    if row.origin_id is not None:
        raise ValueError("WATCHER content origin cannot carry an origin id")
    return WatcherContentOrigin(row.origin_sequence)


def _origin_matches_row(
    row: SourceContentFact,
    origin: ContentObservationOrigin,
) -> bool:
    kind, origin_id, sequence = _origin_values(origin)
    return (
        row.origin_kind is kind
        and row.origin_id == origin_id
        and row.origin_sequence == sequence
    )


def _validate_origin_for_fence(
    fence: ContentFence,
    origin: ContentObservationOrigin,
) -> None:
    if isinstance(fence, ScanFence):
        valid = (
            isinstance(origin, FullScanContentOrigin)
            and origin.scan_id == fence.scan_id
            and origin.generation == fence.generation
        )
    else:
        valid = (
            isinstance(origin, ReconcileContentOrigin)
            and origin.reconcile_intent_id == fence.intent_id
            and origin.through_sequence == fence.through_sequence
        )
    if not valid:
        raise_content_stale(fence)


def _source_fact_from_row(row: SourceContentFact) -> SourceContentFactDto:
    source_format = (
        None if row.source_format is None else SourceFormat(row.source_format)
    )
    digest = None if row.content_digest is None else Sha256Digest(row.content_digest)
    return SourceContentFactDto(
        library_id=row.library_id,
        source_entry_id=row.source_entry_id,
        input_revision=row.input_revision,
        work_revision=row.work_revision,
        admission=AdmissionKind(row.admission),
        source_format=source_format,
        filesystem_identity=row.filesystem_identity,
        expected_stat=SourceStatExpectation(
            device_id=row.device_id,
            file_id=row.file_id,
            size_bytes=row.size_bytes,
            modified_ns=row.modified_ns,
        ),
        policy_version=row.policy_version,
        state=DomainSourceContentState(row.state.value),
        content_digest=digest,
        digest_input_revision=row.digest_input_revision,
        last_origin=_origin_from_row(row),
        available_at=row.available_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
    )


def _same_input(row: SourceContentFact, value: ObservedContentSource) -> bool:
    expected = value.expected_stat
    return (
        row.admission == value.admission.value
        and row.source_format
        == (None if value.source_format is None else value.source_format.value)
        and row.filesystem_identity == value.filesystem_identity
        and row.device_id == expected.device_id
        and row.file_id == expected.file_id
        and row.size_bytes == expected.size_bytes
        and row.modified_ns == expected.modified_ns
        and row.policy_version == value.policy_version
    )


def _load_source_rows(
    session: Session,
    library_id: str,
    source_ids: tuple[str, ...],
) -> dict[str, LibrarySourceEntry]:
    rows: dict[str, LibrarySourceEntry] = {}
    for offset in range(0, len(source_ids), SOURCE_QUERY_CHUNK):
        rows.update(
            (row.id, row)
            for row in session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == library_id,
                    LibrarySourceEntry.id.in_(
                        source_ids[offset : offset + SOURCE_QUERY_CHUNK]
                    ),
                )
                .with_for_update()
            )
        )
    return rows


class SqlAlchemySourceContentObservationRepository:
    """Persist file observations in the caller's scan or watcher transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def observe_sources(
        self,
        fence: ContentFence,
        observations: tuple[ObservedContentSource, ...],
        *,
        observed_at: datetime,
    ) -> SourceContentObservationOutcome:
        if len(observations) > MAX_OBSERVATIONS:
            raise_content_stale(fence)
        require_content_fence(self._session, fence, now=observed_at)
        source_ids = tuple(value.source_entry_id for value in observations)
        if len(set(source_ids)) != len(source_ids):
            raise_content_stale(fence)
        for value in observations:
            _validate_origin_for_fence(fence, value.origin)
        source_rows = _load_source_rows(self._session, fence.library_id, source_ids)
        if set(source_rows) != set(source_ids):
            raise_content_stale(fence)
        generation = presence_generation(fence)
        for value in observations:
            source = source_rows[value.source_entry_id]
            expected = value.expected_stat
            if (
                source.entry_type is not SourceEntryType.FILE
                or source.slot_state is not SlotState.ACTIVE
                or source.layout_state is not LayoutState.PRESENT
                or source.absence_confirmed_at is not None
                or source.last_seen_generation != generation
                or source.filesystem_identity != value.filesystem_identity
                or source.size_bytes != expected.size_bytes
                or source.modified_ns != expected.modified_ns
            ):
                raise_content_stale(fence)
        existing: dict[str, SourceContentFact] = {}
        for offset in range(0, len(source_ids), SOURCE_QUERY_CHUNK):
            existing.update(
                (row.source_entry_id, row)
                for row in self._session.scalars(
                    select(SourceContentFact)
                    .where(
                        SourceContentFact.library_id == fence.library_id,
                        SourceContentFact.source_entry_id.in_(
                            source_ids[offset : offset + SOURCE_QUERY_CHUNK]
                        ),
                    )
                    .with_for_update()
                )
            )
        advanced_required_count = 0
        work_available = False
        readiness_source_ids: list[str] = []
        facts: list[SourceContentFact] = []
        new_rows: list[SourceContentFact] = []
        for value in observations:
            row = existing.get(value.source_entry_id)
            required = source_admission_requires_digest(value.admission)
            if row is None:
                if not required:
                    continue
                kind, origin_id, sequence = _origin_values(value.origin)
                row = SourceContentFact(
                    library_id=fence.library_id,
                    source_entry_id=value.source_entry_id,
                    input_revision=1,
                    work_revision=0,
                    digest_input_revision=None,
                    admission=value.admission.value,
                    source_format=(
                        None
                        if value.source_format is None
                        else value.source_format.value
                    ),
                    filesystem_identity=value.filesystem_identity,
                    device_id=value.expected_stat.device_id,
                    file_id=value.expected_stat.file_id,
                    size_bytes=value.expected_stat.size_bytes,
                    modified_ns=value.expected_stat.modified_ns,
                    policy_version=value.policy_version,
                    origin_kind=kind,
                    origin_id=origin_id,
                    origin_sequence=sequence,
                    available_at=observed_at,
                    state=SourceContentState.PENDING,
                    content_digest=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    created_at=observed_at,
                    updated_at=observed_at,
                )
                new_rows.append(row)
                existing[value.source_entry_id] = row
                advanced_required_count += 1
                work_available = True
                readiness_source_ids.append(value.source_entry_id)
                facts.append(row)
                continue
            repeated_origin = _origin_matches_row(row, value.origin)
            changed = not _same_input(row, value)
            previous_required = source_admission_requires_digest(
                AdmissionKind(row.admission)
            )
            impact = source_input_revision_impact(
                input_facts_changed=changed,
                explicit_modify=False,
                repeated_origin=repeated_origin,
                admission=value.admission,
            )
            if impact.input_revision_delta:
                row.input_revision += 1
                row.admission = value.admission.value
                row.source_format = (
                    None if value.source_format is None else value.source_format.value
                )
                row.filesystem_identity = value.filesystem_identity
                row.device_id = value.expected_stat.device_id
                row.file_id = value.expected_stat.file_id
                row.size_bytes = value.expected_stat.size_bytes
                row.modified_ns = value.expected_stat.modified_ns
                row.policy_version = value.policy_version
                row.state = (
                    SourceContentState.PENDING
                    if required
                    else SourceContentState.INELIGIBLE
                )
                if not required:
                    row.content_digest = None
                    row.digest_input_revision = None
                row.lease_owner = None
                row.lease_expires_at = None
                row.available_at = observed_at
                readiness_source_ids.append(value.source_entry_id)
                if impact.digest_requeue_required:
                    advanced_required_count += 1
                    work_available = True
            elif (
                required
                and row.state is SourceContentState.PENDING
                and is_after(row.available_at, observed_at)
            ):
                row.available_at = observed_at
                row.updated_at = observed_at
                work_available = True
            if not repeated_origin:
                kind, origin_id, sequence = _origin_values(value.origin)
                row.origin_kind = kind
                row.origin_id = origin_id
                row.origin_sequence = sequence
                row.updated_at = observed_at
            elif impact.input_revision_delta:
                row.updated_at = observed_at
            if (
                previous_required
                and not required
                and value.source_entry_id not in readiness_source_ids
            ):
                readiness_source_ids.append(value.source_entry_id)
            facts.append(row)
        self._session.add_all(new_rows)
        self._session.flush()
        if readiness_source_ids:
            mark_current_sources_pending(
                self._session,
                fence.library_id,
                tuple(dict.fromkeys(readiness_source_ids)),
                observed_at=observed_at,
            )
            self._session.flush()
        return SourceContentObservationOutcome(
            facts=tuple(_source_fact_from_row(row) for row in facts),
            advanced_required_count=advanced_required_count,
            work_available=work_available,
        )

    def mark_explicit_modify(
        self,
        modification: ExplicitSourceModify,
        *,
        observed_at: datetime,
    ) -> SourceContentObservationOutcome | None:
        resolved = resolve_raw_paths(
            self._session,
            modification.library_id,
            (modification.relative_path,),
        )
        source = resolved.get(modification.relative_path)
        if source is None or source.entry_type is not SourceEntryType.FILE:
            return None
        row = self._session.scalar(
            select(SourceContentFact)
            .where(
                SourceContentFact.library_id == modification.library_id,
                SourceContentFact.source_entry_id == source.id,
            )
            .with_for_update()
        )
        if row is None:
            return None
        repeated = _origin_matches_row(row, modification.origin)
        if (
            row.origin_kind is ContentOriginKind.WATCHER
            and row.origin_sequence > modification.origin.watcher_sequence
        ):
            raise ReconcileStale()
        admission = AdmissionKind(row.admission)
        impact = source_input_revision_impact(
            input_facts_changed=False,
            explicit_modify=True,
            repeated_origin=repeated,
            admission=admission,
        )
        work_available = False
        if impact.input_revision_delta:
            row.input_revision += 1
            row.origin_kind = ContentOriginKind.WATCHER
            row.origin_id = None
            row.origin_sequence = modification.origin.watcher_sequence
            row.state = (
                SourceContentState.PENDING
                if source_admission_requires_digest(admission)
                else SourceContentState.INELIGIBLE
            )
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = observed_at
            row.updated_at = observed_at
            if impact.digest_requeue_required:
                work_available = True
                mark_current_sources_pending(
                    self._session,
                    modification.library_id,
                    (source.id,),
                    observed_at=observed_at,
                )
        elif (
            source_admission_requires_digest(admission)
            and row.state is SourceContentState.PENDING
            and is_after(row.available_at, observed_at)
        ):
            row.available_at = observed_at
            row.updated_at = observed_at
            work_available = True
        self._session.flush()
        return SourceContentObservationOutcome(
            facts=(_source_fact_from_row(row),),
            advanced_required_count=int(impact.digest_requeue_required),
            work_available=work_available,
        )


def source_path_if_effective(
    session: Session,
    library: CatalogLibrary,
    source: LibrarySourceEntry,
) -> tuple[tuple[str, ...], str] | None:
    generation = library.last_successful_generation
    if generation is None:
        return None
    chain: list[LibrarySourceEntry] = []
    current = source
    visited: set[str] = set()
    for _ in range(MAX_SOURCE_PATH_DEPTH):
        if current.id in visited:
            return None
        visited.add(current.id)
        chain.append(current)
        if current.parent_entry_id is None:
            break
        parent = session.get(LibrarySourceEntry, current.parent_entry_id)
        if parent is None or parent.library_id != library.id:
            return None
        current = parent
    else:
        return None
    root = chain[-1]
    if (
        root.entry_type is not SourceEntryType.SYNTHETIC_ROOT
        or root.filesystem_identity is None
        or root.slot_state is not SlotState.ACTIVE
        or root.layout_state is not LayoutState.PRESENT
        or root.absence_confirmed_at is not None
        or root.last_seen_generation != generation
    ):
        return None
    for child, parent in pairwise(chain):
        if (
            child.slot_state is not SlotState.ACTIVE
            or child.layout_state is not LayoutState.PRESENT
            or child.absence_confirmed_at is not None
            or child.last_seen_generation != generation
            or (
                child.observed_parent_presence_epoch != parent.children_presence_epoch
                and child.pending_observed_parent_presence_epoch
                != parent.children_presence_epoch
            )
        ):
            return None
    return tuple(
        row.local_name for row in reversed(chain[:-1])
    ), root.filesystem_identity


def _source_digest_work(
    session: Session,
    library: CatalogLibrary,
    fact: SourceContentFact,
) -> SourceDigestWork | None:
    source = session.get(LibrarySourceEntry, fact.source_entry_id)
    if (
        source is None
        or source.library_id != fact.library_id
        or source.entry_type is not SourceEntryType.FILE
        or source.filesystem_identity != fact.filesystem_identity
        or source.size_bytes != fact.size_bytes
        or source.modified_ns != fact.modified_ns
    ):
        return None
    path = source_path_if_effective(session, library, source)
    if path is None or fact.lease_owner is None or fact.lease_expires_at is None:
        return None
    relative_path, root_identity = path
    fence = SourceContentWorkFence(
        library_id=fact.library_id,
        source_entry_id=fact.source_entry_id,
        input_revision=fact.input_revision,
        work_revision=fact.work_revision,
        owner_token=fact.lease_owner,
        lease_expires_at=fact.lease_expires_at,
    )
    return SourceDigestWork(
        fence=fence,
        request=SourceDigestRequest(
            library_id=fact.library_id,
            source_entry_id=fact.source_entry_id,
            input_revision=fact.input_revision,
            canonical_root=library.root_path,
            expected_root_identity=root_identity,
            relative_path=relative_path,
            expected_stat=SourceStatExpectation(
                device_id=fact.device_id,
                file_id=fact.file_id,
                size_bytes=fact.size_bytes,
                modified_ns=fact.modified_ns,
            ),
        ),
    )


def _has_current_active_membership(
    session: Session,
    *,
    library_id: str,
    source_entry_id: str,
) -> bool:
    return (
        session.scalar(
            select(TopologyAssetMembership.id)
            .join(
                TopologyUnit,
                and_(
                    TopologyUnit.library_id == TopologyAssetMembership.library_id,
                    TopologyUnit.active_revision_id
                    == TopologyAssetMembership.unit_revision_id,
                ),
            )
            .where(
                TopologyAssetMembership.library_id == library_id,
                TopologyAssetMembership.source_entry_id == source_entry_id,
                TopologyAssetMembership.required_for_reading.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def _owned_source_fact_conditions(
    fence: SourceContentWorkFence,
) -> tuple[ColumnElement[bool], ...]:
    return (
        SourceContentFact.library_id == fence.library_id,
        SourceContentFact.source_entry_id == fence.source_entry_id,
        SourceContentFact.input_revision == fence.input_revision,
        SourceContentFact.work_revision == fence.work_revision,
        SourceContentFact.state == SourceContentState.RUNNING,
        SourceContentFact.lease_owner == fence.owner_token,
        SourceContentFact.lease_expires_at == fence.lease_expires_at,
    )


def project_source_digest_ready(
    session: Session,
    fact: SourceContentFact,
    *,
    published_at: datetime,
) -> None:
    memberships = current_required_memberships_for_sources(
        session,
        fact.library_id,
        (fact.source_entry_id,),
    )
    if not memberships or fact.source_format is None or fact.content_digest is None:
        return
    mark_current_sources_pending(
        session,
        fact.library_id,
        (fact.source_entry_id,),
        observed_at=published_at,
    )
    asset_ids = tuple(dict.fromkeys(row[0] for row in memberships))
    mime_type = canonical_required_mime_type(SourceFormat(fact.source_format))
    for offset in range(0, len(asset_ids), SOURCE_QUERY_CHUNK):
        session.execute(
            update(VolumeAsset)
            .where(
                VolumeAsset.library_id == fact.library_id,
                VolumeAsset.id.in_(asset_ids[offset : offset + SOURCE_QUERY_CHUNK]),
            )
            .values(
                mime_type=mime_type,
                size_bytes=fact.size_bytes,
                content_digest=fact.content_digest,
                validation_state=AssetValidationState.READY,
                updated_at=published_at,
            )
        )


class SqlAlchemySourceContentWorkRepository:
    """Lease and publish complete source digests with input-revision CAS."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def claim_next_digest(
        self,
        library_id: str,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
        defer_until: datetime,
    ) -> SourceDigestClaimOutcome:
        if defer_until <= now:
            raise ValueError("defer_until must be later than now")
        library = self._session.scalar(
            select(CatalogLibrary)
            .where(
                CatalogLibrary.id == library_id,
                CatalogLibrary.control_state == LibraryControlState.ACTIVE,
                CatalogLibrary.last_successful_generation.is_not(None),
            )
            .with_for_update()
        )
        if library is None:
            return SourceDigestClaimOutcome(None, 0)
        candidates = tuple(
            self._session.scalars(
                select(SourceContentFact)
                .where(
                    SourceContentFact.library_id == library_id,
                    or_(
                        and_(
                            SourceContentFact.state == SourceContentState.PENDING,
                            SourceContentFact.available_at <= now,
                        ),
                        and_(
                            SourceContentFact.state == SourceContentState.RUNNING,
                            SourceContentFact.lease_expires_at.is_not(None),
                            SourceContentFact.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(
                    SourceContentFact.available_at,
                    SourceContentFact.source_entry_id,
                )
                .limit(CLAIM_CANDIDATE_LIMIT)
                .with_for_update()
            )
        )
        deferred_count = 0
        for fact in candidates:
            if not source_admission_requires_digest(AdmissionKind(fact.admission)):
                continue
            source = self._session.get(LibrarySourceEntry, fact.source_entry_id)
            if (
                source is None
                or source_path_if_effective(self._session, library, source) is None
                or not _has_current_active_membership(
                    self._session,
                    library_id=library_id,
                    source_entry_id=fact.source_entry_id,
                )
            ):
                if deferred_count >= MAX_DEFERRED_CLAIMS:
                    break
                result = self._session.execute(
                    update(SourceContentFact)
                    .where(
                        SourceContentFact.library_id == library_id,
                        SourceContentFact.source_entry_id == fact.source_entry_id,
                        SourceContentFact.input_revision == fact.input_revision,
                        SourceContentFact.work_revision == fact.work_revision,
                        SourceContentFact.state == fact.state,
                        (
                            SourceContentFact.lease_owner.is_(None)
                            if fact.lease_owner is None
                            else SourceContentFact.lease_owner == fact.lease_owner
                        ),
                        (
                            SourceContentFact.lease_expires_at.is_(None)
                            if fact.lease_expires_at is None
                            else SourceContentFact.lease_expires_at
                            == fact.lease_expires_at
                        ),
                    )
                    .values(
                        state=SourceContentState.PENDING,
                        available_at=defer_until,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                if cast(CursorResult[object], result).rowcount == 1:
                    deferred_count += 1
                continue
            previous_state = fact.state
            previous_owner = fact.lease_owner
            previous_expiry = fact.lease_expires_at
            result = self._session.execute(
                update(SourceContentFact)
                .where(
                    SourceContentFact.library_id == library_id,
                    SourceContentFact.source_entry_id == fact.source_entry_id,
                    SourceContentFact.input_revision == fact.input_revision,
                    SourceContentFact.work_revision == fact.work_revision,
                    SourceContentFact.state == previous_state,
                    (
                        SourceContentFact.lease_owner.is_(None)
                        if previous_owner is None
                        else SourceContentFact.lease_owner == previous_owner
                    ),
                    (
                        SourceContentFact.lease_expires_at.is_(None)
                        if previous_expiry is None
                        else SourceContentFact.lease_expires_at == previous_expiry
                    ),
                )
                .values(
                    work_revision=fact.work_revision + 1,
                    state=SourceContentState.RUNNING,
                    lease_owner=owner_token,
                    lease_expires_at=lease_expires_at,
                    updated_at=now,
                )
            )
            if cast(CursorResult[object], result).rowcount != 1:
                continue
            claimed = self._session.get(
                SourceContentFact,
                (library_id, fact.source_entry_id),
                populate_existing=True,
            )
            if claimed is None:
                return SourceDigestClaimOutcome(None, deferred_count)
            work = _source_digest_work(self._session, library, claimed)
            if work is None:
                return SourceDigestClaimOutcome(None, deferred_count)
            return SourceDigestClaimOutcome(work, deferred_count)
        return SourceDigestClaimOutcome(None, deferred_count)

    def heartbeat_digest(
        self,
        fence: SourceContentWorkFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> SourceContentWorkFence | None:
        result = self._session.execute(
            update(SourceContentFact)
            .where(
                *_owned_source_fact_conditions(fence),
                SourceContentFact.lease_expires_at > now,
            )
            .values(lease_expires_at=lease_expires_at, updated_at=now)
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return SourceContentWorkFence(
            library_id=fence.library_id,
            source_entry_id=fence.source_entry_id,
            input_revision=fence.input_revision,
            work_revision=fence.work_revision,
            owner_token=fence.owner_token,
            lease_expires_at=lease_expires_at,
        )

    def publish_digest(
        self,
        fence: SourceContentWorkFence,
        evidence: SourceDigestEvidence,
        *,
        published_at: datetime,
    ) -> SourceDigestPublishOutcome | None:
        if (
            evidence.source_entry_id != fence.source_entry_id
            or evidence.input_revision != fence.input_revision
        ):
            return None
        row = self._session.scalar(
            select(SourceContentFact)
            .where(
                *_owned_source_fact_conditions(fence),
                SourceContentFact.lease_expires_at > published_at,
            )
            .with_for_update()
        )
        if row is None:
            return None
        expected = evidence.observed_stat
        if (
            row.device_id != expected.device_id
            or row.file_id != expected.file_id
            or row.size_bytes != expected.size_bytes
            or row.modified_ns != expected.modified_ns
            or evidence.bytes_hashed != row.size_bytes
        ):
            return None
        digest = evidence.content_digest.value
        same_current_digest = (
            row.digest_input_revision == fence.input_revision
            and row.content_digest == digest
        )
        changed_current_digest = (
            row.digest_input_revision == fence.input_revision
            and row.content_digest is not None
            and row.content_digest != digest
        )
        target_revision = fence.input_revision + int(changed_current_digest)
        disposition = (
            SourceDigestPublishDisposition.READY_UNCHANGED
            if same_current_digest
            else (
                SourceDigestPublishDisposition.INPUT_REVISION_ADVANCED
                if changed_current_digest
                else SourceDigestPublishDisposition.READY_CHANGED
            )
        )
        result = self._session.execute(
            update(SourceContentFact)
            .where(*_owned_source_fact_conditions(fence))
            .values(
                input_revision=target_revision,
                state=SourceContentState.READY,
                content_digest=digest,
                digest_input_revision=target_revision,
                available_at=published_at,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=published_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        self._session.flush()
        current = self._session.get(
            SourceContentFact,
            (fence.library_id, fence.source_entry_id),
            populate_existing=True,
        )
        if current is None:
            return None
        return SourceDigestPublishOutcome(
            disposition=disposition,
            claimed_input_revision=fence.input_revision,
            current=_source_fact_from_row(current),
        )

    def release_digest_for_retry(
        self,
        fence: SourceContentWorkFence,
        *,
        diagnostic_code: str,
        retry_at: datetime,
        released_at: datetime,
    ) -> SourceContentFactDto | None:
        if not diagnostic_code.strip():
            raise ValueError("diagnostic_code must be non-empty")
        result = self._session.execute(
            update(SourceContentFact)
            .where(
                *_owned_source_fact_conditions(fence),
                SourceContentFact.lease_expires_at > released_at,
            )
            .values(
                state=SourceContentState.PENDING,
                available_at=retry_at,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=released_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        self._session.flush()
        current = self._session.get(
            SourceContentFact,
            (fence.library_id, fence.source_entry_id),
            populate_existing=True,
        )
        return None if current is None else _source_fact_from_row(current)


__all__ = [
    "SqlAlchemySourceContentObservationRepository",
    "SqlAlchemySourceContentWorkRepository",
]
