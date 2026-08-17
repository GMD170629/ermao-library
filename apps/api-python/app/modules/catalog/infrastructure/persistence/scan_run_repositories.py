"""SQLAlchemy repositories for full-scan run and root-work lifecycles."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import and_, case, delete, exists, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.scan_dto import (
    FullScanRun,
    FullScanWorkItem,
    ScanFence,
    ScanLibrarySnapshot,
    WriterReservation,
)
from app.modules.catalog.application.scan_dto import (
    ScanFailureCode as ApplicationScanFailureCode,
)
from app.modules.catalog.domain.library import (
    LibraryControlState as DomainControlState,
)
from app.modules.catalog.domain.library import LibraryHealth as DomainHealth
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.scan import (
    ScanStage as DomainScanStage,
)
from app.modules.catalog.domain.scan import (
    ScanState as DomainScanState,
)

from .enums import (
    LibraryControlState,
    LibraryHealth,
    ScanStage,
    ScanState,
)
from .enums import (
    ScanFailureCode as StoredScanFailureCode,
)
from .models import (
    CatalogLibrary,
    LibraryIgnoreRule,
    LibraryScanRun,
    LibraryScanWorkItem,
)
from .repositories import ignore_rule_from_row
from .scan_fencing import (
    ACTIVE_LIBRARY_STATES as _ACTIVE_LIBRARY_STATES,
)
from .scan_fencing import (
    ACTIVE_SCAN_STATES as _ACTIVE_SCAN_STATES,
)
from .scan_fencing import (
    enum_value as _enum_value,
)
from .scan_fencing import (
    guard_mutation as _guard_mutation,
)
from .scan_fencing import (
    library_fence_conditions as _library_fence_conditions,
)
from .scan_fencing import (
    library_fence_exists as _library_fence_exists,
)
from .scan_fencing import (
    require_live_fence as _require_live_fence,
)
from .scan_fencing import (
    scan_fence_conditions as _scan_fence_conditions,
)


def _scan_row(
    session: Session, library_id: str, scan_id: str
) -> tuple[LibraryScanRun, CatalogLibrary] | None:
    row = session.execute(
        select(LibraryScanRun, CatalogLibrary)
        .join(CatalogLibrary, CatalogLibrary.id == LibraryScanRun.library_id)
        .where(
            LibraryScanRun.library_id == library_id,
            LibraryScanRun.id == scan_id,
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def _full_scan_from_rows(run: LibraryScanRun, library: CatalogLibrary) -> FullScanRun:
    return FullScanRun(
        scan_id=run.id,
        library_id=run.library_id,
        canonical_root=run.root_path_snapshot,
        generation=run.generation,
        config_revision=run.config_revision,
        organization_mode=OrganizationMode(_enum_value(run.mode_snapshot)),
        topology_version=run.topology_version_snapshot,
        path_comparison=PathComparison(_enum_value(run.path_comparison_snapshot)),
        root_identity=run.root_identity_snapshot,
        topology_writer_fence=run.topology_writer_fence,
        state=DomainScanState(_enum_value(run.state)),
        stage=DomainScanStage(_enum_value(run.stage)),
        lease_owner=run.lease_owner,
        lease_expires_at=run.lease_expires_at,
        heartbeat_at=run.heartbeat_at,
        discovered_count=run.discovered_count,
        diagnostic_count=run.diagnostic_count,
        failure_code=(
            None
            if run.failure_code is None
            else ApplicationScanFailureCode(_enum_value(run.failure_code))
        ),
        created_by_actor_id=run.created_by_user_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _updated_scan(
    session: Session, library_id: str, scan_id: str
) -> FullScanRun | None:
    row = _scan_row(session, library_id, scan_id)
    return None if row is None else _full_scan_from_rows(*row)


def _scan_fence_exists(
    fence: ScanFence,
    *,
    states: tuple[ScanState, ...] = _ACTIVE_SCAN_STATES,
) -> ColumnElement[bool]:
    return exists(
        select(LibraryScanRun.id).where(
            *_scan_fence_conditions(fence, states=states),
            _library_fence_exists(fence),
        )
    )


def _work_item_from_row(row: LibraryScanWorkItem) -> FullScanWorkItem:
    if row.scope_relative_path:
        raise RuntimeError("full scan work item is not root-scoped")
    return FullScanWorkItem(
        work_item_id=row.id,
        library_id=row.library_id,
        scan_id=row.scan_run_id,
        root_path_snapshot=row.root_path_snapshot,
        scope_relative_path=(),
        state=DomainScanState(_enum_value(row.state)),
        stage=DomainScanStage(_enum_value(row.stage)),
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        attempt=row.attempt,
        available_at=row.available_at,
        idempotency_key=row.idempotency_key,
        discovered_count=row.discovered_count,
    )


class SqlAlchemyScanLibraryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_scan_for_update(self, library_id: str) -> ScanLibrarySnapshot | None:
        library = self._session.scalar(
            select(CatalogLibrary)
            .where(CatalogLibrary.id == library_id)
            .with_for_update()
        )
        if library is None:
            return None
        rules = self._session.scalars(
            select(LibraryIgnoreRule)
            .where(LibraryIgnoreRule.library_id == library_id)
            .order_by(LibraryIgnoreRule.rule_key)
        ).all()
        return ScanLibrarySnapshot(
            library_id=library.id,
            canonical_root=library.root_path,
            organization_mode=OrganizationMode(_enum_value(library.organization_mode)),
            topology_version=library.topology_version,
            path_comparison=PathComparison(_enum_value(library.path_comparison)),
            control_state=DomainControlState(_enum_value(library.control_state)),
            observed_health=DomainHealth(_enum_value(library.observed_health)),
            config_revision=library.config_revision,
            topology_writer_fence=library.topology_writer_fence,
            next_scan_generation=library.next_scan_generation,
            last_successful_generation=library.last_successful_generation,
            ignore_rules=tuple(ignore_rule_from_row(rule) for rule in rules),
        )

    def reserve_topology_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
        expected_next_generation: int,
    ) -> WriterReservation | None:
        result = self._session.execute(
            update(CatalogLibrary)
            .where(
                CatalogLibrary.id == library_id,
                CatalogLibrary.topology_writer_fence == expected_topology_writer_fence,
                CatalogLibrary.next_scan_generation == expected_next_generation,
                CatalogLibrary.control_state.in_(_ACTIVE_LIBRARY_STATES),
            )
            .values(
                topology_writer_fence=expected_topology_writer_fence + 1,
                next_scan_generation=expected_next_generation + 1,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return WriterReservation(
            generation=expected_next_generation,
            topology_writer_fence=expected_topology_writer_fence + 1,
        )

    def take_over_topology_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
    ) -> int | None:
        next_fence = expected_topology_writer_fence + 1
        result = self._session.execute(
            update(CatalogLibrary)
            .where(
                CatalogLibrary.id == library_id,
                CatalogLibrary.topology_writer_fence == expected_topology_writer_fence,
                CatalogLibrary.control_state.in_(_ACTIVE_LIBRARY_STATES),
            )
            .values(topology_writer_fence=next_fence)
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return next_fence

    def finalize_generation(self, fence: ScanFence, *, completed_at: datetime) -> bool:
        _require_live_fence(self._session, fence, now=completed_at)
        result = self._session.execute(
            update(CatalogLibrary)
            .where(*_library_fence_conditions(fence))
            .values(
                last_successful_generation=fence.generation,
                last_successful_scan_at=completed_at,
                observed_health=LibraryHealth.HEALTHY,
                control_state=case(
                    (
                        CatalogLibrary.control_state == LibraryControlState.ACTIVATING,
                        LibraryControlState.ACTIVE,
                    ),
                    else_=CatalogLibrary.control_state,
                ),
                updated_at=completed_at,
            )
        )
        return cast(CursorResult[object], result).rowcount == 1

    def set_health_if_fence(
        self,
        fence: ScanFence,
        *,
        health: DomainHealth,
        observed_at: datetime,
    ) -> bool:
        _require_live_fence(self._session, fence, now=observed_at)
        result = self._session.execute(
            update(CatalogLibrary)
            .where(*_library_fence_conditions(fence))
            .values(
                observed_health=LibraryHealth(health),
                updated_at=observed_at,
            )
        )
        return cast(CursorResult[object], result).rowcount == 1


class SqlAlchemyFullScanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active_for_update(self, library_id: str) -> FullScanRun | None:
        row = self._session.execute(
            select(LibraryScanRun, CatalogLibrary)
            .join(CatalogLibrary, CatalogLibrary.id == LibraryScanRun.library_id)
            .where(
                LibraryScanRun.library_id == library_id,
                LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
            )
            .with_for_update()
        ).one_or_none()
        return None if row is None else _full_scan_from_rows(*row)

    def get_for_update(self, library_id: str, scan_id: str) -> FullScanRun | None:
        row = self._session.execute(
            select(LibraryScanRun, CatalogLibrary)
            .join(CatalogLibrary, CatalogLibrary.id == LibraryScanRun.library_id)
            .where(
                LibraryScanRun.library_id == library_id,
                LibraryScanRun.id == scan_id,
            )
            .with_for_update()
        ).one_or_none()
        return None if row is None else _full_scan_from_rows(*row)

    def insert(self, run: FullScanRun) -> None:
        if run.created_by_actor_id is None:
            raise ValueError("a new full scan requires a creator")
        self._session.add(
            LibraryScanRun(
                id=run.scan_id,
                library_id=run.library_id,
                generation=run.generation,
                config_revision=run.config_revision,
                mode_snapshot=OrganizationMode(run.organization_mode),
                root_path_snapshot=run.canonical_root,
                path_comparison_snapshot=PathComparison(run.path_comparison),
                topology_version_snapshot=run.topology_version,
                root_identity_snapshot=run.root_identity,
                topology_writer_fence=run.topology_writer_fence,
                state=ScanState(run.state),
                failure_code=(
                    None
                    if run.failure_code is None
                    else StoredScanFailureCode(run.failure_code.value)
                ),
                lease_owner=run.lease_owner,
                lease_expires_at=run.lease_expires_at,
                heartbeat_at=run.heartbeat_at,
                stage=ScanStage(run.stage),
                discovered_count=run.discovered_count,
                diagnostic_count=run.diagnostic_count,
                started_at=run.started_at,
                finished_at=run.finished_at,
                created_by_user_id=run.created_by_actor_id,
            )
        )
        self._session.flush()

    def start_running(
        self,
        fence: ScanFence,
        *,
        root_identity: str,
        started_at: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence, states=(ScanState.PENDING,)),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > started_at,
                _library_fence_exists(fence),
            )
            .values(
                root_identity_snapshot=root_identity,
                state=ScanState.RUNNING,
                started_at=started_at,
                heartbeat_at=started_at,
                lease_expires_at=lease_expires_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def take_over_expired(
        self,
        fence: ScanFence,
        *,
        new_owner_token: str,
        new_topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        library_matches_new_fence = exists(
            select(CatalogLibrary.id).where(
                CatalogLibrary.id == fence.library_id,
                CatalogLibrary.config_revision == fence.config_revision,
                CatalogLibrary.root_path == fence.root_path_snapshot,
                CatalogLibrary.organization_mode
                == OrganizationMode(fence.organization_mode),
                CatalogLibrary.topology_version == fence.topology_version,
                CatalogLibrary.path_comparison == PathComparison(fence.path_comparison),
                CatalogLibrary.topology_writer_fence == new_topology_writer_fence,
                CatalogLibrary.control_state.in_(_ACTIVE_LIBRARY_STATES),
            )
        )
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at <= now,
                library_matches_new_fence,
            )
            .values(
                lease_owner=new_owner_token,
                topology_writer_fence=new_topology_writer_fence,
                stage=case(
                    (
                        LibraryScanRun.state == ScanState.FINALIZING,
                        LibraryScanRun.stage,
                    ),
                    else_=ScanStage.DISCOVER,
                ),
                discovered_count=case(
                    (
                        LibraryScanRun.state == ScanState.FINALIZING,
                        LibraryScanRun.discovered_count,
                    ),
                    else_=0,
                ),
                diagnostic_count=case(
                    (
                        LibraryScanRun.state == ScanState.FINALIZING,
                        LibraryScanRun.diagnostic_count,
                    ),
                    else_=0,
                ),
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def guard_mutation(self, fence: ScanFence, *, now: datetime) -> bool:
        return _guard_mutation(self._session, fence, now=now)

    def heartbeat(
        self,
        fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int = 0,
        diagnostic_increment: int = 0,
    ) -> FullScanRun | None:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > now,
                _library_fence_exists(fence),
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                discovered_count=LibraryScanRun.discovered_count + discovered_increment,
                diagnostic_count=LibraryScanRun.diagnostic_count + diagnostic_increment,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def set_stage(
        self,
        fence: ScanFence,
        *,
        expected_stage: DomainScanStage,
        next_stage: DomainScanStage,
        now: datetime,
    ) -> bool:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence, states=(ScanState.RUNNING,)),
                LibraryScanRun.stage == ScanStage(expected_stage),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > now,
                _library_fence_exists(fence),
            )
            .values(stage=ScanStage(next_stage), heartbeat_at=now)
        )
        return cast(CursorResult[object], result).rowcount == 1

    def begin_finalizing(
        self,
        fence: ScanFence,
        *,
        expected_stage: DomainScanStage,
        now: datetime,
    ) -> FullScanRun | None:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence, states=(ScanState.RUNNING,)),
                LibraryScanRun.stage == ScanStage(expected_stage),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > now,
                _library_fence_exists(fence),
            )
            .values(
                state=ScanState.FINALIZING,
                stage=ScanStage.FINALIZE,
                heartbeat_at=now,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def complete(
        self, fence: ScanFence, *, completed_at: datetime
    ) -> FullScanRun | None:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence, states=(ScanState.FINALIZING,)),
                LibraryScanRun.stage == ScanStage.FINALIZE,
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > completed_at,
                _library_fence_exists(fence),
            )
            .values(
                state=ScanState.COMPLETED,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=completed_at,
                finished_at=completed_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def fail(
        self,
        fence: ScanFence,
        *,
        failure_code: ApplicationScanFailureCode,
        failed_at: datetime,
    ) -> FullScanRun | None:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > failed_at,
                _library_fence_exists(fence),
            )
            .values(
                state=ScanState.FAILED,
                failure_code=StoredScanFailureCode(failure_code.value),
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=failed_at,
                finished_at=failed_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def restart_from_root(
        self,
        fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanRun | None:
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                *_scan_fence_conditions(fence, states=(ScanState.RUNNING,)),
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > now,
                _library_fence_exists(fence),
            )
            .values(
                stage=ScanStage.DISCOVER,
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                discovered_count=0,
                diagnostic_count=0,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, fence.library_id, fence.scan_id)

    def cancel_invalidated(
        self,
        run: FullScanRun,
        *,
        current_library: ScanLibrarySnapshot,
        cancelled_at: datetime,
    ) -> FullScanRun | None:
        last_successful_generation_matches = (
            CatalogLibrary.last_successful_generation.is_(None)
            if current_library.last_successful_generation is None
            else CatalogLibrary.last_successful_generation
            == current_library.last_successful_generation
        )
        current_library_matches = exists(
            select(CatalogLibrary.id).where(
                CatalogLibrary.id == current_library.library_id,
                CatalogLibrary.root_path == current_library.canonical_root,
                CatalogLibrary.config_revision == current_library.config_revision,
                CatalogLibrary.organization_mode
                == OrganizationMode(current_library.organization_mode),
                CatalogLibrary.topology_version == current_library.topology_version,
                CatalogLibrary.path_comparison
                == PathComparison(current_library.path_comparison),
                CatalogLibrary.topology_writer_fence
                == current_library.topology_writer_fence,
                CatalogLibrary.control_state
                == LibraryControlState(current_library.control_state),
                CatalogLibrary.observed_health
                == LibraryHealth(current_library.observed_health),
                CatalogLibrary.next_scan_generation
                == current_library.next_scan_generation,
                last_successful_generation_matches,
                or_(
                    CatalogLibrary.root_path != run.canonical_root,
                    CatalogLibrary.config_revision != run.config_revision,
                    CatalogLibrary.organization_mode
                    != OrganizationMode(run.organization_mode),
                    CatalogLibrary.topology_version != run.topology_version,
                    CatalogLibrary.path_comparison
                    != PathComparison(run.path_comparison),
                    CatalogLibrary.topology_writer_fence != run.topology_writer_fence,
                    CatalogLibrary.control_state.not_in(_ACTIVE_LIBRARY_STATES),
                ),
            )
        )
        root_condition = (
            LibraryScanRun.root_identity_snapshot.is_(None)
            if run.root_identity is None
            else LibraryScanRun.root_identity_snapshot == run.root_identity
        )
        result = self._session.execute(
            update(LibraryScanRun)
            .where(
                LibraryScanRun.id == run.scan_id,
                LibraryScanRun.library_id == run.library_id,
                LibraryScanRun.generation == run.generation,
                LibraryScanRun.root_path_snapshot == run.canonical_root,
                LibraryScanRun.config_revision == run.config_revision,
                LibraryScanRun.mode_snapshot == OrganizationMode(run.organization_mode),
                LibraryScanRun.topology_version_snapshot == run.topology_version,
                LibraryScanRun.path_comparison_snapshot
                == PathComparison(run.path_comparison),
                LibraryScanRun.topology_writer_fence == run.topology_writer_fence,
                LibraryScanRun.lease_owner == run.lease_owner,
                root_condition,
                LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
                current_library_matches,
            )
            .values(
                state=ScanState.CANCELLED,
                failure_code=None,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=cancelled_at,
                finished_at=cancelled_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, run.library_id, run.scan_id)

    def cancel(
        self,
        run: FullScanRun,
        *,
        cancelled_at: datetime,
        next_topology_writer_fence: int,
    ) -> FullScanRun | None:
        fence = run.fence()
        library_matches_new_fence = exists(
            select(CatalogLibrary.id).where(
                CatalogLibrary.id == run.library_id,
                CatalogLibrary.root_path == run.canonical_root,
                CatalogLibrary.config_revision == run.config_revision,
                CatalogLibrary.organization_mode
                == OrganizationMode(run.organization_mode),
                CatalogLibrary.topology_version == run.topology_version,
                CatalogLibrary.path_comparison == PathComparison(run.path_comparison),
                CatalogLibrary.topology_writer_fence == next_topology_writer_fence,
                CatalogLibrary.control_state.in_(_ACTIVE_LIBRARY_STATES),
            )
        )
        result = self._session.execute(
            update(LibraryScanRun)
            .where(*_scan_fence_conditions(fence), library_matches_new_fence)
            .values(
                state=ScanState.CANCELLED,
                topology_writer_fence=next_topology_writer_fence,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=cancelled_at,
                finished_at=cancelled_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        return _updated_scan(self._session, run.library_id, run.scan_id)


class SqlAlchemyRootScanWorkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_root(self, work_item: FullScanWorkItem) -> None:
        self._session.add(
            LibraryScanWorkItem(
                id=work_item.work_item_id,
                library_id=work_item.library_id,
                scan_run_id=work_item.scan_id,
                root_path_snapshot=work_item.root_path_snapshot,
                subtree_root_entry_id=None,
                scope_relative_path="",
                state=ScanState(work_item.state),
                stage=ScanStage(work_item.stage),
                lease_owner=work_item.lease_owner,
                lease_expires_at=work_item.lease_expires_at,
                attempt=work_item.attempt,
                available_at=work_item.available_at,
                idempotency_key=work_item.idempotency_key,
                discovered_count=work_item.discovered_count,
            )
        )
        self._session.flush()

    def get_root_for_update(
        self, library_id: str, scan_id: str
    ) -> FullScanWorkItem | None:
        row = self._session.scalar(
            select(LibraryScanWorkItem)
            .where(
                LibraryScanWorkItem.library_id == library_id,
                LibraryScanWorkItem.scan_run_id == scan_id,
                LibraryScanWorkItem.scope_relative_path == "",
            )
            .with_for_update()
        )
        return None if row is None else _work_item_from_row(row)

    def claim_pending_root(
        self,
        fence: ScanFence,
        *,
        work_item_id: str,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> FullScanWorkItem | None:
        if owner_token != fence.lease_owner:
            return None
        _require_live_fence(self._session, fence, now=now)
        result = self._session.execute(
            update(LibraryScanWorkItem)
            .where(
                LibraryScanWorkItem.id == work_item_id,
                LibraryScanWorkItem.library_id == fence.library_id,
                LibraryScanWorkItem.scan_run_id == fence.scan_id,
                LibraryScanWorkItem.root_path_snapshot == fence.root_path_snapshot,
                LibraryScanWorkItem.scope_relative_path == "",
                LibraryScanWorkItem.state == ScanState.PENDING,
                LibraryScanWorkItem.available_at <= now,
                LibraryScanWorkItem.lease_owner.is_(None),
                _scan_fence_exists(fence),
            )
            .values(
                state=ScanState.RUNNING,
                stage=ScanStage.DISCOVER,
                lease_owner=owner_token,
                lease_expires_at=lease_expires_at,
                attempt=LibraryScanWorkItem.attempt + 1,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        row = self._session.get(LibraryScanWorkItem, work_item_id)
        return None if row is None else _work_item_from_row(row)

    def take_over_expired_root(
        self,
        fence: ScanFence,
        *,
        new_owner_token: str,
        new_topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
        restart_from_root: bool,
    ) -> FullScanWorkItem | None:
        root_condition = (
            LibraryScanRun.root_identity_snapshot.is_(None)
            if fence.root_identity is None
            else LibraryScanRun.root_identity_snapshot == fence.root_identity
        )
        library_matches = exists(
            select(CatalogLibrary.id).where(
                CatalogLibrary.id == fence.library_id,
                CatalogLibrary.config_revision == fence.config_revision,
                CatalogLibrary.root_path == fence.root_path_snapshot,
                CatalogLibrary.organization_mode
                == OrganizationMode(fence.organization_mode),
                CatalogLibrary.topology_version == fence.topology_version,
                CatalogLibrary.path_comparison == PathComparison(fence.path_comparison),
                CatalogLibrary.topology_writer_fence == new_topology_writer_fence,
                CatalogLibrary.control_state.in_(_ACTIVE_LIBRARY_STATES),
            )
        )
        run_matches = exists(
            select(LibraryScanRun.id).where(
                LibraryScanRun.id == fence.scan_id,
                LibraryScanRun.library_id == fence.library_id,
                LibraryScanRun.generation == fence.generation,
                LibraryScanRun.config_revision == fence.config_revision,
                LibraryScanRun.root_path_snapshot == fence.root_path_snapshot,
                LibraryScanRun.mode_snapshot
                == OrganizationMode(fence.organization_mode),
                LibraryScanRun.topology_version_snapshot == fence.topology_version,
                LibraryScanRun.path_comparison_snapshot
                == PathComparison(fence.path_comparison),
                root_condition,
                LibraryScanRun.topology_writer_fence == new_topology_writer_fence,
                LibraryScanRun.lease_owner == new_owner_token,
                LibraryScanRun.lease_expires_at.is_not(None),
                LibraryScanRun.lease_expires_at > now,
                LibraryScanRun.state.in_(_ACTIVE_SCAN_STATES),
                library_matches,
            )
        )
        result = self._session.execute(
            update(LibraryScanWorkItem)
            .where(
                LibraryScanWorkItem.library_id == fence.library_id,
                LibraryScanWorkItem.scan_run_id == fence.scan_id,
                LibraryScanWorkItem.root_path_snapshot == fence.root_path_snapshot,
                LibraryScanWorkItem.scope_relative_path == "",
                or_(
                    and_(
                        LibraryScanWorkItem.state == ScanState.PENDING,
                        LibraryScanWorkItem.lease_owner.is_(None),
                    ),
                    and_(
                        LibraryScanWorkItem.state == ScanState.RUNNING,
                        LibraryScanWorkItem.lease_owner == fence.lease_owner,
                        LibraryScanWorkItem.lease_expires_at.is_not(None),
                        LibraryScanWorkItem.lease_expires_at <= now,
                    ),
                ),
                run_matches,
            )
            .values(
                state=ScanState.RUNNING,
                stage=(
                    ScanStage.DISCOVER
                    if restart_from_root
                    else LibraryScanWorkItem.stage
                ),
                lease_owner=new_owner_token,
                lease_expires_at=lease_expires_at,
                attempt=LibraryScanWorkItem.attempt + 1,
                discovered_count=(
                    0 if restart_from_root else LibraryScanWorkItem.discovered_count
                ),
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            return None
        row = self._session.scalar(
            select(LibraryScanWorkItem).where(
                LibraryScanWorkItem.library_id == fence.library_id,
                LibraryScanWorkItem.scan_run_id == fence.scan_id,
                LibraryScanWorkItem.root_path_snapshot == fence.root_path_snapshot,
                LibraryScanWorkItem.scope_relative_path == "",
            )
        )
        return None if row is None else _work_item_from_row(row)

    def heartbeat_root(
        self,
        fence: ScanFence,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int,
    ) -> bool:
        _require_live_fence(self._session, fence, now=now)
        result = self._session.execute(
            update(LibraryScanWorkItem)
            .where(
                LibraryScanWorkItem.library_id == fence.library_id,
                LibraryScanWorkItem.scan_run_id == fence.scan_id,
                LibraryScanWorkItem.root_path_snapshot == fence.root_path_snapshot,
                LibraryScanWorkItem.scope_relative_path == "",
                LibraryScanWorkItem.state == ScanState.RUNNING,
                LibraryScanWorkItem.lease_owner == fence.lease_owner,
                LibraryScanWorkItem.lease_expires_at.is_not(None),
                LibraryScanWorkItem.lease_expires_at > now,
                _scan_fence_exists(fence),
            )
            .values(
                lease_expires_at=lease_expires_at,
                discovered_count=LibraryScanWorkItem.discovered_count
                + discovered_increment,
            )
        )
        return cast(CursorResult[object], result).rowcount == 1

    def set_stage(
        self,
        fence: ScanFence,
        *,
        expected_stage: DomainScanStage,
        next_stage: DomainScanStage,
    ) -> bool:
        result = self._session.execute(
            update(LibraryScanWorkItem)
            .where(
                LibraryScanWorkItem.library_id == fence.library_id,
                LibraryScanWorkItem.scan_run_id == fence.scan_id,
                LibraryScanWorkItem.scope_relative_path == "",
                LibraryScanWorkItem.state == ScanState.RUNNING,
                LibraryScanWorkItem.stage == ScanStage(expected_stage),
                LibraryScanWorkItem.lease_owner == fence.lease_owner,
                _scan_fence_exists(fence),
            )
            .values(stage=ScanStage(next_stage))
        )
        return cast(CursorResult[object], result).rowcount == 1

    def delete_for_terminal(self, library_id: str, scan_id: str) -> bool:
        terminal_run = exists(
            select(LibraryScanRun.id).where(
                LibraryScanRun.id == scan_id,
                LibraryScanRun.library_id == library_id,
                LibraryScanRun.state.in_(
                    (ScanState.COMPLETED, ScanState.FAILED, ScanState.CANCELLED)
                ),
            )
        )
        result = self._session.execute(
            delete(LibraryScanWorkItem).where(
                LibraryScanWorkItem.library_id == library_id,
                LibraryScanWorkItem.scan_run_id == scan_id,
                LibraryScanWorkItem.scope_relative_path == "",
                terminal_run,
            )
        )
        return cast(CursorResult[object], result).rowcount == 1


__all__ = [
    "SqlAlchemyFullScanRepository",
    "SqlAlchemyRootScanWorkRepository",
    "SqlAlchemyScanLibraryRepository",
]
