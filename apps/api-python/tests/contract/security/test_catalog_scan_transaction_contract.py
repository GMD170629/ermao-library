from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.infrastructure.admission import LocalSourceAdmissionAdapter
from app.modules.catalog.infrastructure.discovery import LocalDirectoryDiscoveryAdapter
from app.modules.catalog.infrastructure.files import LocalLibraryFilesystem
from app.modules.catalog.infrastructure.persistence import (
    CatalogLibrary,
    LibraryScanRun,
    LibraryScanWorkItem,
    LibrarySourceEntry,
    SourceEntryType,
    SqlAlchemyLibraryGrantRepository,
    SqlAlchemyLibraryRepository,
    SqlAlchemyScanUowFactory,
    TopologyUnit,
    TopologyUnitRevision,
    UuidIdGenerator,
)
from app.modules.catalog.infrastructure.persistence import (
    RevisionState as StoredRevisionState,
)
from app.modules.catalog.infrastructure.persistence import (
    ScanFailureCode as StoredScanFailureCode,
)
from app.modules.catalog.infrastructure.persistence import (
    ScanState as StoredScanState,
)
from app.modules.catalog.public import (
    DirectoryRootUnavailable,
    GrantLevel,
    Library,
    LibraryGrant,
    OrganizationMode,
    PathComparison,
    RunFullLibraryScan,
    RunFullLibraryScanCommand,
    ScanConflict,
    ScanRootIdentityChanged,
    StartFullLibraryScan,
    StartFullLibraryScanCommand,
    WritePolicy,
)

_NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
_VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n9\n%%EOF\n"


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _MonotonicClock:
    def seconds(self) -> float:
        return 0.0


@pytest.fixture
def scan_database(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "catalog-scan-contract.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine, clock=lambda: _NOW)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add(CurrentUser(id="admin-1", display_name="Admin", role="admin"))
    yield factory
    engine.dispose()


def _seed_active_library(factory: sessionmaker[Session], root: Path) -> CatalogLibrary:
    observation = LocalLibraryFilesystem().preflight(
        str(root), path_comparison=PathComparison.SENSITIVE
    )
    library = Library.create(
        library_id="library-1",
        name="Books",
        root=observation.registered_root,
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        now=_NOW,
    ).activate(now=_NOW)
    with factory.begin() as session:
        SqlAlchemyLibraryRepository(session).insert(library)
        saved = SqlAlchemyLibraryGrantRepository(session).save_preserving_last_admin(
            LibraryGrant("admin-1", library.id, GrantLevel.ADMIN, 1)
        )
        assert saved
    with factory() as session:
        row = session.get(CatalogLibrary, library.id)
        assert row is not None
        session.expunge(row)
        return row


def _start_scan(factory: sessionmaker[Session], *, owner_token: str) -> LibraryScanRun:
    result = StartFullLibraryScan(
        unit_of_work_factory=SqlAlchemyScanUowFactory(factory),
        id_generator=UuidIdGenerator(),
        clock=_Clock(),
    ).execute(
        StartFullLibraryScanCommand(
            actor_id="admin-1",
            library_id="library-1",
            owner_token=owner_token,
        )
    )
    with factory() as session:
        row = session.get(LibraryScanRun, result.scan_id)
        assert row is not None
        session.expunge(row)
        return row


def _run_scan(
    factory: sessionmaker[Session], *, scan_id: str, owner_token: str
) -> None:
    RunFullLibraryScan(
        unit_of_work_factory=SqlAlchemyScanUowFactory(factory),
        discovery=LocalDirectoryDiscoveryAdapter(),
        admission=LocalSourceAdmissionAdapter(),
        clock=_Clock(),
        monotonic_clock=_MonotonicClock(),
    ).execute(
        RunFullLibraryScanCommand(
            library_id="library-1",
            scan_id=scan_id,
            owner_token=owner_token,
        )
    )


def test_nfd_root_snapshot_round_trips_and_replacement_cannot_rebind_identity(
    scan_database: sessionmaker[Session], tmp_path: Path
) -> None:
    nfd_name = unicodedata.normalize("NFD", "Café")
    root = tmp_path / nfd_name
    root.mkdir()
    (root / "book.pdf").write_bytes(_VALID_PDF)
    seeded = _seed_active_library(scan_database, root)
    assert seeded.root_path == str(root.resolve())
    assert not unicodedata.is_normalized("NFC", Path(seeded.root_path).name)

    first = _start_scan(scan_database, owner_token="worker-1")
    with scan_database() as session:
        work = session.scalar(
            select(LibraryScanWorkItem).where(
                LibraryScanWorkItem.scan_run_id == first.id
            )
        )
        assert work is not None
        assert first.root_path_snapshot == seeded.root_path
        assert work.root_path_snapshot == seeded.root_path

    _run_scan(scan_database, scan_id=first.id, owner_token="worker-1")
    with scan_database() as session:
        synthetic_root = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library-1",
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            )
        )
        source = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library-1",
                LibrarySourceEntry.local_name == "book.pdf",
            )
        )
        library = session.get(CatalogLibrary, "library-1")
        assert synthetic_root is not None
        assert source is not None
        assert library is not None
        original_identity = synthetic_root.filesystem_identity
        assert original_identity
        assert library.last_successful_generation == 1
        assert source.last_seen_generation == 1

    displaced = root.with_name(f"{root.name}-old")
    root.rename(displaced)
    root.mkdir()
    second = _start_scan(scan_database, owner_token="worker-2")
    with pytest.raises(ScanRootIdentityChanged) as caught:
        _run_scan(scan_database, scan_id=second.id, owner_token="worker-2")
    assert seeded.root_path not in str(caught.value)
    assert str(displaced) not in str(caught.value)

    with scan_database() as session:
        synthetic_root = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library-1",
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            )
        )
        source = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library-1",
                LibrarySourceEntry.local_name == "book.pdf",
            )
        )
        failed = session.get(LibraryScanRun, second.id)
        library = session.get(CatalogLibrary, "library-1")
        assert synthetic_root is not None
        assert source is not None
        assert failed is not None
        assert library is not None
        assert synthetic_root.filesystem_identity == original_identity
        assert failed.state is StoredScanState.FAILED
        assert failed.failure_code is StoredScanFailureCode.ROOT_IDENTITY_CHANGED
        assert library.last_successful_generation == 1
        assert source.last_seen_generation == 1


def test_unavailable_root_fails_scan_without_advancing_generation_or_leaking_path(
    scan_database: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    seeded = _seed_active_library(scan_database, root)
    pending = _start_scan(scan_database, owner_token="worker-unavailable")
    root.rmdir()

    with pytest.raises(DirectoryRootUnavailable) as caught:
        _run_scan(
            scan_database,
            scan_id=pending.id,
            owner_token="worker-unavailable",
        )
    assert seeded.root_path not in str(caught.value)

    with scan_database() as session:
        failed = session.get(LibraryScanRun, pending.id)
        library = session.get(CatalogLibrary, "library-1")
        assert failed is not None
        assert library is not None
        assert failed.state is StoredScanState.FAILED
        assert failed.failure_code is StoredScanFailureCode.ROOT_UNAVAILABLE
        assert library.last_successful_generation is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(LibrarySourceEntry)
                .where(LibrarySourceEntry.library_id == "library-1")
            )
            == 0
        )


def _mutate_library_snapshot(row: CatalogLibrary, mismatch: str) -> None:
    if mismatch == "config_revision":
        row.config_revision += 1
    elif mismatch == "path_comparison":
        row.path_comparison = PathComparison.INSENSITIVE
    elif mismatch == "root_path":
        row.root_path = f"{row.root_path}-replacement"
        row.root_path_key = f"{row.root_path_key}-replacement"
    elif mismatch == "topology_version":
        row.topology_version += 1
    elif mismatch == "topology_writer_fence":
        row.topology_writer_fence += 1
    else:
        raise AssertionError(f"unsupported mismatch: {mismatch}")


@pytest.mark.parametrize(
    "mismatch",
    (
        "config_revision",
        "path_comparison",
        "root_path",
        "topology_version",
        "topology_writer_fence",
    ),
)
def test_start_atomically_replaces_only_an_invalidated_live_scan(
    scan_database: sessionmaker[Session], tmp_path: Path, mismatch: str
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_active_library(scan_database, root)
    stale = _start_scan(scan_database, owner_token="worker-stale")

    with pytest.raises(ScanConflict):
        _start_scan(scan_database, owner_token="worker-same-snapshot")

    with scan_database.begin() as session:
        library = session.get(CatalogLibrary, "library-1")
        assert library is not None
        _mutate_library_snapshot(library, mismatch)

    replacement = _start_scan(scan_database, owner_token="worker-replacement")
    with scan_database() as session:
        stale_row = session.get(LibraryScanRun, stale.id)
        replacement_row = session.get(LibraryScanRun, replacement.id)
        assert stale_row is not None
        assert replacement_row is not None
        assert stale_row.state is StoredScanState.CANCELLED
        assert replacement_row.state is StoredScanState.PENDING
        assert (
            session.scalar(
                select(func.count())
                .select_from(LibraryScanWorkItem)
                .where(LibraryScanWorkItem.scan_run_id == stale.id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(LibraryScanWorkItem)
                .where(LibraryScanWorkItem.scan_run_id == replacement.id)
            )
            == 1
        )


def test_concurrent_invalidation_loser_does_not_cancel_the_winning_run(
    scan_database: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_active_library(scan_database, root)
    stale = _start_scan(scan_database, owner_token="worker-stale")
    with scan_database.begin() as session:
        library = session.get(CatalogLibrary, "library-1")
        assert library is not None
        library.config_revision += 1

    def start(owner_token: str) -> str:
        try:
            return _start_scan(scan_database, owner_token=owner_token).id
        except ScanConflict:
            return "SCAN_CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(start, ("worker-winner-a", "worker-winner-b")))
    winning_ids = tuple(value for value in results if value != "SCAN_CONFLICT")
    assert len(winning_ids) == 1
    assert results.count("SCAN_CONFLICT") == 1

    with scan_database() as session:
        active = session.scalar(
            select(LibraryScanRun).where(
                LibraryScanRun.library_id == "library-1",
                LibraryScanRun.state.in_(
                    (StoredScanState.PENDING, StoredScanState.RUNNING)
                ),
            )
        )
        stale_row = session.get(LibraryScanRun, stale.id)
        assert active is not None
        assert stale_row is not None
        assert active.id == winning_ids[0]
        assert active.state is StoredScanState.PENDING
        assert stale_row.state is StoredScanState.CANCELLED
        assert (
            session.scalar(
                select(func.count())
                .select_from(LibraryScanWorkItem)
                .where(LibraryScanWorkItem.scan_run_id == active.id)
            )
            == 1
        )


def test_invalidated_scan_cleanup_is_scoped_and_keeps_active_pointer(
    scan_database: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "book.pdf").write_bytes(_VALID_PDF)
    _seed_active_library(scan_database, root)
    completed = _start_scan(scan_database, owner_token="worker-complete")
    _run_scan(
        scan_database,
        scan_id=completed.id,
        owner_token="worker-complete",
    )
    invalidated = _start_scan(scan_database, owner_token="worker-invalidated")

    target_revision_id = "revision-invalidated"
    unrelated_revision_id = "revision-unrelated"
    with scan_database.begin() as session:
        unit = session.scalar(
            select(TopologyUnit).where(TopologyUnit.library_id == "library-1")
        )
        assert unit is not None
        assert unit.active_revision_id is not None
        active_revision_id = unit.active_revision_id
        active_revision = session.get(TopologyUnitRevision, active_revision_id)
        assert active_revision is not None
        session.add_all(
            (
                TopologyUnitRevision(
                    id=target_revision_id,
                    library_id="library-1",
                    unit_id=unit.id,
                    scan_run_id=invalidated.id,
                    unit_root_entry_id=active_revision.unit_root_entry_id,
                    revision=active_revision.revision + 1,
                    state=StoredRevisionState.STAGING,
                ),
                TopologyUnitRevision(
                    id=unrelated_revision_id,
                    library_id="library-1",
                    unit_id=unit.id,
                    scan_run_id=completed.id,
                    unit_root_entry_id=active_revision.unit_root_entry_id,
                    revision=active_revision.revision + 2,
                    state=StoredRevisionState.STAGING,
                ),
            )
        )
        library = session.get(CatalogLibrary, "library-1")
        assert library is not None
        library.config_revision += 1

    replacement = _start_scan(scan_database, owner_token="worker-replacement")
    with scan_database() as session:
        unit = session.scalar(
            select(TopologyUnit).where(TopologyUnit.library_id == "library-1")
        )
        target_revision = session.get(TopologyUnitRevision, target_revision_id)
        unrelated_revision = session.get(TopologyUnitRevision, unrelated_revision_id)
        invalidated_run = session.get(LibraryScanRun, invalidated.id)
        replacement_run = session.get(LibraryScanRun, replacement.id)
        assert unit is not None
        assert target_revision is not None
        assert unrelated_revision is not None
        assert invalidated_run is not None
        assert replacement_run is not None
        assert unit.active_revision_id == active_revision_id
        assert target_revision.state is StoredRevisionState.ABANDONED
        assert unrelated_revision.state is StoredRevisionState.STAGING
        assert invalidated_run.state is StoredScanState.CANCELLED
        assert replacement_run.state is StoredScanState.PENDING
