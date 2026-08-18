"""Shared SQLAlchemy fencing and scheduling primitives for PR6A content work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.content_dto import (
    VolumeProcessingWorkFence,
)
from app.modules.catalog.application.scan_dto import ScanFence
from app.modules.catalog.application.watcher_dto import ReconcileFence
from app.modules.catalog.domain.content import (
    Sha256Digest,
)
from app.modules.catalog.domain.scan import (
    ScanStale,
)
from app.modules.catalog.domain.watcher import ReconcileStale

from .enums import (
    AssetValidationState,
    ContentProcessorKind,
    ProcessorState,
    VolumeContentState,
)
from .models import (
    LibraryVolume,
    TopologyAssetMembership,
    TopologyUnit,
    VolumeAsset,
    VolumeProcessingFact,
)
from .reconcile_fencing import require_live_reconcile
from .scan_fencing import require_live_fence, stable_id
from .source_path_resolution import SOURCE_QUERY_CHUNK

ContentFence = ScanFence | ReconcileFence

MAX_OBSERVATIONS = 5_000
MAX_REQUIRED_ASSETS = 10_000
CLAIM_CANDIDATE_LIMIT = 101
MAX_DEFERRED_CLAIMS = 100
MAX_SOURCE_PATH_DEPTH = 1_024
REQUIRED_MANIFEST_PROCESSOR_VERSION = "required-manifest-v1"
REQUIRED_OPENING_PROCESSOR_VERSION = "required-opening-v1"
DELIVERY_POLICY_VERSION = 1


def is_after(left: datetime, right: datetime) -> bool:
    def utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    return utc_naive(left) > utc_naive(right)


def raise_content_stale(fence: ContentFence) -> NoReturn:
    if isinstance(fence, ScanFence):
        raise ScanStale()
    raise ReconcileStale()


def require_content_fence(
    session: Session,
    fence: ContentFence,
    *,
    now: datetime,
) -> None:
    if isinstance(fence, ScanFence):
        require_live_fence(session, fence, now=now)
    else:
        require_live_reconcile(session, fence, now=now)


def presence_generation(fence: ContentFence) -> int:
    if isinstance(fence, ScanFence):
        return fence.generation
    return fence.presence_generation


def current_required_memberships_for_sources(
    session: Session,
    library_id: str,
    source_ids: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for offset in range(0, len(source_ids), SOURCE_QUERY_CHUNK):
        for asset_id, volume_id, revision_id in session.execute(
            select(
                TopologyAssetMembership.asset_id,
                TopologyAssetMembership.volume_id,
                TopologyAssetMembership.unit_revision_id,
            )
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
                TopologyAssetMembership.required_for_reading.is_(True),
                TopologyAssetMembership.source_entry_id.in_(
                    source_ids[offset : offset + SOURCE_QUERY_CHUNK]
                ),
            )
        ):
            rows.append((asset_id, volume_id, revision_id))
    return tuple(dict.fromkeys(rows))


def pending_manifest_fingerprint(
    library_id: str,
    volume_id: str,
    topology_revision_id: str,
) -> str:
    value = stable_id(
        "content_pending",
        library_id,
        volume_id,
        topology_revision_id,
    ).encode("ascii")
    return Sha256Digest.from_bytes(value).value


def _upsert_manifest_processing(
    session: Session,
    *,
    library_id: str,
    volume: LibraryVolume,
    topology_revision_id: str,
    input_fingerprint: str,
    observed_at: datetime,
) -> VolumeProcessingFact:
    row = session.get(
        VolumeProcessingFact,
        (library_id, volume.id, ContentProcessorKind.REQUIRED_MANIFEST),
    )
    return apply_manifest_processing(
        session,
        row=row,
        library_id=library_id,
        volume=volume,
        topology_revision_id=topology_revision_id,
        input_fingerprint=input_fingerprint,
        observed_at=observed_at,
    )


def apply_manifest_processing(
    session: Session,
    *,
    row: VolumeProcessingFact | None,
    library_id: str,
    volume: LibraryVolume,
    topology_revision_id: str,
    input_fingerprint: str,
    observed_at: datetime,
) -> VolumeProcessingFact:
    if row is None:
        row = VolumeProcessingFact(
            library_id=library_id,
            volume_id=volume.id,
            processor_kind=ContentProcessorKind.REQUIRED_MANIFEST,
            work_revision=1,
            processor_version=REQUIRED_MANIFEST_PROCESSOR_VERSION,
            active_topology_revision_id=topology_revision_id,
            expected_content_revision=volume.content_revision,
            expected_required_manifest_revision=volume.required_manifest_revision,
            input_fingerprint=input_fingerprint,
            available_at=observed_at,
            state=ProcessorState.PENDING,
            failure_code=None,
            lease_owner=None,
            lease_expires_at=None,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(row)
        return row
    changed = (
        row.processor_version != REQUIRED_MANIFEST_PROCESSOR_VERSION
        or row.active_topology_revision_id != topology_revision_id
        or row.expected_content_revision != volume.content_revision
        or row.expected_required_manifest_revision != volume.required_manifest_revision
        or row.input_fingerprint != input_fingerprint
    )
    if changed:
        row.work_revision += 1
        row.processor_version = REQUIRED_MANIFEST_PROCESSOR_VERSION
        row.active_topology_revision_id = topology_revision_id
        row.expected_content_revision = volume.content_revision
        row.expected_required_manifest_revision = volume.required_manifest_revision
        row.input_fingerprint = input_fingerprint
        row.available_at = observed_at
        row.state = ProcessorState.PENDING
        row.failure_code = None
        row.lease_owner = None
        row.lease_expires_at = None
        row.updated_at = observed_at
    elif row.state is ProcessorState.PENDING and is_after(
        row.available_at, observed_at
    ):
        row.available_at = observed_at
        row.updated_at = observed_at
    return row


def owned_processing_conditions(
    fence: VolumeProcessingWorkFence,
) -> tuple[ColumnElement[bool], ...]:
    return (
        VolumeProcessingFact.library_id == fence.library_id,
        VolumeProcessingFact.volume_id == fence.volume_id,
        VolumeProcessingFact.processor_kind
        == ContentProcessorKind(fence.processor_kind.value),
        VolumeProcessingFact.work_revision == fence.work_revision,
        VolumeProcessingFact.state == ProcessorState.RUNNING,
        VolumeProcessingFact.lease_owner == fence.owner_token,
        VolumeProcessingFact.lease_expires_at == fence.lease_expires_at,
    )


def mark_current_sources_pending(
    session: Session,
    library_id: str,
    source_ids: tuple[str, ...],
    *,
    observed_at: datetime,
) -> None:
    memberships = current_required_memberships_for_sources(
        session, library_id, source_ids
    )
    if not memberships:
        return
    asset_ids = tuple(dict.fromkeys(value[0] for value in memberships))
    volume_revisions = tuple(
        dict.fromkeys((value[1], value[2]) for value in memberships)
    )
    for offset in range(0, len(asset_ids), SOURCE_QUERY_CHUNK):
        session.execute(
            update(VolumeAsset)
            .where(
                VolumeAsset.library_id == library_id,
                VolumeAsset.id.in_(asset_ids[offset : offset + SOURCE_QUERY_CHUNK]),
            )
            .values(
                validation_state=AssetValidationState.PENDING,
                updated_at=observed_at,
            )
        )
    volume_ids = tuple(dict.fromkeys(value[0] for value in volume_revisions))
    volumes: dict[str, LibraryVolume] = {}
    for offset in range(0, len(volume_ids), SOURCE_QUERY_CHUNK):
        volumes.update(
            (row.id, row)
            for row in session.scalars(
                select(LibraryVolume)
                .where(
                    LibraryVolume.library_id == library_id,
                    LibraryVolume.id.in_(
                        volume_ids[offset : offset + SOURCE_QUERY_CHUNK]
                    ),
                )
                .with_for_update()
            )
        )
    for volume_id, topology_revision_id in volume_revisions:
        volume = volumes.get(volume_id)
        if volume is None:
            continue
        volume.content_state = VolumeContentState.PENDING
        volume.updated_at = observed_at
        _upsert_manifest_processing(
            session,
            library_id=library_id,
            volume=volume,
            topology_revision_id=topology_revision_id,
            input_fingerprint=pending_manifest_fingerprint(
                library_id,
                volume_id,
                topology_revision_id,
            ),
            observed_at=observed_at,
        )


__all__ = ["ContentFence"]
