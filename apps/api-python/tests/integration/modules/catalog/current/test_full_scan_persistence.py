from __future__ import annotations

import json
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.ports import AuditEvent, OutboxEvent
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    FullScanRun,
    FullScanWorkItem,
    PathCollision,
    SourceObservation,
    SourcePathBinding,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)
from app.modules.catalog.application.watcher_dto import (
    BoundTopologyStageBatch,
    BoundTopologyUnitPlan,
    required_topology_source_paths,
)
from app.modules.catalog.domain.admission import (
    AudioCodec,
    AudioEvidence,
    DirectFileEvidence,
    SourceAdmissionEvidence,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    SourceKind,
)
from app.modules.catalog.domain.scan import (
    AssetMembershipPlan,
    ReadingMorphology,
    ScanConflict,
    TopologyStageBatch,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
    iter_stage_batches,
)
from app.modules.catalog.domain.scan import (
    AssetRole as DomainAssetRole,
)
from app.modules.catalog.domain.scan import (
    ScanStage as DomainScanStage,
)
from app.modules.catalog.domain.scan import (
    ScanState as DomainScanState,
)
from app.modules.catalog.domain.scan import (
    TopologyUnitKind as DomainTopologyUnitKind,
)
from app.modules.catalog.domain.scan import (
    VersionKind as DomainVersionKind,
)
from app.modules.catalog.infrastructure.persistence import (
    AdministrativeAuditEvent,
    AssetValidationState,
    CatalogLibrary,
    CatalogOutbox,
    GrantLevel,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibraryScanRun,
    LibraryScanWorkItem,
    LibrarySourceEntry,
    LibraryVolume,
    LibraryWatcherState,
    PathCollisionObservation,
    RevisionState,
    ScanState,
    SlotState,
    SourceEntryType,
    SqlAlchemyScanUnitOfWork,
    SqlAlchemyScanUowFactory,
    TopologyUnit,
    TopologyUnitRevision,
    UserLibraryGrant,
    VolumeAsset,
    WritePolicy,
)


class _SqliteBusyError(Exception):
    sqlite_errorcode = 5


class _CleanupTrackingSession(Session):
    rollback_called = False
    close_called = False

    def rollback(self) -> None:
        _CleanupTrackingSession.rollback_called = True
        super().rollback()

    def close(self) -> None:
        _CleanupTrackingSession.close_called = True
        super().close()


def _raise_busy(
    _connection: object,
    _cursor: object,
    _statement: str,
    _parameters: object,
    _context: object,
    _executemany: bool,
) -> NoReturn:
    raise OperationalError(
        None,
        None,
        _SqliteBusyError("database is locked"),
    )


@pytest.fixture
def persistence(tmp_path: Path):
    database_path = tmp_path / "full-scan.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(CurrentUser(id="admin", display_name="Admin", role="admin"))
    try:
        yield engine, factory
    finally:
        engine.dispose()


def _seed_library(
    factory: sessionmaker[Session],
    *,
    comparison: PathComparison = PathComparison.SENSITIVE,
) -> None:
    with factory.begin() as session:
        session.add_all(
            (
                CatalogLibrary(
                    id="library",
                    name="Library",
                    root_path="/srv/library",
                    root_path_key="/srv/library",
                    organization_mode=OrganizationMode.FLAT,
                    topology_version=1,
                    path_comparison=comparison,
                    write_policy=WritePolicy.READ_ONLY,
                    control_state=LibraryControlState.ACTIVE,
                    observed_health=LibraryHealth.UNKNOWN,
                    config_revision=1,
                    topology_writer_fence=1,
                    next_scan_generation=2,
                ),
                UserLibraryGrant(
                    user_id="admin",
                    library_id="library",
                    level=GrantLevel.ADMIN,
                    scope_epoch=1,
                ),
                LibraryWatcherState(
                    library_id="library",
                    latest_sequence=0,
                    overflow_through_sequence=None,
                    full_rescan_reason=None,
                    updated_at=datetime.now(UTC),
                ),
            )
        )


def _pending_run(now: datetime) -> FullScanRun:
    return FullScanRun(
        scan_id="scan",
        library_id="library",
        canonical_root="/srv/library",
        generation=1,
        config_revision=1,
        organization_mode=OrganizationMode.FLAT,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        root_identity=None,
        topology_writer_fence=1,
        state=DomainScanState.PENDING,
        failure_code=None,
        stage=DomainScanStage.DISCOVER,
        lease_owner="worker",
        lease_expires_at=now + timedelta(minutes=5),
        heartbeat_at=now,
        discovered_count=0,
        diagnostic_count=0,
        created_by_actor_id="admin",
        started_at=None,
        finished_at=None,
        watcher_sequence_watermark=0,
    )


def _root_work(now: datetime) -> FullScanWorkItem:
    return FullScanWorkItem(
        work_item_id="root-work",
        library_id="library",
        scan_id="scan",
        root_path_snapshot="/srv/library",
        scope_relative_path=(),
        state=DomainScanState.PENDING,
        stage=DomainScanStage.DISCOVER,
        lease_owner=None,
        lease_expires_at=None,
        attempt=0,
        available_at=now,
        idempotency_key="library:1:root",
        discovered_count=0,
    )


def _insert_pending_scan(factory: sessionmaker[Session], now: datetime) -> None:
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.scans.insert(_pending_run(now))
        uow.work_items.insert_root(_root_work(now))
        uow.commit()


def _bind_running_scan(factory: sessionmaker[Session], now: datetime) -> FullScanRun:
    with SqlAlchemyScanUowFactory(factory)() as uow:
        pending = uow.scans.get_for_update("library", "scan")
        assert pending is not None
        assert uow.sources.bind_synthetic_root(
            pending.fence(),
            observed_identity="dev:root",
            observed_at=now,
        )
        running = uow.scans.start_running(
            pending.fence(),
            root_identity="dev:root",
            started_at=now,
            lease_expires_at=now + timedelta(minutes=5),
        )
        assert running is not None
        uow.commit()
        return running


def _file_observation(
    path: tuple[str, ...],
    *,
    generation: int = 1,
    source_format: SourceFormat = SourceFormat.PDF,
    identity: str | None = None,
) -> SourceObservation:
    stat = SourceStatExpectation(1, abs(hash(path)) % 1_000_000, 128, 1)
    if source_format is SourceFormat.MP3:
        evidence = AudioEvidence(
            source_format,
            AudioCodec.MPEG_LAYER_III,
            4,
            64,
        )
        admission_kind = AdmissionKind.AUDIO_TRACK
    else:
        evidence = DirectFileEvidence(source_format, 4, 64)
        admission_kind = AdmissionKind.PRIMARY
    admission = SourceAdmissionEvidence(
        path,
        EntryType.FILE,
        admission_kind,
        source_format=source_format,
        evidence=evidence,
    )
    return SourceObservation(
        DiscoveredSource(
            path,
            DiscoveryEntryType.FILE,
            identity or f"dev:{stat.file_id}",
            stat,
        ),
        generation,
        admission,
    )


def _directory_observation(
    path: tuple[str, ...], *, generation: int = 1
) -> SourceObservation:
    return SourceObservation(
        DiscoveredSource(
            path,
            DiscoveryEntryType.DIRECTORY,
            f"dev:dir:{'/'.join(path)}",
            None,
        ),
        generation,
        None,
    )


def test_scan_uow_rollback_and_audit_outbox_are_atomic(persistence) -> None:
    _engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)

    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.scans.insert(_pending_run(now))
        uow.work_items.insert_root(_root_work(now))
        uow.audit.append(AuditEvent("SCAN_STARTED", "admin", "library"))
        uow.outbox.append(OutboxEvent("SCAN_STARTED", "library", "admin"))

    with factory() as session:
        assert session.get(LibraryScanRun, "scan") is None
        assert session.get(LibraryScanWorkItem, "root-work") is None
        assert (
            session.scalar(select(func.count()).select_from(AdministrativeAuditEvent))
            == 0
        )
        assert session.scalar(select(func.count()).select_from(CatalogOutbox)) == 0

    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.scans.insert(_pending_run(now))
        uow.work_items.insert_root(_root_work(now))
        uow.audit.append(AuditEvent("SCAN_STARTED", "admin", "library"))
        uow.outbox.append(OutboxEvent("SCAN_STARTED", "library", "admin"))
        uow.commit()

    with factory() as session:
        work = session.get(LibraryScanWorkItem, "root-work")
        assert work is not None
        assert work.root_path_snapshot == "/srv/library"
        assert (
            session.scalar(select(func.count()).select_from(AdministrativeAuditEvent))
            == 1
        )
        assert session.scalar(select(func.count()).select_from(CatalogOutbox)) == 1


def test_root_binding_never_overwrites_persisted_identity(persistence) -> None:
    _engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    running = _bind_running_scan(factory, now)

    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert not uow.sources.bind_synthetic_root(
            running.fence(),
            observed_identity="dev:replacement",
            observed_at=now + timedelta(seconds=1),
        )
        uow.commit()

    with factory() as session:
        root = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT
            )
        )
        assert root is not None
        assert root.filesystem_identity == "dev:root"


def test_deleted_scan_creator_does_not_break_load_or_finalize(persistence) -> None:
    _engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    running = _bind_running_scan(factory, now)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert uow.scans.set_stage(
            running.fence(),
            expected_stage=DomainScanStage.DISCOVER,
            next_stage=DomainScanStage.RECONCILE,
            now=now,
        )
        finalizing = uow.scans.begin_finalizing(
            running.fence(),
            expected_stage=DomainScanStage.RECONCILE,
            now=now,
        )
        assert finalizing is not None
        uow.commit()
    with factory.begin() as session:
        creator = session.get(CurrentUser, "admin")
        assert creator is not None
        session.delete(creator)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        loaded = uow.scans.get_for_update("library", "scan")
        assert loaded is not None and loaded.created_by_actor_id is None
        assert uow.libraries.finalize_generation(loaded.fence(), completed_at=now)
        uow.commit()


def test_source_batch_preserves_names_collisions_presence_and_query_budget(
    persistence,
) -> None:
    engine, factory = persistence
    _seed_library(factory, comparison=PathComparison.INSENSITIVE)
    now = datetime.now(UTC)
    run = replace(_pending_run(now), path_comparison=PathComparison.INSENSITIVE)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.scans.insert(run)
        uow.work_items.insert_root(_root_work(now))
        uow.commit()
    running = _bind_running_scan(factory, now)
    assert running.path_comparison is PathComparison.INSENSITIVE
    nfd_name = unicodedata.normalize("NFD", "Café.pdf")
    observations = (
        _directory_observation(("Shelf",)),
        _file_observation(("Shelf", "Book.pdf")),
        _file_observation(("Shelf", "book.pdf")),
        _file_observation(("Shelf", nfd_name)),
        _file_observation(("Shelf", "Café.pdf")),
        _file_observation(("Shelf", "seen.pdf")),
        _file_observation(("Shelf", "unseen.pdf")),
        _directory_observation(("Folder",)),
        _directory_observation(("folder",)),
        _file_observation(("Folder", "left.pdf")),
        _file_observation(("folder", "right.pdf")),
        *tuple(_file_observation((f"unique-{index}.pdf",)) for index in range(500)),
    )
    statement_count = 0

    def count_statement(
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with SqlAlchemyScanUowFactory(factory)() as uow:
            outcome = uow.sources.upsert_observations(
                running.fence(), observations, observed_at=now
            )
            uow.collisions.record(running.fence(), outcome.collisions, observed_at=now)
            uow.commit()
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_count < 40
    assert len(outcome.collisions) == 3
    with factory() as session:
        colliding = tuple(
            session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.slot_state == SlotState.COLLIDING,
                    LibrarySourceEntry.entry_type == SourceEntryType.FILE,
                )
            )
        )
        assert {entry.local_name for entry in colliding} == {
            "Book.pdf",
            "book.pdf",
            nfd_name,
            "Café.pdf",
        }
        assert all(entry.layout_state is LayoutState.INVALID for entry in colliding)
        nfd = next(entry for entry in colliding if entry.local_name == nfd_name)
        assert nfd.local_name != unicodedata.normalize("NFC", nfd.local_name)
        assert nfd.local_name_key == unicodedata.normalize("NFC", nfd_name).casefold()
        shelf = session.scalar(
            select(LibrarySourceEntry).where(LibrarySourceEntry.local_name == "Shelf")
        )
        assert shelf is not None
        assert shelf.children_presence_epoch == 0
        children = tuple(
            session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.parent_entry_id == shelf.id,
                    LibrarySourceEntry.local_name.in_(("seen.pdf", "unseen.pdf")),
                )
            )
        )
        assert {child.observed_parent_presence_epoch for child in children} == {0}
        shelf.next_children_presence_epoch = 1
        shelf.children_presence_epoch = 1
        session.commit()

    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.sources.upsert_observations(
            running.fence(),
            (_file_observation(("Shelf", "seen.pdf")),),
            observed_at=now + timedelta(seconds=1),
        )
        uow.commit()
    with factory() as session:
        epochs = {
            entry.local_name: entry.observed_parent_presence_epoch
            for entry in session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.local_name.in_(("seen.pdf", "unseen.pdf"))
                )
            )
        }
        assert epochs == {"seen.pdf": 1, "unseen.pdf": 0}

    with factory() as session:
        collision_directories = tuple(
            session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.local_name.in_(("Folder", "folder"))
                )
            )
        )
        collision_children = tuple(
            session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.local_name.in_(("left.pdf", "right.pdf"))
                )
            )
        )
        assert len(collision_directories) == 2
        assert all(
            entry.layout_state is LayoutState.INVALID
            and entry.slot_state is SlotState.COLLIDING
            for entry in collision_directories
        )
        assert len(collision_children) == 2
        assert all(
            entry.layout_state is LayoutState.PRESENT for entry in collision_children
        )
    blocked_plan = _flat_plan(
        source_format=SourceFormat.PDF,
        morphology=ReadingMorphology.PDF,
        path=("Folder", "left.pdf"),
        unit_suffix="blocked-left",
    )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert _bind_plan(uow, running, blocked_plan, outcome.bindings) is None


def test_large_collision_group_has_linear_bounded_evidence(persistence) -> None:
    engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    running = _bind_running_scan(factory, now)
    peer_count = 1_000
    collision = PathCollision(
        parent_path=(),
        comparison_key="shared-key",
        related_paths=tuple((f"peer-{index:04}",) for index in range(peer_count)),
    )
    statement_count = 0

    def count_statement(
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with SqlAlchemyScanUowFactory(factory)() as uow:
            uow.collisions.record(running.fence(), (collision,), observed_at=now)
            uow.commit()
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_count < 20
    with factory() as session:
        rows = tuple(session.scalars(select(PathCollisionObservation)))
    assert len(rows) == peer_count
    assert all("relatedPaths" not in row.evidence for row in rows)
    assert sum(len(json.dumps(row.evidence)) for row in rows) < peer_count * 256


def test_reverse_order_directory_collision_keeps_children_but_blocks_publish(
    persistence,
) -> None:
    _engine, factory = persistence
    _seed_library(factory, comparison=PathComparison.INSENSITIVE)
    now = datetime.now(UTC)
    run = replace(_pending_run(now), path_comparison=PathComparison.INSENSITIVE)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.scans.insert(run)
        uow.work_items.insert_root(_root_work(now))
        uow.commit()
    running = _bind_running_scan(factory, now)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        outcome = uow.sources.upsert_observations(
            running.fence(),
            (
                _directory_observation(("folder",)),
                _directory_observation(("Folder",)),
                _file_observation(("folder", "right.pdf")),
                _file_observation(("Folder", "left.pdf")),
            ),
            observed_at=now,
        )
        uow.collisions.record(running.fence(), outcome.collisions, observed_at=now)
        uow.commit()
    assert len(outcome.collisions) == 1
    blocked_plan = _flat_plan(
        source_format=SourceFormat.PDF,
        morphology=ReadingMorphology.PDF,
        path=("folder", "right.pdf"),
        unit_suffix="blocked-right",
    )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert _bind_plan(uow, running, blocked_plan, outcome.bindings) is None
    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert uow.scans.set_stage(
            running.fence(),
            expected_stage=DomainScanStage.DISCOVER,
            next_stage=DomainScanStage.RECONCILE,
            now=now,
        )
        finalizing = uow.scans.begin_finalizing(
            running.fence(),
            expected_stage=DomainScanStage.RECONCILE,
            now=now,
        )
        assert finalizing is not None
        assert uow.libraries.finalize_generation(finalizing.fence(), completed_at=now)
        completed = uow.scans.complete(finalizing.fence(), completed_at=now)
        assert completed is not None
        assert uow.work_items.delete_for_terminal("library", "scan")
        uow.commit()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(TopologyUnit)) == 0


def _flat_plan(
    *,
    source_format: SourceFormat,
    morphology: ReadingMorphology,
    path: tuple[str, ...] = ("book.bin",),
    unit_suffix: str = "book",
) -> TopologyUnitPlan:
    source_name = path[-1]
    return TopologyUnitPlan(
        unit_key=f"FLAT_VOLUME:{unit_suffix}",
        unit_kind=DomainTopologyUnitKind.FLAT_VOLUME,
        owner_path=path,
        unit_root_path=path,
        rows=(
            WorkProjectionPlan(path, "work", source_name, unit_suffix),
            VersionProjectionPlan(
                work_path=path,
                root_path=None,
                kind=DomainVersionKind.IMPLICIT,
                structure_key="version",
                source_name=None,
                sort_key="",
            ),
            VolumeProjectionPlan(
                work_path=path,
                version_path=None,
                root_path=path,
                source_kind=SourceKind.SINGLE_FILE,
                reading_morphology=morphology,
                structure_key="volume",
                source_name=source_name,
                sort_key=unit_suffix,
            ),
            AssetMembershipPlan(
                volume_path=path,
                source_path=path,
                source_format=source_format,
                role=DomainAssetRole.PRIMARY,
                disc_number=0,
                asset_order=0,
            ),
        ),
    )


def _bind_plan(
    uow: SqlAlchemyScanUnitOfWork,
    run: FullScanRun,
    plan: TopologyUnitPlan,
    available_bindings: tuple[SourcePathBinding, ...],
) -> BoundTopologyUnitPlan | None:
    fence = run.fence()
    by_path = {binding.relative_path: binding for binding in available_bindings}
    required = required_topology_source_paths(plan)
    if any(path not in by_path for path in required):
        return None
    bindings = tuple(by_path[path] for path in required)
    return uow.topology.bind_plan(fence, plan, bindings)


def _bound_batch(
    plan: BoundTopologyUnitPlan,
    batch: TopologyStageBatch,
) -> BoundTopologyStageBatch:
    return BoundTopologyStageBatch(
        first_row=batch.first_row,
        rows=batch.rows,
        bindings=plan.projections[batch.first_row : batch.first_row + len(batch.rows)],
        complete=batch.complete,
    )


def test_topology_pointer_and_stable_facts_change_only_on_activation(
    persistence,
) -> None:
    _engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    running = _bind_running_scan(factory, now)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        source_outcome = uow.sources.upsert_observations(
            running.fence(), (_file_observation(("book.bin",)),), observed_at=now
        )
        uow.commit()

    pdf_plan = _flat_plan(
        source_format=SourceFormat.PDF, morphology=ReadingMorphology.PDF
    )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        bound_pdf = _bind_plan(uow, running, pdf_plan, source_outcome.bindings)
        assert bound_pdf is not None
        staging = uow.topology.begin_staging(
            running.fence(),
            bound_pdf,
            expected_active_revision_id=None,
            created_at=now,
        )
        assert staging is not None
        staging = uow.topology.append_staging_batch(
            running.fence(),
            staging,
            _bound_batch(bound_pdf, TopologyStageBatch(0, pdf_plan.rows, True)),
            staged_at=now,
        )
        unit = uow.topology.get_active_revision_id("library", unit_id=bound_pdf.unit_id)
        assert unit is None
        assert uow.topology.activate_staging_group(
            running.fence(), (staging,), activated_at=now
        )
        uow.commit()

    with factory.begin() as session:
        volume = session.scalar(select(LibraryVolume))
        asset = session.scalar(select(VolumeAsset))
        assert volume is not None and asset is not None
        volume.content_state = "READY"
        asset.validation_state = AssetValidationState.READY

    comic_plan = _flat_plan(
        source_format=SourceFormat.CBZ, morphology=ReadingMorphology.COMIC
    )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        bound_comic = _bind_plan(uow, running, comic_plan, source_outcome.bindings)
        assert bound_comic is not None
        assert bound_comic.unit_id == bound_pdf.unit_id
        active = uow.topology.get_active_revision_id(
            "library", unit_id=bound_comic.unit_id
        )
        assert active is not None
        comic_staging = uow.topology.begin_staging(
            running.fence(),
            bound_comic,
            expected_active_revision_id=active,
            created_at=now + timedelta(seconds=1),
        )
        assert comic_staging is not None
        comic_staging = uow.topology.append_staging_batch(
            running.fence(),
            comic_staging,
            _bound_batch(
                bound_comic,
                TopologyStageBatch(0, comic_plan.rows, True),
            ),
            staged_at=now + timedelta(seconds=1),
        )
        uow.commit()

    with factory() as session:
        unit = session.scalar(select(TopologyUnit))
        volume = session.scalar(select(LibraryVolume))
        asset = session.scalar(select(VolumeAsset))
        assert unit is not None and unit.active_revision_id != comic_staging.revision_id
        assert volume is not None and volume.reading_morphology == "PDF"
        assert volume.content_state == "READY"
        assert asset is not None and asset.source_format == SourceFormat.PDF.value
        assert asset.validation_state is AssetValidationState.READY
        assert (
            session.get(TopologyUnitRevision, comic_staging.revision_id).state
            is RevisionState.STAGING
        )

    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert uow.topology.activate_staging_group(
            running.fence(),
            (comic_staging,),
            activated_at=now + timedelta(seconds=2),
        )
        uow.commit()
    with factory() as session:
        unit = session.scalar(select(TopologyUnit))
        volume = session.scalar(select(LibraryVolume))
        asset = session.scalar(select(VolumeAsset))
        assert unit is not None and unit.active_revision_id == comic_staging.revision_id
        assert volume is not None and volume.reading_morphology == "COMIC"
        assert asset is not None and asset.source_format == SourceFormat.CBZ.value
        assert volume.content_state == "PENDING"
        assert asset.validation_state is AssetValidationState.PENDING

    with factory.begin() as session:
        volume = session.scalar(select(LibraryVolume))
        asset = session.scalar(select(VolumeAsset))
        assert volume is not None and asset is not None
        volume.content_state = "READY"
        asset.validation_state = AssetValidationState.READY
    with SqlAlchemyScanUowFactory(factory)() as uow:
        unchanged = _bind_plan(uow, running, comic_plan, source_outcome.bindings)
        assert unchanged is not None
        assert (
            uow.topology.begin_staging(
                running.fence(),
                unchanged,
                expected_active_revision_id=comic_staging.revision_id,
                created_at=now + timedelta(seconds=3),
            )
            is None
        )
        uow.commit()
    with factory() as session:
        volume = session.scalar(select(LibraryVolume))
        asset = session.scalar(select(VolumeAsset))
        assert volume is not None and volume.content_state == "READY"
        assert asset is not None
        assert asset.validation_state is AssetValidationState.READY


def test_ten_thousand_track_topology_pipeline_has_bounded_statements(
    persistence,
) -> None:
    engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    running = _bind_running_scan(factory, now)
    work_path = ("Audiobook",)
    track_paths = tuple(
        (*work_path, f"track-{index:05}.mp3") for index in range(10_000)
    )
    observations = (
        _directory_observation(work_path),
        *tuple(
            _file_observation(path, source_format=SourceFormat.MP3)
            for path in track_paths
        ),
    )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        source_outcome = uow.sources.upsert_observations(
            running.fence(), observations, observed_at=now
        )
        uow.commit()

    rows = (
        WorkProjectionPlan(work_path, "work", "Audiobook", "audiobook"),
        VersionProjectionPlan(
            work_path=work_path,
            root_path=None,
            kind=DomainVersionKind.IMPLICIT,
            structure_key="version",
            source_name=None,
            sort_key="",
        ),
        VolumeProjectionPlan(
            work_path=work_path,
            version_path=None,
            root_path=work_path,
            source_kind=SourceKind.MULTI_ASSET_AUDIO,
            reading_morphology=ReadingMorphology.AUDIO,
            structure_key="volume",
            source_name="Audiobook",
            sort_key="audiobook",
        ),
        *tuple(
            AssetMembershipPlan(
                volume_path=work_path,
                source_path=path,
                source_format=SourceFormat.MP3,
                role=DomainAssetRole.AUDIO_TRACK,
                disc_number=0,
                asset_order=index,
            )
            for index, path in enumerate(track_paths)
        ),
    )
    plan = TopologyUnitPlan(
        unit_key="AUDIOBOOK_WORK:audiobook",
        unit_kind=DomainTopologyUnitKind.AUDIOBOOK_WORK,
        owner_path=work_path,
        unit_root_path=work_path,
        rows=rows,
    )
    statement_count = 0

    def count_statement(
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with SqlAlchemyScanUowFactory(factory)() as uow:
            bound_plan = _bind_plan(uow, running, plan, source_outcome.bindings)
            assert bound_plan is not None
            staging = uow.topology.begin_staging(
                running.fence(),
                bound_plan,
                expected_active_revision_id=None,
                created_at=now,
            )
            assert staging is not None
            uow.commit()
        for batch in iter_stage_batches(plan):
            with SqlAlchemyScanUowFactory(factory)() as uow:
                staging = uow.topology.append_staging_batch(
                    running.fence(),
                    staging,
                    _bound_batch(bound_plan, batch),
                    staged_at=now,
                )
                uow.commit()
        with SqlAlchemyScanUowFactory(factory)() as uow:
            assert uow.topology.activate_staging_group(
                running.fence(), (staging,), activated_at=now
            )
            uow.commit()
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_count < 500


def test_finalize_advances_generation_without_rewriting_unseen_sources(
    persistence,
) -> None:
    engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    running = _bind_running_scan(factory, now)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        uow.sources.upsert_observations(
            running.fence(), (_file_observation(("seen.pdf",)),), observed_at=now
        )
        uow.commit()
    with factory.begin() as session:
        root = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT
            )
        )
        assert root is not None
        session.add(
            LibrarySourceEntry(
                id="unseen",
                library_id="library",
                parent_entry_id=root.id,
                local_name="unseen.pdf",
                local_name_key="unseen.pdf",
                entry_type=SourceEntryType.FILE,
                filesystem_identity="old",
                last_seen_generation=0,
                children_presence_epoch=0,
                observed_parent_presence_epoch=0,
                layout_state=LayoutState.PRESENT,
                slot_state=SlotState.ACTIVE,
            )
        )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        assert uow.scans.set_stage(
            running.fence(),
            expected_stage=DomainScanStage.DISCOVER,
            next_stage=DomainScanStage.RECONCILE,
            now=now,
        )
        finalizing = uow.scans.begin_finalizing(
            running.fence(),
            expected_stage=DomainScanStage.RECONCILE,
            now=now,
        )
        assert finalizing is not None
        uow.commit()

    statements = 0

    def count_statement(
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal statements
        statements += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        with SqlAlchemyScanUowFactory(factory)() as uow:
            assert uow.libraries.finalize_generation(
                finalizing.fence(), completed_at=now + timedelta(seconds=1)
            )
            uow.commit()
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)
    assert statements <= 4
    with factory() as session:
        library = session.get(CatalogLibrary, "library")
        unseen = session.get(LibrarySourceEntry, "unseen")
        assert library is not None and library.last_successful_generation == 1
        assert unseen is not None
        assert unseen.last_seen_generation == 0
        assert unseen.slot_state is SlotState.ACTIVE
        assert unseen.absence_confirmed_at is None


def test_invalidated_or_paused_run_cleanup_is_cas_scoped(
    persistence,
) -> None:
    _engine, factory = persistence
    _seed_library(factory)
    now = datetime.now(UTC)
    _insert_pending_scan(factory, now)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        run = uow.scans.get_active_for_update("library")
        library = uow.libraries.get_for_scan_for_update("library")
        assert run is not None and library is not None
        assert (
            uow.scans.cancel_invalidated(run, current_library=library, cancelled_at=now)
            is None
        )

    with factory.begin() as session:
        session.execute(
            update(CatalogLibrary)
            .where(CatalogLibrary.id == "library")
            .values(control_state=LibraryControlState.PAUSED)
        )
    with SqlAlchemyScanUowFactory(factory)() as uow:
        run = uow.scans.get_active_for_update("library")
        library = uow.libraries.get_for_scan_for_update("library")
        assert run is not None and library is not None
        cancelled = uow.scans.cancel_invalidated(
            run, current_library=library, cancelled_at=now
        )
        assert cancelled is not None
        assert uow.topology.abandon_cancelled_scan_staging(
            "library", "scan", abandoned_at=now
        )
        assert uow.work_items.delete_for_terminal("library", "scan")
        uow.commit()
    with factory() as session:
        run_row = session.get(LibraryScanRun, "scan")
        assert run_row is not None and run_row.state is ScanState.CANCELLED
        assert session.get(LibraryScanWorkItem, "root-work") is None


def test_root_only_drift_rejects_cancel_and_both_takeover_paths(
    persistence,
) -> None:
    _engine, factory = persistence
    now = datetime.now(UTC)
    expired_at = now - timedelta(minutes=10)
    _seed_library(factory)
    _insert_pending_scan(factory, expired_at)
    with factory.begin() as session:
        library = session.get(CatalogLibrary, "library")
        assert library is not None
        library.root_path = "/srv/rebound"
        library.topology_writer_fence = 2

    with SqlAlchemyScanUowFactory(factory)() as uow:
        run = uow.scans.get_active_for_update("library")
        assert run is not None
        assert (
            uow.scans.cancel(
                run,
                cancelled_at=now,
                next_topology_writer_fence=2,
            )
            is None
        )
        assert (
            uow.scans.take_over_expired(
                run.fence(),
                new_owner_token="new-worker",
                new_topology_writer_fence=2,
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            is None
        )

    with factory.begin() as session:
        run_row = session.get(LibraryScanRun, "scan")
        assert run_row is not None
        run_row.topology_writer_fence = 2
        run_row.lease_owner = "new-worker"
        run_row.lease_expires_at = now + timedelta(minutes=5)
    with SqlAlchemyScanUowFactory(factory)() as uow:
        run = uow.scans.get_active_for_update("library")
        assert run is not None
        assert (
            uow.work_items.take_over_expired_root(
                run.fence(),
                new_owner_token="new-worker",
                new_topology_writer_fence=2,
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
                restart_from_root=True,
            )
            is None
        )


def test_busy_writer_gate_maps_conflict_with_cause_and_cleans_session(
    persistence,
) -> None:
    engine, _factory = persistence
    _CleanupTrackingSession.rollback_called = False
    _CleanupTrackingSession.close_called = False
    factory = sessionmaker(
        engine,
        class_=_CleanupTrackingSession,
        expire_on_commit=False,
    )
    event.listen(engine, "before_cursor_execute", _raise_busy)
    try:
        with (
            pytest.raises(ScanConflict) as captured,
            SqlAlchemyScanUowFactory(factory)(),
        ):
            pass
    finally:
        event.remove(engine, "before_cursor_execute", _raise_busy)
    assert isinstance(captured.value.__cause__, OperationalError)
    assert _CleanupTrackingSession.rollback_called
    assert _CleanupTrackingSession.close_called
