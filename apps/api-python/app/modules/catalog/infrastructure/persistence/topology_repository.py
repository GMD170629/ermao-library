"""SQLAlchemy persistence for opaque-identity topology projections."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn, cast

from sqlalchemy import and_, exists, func, select, union_all, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.scan_dto import (
    ScanFence,
    SourcePathBinding,
    StagingRevision,
)
from app.modules.catalog.application.watcher_dto import (
    BoundProjectionKind,
    BoundTopologyProjection,
    BoundTopologyStageBatch,
    BoundTopologyUnitPlan,
    ReconcileFence,
    required_topology_source_paths,
)
from app.modules.catalog.domain.scan import (
    AssetMembershipPlan,
    ScanStale,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
)
from app.modules.catalog.domain.scan import (
    TopologyUnitKind as DomainTopologyUnitKind,
)
from app.modules.catalog.domain.watcher import ReconcileStale

from .enums import (
    AssetRole,
    AssetValidationState,
    LayoutState,
    RevisionState,
    ScanState,
    SlotState,
    SourceEntryType,
    TopologyUnitKind,
    VersionKind,
)
from .models import (
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryVolume,
    LibraryWork,
    TopologyAssetMembership,
    TopologyUnit,
    TopologyUnitRevision,
    TopologyVersionProjection,
    TopologyVolumeProjection,
    TopologyWorkProjection,
    VolumeAsset,
    WorkVersion,
)
from .reconcile_fencing import require_live_reconcile
from .scan_fencing import comparison_components, require_live_fence, stable_id

TopologyFence = ScanFence | ReconcileFence
ProjectionPlan = (
    WorkProjectionPlan
    | VersionProjectionPlan
    | VolumeProjectionPlan
    | AssetMembershipPlan
)
_QUERY_CHUNK = 400


def disc_number_to_storage(value: int) -> int | None:
    if value < 0:
        raise ValueError("disc number cannot be negative")
    return None if value == 0 else value


def disc_number_from_storage(value: int | None) -> int:
    if value is not None and value <= 0:
        raise ValueError("stored disc number must be positive")
    return 0 if value is None else value


def _raise_stale(fence: TopologyFence) -> NoReturn:
    if isinstance(fence, ScanFence):
        raise ScanStale()
    raise ReconcileStale()


def _require_fence(session: Session, fence: TopologyFence, *, now: datetime) -> None:
    if isinstance(fence, ScanFence):
        require_live_fence(session, fence, now=now)
    else:
        require_live_reconcile(session, fence, now=now)


def _presence_generation(fence: TopologyFence) -> int:
    if isinstance(fence, ScanFence):
        return fence.generation
    return fence.presence_generation


def _origin_id(fence: TopologyFence) -> str:
    return fence.scan_id if isinstance(fence, ScanFence) else fence.intent_id


def _origin_conditions(fence: TopologyFence) -> tuple[ColumnElement[bool], ...]:
    if isinstance(fence, ScanFence):
        return (
            TopologyUnitRevision.scan_run_id == fence.scan_id,
            TopologyUnitRevision.reconcile_origin_id.is_(None),
        )
    return (
        TopologyUnitRevision.scan_run_id.is_(None),
        TopologyUnitRevision.reconcile_origin_id == fence.intent_id,
    )


def _origin_values(fence: TopologyFence) -> tuple[str | None, str | None]:
    if isinstance(fence, ScanFence):
        return fence.scan_id, None
    return None, fence.intent_id


def _work_stable_id(library_id: str, root_source_entry_id: str) -> str:
    return stable_id("work", library_id, root_source_entry_id)


def _version_stable_id(
    library_id: str,
    work_stable_id: str,
    root_source_entry_id: str | None,
) -> str:
    if root_source_entry_id is None:
        return stable_id("version", library_id, work_stable_id, "implicit")
    return stable_id("version", library_id, root_source_entry_id)


def _volume_stable_id(library_id: str, root_source_entry_id: str) -> str:
    return stable_id("volume", library_id, root_source_entry_id)


def _asset_stable_id(library_id: str, source_entry_id: str, role: str) -> str:
    return stable_id("asset", library_id, source_entry_id, role)


def _unit_stable_id(
    library_id: str, unit_kind: DomainTopologyUnitKind, owner_stable_id: str
) -> str:
    return stable_id("unit", library_id, unit_kind.value, owner_stable_id)


def _revision_row_count(session: Session, revision_id: str) -> int:
    projection_rows = union_all(
        select(TopologyWorkProjection.id).where(
            TopologyWorkProjection.unit_revision_id == revision_id
        ),
        select(TopologyVersionProjection.id).where(
            TopologyVersionProjection.unit_revision_id == revision_id
        ),
        select(TopologyVolumeProjection.id).where(
            TopologyVolumeProjection.unit_revision_id == revision_id
        ),
        select(TopologyAssetMembership.id).where(
            TopologyAssetMembership.unit_revision_id == revision_id
        ),
    )
    return (
        session.scalar(select(func.count()).select_from(projection_rows.subquery()))
        or 0
    )


def _source_ids_are_valid(
    session: Session,
    fence: TopologyFence,
    source_ids: set[str],
    *,
    pending_proofs: dict[str, int] | None = None,
    allow_reconcile_pending: bool = False,
) -> bool:
    loaded: dict[str, LibrarySourceEntry] = {}
    frontier = set(source_ids)
    generation = _presence_generation(fence)
    while frontier:
        ordered = tuple(sorted(frontier))
        rows: dict[str, LibrarySourceEntry] = {}
        for offset in range(0, len(ordered), _QUERY_CHUNK):
            rows.update(
                (row.id, row)
                for row in session.scalars(
                    select(LibrarySourceEntry).where(
                        LibrarySourceEntry.library_id == fence.library_id,
                        LibrarySourceEntry.id.in_(
                            ordered[offset : offset + _QUERY_CHUNK]
                        ),
                    )
                )
            )
        if set(rows) != frontier:
            return False
        if any(
            row.last_seen_generation != generation
            or row.absence_confirmed_at is not None
            or row.layout_state is not LayoutState.PRESENT
            or row.slot_state is not SlotState.ACTIVE
            for row in rows.values()
        ):
            return False
        loaded.update(rows)
        frontier = {
            row.parent_entry_id
            for row in rows.values()
            if row.parent_entry_id is not None and row.parent_entry_id not in loaded
        }
    for row in loaded.values():
        if row.parent_entry_id is None:
            if row.entry_type is not SourceEntryType.SYNTHETIC_ROOT:
                return False
            continue
        parent = loaded.get(row.parent_entry_id)
        if parent is None or parent.entry_type not in {
            SourceEntryType.SYNTHETIC_ROOT,
            SourceEntryType.DIRECTORY,
        }:
            return False
        if row.observed_parent_presence_epoch == parent.children_presence_epoch:
            continue
        if row.pending_observed_parent_presence_epoch == parent.children_presence_epoch:
            continue
        pending_epoch = row.pending_observed_parent_presence_epoch
        if (
            not isinstance(fence, ReconcileFence)
            or pending_epoch is None
            or pending_epoch != parent.next_children_presence_epoch
        ):
            return False
        if allow_reconcile_pending:
            continue
        if pending_proofs is None or pending_proofs.get(row.id) != pending_epoch:
            return False
    return True


def _revision_sources_valid(
    session: Session, fence: TopologyFence, revision: TopologyUnitRevision
) -> bool:
    source_ids = {revision.unit_root_entry_id}
    source_ids.update(
        session.scalars(
            select(TopologyWorkProjection.root_entry_id).where(
                TopologyWorkProjection.library_id == fence.library_id,
                TopologyWorkProjection.unit_revision_id == revision.id,
            )
        )
    )
    source_ids.update(
        value
        for value in session.scalars(
            select(TopologyVersionProjection.root_entry_id).where(
                TopologyVersionProjection.library_id == fence.library_id,
                TopologyVersionProjection.unit_revision_id == revision.id,
                TopologyVersionProjection.root_entry_id.is_not(None),
            )
        )
        if value is not None
    )
    source_ids.update(
        session.scalars(
            select(TopologyVolumeProjection.root_entry_id).where(
                TopologyVolumeProjection.library_id == fence.library_id,
                TopologyVolumeProjection.unit_revision_id == revision.id,
            )
        )
    )
    source_ids.update(
        session.scalars(
            select(TopologyAssetMembership.source_entry_id).where(
                TopologyAssetMembership.library_id == fence.library_id,
                TopologyAssetMembership.unit_revision_id == revision.id,
            )
        )
    )
    return _source_ids_are_valid(
        session,
        fence,
        source_ids,
        allow_reconcile_pending=isinstance(fence, ReconcileFence),
    )


def _work_binding(
    fence: TopologyFence,
    row_index: int,
    row: WorkProjectionPlan,
    sources: dict[tuple[str, ...], SourcePathBinding],
) -> BoundTopologyProjection:
    source_id = sources[row.root_path].source_entry_id
    structure_key = stable_id(
        "structure",
        fence.library_id,
        str(fence.topology_version),
        "work",
        comparison_components((row.root_path[-1],), fence.path_comparison)[0],
    )
    return BoundTopologyProjection(
        row_index,
        BoundProjectionKind.WORK,
        _work_stable_id(fence.library_id, source_id),
        None,
        None,
        source_id,
        None,
        structure_key,
    )


def _version_binding(
    fence: TopologyFence,
    row_index: int,
    row: VersionProjectionPlan,
    sources: dict[tuple[str, ...], SourcePathBinding],
) -> BoundTopologyProjection:
    work_id = _work_stable_id(fence.library_id, sources[row.work_path].source_entry_id)
    root_id = None if row.root_path is None else sources[row.root_path].source_entry_id
    local_key = (
        "$implicit"
        if row.root_path is None
        else comparison_components((row.root_path[-1],), fence.path_comparison)[0]
    )
    structure_key = stable_id(
        "structure",
        fence.library_id,
        str(fence.topology_version),
        "version",
        work_id,
        row.kind.value,
        local_key,
    )
    return BoundTopologyProjection(
        row_index,
        BoundProjectionKind.VERSION,
        _version_stable_id(fence.library_id, work_id, root_id),
        work_id,
        BoundProjectionKind.WORK,
        root_id,
        None,
        structure_key,
    )


def _volume_binding(
    fence: TopologyFence,
    row_index: int,
    row: VolumeProjectionPlan,
    sources: dict[tuple[str, ...], SourcePathBinding],
) -> BoundTopologyProjection:
    work_id = _work_stable_id(fence.library_id, sources[row.work_path].source_entry_id)
    version_root_id = (
        None if row.version_path is None else sources[row.version_path].source_entry_id
    )
    version_id = _version_stable_id(fence.library_id, work_id, version_root_id)
    root_id = sources[row.root_path].source_entry_id
    structure_key = stable_id(
        "structure",
        fence.library_id,
        str(fence.topology_version),
        "volume",
        version_id,
        row.source_kind.value,
        comparison_components((row.root_path[-1],), fence.path_comparison)[0],
    )
    return BoundTopologyProjection(
        row_index,
        BoundProjectionKind.VOLUME,
        _volume_stable_id(fence.library_id, root_id),
        version_id,
        BoundProjectionKind.VERSION,
        root_id,
        None,
        structure_key,
    )


def _asset_binding(
    fence: TopologyFence,
    row_index: int,
    row: AssetMembershipPlan,
    sources: dict[tuple[str, ...], SourcePathBinding],
) -> BoundTopologyProjection:
    volume_source_id = sources[row.volume_path].source_entry_id
    source_id = sources[row.source_path].source_entry_id
    return BoundTopologyProjection(
        row_index,
        BoundProjectionKind.ASSET,
        _asset_stable_id(fence.library_id, source_id, row.role.value),
        _volume_stable_id(fence.library_id, volume_source_id),
        BoundProjectionKind.VOLUME,
        None,
        source_id,
        None,
    )


def _projection_binding(
    fence: TopologyFence,
    row_index: int,
    row: ProjectionPlan,
    sources: dict[tuple[str, ...], SourcePathBinding],
) -> BoundTopologyProjection:
    if isinstance(row, WorkProjectionPlan):
        return _work_binding(fence, row_index, row, sources)
    if isinstance(row, VersionProjectionPlan):
        return _version_binding(fence, row_index, row, sources)
    if isinstance(row, VolumeProjectionPlan):
        return _volume_binding(fence, row_index, row, sources)
    return _asset_binding(fence, row_index, row, sources)


def _owner_kind(unit_kind: DomainTopologyUnitKind) -> BoundProjectionKind:
    if unit_kind in {
        DomainTopologyUnitKind.WORK_CONTAINER,
        DomainTopologyUnitKind.AUDIOBOOK_WORK,
    }:
        return BoundProjectionKind.WORK
    if unit_kind is DomainTopologyUnitKind.VERSION_CONTAINER:
        return BoundProjectionKind.VERSION
    return BoundProjectionKind.VOLUME


def _expected_signature(
    bound: BoundTopologyUnitPlan,
) -> tuple[tuple[object, ...], ...]:
    signature: list[tuple[object, ...]] = []
    for row, projection in zip(bound.plan.rows, bound.projections, strict=True):
        if isinstance(row, WorkProjectionPlan):
            signature.append(
                (
                    "work",
                    projection.stable_id,
                    projection.root_source_entry_id,
                    projection.structure_key,
                    row.source_name,
                    row.sort_key,
                )
            )
        elif isinstance(row, VersionProjectionPlan):
            signature.append(
                (
                    "version",
                    projection.stable_id,
                    projection.parent_stable_id,
                    projection.root_source_entry_id,
                    row.kind.value,
                    projection.structure_key,
                    row.source_name,
                    row.sort_key,
                )
            )
        elif isinstance(row, VolumeProjectionPlan):
            signature.append(
                (
                    "volume",
                    projection.stable_id,
                    projection.parent_stable_id,
                    projection.root_source_entry_id,
                    row.source_kind.value,
                    row.reading_morphology.value,
                    projection.structure_key,
                    row.source_name,
                    row.sort_key,
                )
            )
        else:
            signature.append(
                (
                    "asset",
                    projection.parent_stable_id,
                    projection.source_entry_id,
                    row.role.value,
                    row.source_format.value,
                    disc_number_to_storage(row.disc_number),
                    row.asset_order,
                    row.required_for_reading,
                )
            )
    return tuple(sorted(signature, key=repr))


def _stored_signature(
    session: Session, revision_id: str
) -> tuple[tuple[object, ...], ...]:
    signature: list[tuple[object, ...]] = []
    for work_projection in session.scalars(
        select(TopologyWorkProjection).where(
            TopologyWorkProjection.unit_revision_id == revision_id
        )
    ):
        signature.append(
            (
                "work",
                work_projection.work_id,
                work_projection.root_entry_id,
                work_projection.structure_key,
                work_projection.source_name,
                work_projection.sort_key,
            )
        )
    for version_projection in session.scalars(
        select(TopologyVersionProjection).where(
            TopologyVersionProjection.unit_revision_id == revision_id
        )
    ):
        signature.append(
            (
                "version",
                version_projection.version_id,
                version_projection.work_id,
                version_projection.root_entry_id,
                version_projection.kind.value,
                version_projection.structure_key,
                version_projection.source_name,
                version_projection.sort_key,
            )
        )
    for volume_projection in session.scalars(
        select(TopologyVolumeProjection).where(
            TopologyVolumeProjection.unit_revision_id == revision_id
        )
    ):
        signature.append(
            (
                "volume",
                volume_projection.volume_id,
                volume_projection.version_id,
                volume_projection.root_entry_id,
                volume_projection.source_kind.value,
                volume_projection.reading_morphology,
                volume_projection.structure_key,
                volume_projection.source_name,
                volume_projection.sort_key,
            )
        )
    for asset_membership in session.scalars(
        select(TopologyAssetMembership).where(
            TopologyAssetMembership.unit_revision_id == revision_id
        )
    ):
        signature.append(
            (
                "asset",
                asset_membership.volume_id,
                asset_membership.source_entry_id,
                asset_membership.role.value,
                asset_membership.source_format,
                asset_membership.disc_number,
                asset_membership.asset_order,
                asset_membership.required_for_reading,
            )
        )
    return tuple(sorted(signature, key=repr))


def _existing_ids(
    session: Session,
    id_column: InstrumentedAttribute[str],
    library_column: InstrumentedAttribute[str],
    library_id: str,
    identifiers: set[str],
) -> set[str]:
    found: set[str] = set()
    ordered = tuple(sorted(identifiers))
    for offset in range(0, len(ordered), _QUERY_CHUNK):
        found.update(
            session.scalars(
                select(id_column).where(
                    library_column == library_id,
                    id_column.in_(ordered[offset : offset + _QUERY_CHUNK]),
                )
            )
        )
    return found


def _ensure_unit_owner(
    session: Session,
    fence: TopologyFence,
    bound: BoundTopologyUnitPlan,
    *,
    created_at: datetime,
) -> TopologyUnit:
    owner = next(
        (
            value
            for value in bound.projections
            if value.stable_id == bound.owner_stable_id
        ),
        None,
    )
    if owner is None:
        _raise_stale(fence)
    owner_ids: tuple[str | None, str | None, str | None]
    if owner.kind is BoundProjectionKind.WORK:
        if session.get(LibraryWork, owner.stable_id) is None:
            session.add(LibraryWork(id=owner.stable_id, library_id=fence.library_id))
        owner_ids = (owner.stable_id, None, None)
    elif owner.kind is BoundProjectionKind.VERSION:
        if session.get(WorkVersion, owner.stable_id) is None:
            session.add(WorkVersion(id=owner.stable_id, library_id=fence.library_id))
        owner_ids = (None, owner.stable_id, None)
    else:
        volume_plan = next(
            (
                row
                for row, projection in zip(
                    bound.plan.rows, bound.projections, strict=True
                )
                if projection.stable_id == owner.stable_id
                and isinstance(row, VolumeProjectionPlan)
            ),
            None,
        )
        if volume_plan is None:
            _raise_stale(fence)
        if session.get(LibraryVolume, owner.stable_id) is None:
            session.add(
                LibraryVolume(
                    id=owner.stable_id,
                    library_id=fence.library_id,
                    reading_morphology=volume_plan.reading_morphology.value,
                    content_state="PENDING",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        owner_ids = (None, None, owner.stable_id)
    session.flush()
    unit = session.get(TopologyUnit, bound.unit_id)
    expected_kind = TopologyUnitKind(bound.plan.unit_kind.value)
    if unit is None:
        unit = TopologyUnit(
            id=bound.unit_id,
            library_id=fence.library_id,
            unit_kind=expected_kind,
            work_owner_id=owner_ids[0],
            version_owner_id=owner_ids[1],
            volume_owner_id=owner_ids[2],
            active_revision_id=None,
            created_at=created_at,
        )
        session.add(unit)
        session.flush()
    elif (
        unit.library_id != fence.library_id
        or unit.unit_kind is not expected_kind
        or unit.work_owner_id != owner_ids[0]
        or unit.version_owner_id != owner_ids[1]
        or unit.volume_owner_id != owner_ids[2]
    ):
        _raise_stale(fence)
    return unit


def _prepare_dependencies(
    session: Session,
    fence: TopologyFence,
    batch: BoundTopologyStageBatch,
    *,
    staged_at: datetime,
) -> dict[str, LibrarySourceEntry]:
    work_ids: set[str] = set()
    version_ids: set[str] = set()
    volume_ids: set[str] = set()
    morphologies: dict[str, str] = {}
    asset_specs: dict[str, tuple[str, str]] = {}
    source_ids: set[str] = set()
    for row, binding in zip(batch.rows, batch.bindings, strict=True):
        if isinstance(row, WorkProjectionPlan):
            work_ids.add(binding.stable_id)
            if binding.root_source_entry_id is not None:
                source_ids.add(binding.root_source_entry_id)
        elif isinstance(row, VersionProjectionPlan):
            version_ids.add(binding.stable_id)
            if binding.parent_stable_id is None:
                _raise_stale(fence)
            work_ids.add(binding.parent_stable_id)
            if binding.root_source_entry_id is not None:
                source_ids.add(binding.root_source_entry_id)
        elif isinstance(row, VolumeProjectionPlan):
            volume_ids.add(binding.stable_id)
            if binding.parent_stable_id is None or binding.root_source_entry_id is None:
                _raise_stale(fence)
            version_ids.add(binding.parent_stable_id)
            source_ids.add(binding.root_source_entry_id)
            previous = morphologies.setdefault(
                binding.stable_id, row.reading_morphology.value
            )
            if previous != row.reading_morphology.value:
                _raise_stale(fence)
        else:
            if binding.parent_stable_id is None or binding.source_entry_id is None:
                _raise_stale(fence)
            volume_ids.add(binding.parent_stable_id)
            source_ids.add(binding.source_entry_id)
            previous_asset = asset_specs.setdefault(
                binding.stable_id,
                (binding.source_entry_id, row.source_format.value),
            )
            if previous_asset != (binding.source_entry_id, row.source_format.value):
                _raise_stale(fence)
    sources: dict[str, LibrarySourceEntry] = {}
    ordered_sources = tuple(sorted(source_ids))
    for offset in range(0, len(ordered_sources), _QUERY_CHUNK):
        sources.update(
            (row.id, row)
            for row in session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.id.in_(
                        ordered_sources[offset : offset + _QUERY_CHUNK]
                    ),
                )
            )
        )
    existing_works = _existing_ids(
        session, LibraryWork.id, LibraryWork.library_id, fence.library_id, work_ids
    )
    existing_versions = _existing_ids(
        session,
        WorkVersion.id,
        WorkVersion.library_id,
        fence.library_id,
        version_ids,
    )
    existing_volumes = _existing_ids(
        session,
        LibraryVolume.id,
        LibraryVolume.library_id,
        fence.library_id,
        volume_ids,
    )
    missing_volumes = volume_ids - existing_volumes
    if not missing_volumes.issubset(morphologies):
        _raise_stale(fence)
    existing_assets = _existing_ids(
        session,
        VolumeAsset.id,
        VolumeAsset.library_id,
        fence.library_id,
        set(asset_specs),
    )
    session.add_all(
        LibraryWork(id=value, library_id=fence.library_id)
        for value in work_ids - existing_works
    )
    session.add_all(
        WorkVersion(id=value, library_id=fence.library_id)
        for value in version_ids - existing_versions
    )
    session.add_all(
        LibraryVolume(
            id=value,
            library_id=fence.library_id,
            reading_morphology=morphologies[value],
            content_state="PENDING",
            created_at=staged_at,
            updated_at=staged_at,
        )
        for value in missing_volumes
    )
    session.add_all(
        VolumeAsset(
            id=value,
            library_id=fence.library_id,
            source_format=asset_specs[value][1],
            size_bytes=sources[asset_specs[value][0]].size_bytes,
            validation_state=AssetValidationState.PENDING,
            created_at=staged_at,
            updated_at=staged_at,
        )
        for value in set(asset_specs) - existing_assets
    )
    session.flush()
    return sources


def _apply_activated_facts(
    session: Session,
    library_id: str,
    revision_ids: tuple[str, ...],
    *,
    activated_at: datetime,
) -> None:
    volume_exists = exists(
        select(TopologyVolumeProjection.id).where(
            TopologyVolumeProjection.library_id == LibraryVolume.library_id,
            TopologyVolumeProjection.volume_id == LibraryVolume.id,
            TopologyVolumeProjection.unit_revision_id.in_(revision_ids),
        )
    )
    morphology = (
        select(TopologyVolumeProjection.reading_morphology)
        .where(
            TopologyVolumeProjection.library_id == LibraryVolume.library_id,
            TopologyVolumeProjection.volume_id == LibraryVolume.id,
            TopologyVolumeProjection.unit_revision_id.in_(revision_ids),
        )
        .limit(1)
        .correlate(LibraryVolume)
        .scalar_subquery()
    )
    session.execute(
        update(LibraryVolume)
        .where(LibraryVolume.library_id == library_id, volume_exists)
        .values(
            reading_morphology=morphology,
            content_state="PENDING",
            updated_at=activated_at,
        )
    )
    membership_exists = exists(
        select(TopologyAssetMembership.id).where(
            TopologyAssetMembership.library_id == VolumeAsset.library_id,
            TopologyAssetMembership.asset_id == VolumeAsset.id,
            TopologyAssetMembership.unit_revision_id.in_(revision_ids),
        )
    )
    source_format = (
        select(TopologyAssetMembership.source_format)
        .where(
            TopologyAssetMembership.library_id == VolumeAsset.library_id,
            TopologyAssetMembership.asset_id == VolumeAsset.id,
            TopologyAssetMembership.unit_revision_id.in_(revision_ids),
        )
        .limit(1)
        .correlate(VolumeAsset)
        .scalar_subquery()
    )
    source_size = (
        select(LibrarySourceEntry.size_bytes)
        .join(
            TopologyAssetMembership,
            and_(
                TopologyAssetMembership.library_id == LibrarySourceEntry.library_id,
                TopologyAssetMembership.source_entry_id == LibrarySourceEntry.id,
            ),
        )
        .where(
            TopologyAssetMembership.library_id == VolumeAsset.library_id,
            TopologyAssetMembership.asset_id == VolumeAsset.id,
            TopologyAssetMembership.unit_revision_id.in_(revision_ids),
        )
        .limit(1)
        .correlate(VolumeAsset)
        .scalar_subquery()
    )
    session.execute(
        update(VolumeAsset)
        .where(VolumeAsset.library_id == library_id, membership_exists)
        .values(
            source_format=source_format,
            size_bytes=source_size,
            validation_state=AssetValidationState.PENDING,
            updated_at=activated_at,
        )
    )


class SqlAlchemyTopologyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def abandon_scan_staging(self, fence: ScanFence, *, abandoned_at: datetime) -> None:
        require_live_fence(self._session, fence, now=abandoned_at)
        self._session.execute(
            update(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.scan_run_id == fence.scan_id,
                TopologyUnitRevision.reconcile_origin_id.is_(None),
                TopologyUnitRevision.state == RevisionState.STAGING,
            )
            .values(state=RevisionState.ABANDONED)
        )
        self._session.flush()

    def abandon_cancelled_scan_staging(
        self,
        library_id: str,
        scan_id: str,
        *,
        abandoned_at: datetime,
    ) -> bool:
        del abandoned_at
        cancelled = exists(
            select(LibraryScanRun.id).where(
                LibraryScanRun.id == scan_id,
                LibraryScanRun.library_id == library_id,
                LibraryScanRun.state == ScanState.CANCELLED,
            )
        )
        self._session.execute(
            update(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.library_id == library_id,
                TopologyUnitRevision.scan_run_id == scan_id,
                TopologyUnitRevision.reconcile_origin_id.is_(None),
                TopologyUnitRevision.state == RevisionState.STAGING,
                cancelled,
            )
            .values(state=RevisionState.ABANDONED)
        )
        self._session.flush()
        return bool(self._session.scalar(select(cancelled)))

    def bind_plan(
        self,
        fence: TopologyFence,
        plan: TopologyUnitPlan,
        source_bindings: tuple[SourcePathBinding, ...],
        *,
        bound_at: datetime | None = None,
    ) -> BoundTopologyUnitPlan | None:
        if bound_at is not None:
            _require_fence(self._session, fence, now=bound_at)
        if tuple(value.relative_path for value in source_bindings) != (
            required_topology_source_paths(plan)
        ) or len({value.source_entry_id for value in source_bindings}) != len(
            source_bindings
        ):
            return None
        sources = {value.relative_path: value for value in source_bindings}
        try:
            projections = tuple(
                _projection_binding(fence, index, row, sources)
                for index, row in enumerate(plan.rows)
            )
            owner_source_id = sources[plan.owner_path].source_entry_id
            owner = next(
                value
                for value in projections
                if value.kind is _owner_kind(plan.unit_kind)
                and value.root_source_entry_id == owner_source_id
            )
        except (KeyError, StopIteration):
            return None
        if not _source_ids_are_valid(
            self._session,
            fence,
            {value.source_entry_id for value in source_bindings},
            pending_proofs={
                value.source_entry_id: value.pending_parent_presence_epoch
                for value in source_bindings
                if value.pending_parent_presence_epoch is not None
            },
        ):
            return None
        return BoundTopologyUnitPlan(
            plan=plan,
            unit_id=_unit_stable_id(fence.library_id, plan.unit_kind, owner.stable_id),
            owner_stable_id=owner.stable_id,
            source_bindings=source_bindings,
            projections=projections,
        )

    def abandon_incomplete(
        self,
        fence: TopologyFence,
        *,
        unit_id: str,
        abandoned_at: datetime,
    ) -> None:
        _require_fence(self._session, fence, now=abandoned_at)
        self._session.execute(
            update(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.unit_id == unit_id,
                TopologyUnitRevision.state == RevisionState.STAGING,
                *_origin_conditions(fence),
            )
            .values(state=RevisionState.ABANDONED)
        )
        self._session.flush()

    def get_active_revision_id(self, library_id: str, *, unit_id: str) -> str | None:
        return self._session.scalar(
            select(TopologyUnit.active_revision_id).where(
                TopologyUnit.library_id == library_id,
                TopologyUnit.id == unit_id,
            )
        )

    def begin_staging(
        self,
        fence: TopologyFence,
        plan: BoundTopologyUnitPlan,
        *,
        expected_active_revision_id: str | None,
        created_at: datetime,
    ) -> StagingRevision | None:
        _require_fence(self._session, fence, now=created_at)
        if not _source_ids_are_valid(
            self._session,
            fence,
            {value.source_entry_id for value in plan.source_bindings},
            pending_proofs={
                value.source_entry_id: value.pending_parent_presence_epoch
                for value in plan.source_bindings
                if value.pending_parent_presence_epoch is not None
            },
        ):
            _raise_stale(fence)
        unit = _ensure_unit_owner(self._session, fence, plan, created_at=created_at)
        if unit.active_revision_id != expected_active_revision_id:
            _raise_stale(fence)
        if expected_active_revision_id is not None and _stored_signature(
            self._session, expected_active_revision_id
        ) == _expected_signature(plan):
            return None
        latest = self._session.scalar(
            select(func.max(TopologyUnitRevision.revision)).where(
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.unit_id == unit.id,
            )
        )
        revision_number = (latest or 0) + 1
        revision_id = stable_id(
            "revision",
            fence.library_id,
            unit.id,
            _origin_id(fence),
            str(revision_number),
        )
        scan_origin, reconcile_origin = _origin_values(fence)
        root = {value.relative_path: value for value in plan.source_bindings}.get(
            plan.plan.unit_root_path
        )
        if root is None:
            _raise_stale(fence)
        self._session.add(
            TopologyUnitRevision(
                id=revision_id,
                library_id=fence.library_id,
                unit_id=unit.id,
                scan_run_id=scan_origin,
                reconcile_origin_id=reconcile_origin,
                unit_root_entry_id=root.source_entry_id,
                revision=revision_number,
                state=RevisionState.STAGING,
                created_at=created_at,
            )
        )
        self._session.flush()
        return StagingRevision(
            revision_id,
            unit.id,
            expected_active_revision_id,
            len(plan.plan.rows),
            0,
        )

    def append_staging_batch(
        self,
        fence: TopologyFence,
        staging: StagingRevision,
        batch: BoundTopologyStageBatch,
        *,
        staged_at: datetime,
    ) -> StagingRevision:
        _require_fence(self._session, fence, now=staged_at)
        revision = self._session.scalar(
            select(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.id == staging.revision_id,
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.unit_id == staging.unit_id,
                TopologyUnitRevision.state == RevisionState.STAGING,
                *_origin_conditions(fence),
            )
            .with_for_update()
        )
        count = _revision_row_count(self._session, staging.revision_id)
        if (
            revision is None
            or count != staging.staged_row_count
            or batch.first_row != staging.staged_row_count
            or count + len(batch.rows) > staging.expected_row_count
            or batch.complete != (count + len(batch.rows) == staging.expected_row_count)
        ):
            _raise_stale(fence)
        sources = _prepare_dependencies(
            self._session, fence, batch, staged_at=staged_at
        )
        for row, binding in zip(batch.rows, batch.bindings, strict=True):
            self._append_projection(fence, revision, row, binding, sources)
        self._session.flush()
        staged_count = _revision_row_count(self._session, staging.revision_id)
        if staged_count != count + len(batch.rows):
            _raise_stale(fence)
        return StagingRevision(
            staging.revision_id,
            staging.unit_id,
            staging.expected_active_revision_id,
            staging.expected_row_count,
            staged_count,
        )

    def _append_projection(
        self,
        fence: TopologyFence,
        revision: TopologyUnitRevision,
        row: ProjectionPlan,
        binding: BoundTopologyProjection,
        sources: dict[str, LibrarySourceEntry],
    ) -> None:
        row_index = str(binding.row_index)
        if isinstance(row, WorkProjectionPlan):
            if binding.root_source_entry_id not in sources:
                _raise_stale(fence)
            self._session.add(
                TopologyWorkProjection(
                    id=stable_id("work_projection", revision.id, row_index),
                    library_id=fence.library_id,
                    unit_revision_id=revision.id,
                    work_id=binding.stable_id,
                    root_entry_id=binding.root_source_entry_id,
                    structure_key=cast(str, binding.structure_key),
                    source_name=row.source_name,
                    sort_key=row.sort_key,
                )
            )
            return
        if isinstance(row, VersionProjectionPlan):
            if binding.parent_stable_id is None:
                _raise_stale(fence)
            self._session.add(
                TopologyVersionProjection(
                    id=stable_id("version_projection", revision.id, row_index),
                    library_id=fence.library_id,
                    unit_revision_id=revision.id,
                    version_id=binding.stable_id,
                    work_id=binding.parent_stable_id,
                    root_entry_id=binding.root_source_entry_id,
                    kind=VersionKind(row.kind.value),
                    structure_key=cast(str, binding.structure_key),
                    source_name=row.source_name,
                    sort_key=row.sort_key,
                )
            )
            return
        if isinstance(row, VolumeProjectionPlan):
            if (
                binding.parent_stable_id is None
                or binding.root_source_entry_id not in sources
            ):
                _raise_stale(fence)
            self._session.add(
                TopologyVolumeProjection(
                    id=stable_id("volume_projection", revision.id, row_index),
                    library_id=fence.library_id,
                    unit_revision_id=revision.id,
                    volume_id=binding.stable_id,
                    version_id=binding.parent_stable_id,
                    root_entry_id=binding.root_source_entry_id,
                    source_kind=row.source_kind,
                    reading_morphology=row.reading_morphology.value,
                    structure_key=cast(str, binding.structure_key),
                    source_name=row.source_name,
                    sort_key=row.sort_key,
                )
            )
            return
        if binding.parent_stable_id is None or binding.source_entry_id not in sources:
            _raise_stale(fence)
        self._session.add(
            TopologyAssetMembership(
                id=stable_id("asset_membership", revision.id, row_index),
                library_id=fence.library_id,
                unit_revision_id=revision.id,
                asset_id=binding.stable_id,
                volume_id=binding.parent_stable_id,
                source_entry_id=binding.source_entry_id,
                role=AssetRole(row.role.value),
                source_format=row.source_format.value,
                disc_number=disc_number_to_storage(row.disc_number),
                asset_order=row.asset_order,
                required_for_reading=row.required_for_reading,
            )
        )

    def activate_staging_group(
        self,
        fence: TopologyFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> bool:
        _require_fence(self._session, fence, now=activated_at)
        if not staging or len({value.unit_id for value in staging}) != len(staging):
            return False
        validated: list[tuple[StagingRevision, TopologyUnitRevision]] = []
        for expected in staging:
            revision = self._session.scalar(
                select(TopologyUnitRevision)
                .where(
                    TopologyUnitRevision.id == expected.revision_id,
                    TopologyUnitRevision.library_id == fence.library_id,
                    TopologyUnitRevision.unit_id == expected.unit_id,
                    TopologyUnitRevision.state == RevisionState.STAGING,
                    *_origin_conditions(fence),
                )
                .with_for_update()
            )
            unit = self._session.get(TopologyUnit, expected.unit_id)
            if (
                revision is None
                or unit is None
                or unit.library_id != fence.library_id
                or unit.active_revision_id != expected.expected_active_revision_id
                or expected.staged_row_count != expected.expected_row_count
                or _revision_row_count(self._session, expected.revision_id)
                != expected.expected_row_count
                or not _revision_sources_valid(self._session, fence, revision)
            ):
                return False
            validated.append((expected, revision))
        for expected, _ in validated:
            if expected.expected_active_revision_id is None:
                continue
            superseded = self._session.execute(
                update(TopologyUnitRevision)
                .where(
                    TopologyUnitRevision.id == expected.expected_active_revision_id,
                    TopologyUnitRevision.library_id == fence.library_id,
                    TopologyUnitRevision.unit_id == expected.unit_id,
                    TopologyUnitRevision.state == RevisionState.ACTIVE,
                )
                .values(state=RevisionState.SUPERSEDED)
            )
            if cast(CursorResult[object], superseded).rowcount != 1:
                return False
        for expected, _ in validated:
            activated = self._session.execute(
                update(TopologyUnitRevision)
                .where(
                    TopologyUnitRevision.id == expected.revision_id,
                    TopologyUnitRevision.library_id == fence.library_id,
                    TopologyUnitRevision.unit_id == expected.unit_id,
                    TopologyUnitRevision.state == RevisionState.STAGING,
                )
                .values(state=RevisionState.ACTIVE)
            )
            if cast(CursorResult[object], activated).rowcount != 1:
                return False
        revision_ids = tuple(value.revision_id for value, _ in validated)
        _apply_activated_facts(
            self._session,
            fence.library_id,
            revision_ids,
            activated_at=activated_at,
        )
        for expected, _ in validated:
            pointer = (
                TopologyUnit.active_revision_id.is_(None)
                if expected.expected_active_revision_id is None
                else TopologyUnit.active_revision_id
                == expected.expected_active_revision_id
            )
            updated = self._session.execute(
                update(TopologyUnit)
                .where(
                    TopologyUnit.id == expected.unit_id,
                    TopologyUnit.library_id == fence.library_id,
                    pointer,
                )
                .values(active_revision_id=expected.revision_id)
            )
            if cast(CursorResult[object], updated).rowcount != 1:
                return False
        self._session.flush()
        return True


__all__ = [
    "SqlAlchemyTopologyRepository",
    "disc_number_from_storage",
    "disc_number_to_storage",
]
