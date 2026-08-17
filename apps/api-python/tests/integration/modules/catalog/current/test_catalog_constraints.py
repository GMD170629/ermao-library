from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence import CurrentUser
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.infrastructure.persistence import (
    AdministrativeAuditEvent,
    AssetRole,
    AssetValidationState,
    AttachmentRole,
    AuditActorKind,
    CatalogLibrary,
    LayoutState,
    LibraryControlState,
    LibraryHealth,
    LibraryRootRegistryLock,
    LibraryScanRun,
    LibrarySourceEntry,
    LibraryVolume,
    LibraryWork,
    OperationState,
    RevisionState,
    ScanStage,
    ScanState,
    SlotState,
    SourceAttachment,
    SourceEntryType,
    SourceWriteOperation,
    TopologyAssetMembership,
    TopologyUnit,
    TopologyUnitKind,
    TopologyUnitRevision,
    TopologyVersionProjection,
    TopologyVolumeProjection,
    TopologyWorkProjection,
    VersionKind,
    VolumeAsset,
    WorkVersion,
    WritePolicy,
)
from app.modules.catalog.public import SourceKind


@pytest.fixture
def engine(tmp_path: Path):
    database_path = tmp_path / "catalog-current.sqlite3"
    upgrade_current_schema(database_path)
    current_engine = create_current_engine(database_path)
    try:
        yield current_engine
    finally:
        current_engine.dispose()


def _library(library_id: str) -> CatalogLibrary:
    return CatalogLibrary(
        id=library_id,
        name=library_id,
        root_path=f"/srv/{library_id}",
        root_path_key=f"/srv/{library_id}",
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        control_state=LibraryControlState.ACTIVE,
        observed_health=LibraryHealth.UNKNOWN,
    )


def _root(library_id: str, entry_id: str = "root") -> LibrarySourceEntry:
    return LibrarySourceEntry(
        id=entry_id,
        library_id=library_id,
        local_name="$root",
        local_name_key="$root",
        entry_type=SourceEntryType.SYNTHETIC_ROOT,
        layout_state=LayoutState.PRESENT,
        slot_state=SlotState.ACTIVE,
    )


def _file(
    library_id: str,
    entry_id: str,
    parent_entry_id: str | None = "root",
    local_name: str = "book.epub",
    slot_state: SlotState = SlotState.ACTIVE,
) -> LibrarySourceEntry:
    return LibrarySourceEntry(
        id=entry_id,
        library_id=library_id,
        parent_entry_id=parent_entry_id,
        local_name=local_name,
        local_name_key=local_name.casefold(),
        entry_type=SourceEntryType.FILE,
        layout_state=LayoutState.PRESENT,
        slot_state=slot_state,
    )


def _work(library_id: str, work_id: str = "work") -> LibraryWork:
    return LibraryWork(id=work_id, library_id=library_id)


def _version(library_id: str, version_id: str = "version") -> WorkVersion:
    return WorkVersion(id=version_id, library_id=library_id)


def _volume(library_id: str, volume_id: str = "volume") -> LibraryVolume:
    return LibraryVolume(
        id=volume_id,
        library_id=library_id,
        reading_morphology="REFLOWABLE",
        content_state="PENDING",
    )


def _scan(library_id: str, scan_id: str = "scan") -> LibraryScanRun:
    return LibraryScanRun(
        id=scan_id,
        library_id=library_id,
        generation=1,
        config_revision=1,
        mode_snapshot=OrganizationMode.FLAT,
        topology_version_snapshot=1,
        topology_writer_fence=0,
        state=ScanState.COMPLETED,
        stage=ScanStage.FINALIZE,
    )


def _revision(
    library_id: str,
    unit_id: str,
    scan_id: str = "scan",
    root_entry_id: str = "root",
    revision_id: str = "revision",
    state: RevisionState = RevisionState.STAGING,
) -> TopologyUnitRevision:
    return TopologyUnitRevision(
        id=revision_id,
        library_id=library_id,
        unit_id=unit_id,
        scan_run_id=scan_id,
        unit_root_entry_id=root_entry_id,
        revision=1,
        state=state,
    )


def _commit_fails(session: Session, *objects: object) -> None:
    session.add_all(objects)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def _commit(session: Session, *objects: object) -> None:
    session.add_all(objects)
    session.commit()


def test_cross_library_parent_source_and_owner_fks_are_rejected(engine) -> None:
    with Session(engine) as session:
        _commit(session, _library("library-a"), _library("library-b"))
        _commit(session, _root("library-a", "root-a"), _root("library-b", "root-b"))
        _commit(session, _work("library-a"), _volume("library-a"))

        _commit_fails(
            session,
            _file("library-b", "child", parent_entry_id="root-a"),
        )
        _commit_fails(
            session,
            SourceAttachment(
                id="attachment",
                library_id="library-b",
                source_entry_id="root-a",
                work_id="work-a",
                role=AttachmentRole.COVER,
            ),
        )
        _commit_fails(
            session,
            TopologyUnit(
                id="unit",
                library_id="library-b",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work",
            ),
        )


def test_synthetic_root_shape_and_one_root_per_library(engine) -> None:
    with Session(engine) as session:
        _commit(session, _library("library-a"))
        _commit(session, _root("library-a"))
        _commit_fails(session, _root("library-a", "second-root"))
        _commit_fails(
            session,
            LibrarySourceEntry(
                id="bad-root",
                library_id="library-a",
                parent_entry_id="root",
                local_name="$root",
                local_name_key="$root",
                entry_type=SourceEntryType.SYNTHETIC_ROOT,
                layout_state=LayoutState.PRESENT,
                slot_state=SlotState.ACTIVE,
            ),
        )
        _commit_fails(session, _file("library-a", "orphan", parent_entry_id=None))


def test_active_source_slot_is_unique_but_retired_slot_is_free(engine) -> None:
    with Session(engine) as session:
        _commit(session, _library("library-a"), _root("library-a"))
        _commit(session, _file("library-a", "first"))
        _commit_fails(session, _file("library-a", "second"))
        _commit(session, _file("library-a", "retired", slot_state=SlotState.RETIRED))
        first = session.get(LibrarySourceEntry, "first")
        assert first is not None
        first.slot_state = SlotState.RETIRED
        session.commit()
        _commit(session, _file("library-a", "replacement"))


def test_source_attachment_requires_exactly_one_owner(engine) -> None:
    with Session(engine) as session:
        _commit(
            session,
            _library("library-a"),
            _root("library-a"),
            _work("library-a"),
            _version("library-a"),
            _volume("library-a"),
            _file("library-a", "source"),
        )
        _commit_fails(
            session,
            SourceAttachment(
                id="none",
                library_id="library-a",
                source_entry_id="source",
                role=AttachmentRole.COVER,
            ),
        )
        _commit_fails(
            session,
            SourceAttachment(
                id="two",
                library_id="library-a",
                source_entry_id="source",
                work_id="work",
                volume_id="volume",
                role=AttachmentRole.COVER,
            ),
        )
        _commit(
            session,
            SourceAttachment(
                id="one",
                library_id="library-a",
                source_entry_id="source",
                version_id="version",
                role=AttachmentRole.OPF,
            ),
        )


def test_topology_unit_owner_shape_kind_and_uniqueness(engine) -> None:
    with Session(engine) as session:
        _commit(
            session,
            _library("library-a"),
            _work("library-a"),
            _version("library-a"),
            _volume("library-a"),
        )
        _commit_fails(
            session,
            TopologyUnit(
                id="none",
                library_id="library-a",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
            ),
        )
        _commit_fails(
            session,
            TopologyUnit(
                id="two",
                library_id="library-a",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work",
                volume_owner_id="volume",
            ),
        )
        _commit_fails(
            session,
            TopologyUnit(
                id="wrong-kind",
                library_id="library-a",
                unit_kind=TopologyUnitKind.VERSION_CONTAINER,
                volume_owner_id="volume",
            ),
        )
        _commit(
            session,
            TopologyUnit(
                id="unit",
                library_id="library-a",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work",
            ),
        )
        _commit_fails(
            session,
            TopologyUnit(
                id="duplicate-owner",
                library_id="library-a",
                unit_kind=TopologyUnitKind.AUDIOBOOK_WORK,
                work_owner_id="work",
            ),
        )


def test_active_revision_is_same_library_and_unit_and_unique_per_unit(engine) -> None:
    with Session(engine) as session:
        _commit(
            session,
            _library("library-a"),
            _library("library-b"),
            _root("library-a", "root-a"),
            _root("library-b", "root-b"),
            _scan("library-a"),
            _scan("library-b", "scan-b"),
            _work("library-a", "work-a"),
            _work("library-b", "work-b"),
        )
        _commit(
            session,
            TopologyUnit(
                id="unit-a",
                library_id="library-a",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work-a",
            ),
            TopologyUnit(
                id="unit-b",
                library_id="library-b",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work-b",
            ),
        )
        _commit(
            session,
            _revision(
                "library-a",
                "unit-a",
                root_entry_id="root-a",
                revision_id="revision-a",
                state=RevisionState.ACTIVE,
            ),
            _revision(
                "library-b",
                "unit-b",
                scan_id="scan-b",
                root_entry_id="root-b",
                revision_id="revision-b",
                state=RevisionState.ACTIVE,
            ),
        )
        unit_a = session.get(TopologyUnit, "unit-a")
        assert unit_a is not None
        unit_a.active_revision_id = "revision-a"
        session.commit()
        unit_a.active_revision_id = "revision-b"
        _commit_fails(session, unit_a)

        unit_a.active_revision_id = "revision-a"
        session.commit()
        _commit_fails(
            session,
            TopologyUnitRevision(
                id="revision-a-2",
                library_id="library-a",
                unit_id="unit-a",
                scan_run_id="scan",
                unit_root_entry_id="root-a",
                revision=2,
                state=RevisionState.ACTIVE,
            ),
        )


def test_projection_and_asset_membership_structural_uniqueness(engine) -> None:
    with Session(engine) as session:
        _commit(
            session,
            _library("library-a"),
            _root("library-a"),
            _file("library-a", "source"),
            _work("library-a"),
            _version("library-a"),
            _volume("library-a"),
            VolumeAsset(
                id="asset",
                library_id="library-a",
                source_format="mp3",
                validation_state=AssetValidationState.PENDING,
            ),
            _scan("library-a"),
            TopologyUnit(
                id="unit",
                library_id="library-a",
                unit_kind=TopologyUnitKind.MULTI_ASSET_VOLUME,
                volume_owner_id="volume",
            ),
        )
        _commit(session, _revision("library-a", "unit"))
        _commit(
            session,
            TopologyVolumeProjection(
                id="volume-projection",
                library_id="library-a",
                unit_revision_id="revision",
                volume_id="volume",
                root_entry_id="source",
                source_kind=SourceKind.MULTI_ASSET_AUDIO,
                structure_key="volume",
                source_name="volume",
                sort_key="volume",
            ),
            TopologyWorkProjection(
                id="work-projection",
                library_id="library-a",
                unit_revision_id="revision",
                work_id="work",
                root_entry_id="source",
                structure_key="work",
                source_name="work",
                sort_key="work",
            ),
            TopologyVersionProjection(
                id="version-projection",
                library_id="library-a",
                unit_revision_id="revision",
                version_id="version",
                work_id="work",
                kind=VersionKind.IMPLICIT,
                structure_key="version",
                source_name="version",
                sort_key="version",
            ),
        )
        _commit_fails(
            session,
            TopologyVolumeProjection(
                id="volume-projection-2",
                library_id="library-a",
                unit_revision_id="revision",
                volume_id="volume",
                root_entry_id="source",
                source_kind=SourceKind.MULTI_ASSET_AUDIO,
                structure_key="volume-2",
                source_name="volume-2",
                sort_key="volume-2",
            ),
        )
        _commit(
            session,
            TopologyAssetMembership(
                id="membership",
                library_id="library-a",
                unit_revision_id="revision",
                asset_id="asset",
                volume_id="volume",
                source_entry_id="source",
                role=AssetRole.AUDIO_TRACK,
                source_format="mp3",
                asset_order=0,
            ),
        )
        _commit_fails(
            session,
            TopologyAssetMembership(
                id="membership-duplicate",
                library_id="library-a",
                unit_revision_id="revision",
                asset_id="asset",
                volume_id="volume",
                source_entry_id="source",
                role=AssetRole.AUDIO_TRACK,
                source_format="mp3",
                asset_order=1,
            ),
        )


def test_source_write_active_slot_unique_and_terminal_releases_slot(engine) -> None:
    with Session(engine) as session:
        _commit(session, _library("library-a"))
        _commit(
            session,
            SourceWriteOperation(
                id="operation-1",
                library_id="library-a",
                idempotency_key="key-1",
                organization_mode=OrganizationMode.FLAT,
                destination="book.epub",
                target_slot_key="book",
                state=OperationState.COMPLETED,
                expected_config_revision=1,
            ),
            SourceWriteOperation(
                id="operation-2",
                library_id="library-a",
                idempotency_key="key-2",
                organization_mode=OrganizationMode.FLAT,
                destination="book-2.epub",
                target_slot_key="book",
                state=OperationState.PREPARED,
                expected_config_revision=1,
            ),
        )
        _commit_fails(
            session,
            SourceWriteOperation(
                id="operation-3",
                library_id="library-a",
                idempotency_key="key-3",
                organization_mode=OrganizationMode.FLAT,
                destination="book-3.epub",
                target_slot_key="book",
                state=OperationState.NEEDS_ATTENTION,
                expected_config_revision=1,
            ),
        )


def test_administrative_audit_survives_library_delete(engine) -> None:
    with Session(engine) as session:
        user = CurrentUser(
            id="user", display_name="User", role="admin", status="active"
        )
        _commit(session, user, _library("library-a"))
        _commit(
            session,
            AdministrativeAuditEvent(
                id="audit",
                former_library_id="library-a",
                code="SOURCE_BYTES_PRESERVED_DURING_REMOVAL",
                actor_kind=AuditActorKind.SYSTEM,
                evidence={"preserved": True},
            ),
        )
        session.delete(session.get(CatalogLibrary, "library-a"))
        session.commit()
        assert session.get(AdministrativeAuditEvent, "audit") is not None


def test_populated_library_requires_active_pointer_clear_before_removal(engine) -> None:
    with Session(engine) as session:
        _commit(
            session,
            _library("library-a"),
            _root("library-a"),
            _work("library-a"),
            _scan("library-a"),
            TopologyUnit(
                id="unit",
                library_id="library-a",
                unit_kind=TopologyUnitKind.WORK_CONTAINER,
                work_owner_id="work",
            ),
        )
        _commit(
            session,
            _revision(
                "library-a",
                "unit",
                revision_id="revision",
                state=RevisionState.ACTIVE,
            ),
            AdministrativeAuditEvent(
                id="audit",
                former_library_id="library-a",
                code="LIBRARY_REMOVAL",
                actor_kind=AuditActorKind.SYSTEM,
                evidence={"library": "library-a"},
            ),
        )
        unit = session.get(TopologyUnit, "unit")
        library = session.get(CatalogLibrary, "library-a")
        assert unit is not None
        assert library is not None
        unit.active_revision_id = "revision"
        session.commit()

        session.delete(library)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        unit = session.get(TopologyUnit, "unit")
        library = session.get(CatalogLibrary, "library-a")
        assert unit is not None
        assert library is not None
        unit.active_revision_id = None
        session.commit()

        session.delete(library)
        session.commit()
        assert session.get(CatalogLibrary, "library-a") is None
        assert session.get(TopologyUnit, "unit") is None
        assert session.get(TopologyUnitRevision, "revision") is None
        assert session.get(AdministrativeAuditEvent, "audit") is not None


def test_library_root_registry_lock_is_singleton_id_one(engine) -> None:
    with Session(engine) as session:
        _commit(session, LibraryRootRegistryLock(id=1))
        _commit_fails(session, LibraryRootRegistryLock(id=2))
