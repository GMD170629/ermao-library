"""SQLAlchemy persistence for staged catalog topology projections."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.modules.catalog.application.scan_dto import ScanFence, StagingRevision
from app.modules.catalog.domain.model import PathComparison
from app.modules.catalog.domain.scan import (
    AssetMembershipPlan,
    ScanStale,
    TopologyStageBatch,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
)
from app.modules.catalog.domain.scan import (
    TopologyUnitKind as DomainTopologyUnitKind,
)

from .enums import (
    AssetRole,
    AssetValidationState,
    LayoutState,
    RevisionState,
    ScanState,
    SlotState,
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
from .scan_fencing import (
    path_token as _path_token,
)
from .scan_fencing import (
    require_live_fence as _require_live_fence,
)
from .scan_fencing import (
    source_entry_id as _source_entry_id,
)
from .scan_fencing import (
    stable_id as _stable_id,
)

_SOURCE_VALIDATION_CHUNK = 400


def disc_number_to_storage(value: int) -> int | None:
    if value < 0:
        raise ValueError("disc number cannot be negative")
    return None if value == 0 else value


def disc_number_from_storage(value: int | None) -> int:
    if value is not None and value <= 0:
        raise ValueError("stored disc number must be positive")
    return 0 if value is None else value


def _work_id(library_id: str, path: tuple[str, ...], comparison: PathComparison) -> str:
    return _stable_id("work", library_id, _path_token(path, comparison))


def _version_id(
    library_id: str,
    *,
    work_path: tuple[str, ...],
    version_path: tuple[str, ...] | None,
    comparison: PathComparison,
) -> str:
    if version_path is None:
        return _stable_id(
            "version",
            library_id,
            _path_token(work_path, comparison),
            "implicit",
        )
    return _stable_id("version", library_id, _path_token(version_path, comparison))


def _volume_id(
    library_id: str, path: tuple[str, ...], comparison: PathComparison
) -> str:
    return _stable_id("volume", library_id, _path_token(path, comparison))


def _unit_id(library_id: str, unit_key: str) -> str:
    return _stable_id("unit", library_id, unit_key)


def _revision_row_count(session: Session, revision_id: str) -> int:
    projection_models = (
        TopologyWorkProjection,
        TopologyVersionProjection,
        TopologyVolumeProjection,
        TopologyAssetMembership,
    )
    return sum(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.unit_revision_id == revision_id)
        )
        or 0
        for model in projection_models
    )


def _revision_sources_valid(
    session: Session,
    fence: ScanFence,
    revision: TopologyUnitRevision,
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
        source_id
        for source_id in session.scalars(
            select(TopologyVersionProjection.root_entry_id).where(
                TopologyVersionProjection.library_id == fence.library_id,
                TopologyVersionProjection.unit_revision_id == revision.id,
                TopologyVersionProjection.root_entry_id.is_not(None),
            )
        )
        if source_id is not None
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
    return _source_ids_are_valid(session, fence, source_ids)


def _source_ids_are_valid(
    session: Session,
    fence: ScanFence,
    source_ids: set[str],
) -> bool:
    validated_ids: set[str] = set()
    frontier = set(source_ids)
    while frontier:
        ordered_ids = tuple(sorted(frontier))
        valid_rows: dict[str, str | None] = {}
        for offset in range(0, len(ordered_ids), _SOURCE_VALIDATION_CHUNK):
            for entry_id, parent_entry_id in session.execute(
                select(
                    LibrarySourceEntry.id,
                    LibrarySourceEntry.parent_entry_id,
                ).where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.id.in_(
                        ordered_ids[offset : offset + _SOURCE_VALIDATION_CHUNK]
                    ),
                    LibrarySourceEntry.last_seen_generation == fence.generation,
                    LibrarySourceEntry.layout_state == LayoutState.PRESENT,
                    LibrarySourceEntry.slot_state == SlotState.ACTIVE,
                )
            ):
                valid_rows[entry_id] = parent_entry_id
        if set(valid_rows) != frontier:
            return False
        validated_ids.update(frontier)
        frontier = {
            parent_entry_id
            for parent_entry_id in valid_rows.values()
            if parent_entry_id is not None and parent_entry_id not in validated_ids
        }
    return True


def _plan_sources_valid(
    session: Session,
    fence: ScanFence,
    plan: TopologyUnitPlan,
) -> bool:
    source_ids = {_source_entry_id(fence.library_id, plan.unit_root_path)}
    for row in plan.rows:
        if isinstance(
            row, WorkProjectionPlan | VersionProjectionPlan | VolumeProjectionPlan
        ):
            root_path = row.root_path
            if root_path is not None:
                source_ids.add(_source_entry_id(fence.library_id, root_path))
        elif isinstance(row, AssetMembershipPlan):
            source_ids.add(_source_entry_id(fence.library_id, row.source_path))
    return _source_ids_are_valid(session, fence, source_ids)


def _ensure_work(session: Session, library_id: str, work_id: str) -> None:
    if session.get(LibraryWork, work_id) is None:
        session.add(LibraryWork(id=work_id, library_id=library_id))


def _ensure_version(session: Session, library_id: str, version_id: str) -> None:
    if session.get(WorkVersion, version_id) is None:
        session.add(WorkVersion(id=version_id, library_id=library_id))


def _ensure_volume(
    session: Session,
    library_id: str,
    volume_id: str,
    *,
    reading_morphology: str,
    staged_at: datetime,
) -> None:
    row = session.get(LibraryVolume, volume_id)
    if row is None:
        session.add(
            LibraryVolume(
                id=volume_id,
                library_id=library_id,
                reading_morphology=reading_morphology,
                content_state="PENDING",
                created_at=staged_at,
                updated_at=staged_at,
            )
        )


def _prepare_projection_dependencies(
    session: Session,
    fence: ScanFence,
    batch: TopologyStageBatch,
    *,
    comparison: PathComparison,
    staged_at: datetime,
) -> dict[str, LibrarySourceEntry]:
    """Persist stable identities before projection rows reference them."""

    work_ids: set[str] = set()
    version_ids: set[str] = set()
    volume_ids: set[str] = set()
    source_ids: set[str] = set()
    volume_morphologies: dict[str, str] = {}
    asset_specs: dict[str, tuple[str, str]] = {}
    for row in batch.rows:
        if isinstance(row, WorkProjectionPlan):
            work_ids.add(_work_id(fence.library_id, row.root_path, comparison))
            source_ids.add(_source_entry_id(fence.library_id, row.root_path))
        elif isinstance(row, VersionProjectionPlan):
            work_ids.add(_work_id(fence.library_id, row.work_path, comparison))
            version_ids.add(
                _version_id(
                    fence.library_id,
                    work_path=row.work_path,
                    version_path=row.root_path,
                    comparison=comparison,
                )
            )
            if row.root_path is not None:
                source_ids.add(_source_entry_id(fence.library_id, row.root_path))
        elif isinstance(row, VolumeProjectionPlan):
            work_ids.add(_work_id(fence.library_id, row.work_path, comparison))
            version_ids.add(
                _version_id(
                    fence.library_id,
                    work_path=row.work_path,
                    version_path=row.version_path,
                    comparison=comparison,
                )
            )
            volume_id = _volume_id(fence.library_id, row.root_path, comparison)
            morphology = row.reading_morphology.value
            existing_morphology = volume_morphologies.setdefault(volume_id, morphology)
            if existing_morphology != morphology:
                raise ScanStale()
            volume_ids.add(volume_id)
            source_ids.add(_source_entry_id(fence.library_id, row.root_path))
        else:
            source_id = _source_entry_id(fence.library_id, row.source_path)
            source_ids.add(source_id)
            volume_ids.add(_volume_id(fence.library_id, row.volume_path, comparison))
            asset_id = _stable_id("asset", fence.library_id, source_id)
            asset_spec = (source_id, row.source_format.value)
            existing_asset_spec = asset_specs.setdefault(asset_id, asset_spec)
            if existing_asset_spec != asset_spec:
                raise ScanStale()

    sources: dict[str, LibrarySourceEntry] = {}
    ordered_source_ids = tuple(sorted(source_ids))
    for offset in range(0, len(ordered_source_ids), _SOURCE_VALIDATION_CHUNK):
        sources.update(
            (source.id, source)
            for source in session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.id.in_(
                        ordered_source_ids[offset : offset + _SOURCE_VALIDATION_CHUNK]
                    ),
                )
            )
        )
    if set(sources) != source_ids:
        raise ScanStale()

    existing_work_ids: set[str] = set()
    ordered_work_ids = tuple(sorted(work_ids))
    for offset in range(0, len(ordered_work_ids), _SOURCE_VALIDATION_CHUNK):
        existing_work_ids.update(
            session.scalars(
                select(LibraryWork.id).where(
                    LibraryWork.library_id == fence.library_id,
                    LibraryWork.id.in_(
                        ordered_work_ids[offset : offset + _SOURCE_VALIDATION_CHUNK]
                    ),
                )
            )
        )
    existing_version_ids: set[str] = set()
    ordered_version_ids = tuple(sorted(version_ids))
    for offset in range(0, len(ordered_version_ids), _SOURCE_VALIDATION_CHUNK):
        existing_version_ids.update(
            session.scalars(
                select(WorkVersion.id).where(
                    WorkVersion.library_id == fence.library_id,
                    WorkVersion.id.in_(
                        ordered_version_ids[offset : offset + _SOURCE_VALIDATION_CHUNK]
                    ),
                )
            )
        )
    existing_volume_ids: set[str] = set()
    ordered_volume_ids = tuple(sorted(volume_ids))
    for offset in range(0, len(ordered_volume_ids), _SOURCE_VALIDATION_CHUNK):
        existing_volume_ids.update(
            session.scalars(
                select(LibraryVolume.id).where(
                    LibraryVolume.library_id == fence.library_id,
                    LibraryVolume.id.in_(
                        ordered_volume_ids[offset : offset + _SOURCE_VALIDATION_CHUNK]
                    ),
                )
            )
        )
    missing_volume_ids = volume_ids - existing_volume_ids
    if not missing_volume_ids.issubset(volume_morphologies):
        raise ScanStale()
    asset_ids = set(asset_specs)
    existing_asset_ids: set[str] = set()
    ordered_asset_ids = tuple(sorted(asset_ids))
    for offset in range(0, len(ordered_asset_ids), _SOURCE_VALIDATION_CHUNK):
        existing_asset_ids.update(
            session.scalars(
                select(VolumeAsset.id).where(
                    VolumeAsset.library_id == fence.library_id,
                    VolumeAsset.id.in_(
                        ordered_asset_ids[offset : offset + _SOURCE_VALIDATION_CHUNK]
                    ),
                )
            )
        )
    session.add_all(
        [
            LibraryWork(id=work_id, library_id=fence.library_id)
            for work_id in work_ids - existing_work_ids
        ]
    )
    session.add_all(
        [
            WorkVersion(id=version_id, library_id=fence.library_id)
            for version_id in version_ids - existing_version_ids
        ]
    )
    session.add_all(
        [
            LibraryVolume(
                id=volume_id,
                library_id=fence.library_id,
                reading_morphology=volume_morphologies[volume_id],
                content_state="PENDING",
                created_at=staged_at,
                updated_at=staged_at,
            )
            for volume_id in missing_volume_ids
        ]
    )
    session.add_all(
        [
            VolumeAsset(
                id=asset_id,
                library_id=fence.library_id,
                source_format=asset_specs[asset_id][1],
                size_bytes=sources[asset_specs[asset_id][0]].size_bytes,
                validation_state=AssetValidationState.PENDING,
                created_at=staged_at,
                updated_at=staged_at,
            )
            for asset_id in asset_ids - existing_asset_ids
        ]
    )
    session.flush()
    return sources


def _owner_ids(
    fence: ScanFence, plan: TopologyUnitPlan
) -> tuple[str | None, str | None, str | None]:
    comparison = PathComparison(fence.path_comparison)
    if plan.unit_kind in {
        DomainTopologyUnitKind.WORK_CONTAINER,
        DomainTopologyUnitKind.AUDIOBOOK_WORK,
    }:
        return _work_id(fence.library_id, plan.owner_path, comparison), None, None
    if plan.unit_kind is DomainTopologyUnitKind.VERSION_CONTAINER:
        return (
            None,
            _version_id(
                fence.library_id,
                work_path=plan.owner_path[:-1],
                version_path=plan.owner_path,
                comparison=comparison,
            ),
            None,
        )
    return None, None, _volume_id(fence.library_id, plan.owner_path, comparison)


def _ensure_unit_owner(
    session: Session,
    fence: ScanFence,
    plan: TopologyUnitPlan,
    *,
    created_at: datetime,
) -> TopologyUnit:
    work_owner_id, version_owner_id, volume_owner_id = _owner_ids(fence, plan)
    if work_owner_id is not None:
        _ensure_work(session, fence.library_id, work_owner_id)
    if version_owner_id is not None:
        _ensure_version(session, fence.library_id, version_owner_id)
    if volume_owner_id is not None:
        volume_plan = next(
            (
                row
                for row in plan.rows
                if isinstance(row, VolumeProjectionPlan)
                and _volume_id(
                    fence.library_id,
                    row.root_path,
                    PathComparison(fence.path_comparison),
                )
                == volume_owner_id
            ),
            None,
        )
        morphology = (
            "REFLOWABLE"
            if volume_plan is None
            else volume_plan.reading_morphology.value
        )
        _ensure_volume(
            session,
            fence.library_id,
            volume_owner_id,
            reading_morphology=morphology,
            staged_at=created_at,
        )
    session.flush()
    unit_id = _unit_id(fence.library_id, plan.unit_key)
    unit = session.get(TopologyUnit, unit_id)
    if unit is None:
        unit = TopologyUnit(
            id=unit_id,
            library_id=fence.library_id,
            unit_kind=TopologyUnitKind(plan.unit_kind.value),
            work_owner_id=work_owner_id,
            version_owner_id=version_owner_id,
            volume_owner_id=volume_owner_id,
            active_revision_id=None,
            created_at=created_at,
        )
        session.add(unit)
        session.flush()
    elif (
        unit.unit_kind != TopologyUnitKind(plan.unit_kind.value)
        or unit.work_owner_id != work_owner_id
        or unit.version_owner_id != version_owner_id
        or unit.volume_owner_id != volume_owner_id
    ):
        raise ScanStale()
    return unit


def _expected_signature(
    fence: ScanFence, plan: TopologyUnitPlan
) -> tuple[tuple[object, ...], ...]:
    comparison = PathComparison(fence.path_comparison)
    signature: list[tuple[object, ...]] = []
    for row in plan.rows:
        if isinstance(row, WorkProjectionPlan):
            signature.append(
                (
                    "work",
                    _work_id(fence.library_id, row.root_path, comparison),
                    _source_entry_id(fence.library_id, row.root_path),
                    row.structure_key,
                    row.source_name,
                    row.sort_key,
                )
            )
        elif isinstance(row, VersionProjectionPlan):
            signature.append(
                (
                    "version",
                    _version_id(
                        fence.library_id,
                        work_path=row.work_path,
                        version_path=row.root_path,
                        comparison=comparison,
                    ),
                    _work_id(fence.library_id, row.work_path, comparison),
                    (
                        None
                        if row.root_path is None
                        else _source_entry_id(fence.library_id, row.root_path)
                    ),
                    row.kind.value,
                    row.structure_key,
                    row.source_name,
                    row.sort_key,
                )
            )
        elif isinstance(row, VolumeProjectionPlan):
            signature.append(
                (
                    "volume",
                    _volume_id(fence.library_id, row.root_path, comparison),
                    _version_id(
                        fence.library_id,
                        work_path=row.work_path,
                        version_path=row.version_path,
                        comparison=comparison,
                    ),
                    _source_entry_id(fence.library_id, row.root_path),
                    row.source_kind.value,
                    row.reading_morphology.value,
                    row.structure_key,
                    row.source_name,
                    row.sort_key,
                )
            )
        else:
            signature.append(
                (
                    "asset",
                    _volume_id(fence.library_id, row.volume_path, comparison),
                    _source_entry_id(fence.library_id, row.source_path),
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
    for membership in session.scalars(
        select(TopologyAssetMembership).where(
            TopologyAssetMembership.unit_revision_id == revision_id
        )
    ):
        signature.append(
            (
                "asset",
                membership.volume_id,
                membership.source_entry_id,
                membership.role.value,
                membership.source_format,
                membership.disc_number,
                membership.asset_order,
                membership.required_for_reading,
            )
        )
    return tuple(sorted(signature, key=repr))


def _apply_activated_stable_facts(
    session: Session,
    fence: ScanFence,
    revision_ids: tuple[str, ...],
    *,
    activated_at: datetime,
) -> None:
    volume_projection_exists = exists(
        select(TopologyVolumeProjection.id).where(
            TopologyVolumeProjection.library_id == LibraryVolume.library_id,
            TopologyVolumeProjection.volume_id == LibraryVolume.id,
            TopologyVolumeProjection.unit_revision_id.in_(revision_ids),
        )
    )
    activated_morphology = (
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
        .where(
            LibraryVolume.library_id == fence.library_id,
            volume_projection_exists,
        )
        .values(
            reading_morphology=activated_morphology,
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
    activated_source_format = (
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
    activated_size = (
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
        .where(
            VolumeAsset.library_id == fence.library_id,
            membership_exists,
        )
        .values(
            source_format=activated_source_format,
            size_bytes=activated_size,
            validation_state=AssetValidationState.PENDING,
            updated_at=activated_at,
        )
    )


class SqlAlchemyTopologyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def abandon_scan_staging(self, fence: ScanFence, *, abandoned_at: datetime) -> None:
        _require_live_fence(self._session, fence, now=abandoned_at)
        self._session.execute(
            update(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.scan_run_id == fence.scan_id,
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
        cancelled_run = exists(
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
                TopologyUnitRevision.state == RevisionState.STAGING,
                cancelled_run,
            )
            .values(state=RevisionState.ABANDONED)
        )
        self._session.flush()
        return bool(self._session.scalar(select(cancelled_run)))

    def abandon_incomplete(
        self, fence: ScanFence, *, unit_key: str, abandoned_at: datetime
    ) -> None:
        _require_live_fence(self._session, fence, now=abandoned_at)
        self._session.execute(
            update(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.unit_id == _unit_id(fence.library_id, unit_key),
                TopologyUnitRevision.state == RevisionState.STAGING,
            )
            .values(state=RevisionState.ABANDONED)
        )
        self._session.flush()

    def get_active_revision_id(self, library_id: str, *, unit_key: str) -> str | None:
        return self._session.scalar(
            select(TopologyUnit.active_revision_id).where(
                TopologyUnit.library_id == library_id,
                TopologyUnit.id == _unit_id(library_id, unit_key),
            )
        )

    def begin_staging(
        self,
        fence: ScanFence,
        plan: TopologyUnitPlan,
        *,
        expected_active_revision_id: str | None,
        created_at: datetime,
    ) -> StagingRevision | None:
        _require_live_fence(self._session, fence, now=created_at)
        if not _plan_sources_valid(self._session, fence, plan):
            raise ScanStale()
        unit = _ensure_unit_owner(self._session, fence, plan, created_at=created_at)
        if unit.active_revision_id != expected_active_revision_id:
            raise ScanStale()
        if expected_active_revision_id is not None and _stored_signature(
            self._session, expected_active_revision_id
        ) == _expected_signature(fence, plan):
            return None
        latest_revision = self._session.scalar(
            select(func.max(TopologyUnitRevision.revision)).where(
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.unit_id == unit.id,
            )
        )
        revision_number = (latest_revision or 0) + 1
        revision_id = _stable_id(
            "revision",
            fence.library_id,
            unit.id,
            fence.scan_id,
            str(revision_number),
        )
        self._session.add(
            TopologyUnitRevision(
                id=revision_id,
                library_id=fence.library_id,
                unit_id=unit.id,
                scan_run_id=fence.scan_id,
                unit_root_entry_id=_source_entry_id(
                    fence.library_id, plan.unit_root_path
                ),
                revision=revision_number,
                state=RevisionState.STAGING,
                created_at=created_at,
            )
        )
        self._session.flush()
        return StagingRevision(
            revision_id=revision_id,
            unit_id=unit.id,
            expected_active_revision_id=expected_active_revision_id,
            expected_row_count=len(plan.rows),
            staged_row_count=0,
        )

    def append_staging_batch(
        self,
        fence: ScanFence,
        staging: StagingRevision,
        batch: TopologyStageBatch,
        *,
        staged_at: datetime,
    ) -> StagingRevision:
        _require_live_fence(self._session, fence, now=staged_at)
        revision = self._session.scalar(
            select(TopologyUnitRevision)
            .where(
                TopologyUnitRevision.id == staging.revision_id,
                TopologyUnitRevision.library_id == fence.library_id,
                TopologyUnitRevision.unit_id == staging.unit_id,
                TopologyUnitRevision.scan_run_id == fence.scan_id,
                TopologyUnitRevision.state == RevisionState.STAGING,
            )
            .with_for_update()
        )
        actual_count = _revision_row_count(self._session, staging.revision_id)
        if (
            revision is None
            or actual_count != staging.staged_row_count
            or batch.first_row != staging.staged_row_count
            or actual_count + len(batch.rows) > staging.expected_row_count
            or batch.complete
            != (actual_count + len(batch.rows) == staging.expected_row_count)
        ):
            raise ScanStale()
        comparison = PathComparison(fence.path_comparison)
        sources = _prepare_projection_dependencies(
            self._session,
            fence,
            batch,
            comparison=comparison,
            staged_at=staged_at,
        )
        with self._session.no_autoflush:
            for row_index, row in enumerate(batch.rows, start=batch.first_row):
                self._append_projection(
                    fence,
                    revision,
                    row,
                    row_index=row_index,
                    comparison=comparison,
                    sources=sources,
                )
        self._session.flush()
        staged_count = _revision_row_count(self._session, staging.revision_id)
        if staged_count != actual_count + len(batch.rows):
            raise ScanStale()
        return StagingRevision(
            revision_id=staging.revision_id,
            unit_id=staging.unit_id,
            expected_active_revision_id=staging.expected_active_revision_id,
            expected_row_count=staging.expected_row_count,
            staged_row_count=staged_count,
        )

    def _append_projection(
        self,
        fence: ScanFence,
        revision: TopologyUnitRevision,
        row: WorkProjectionPlan
        | VersionProjectionPlan
        | VolumeProjectionPlan
        | AssetMembershipPlan,
        *,
        row_index: int,
        comparison: PathComparison,
        sources: dict[str, LibrarySourceEntry],
    ) -> None:
        if isinstance(row, WorkProjectionPlan):
            source = sources[_source_entry_id(fence.library_id, row.root_path)]
            work_id = _work_id(fence.library_id, row.root_path, comparison)
            self._session.add(
                TopologyWorkProjection(
                    id=_stable_id("work_projection", revision.id, str(row_index)),
                    library_id=fence.library_id,
                    unit_revision_id=revision.id,
                    work_id=work_id,
                    root_entry_id=source.id,
                    structure_key=row.structure_key,
                    source_name=row.source_name,
                    sort_key=row.sort_key,
                )
            )
            return
        if isinstance(row, VersionProjectionPlan):
            work_id = _work_id(fence.library_id, row.work_path, comparison)
            version_id = _version_id(
                fence.library_id,
                work_path=row.work_path,
                version_path=row.root_path,
                comparison=comparison,
            )
            root_entry_id = (
                None
                if row.root_path is None
                else sources[_source_entry_id(fence.library_id, row.root_path)].id
            )
            self._session.add(
                TopologyVersionProjection(
                    id=_stable_id("version_projection", revision.id, str(row_index)),
                    library_id=fence.library_id,
                    unit_revision_id=revision.id,
                    version_id=version_id,
                    work_id=work_id,
                    root_entry_id=root_entry_id,
                    kind=VersionKind(row.kind.value),
                    structure_key=row.structure_key,
                    source_name=row.source_name,
                    sort_key=row.sort_key,
                )
            )
            return
        if isinstance(row, VolumeProjectionPlan):
            source = sources[_source_entry_id(fence.library_id, row.root_path)]
            work_id = _work_id(fence.library_id, row.work_path, comparison)
            version_id = _version_id(
                fence.library_id,
                work_path=row.work_path,
                version_path=row.version_path,
                comparison=comparison,
            )
            volume_id = _volume_id(fence.library_id, row.root_path, comparison)
            self._session.add(
                TopologyVolumeProjection(
                    id=_stable_id("volume_projection", revision.id, str(row_index)),
                    library_id=fence.library_id,
                    unit_revision_id=revision.id,
                    volume_id=volume_id,
                    version_id=version_id,
                    root_entry_id=source.id,
                    source_kind=row.source_kind,
                    reading_morphology=row.reading_morphology.value,
                    structure_key=row.structure_key,
                    source_name=row.source_name,
                    sort_key=row.sort_key,
                )
            )
            return
        source = sources[_source_entry_id(fence.library_id, row.source_path)]
        volume_id = _volume_id(fence.library_id, row.volume_path, comparison)
        asset_id = _stable_id("asset", fence.library_id, source.id)
        self._session.add(
            TopologyAssetMembership(
                id=_stable_id("asset_membership", revision.id, str(row_index)),
                library_id=fence.library_id,
                unit_revision_id=revision.id,
                asset_id=asset_id,
                volume_id=volume_id,
                source_entry_id=source.id,
                role=AssetRole(row.role.value),
                source_format=row.source_format.value,
                disc_number=disc_number_to_storage(row.disc_number),
                asset_order=row.asset_order,
                required_for_reading=row.required_for_reading,
            )
        )

    def activate_staging_group(
        self,
        fence: ScanFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> bool:
        _require_live_fence(self._session, fence, now=activated_at)
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
                    TopologyUnitRevision.scan_run_id == fence.scan_id,
                    TopologyUnitRevision.state == RevisionState.STAGING,
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
        for expected, _revision in validated:
            if expected.expected_active_revision_id is None:
                continue
            result = self._session.execute(
                update(TopologyUnitRevision)
                .where(
                    TopologyUnitRevision.id == expected.expected_active_revision_id,
                    TopologyUnitRevision.library_id == fence.library_id,
                    TopologyUnitRevision.unit_id == expected.unit_id,
                    TopologyUnitRevision.state == RevisionState.ACTIVE,
                )
                .values(state=RevisionState.SUPERSEDED)
            )
            if cast(CursorResult[object], result).rowcount != 1:
                return False
        for expected, _revision in validated:
            result = self._session.execute(
                update(TopologyUnitRevision)
                .where(
                    TopologyUnitRevision.id == expected.revision_id,
                    TopologyUnitRevision.library_id == fence.library_id,
                    TopologyUnitRevision.unit_id == expected.unit_id,
                    TopologyUnitRevision.state == RevisionState.STAGING,
                )
                .values(state=RevisionState.ACTIVE)
            )
            if cast(CursorResult[object], result).rowcount != 1:
                return False
        _apply_activated_stable_facts(
            self._session,
            fence,
            tuple(expected.revision_id for expected, _revision in validated),
            activated_at=activated_at,
        )
        for expected, _revision in validated:
            pointer_condition = (
                TopologyUnit.active_revision_id.is_(None)
                if expected.expected_active_revision_id is None
                else TopologyUnit.active_revision_id
                == expected.expected_active_revision_id
            )
            result = self._session.execute(
                update(TopologyUnit)
                .where(
                    TopologyUnit.id == expected.unit_id,
                    TopologyUnit.library_id == fence.library_id,
                    pointer_condition,
                )
                .values(active_revision_id=expected.revision_id)
            )
            if cast(CursorResult[object], result).rowcount != 1:
                return False
        self._session.flush()
        return True


__all__ = [
    "SqlAlchemyTopologyRepository",
    "disc_number_from_storage",
    "disc_number_to_storage",
]
