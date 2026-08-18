"""Bounded projection of ACTIVE topology into content-processing work."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.content_dto import (
    ContentTopologyProjectionBatchOutcome,
    ContentTopologyProjectionRequestOutcome,
)
from app.modules.catalog.application.content_dto import (
    ContentTopologyProjectionState as ContentTopologyProjectionStateDto,
)
from app.modules.catalog.application.scan_dto import ScanFence, StagingRevision

from .content_persistence_primitives import (
    REQUIRED_MANIFEST_PROCESSOR_VERSION,
    ContentFence,
    apply_manifest_processing,
    pending_manifest_fingerprint,
    raise_content_stale,
    require_content_fence,
)
from .enums import ContentProcessorKind, RevisionState, VolumeContentState
from .models import (
    ContentTopologyProjectionState,
    LibraryVolume,
    TopologyUnit,
    TopologyUnitRevision,
    TopologyVolumeProjection,
    VolumeProcessingFact,
)
from .source_path_resolution import SOURCE_QUERY_CHUNK

_MAX_PROJECTION_BATCH = 500


def _projection_state_from_row(
    row: ContentTopologyProjectionState,
) -> ContentTopologyProjectionStateDto:
    return ContentTopologyProjectionStateDto(
        library_id=row.library_id,
        requested_epoch=row.requested_epoch,
        claimed_epoch=row.claimed_epoch,
        applied_epoch=row.applied_epoch,
        cursor_volume_id=row.cursor_volume_id,
    )


def _require_projection_state(
    session: Session,
    library_id: str,
) -> ContentTopologyProjectionState:
    row = session.scalar(
        select(ContentTopologyProjectionState)
        .where(ContentTopologyProjectionState.library_id == library_id)
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("content topology projection state is not initialized")
    return row


class SqlAlchemyContentTopologyActivationRepository:
    """Advance the per-library projection epoch in the pointer transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record_topology_activation(
        self,
        fence: ContentFence,
        staging: tuple[StagingRevision, ...],
        *,
        activated_at: datetime,
    ) -> ContentTopologyProjectionRequestOutcome:
        require_content_fence(self._session, fence, now=activated_at)
        revision_ids = tuple(value.revision_id for value in staging)
        if not revision_ids or len(set(revision_ids)) != len(revision_ids):
            raise_content_stale(fence)
        origin_conditions: tuple[ColumnElement[bool], ColumnElement[bool]]
        if isinstance(fence, ScanFence):
            origin_conditions = (
                TopologyUnitRevision.scan_run_id == fence.scan_id,
                TopologyUnitRevision.reconcile_origin_id.is_(None),
            )
        else:
            origin_conditions = (
                TopologyUnitRevision.scan_run_id.is_(None),
                TopologyUnitRevision.reconcile_origin_id == fence.intent_id,
            )
        found_revision_ids: set[str] = set()
        for offset in range(0, len(revision_ids), SOURCE_QUERY_CHUNK):
            found_revision_ids.update(
                self._session.scalars(
                    select(TopologyUnitRevision.id).where(
                        TopologyUnitRevision.library_id == fence.library_id,
                        TopologyUnitRevision.id.in_(
                            revision_ids[offset : offset + SOURCE_QUERY_CHUNK]
                        ),
                        TopologyUnitRevision.state == RevisionState.ACTIVE,
                        *origin_conditions,
                    )
                )
            )
        if found_revision_ids != set(revision_ids):
            raise_content_stale(fence)

        state = _require_projection_state(self._session, fence.library_id)
        wake_required = state.applied_epoch == state.requested_epoch
        state.requested_epoch += 1
        state.updated_at = activated_at
        self._session.flush()
        return ContentTopologyProjectionRequestOutcome(
            state=_projection_state_from_row(state),
            wake_required=wake_required,
        )


class SqlAlchemyContentTopologyProjectionRepository:
    """Project at most 500 active-volume mismatches in one short UoW."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def project_next_batch(
        self,
        library_id: str,
        *,
        limit: int,
        projected_at: datetime,
    ) -> ContentTopologyProjectionBatchOutcome:
        if isinstance(limit, bool) or not 1 <= limit <= _MAX_PROJECTION_BATCH:
            raise ValueError("limit must be between 1 and 500")
        state = _require_projection_state(self._session, library_id)
        if state.applied_epoch == state.requested_epoch:
            return ContentTopologyProjectionBatchOutcome(
                state=_projection_state_from_row(state),
                projection_performed=False,
                processed_volume_count=0,
            )
        if state.applied_epoch == state.claimed_epoch:
            state.claimed_epoch = state.requested_epoch
            state.cursor_volume_id = None

        rows = self._mismatched_volumes(
            library_id,
            after_volume_id=state.cursor_volume_id,
            limit=limit,
        )
        batch = rows[:limit]
        for volume, topology_revision_id, processing in batch:
            volume.content_state = VolumeContentState.PENDING
            volume.updated_at = projected_at
            apply_manifest_processing(
                self._session,
                row=processing,
                library_id=library_id,
                volume=volume,
                topology_revision_id=topology_revision_id,
                input_fingerprint=pending_manifest_fingerprint(
                    library_id,
                    volume.id,
                    topology_revision_id,
                ),
                observed_at=projected_at,
            )

        if len(rows) > limit:
            state.cursor_volume_id = batch[-1][0].id
        else:
            state.applied_epoch = state.claimed_epoch
            state.cursor_volume_id = None
            state.claimed_epoch = max(state.claimed_epoch, state.requested_epoch)
        state.updated_at = projected_at
        self._session.flush()
        return ContentTopologyProjectionBatchOutcome(
            state=_projection_state_from_row(state),
            projection_performed=True,
            processed_volume_count=len(batch),
        )

    def _mismatched_volumes(
        self,
        library_id: str,
        *,
        after_volume_id: str | None,
        limit: int,
    ) -> tuple[tuple[LibraryVolume, str, VolumeProcessingFact | None], ...]:
        statement = (
            select(
                LibraryVolume,
                TopologyUnitRevision.id,
                VolumeProcessingFact,
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
                    TopologyUnitRevision.library_id
                    == TopologyVolumeProjection.library_id,
                    TopologyUnitRevision.id
                    == TopologyVolumeProjection.unit_revision_id,
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
            .outerjoin(
                VolumeProcessingFact,
                and_(
                    VolumeProcessingFact.library_id == LibraryVolume.library_id,
                    VolumeProcessingFact.volume_id == LibraryVolume.id,
                    VolumeProcessingFact.processor_kind
                    == ContentProcessorKind.REQUIRED_MANIFEST,
                ),
            )
            .where(
                LibraryVolume.library_id == library_id,
                or_(
                    VolumeProcessingFact.volume_id.is_(None),
                    VolumeProcessingFact.processor_version
                    != REQUIRED_MANIFEST_PROCESSOR_VERSION,
                    VolumeProcessingFact.active_topology_revision_id
                    != TopologyUnitRevision.id,
                    VolumeProcessingFact.expected_content_revision
                    != LibraryVolume.content_revision,
                    VolumeProcessingFact.expected_required_manifest_revision
                    != LibraryVolume.required_manifest_revision,
                ),
            )
            .order_by(LibraryVolume.id)
            .limit(limit + 1)
            .with_for_update()
        )
        if after_volume_id is not None:
            statement = statement.where(LibraryVolume.id > after_volume_id)
        # SQLAlchemy types an outer-joined entity as non-optional even though
        # the runtime row correctly contains ``None`` when no processing fact
        # exists.
        return cast(
            tuple[tuple[LibraryVolume, str, VolumeProcessingFact | None], ...],
            tuple(self._session.execute(statement)),
        )


__all__ = [
    "SqlAlchemyContentTopologyActivationRepository",
    "SqlAlchemyContentTopologyProjectionRepository",
]
