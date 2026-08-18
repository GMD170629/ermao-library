from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema
from app.modules.auth.infrastructure.persistence.models import CurrentUser
from app.modules.catalog.application.scan_ports import (
    DirectoryDiscoverySession,
    ScanUowFactory,
)
from app.modules.catalog.application.watcher_ports import WatcherUowFactory
from app.modules.catalog.infrastructure.admission import LocalSourceAdmissionAdapter
from app.modules.catalog.infrastructure.discovery import LocalDirectoryDiscoveryAdapter
from app.modules.catalog.infrastructure.files import LocalLibraryFilesystem
from app.modules.catalog.infrastructure.persistence import (
    LibrarySourceEntry,
    LibraryVolume,
    LibraryWork,
    SqlAlchemyLibraryGrantRepository,
    SqlAlchemyLibraryRepository,
    SqlAlchemyScanUowFactory,
    SqlAlchemyWatcherUowFactory,
    TopologyAssetMembership,
    TopologyUnit,
    TopologyUnitKind,
    TopologyVersionProjection,
    TopologyVolumeProjection,
    TopologyWorkProjection,
    UuidIdGenerator,
    VolumeAsset,
    WorkVersion,
)
from app.modules.catalog.public import (
    GrantLevel,
    Library,
    LibraryGrant,
    OrganizationMode,
    PathComparison,
    ReconcileRunDisposition,
    RecordWatcherEvent,
    RecordWatcherEventCommand,
    RunFullLibraryScan,
    RunFullLibraryScanCommand,
    RunNextReconcileSubtree,
    RunNextReconcileSubtreeCommand,
    StartFullLibraryScan,
    StartFullLibraryScanCommand,
    WatcherEntryHint,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WritePolicy,
)

NOW = datetime(2026, 8, 18, 15, tzinfo=UTC)
VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n9\n%%EOF\n"


class _Clock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    def advance(self) -> None:
        self.current += timedelta(seconds=1)


class _MonotonicClock:
    def seconds(self) -> float:
        return 0.0


class _SuccessorInjectingDiscovery:
    def __init__(self, factory: sessionmaker[Session], clock: _Clock) -> None:
        self._factory = factory
        self._clock = clock
        self._injected = False

    def open(self, *, canonical_root: str) -> DirectoryDiscoverySession:
        if not self._injected:
            self._injected = True
            RecordWatcherEvent(
                unit_of_work_factory=cast(
                    WatcherUowFactory, SqlAlchemyWatcherUowFactory(self._factory)
                ),
                id_generator=UuidIdGenerator(),
                clock=self._clock,
            ).execute(
                RecordWatcherEventCommand(
                    "library",
                    _root_identity(self._factory),
                    WatcherPathEvent(
                        WatcherPathEventKind.CREATE,
                        ("Work", "Edition", "newer-event.pdf"),
                        WatcherEntryHint.FILE,
                    ),
                )
            )
        return LocalDirectoryDiscoveryAdapter().open(canonical_root=canonical_root)


@dataclass(frozen=True, slots=True)
class _TopologySnapshot:
    source_ids_by_identity: dict[str, str]
    work_ids: frozenset[str]
    version_ids: frozenset[str]
    volume_ids: frozenset[str]
    asset_ids: frozenset[str]
    unit_ids: dict[TopologyUnitKind, str]
    active_revision_ids: dict[TopologyUnitKind, str]
    entity_updated_at: dict[str, datetime]
    work_projection: tuple[str, str]
    version_projection: tuple[str | None, str]
    volume_projection: tuple[str, str]


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "trusted-move.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine, clock=lambda: NOW)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(CurrentUser(id="admin", display_name="Admin", role="admin"))
    try:
        yield factory
    finally:
        engine.dispose()


def _seed_library(factory: sessionmaker[Session], root: Path) -> None:
    root_observation = LocalLibraryFilesystem().preflight(
        str(root), path_comparison=PathComparison.SENSITIVE
    )
    library = Library.create(
        library_id="library",
        name="Library",
        root=root_observation.registered_root,
        organization_mode=OrganizationMode.VOLUMES,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        now=NOW,
    ).activate(now=NOW)
    with factory.begin() as session:
        SqlAlchemyLibraryRepository(session).insert(library)
        assert SqlAlchemyLibraryGrantRepository(session).save_preserving_last_admin(
            LibraryGrant("admin", "library", GrantLevel.ADMIN, 1)
        )


def _full_scan(factory: sessionmaker[Session], clock: _Clock) -> None:
    started = StartFullLibraryScan(
        unit_of_work_factory=cast(ScanUowFactory, SqlAlchemyScanUowFactory(factory)),
        id_generator=UuidIdGenerator(),
        clock=clock,
    ).execute(StartFullLibraryScanCommand("admin", "library", "scan-worker"))
    RunFullLibraryScan(
        unit_of_work_factory=cast(ScanUowFactory, SqlAlchemyScanUowFactory(factory)),
        discovery=LocalDirectoryDiscoveryAdapter(),
        admission=LocalSourceAdmissionAdapter(),
        clock=clock,
        monotonic_clock=_MonotonicClock(),
    ).execute(RunFullLibraryScanCommand("library", started.scan_id, "scan-worker"))


def _root_identity(factory: sessionmaker[Session]) -> str:
    with factory() as session:
        identity = session.scalar(
            select(LibrarySourceEntry.filesystem_identity).where(
                LibrarySourceEntry.library_id == "library",
                LibrarySourceEntry.parent_entry_id.is_(None),
            )
        )
        assert identity is not None
        return identity


def _trusted_move(
    factory: sessionmaker[Session],
    clock: _Clock,
    *,
    source: tuple[str, ...],
    destination: tuple[str, ...],
    entry_type: WatcherMovedEntryType,
) -> None:
    RecordWatcherEvent(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(factory)
        ),
        id_generator=UuidIdGenerator(),
        clock=clock,
    ).execute(
        RecordWatcherEventCommand(
            "library",
            _root_identity(factory),
            WatcherMoveEvent(source, destination, entry_type),
        )
    )
    result = RunNextReconcileSubtree(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(factory)
        ),
        discovery=LocalDirectoryDiscoveryAdapter(),
        admission=LocalSourceAdmissionAdapter(),
        clock=clock,
        monotonic_clock=_MonotonicClock(),
    ).execute(RunNextReconcileSubtreeCommand("library", "reconcile-worker"))
    assert result.disposition is ReconcileRunDisposition.COMPLETED


def _snapshot(factory: sessionmaker[Session]) -> _TopologySnapshot:
    with factory() as session:
        sources = tuple(
            session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.library_id == "library",
                    LibrarySourceEntry.filesystem_identity.is_not(None),
                )
            )
        )
        works = tuple(session.scalars(select(LibraryWork)))
        versions = tuple(session.scalars(select(WorkVersion)))
        volumes = tuple(session.scalars(select(LibraryVolume)))
        assets = tuple(session.scalars(select(VolumeAsset)))
        units = tuple(session.scalars(select(TopologyUnit)))
        assert len(works) == len(versions) == len(volumes) == len(assets) == 1
        assert len(units) == 3
        unit_by_kind = {unit.unit_kind: unit for unit in units}
        active_revision_ids = {
            kind: unit.active_revision_id for kind, unit in unit_by_kind.items()
        }
        assert all(active_revision_ids.values())
        work_revision = cast(str, active_revision_ids[TopologyUnitKind.WORK_CONTAINER])
        version_revision = cast(
            str, active_revision_ids[TopologyUnitKind.VERSION_CONTAINER]
        )
        volume_kind = next(
            kind
            for kind in unit_by_kind
            if kind
            in {
                TopologyUnitKind.SINGLE_FILE_VOLUME,
                TopologyUnitKind.MULTI_ASSET_VOLUME,
            }
        )
        volume_revision = cast(str, active_revision_ids[volume_kind])
        work_projection = session.scalar(
            select(TopologyWorkProjection).where(
                TopologyWorkProjection.unit_revision_id == work_revision
            )
        )
        version_projection = session.scalar(
            select(TopologyVersionProjection).where(
                TopologyVersionProjection.unit_revision_id == version_revision
            )
        )
        volume_projection = session.scalar(
            select(TopologyVolumeProjection).where(
                TopologyVolumeProjection.unit_revision_id == volume_revision
            )
        )
        memberships = tuple(
            session.scalars(
                select(TopologyAssetMembership).where(
                    TopologyAssetMembership.unit_revision_id == volume_revision
                )
            )
        )
        assert work_projection is not None
        assert version_projection is not None
        assert volume_projection is not None
        assert len(memberships) == 1
        source_ids_by_identity = {
            cast(str, source.filesystem_identity): source.id for source in sources
        }
        assert len(source_ids_by_identity) == len(sources)
        return _TopologySnapshot(
            source_ids_by_identity=source_ids_by_identity,
            work_ids=frozenset(value.id for value in works),
            version_ids=frozenset(value.id for value in versions),
            volume_ids=frozenset(value.id for value in volumes),
            asset_ids=frozenset(value.id for value in assets),
            unit_ids={kind: unit.id for kind, unit in unit_by_kind.items()},
            active_revision_ids=cast(dict[TopologyUnitKind, str], active_revision_ids),
            entity_updated_at={
                f"work:{works[0].id}": works[0].updated_at,
                f"version:{versions[0].id}": versions[0].updated_at,
                f"volume:{volumes[0].id}": volumes[0].updated_at,
                f"asset:{assets[0].id}": assets[0].updated_at,
            },
            work_projection=(
                work_projection.source_name,
                work_projection.structure_key,
            ),
            version_projection=(
                version_projection.source_name,
                version_projection.structure_key,
            ),
            volume_projection=(
                volume_projection.source_name,
                volume_projection.structure_key,
            ),
        )


def _assert_all_stable_ids(
    previous: _TopologySnapshot, current: _TopologySnapshot
) -> None:
    assert current.source_ids_by_identity == previous.source_ids_by_identity
    assert current.work_ids == previous.work_ids
    assert current.version_ids == previous.version_ids
    assert current.volume_ids == previous.volume_ids
    assert current.asset_ids == previous.asset_ids
    assert current.unit_ids == previous.unit_ids


def _volume_kind(snapshot: _TopologySnapshot) -> TopologyUnitKind:
    return next(
        kind
        for kind in snapshot.unit_ids
        if kind
        in {
            TopologyUnitKind.SINGLE_FILE_VOLUME,
            TopologyUnitKind.MULTI_ASSET_VOLUME,
        }
    )


def test_trusted_layered_moves_preserve_ids_and_limit_revision_churn(
    database: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "library-root"
    volume = root / "Work" / "Edition" / "book.pdf"
    volume.parent.mkdir(parents=True)
    volume.write_bytes(VALID_PDF)
    clock = _Clock()
    _seed_library(database, root)
    _full_scan(database, clock)
    initial = _snapshot(database)
    volume_kind = _volume_kind(initial)

    renamed_work = root / "Renamed Work"
    (root / "Work").rename(renamed_work)
    clock.advance()
    _trusted_move(
        database,
        clock,
        source=("Work",),
        destination=("Renamed Work",),
        entry_type=WatcherMovedEntryType.DIRECTORY,
    )
    after_work = _snapshot(database)
    _assert_all_stable_ids(initial, after_work)
    assert (
        after_work.active_revision_ids[TopologyUnitKind.WORK_CONTAINER]
        != (initial.active_revision_ids[TopologyUnitKind.WORK_CONTAINER])
    )
    assert (
        after_work.active_revision_ids[TopologyUnitKind.VERSION_CONTAINER]
        == (initial.active_revision_ids[TopologyUnitKind.VERSION_CONTAINER])
    )
    assert (
        after_work.active_revision_ids[volume_kind]
        == (initial.active_revision_ids[volume_kind])
    )
    assert after_work.work_projection != initial.work_projection
    assert after_work.version_projection == initial.version_projection
    assert after_work.volume_projection == initial.volume_projection
    assert {
        key: value
        for key, value in after_work.entity_updated_at.items()
        if not key.startswith("work:")
    } == {
        key: value
        for key, value in initial.entity_updated_at.items()
        if not key.startswith("work:")
    }

    renamed_version = renamed_work / "Second Edition"
    (renamed_work / "Edition").rename(renamed_version)
    clock.advance()
    _trusted_move(
        database,
        clock,
        source=("Renamed Work", "Edition"),
        destination=("Renamed Work", "Second Edition"),
        entry_type=WatcherMovedEntryType.DIRECTORY,
    )
    after_version = _snapshot(database)
    _assert_all_stable_ids(after_work, after_version)
    assert (
        after_version.active_revision_ids[TopologyUnitKind.WORK_CONTAINER]
        == (after_work.active_revision_ids[TopologyUnitKind.WORK_CONTAINER])
    )
    assert (
        after_version.active_revision_ids[TopologyUnitKind.VERSION_CONTAINER]
        != (after_work.active_revision_ids[TopologyUnitKind.VERSION_CONTAINER])
    )
    assert (
        after_version.active_revision_ids[volume_kind]
        == (after_work.active_revision_ids[volume_kind])
    )
    assert after_version.work_projection == after_work.work_projection
    assert after_version.version_projection != after_work.version_projection
    assert after_version.volume_projection == after_work.volume_projection
    assert {
        key: value
        for key, value in after_version.entity_updated_at.items()
        if not key.startswith("version:")
    } == {
        key: value
        for key, value in after_work.entity_updated_at.items()
        if not key.startswith("version:")
    }

    renamed_volume = renamed_version / "renamed.pdf"
    (renamed_version / "book.pdf").rename(renamed_volume)
    clock.advance()
    _trusted_move(
        database,
        clock,
        source=("Renamed Work", "Second Edition", "book.pdf"),
        destination=("Renamed Work", "Second Edition", "renamed.pdf"),
        entry_type=WatcherMovedEntryType.FILE,
    )
    after_volume = _snapshot(database)
    _assert_all_stable_ids(after_version, after_volume)
    assert (
        after_volume.active_revision_ids[TopologyUnitKind.WORK_CONTAINER]
        == (after_version.active_revision_ids[TopologyUnitKind.WORK_CONTAINER])
    )
    assert (
        after_volume.active_revision_ids[TopologyUnitKind.VERSION_CONTAINER]
        == (after_version.active_revision_ids[TopologyUnitKind.VERSION_CONTAINER])
    )
    assert (
        after_volume.active_revision_ids[volume_kind]
        != (after_version.active_revision_ids[volume_kind])
    )
    assert after_volume.work_projection == after_version.work_projection
    assert after_volume.version_projection == after_version.version_projection
    assert after_volume.volume_projection != after_version.volume_projection


def test_full_scan_never_infers_hardlink_or_offline_rename_identity(
    database: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "library-root"
    original = root / "Work" / "Edition" / "book.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(VALID_PDF)
    clock = _Clock()
    _seed_library(database, root)
    _full_scan(database, clock)
    _snapshot(database)
    with database() as session:
        original_source = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library",
                LibrarySourceEntry.local_name == "book.pdf",
            )
        )
        assert original_source is not None
        original_source_id = original_source.id
        original_identity = original_source.filesystem_identity
        assert original_identity is not None

    hardlink = original.with_name("0-copy.pdf")
    os.link(original, hardlink)
    clock.advance()
    _full_scan(database, clock)
    with database() as session:
        linked_sources = tuple(
            session.scalars(
                select(LibrarySourceEntry).where(
                    LibrarySourceEntry.library_id == "library",
                    LibrarySourceEntry.filesystem_identity == original_identity,
                    LibrarySourceEntry.local_name.in_(("book.pdf", "0-copy.pdf")),
                )
            )
        )
        assert len(linked_sources) == 2
        assert len({value.id for value in linked_sources}) == 2
        assert (
            next(value.id for value in linked_sources if value.local_name == "book.pdf")
            == original_source_id
        )

    hardlink.unlink()
    offline = original.with_name("offline-renamed.pdf")
    original.rename(offline)
    clock.advance()
    _full_scan(database, clock)
    with database() as session:
        renamed_source = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library",
                LibrarySourceEntry.local_name == "offline-renamed.pdf",
            )
        )
        assert renamed_source is not None
        assert renamed_source.filesystem_identity == original_identity
        assert renamed_source.id != original_source_id


def test_newer_overlapping_event_prevents_running_move_from_rebinding_source_id(
    database: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "library-root"
    original = root / "Work" / "Edition" / "book.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(VALID_PDF)
    clock = _Clock()
    _seed_library(database, root)
    _full_scan(database, clock)
    with database() as session:
        original_source = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library",
                LibrarySourceEntry.local_name == "book.pdf",
            )
        )
        assert original_source is not None
        original_source_id = original_source.id

    renamed = original.with_name("renamed.pdf")
    original.rename(renamed)
    clock.advance()
    RecordWatcherEvent(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(database)
        ),
        id_generator=UuidIdGenerator(),
        clock=clock,
    ).execute(
        RecordWatcherEventCommand(
            "library",
            _root_identity(database),
            WatcherMoveEvent(
                ("Work", "Edition", "book.pdf"),
                ("Work", "Edition", "renamed.pdf"),
                WatcherMovedEntryType.FILE,
            ),
        )
    )
    result = RunNextReconcileSubtree(
        unit_of_work_factory=cast(
            WatcherUowFactory, SqlAlchemyWatcherUowFactory(database)
        ),
        discovery=_SuccessorInjectingDiscovery(database, clock),
        admission=LocalSourceAdmissionAdapter(),
        clock=clock,
        monotonic_clock=_MonotonicClock(),
    ).execute(RunNextReconcileSubtreeCommand("library", "old-worker"))

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    with database() as session:
        old_source = session.get(LibrarySourceEntry, original_source_id)
        renamed_source = session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == "library",
                LibrarySourceEntry.local_name == "renamed.pdf",
            )
        )
        assert old_source is not None and old_source.local_name == "book.pdf"
        assert renamed_source is not None and renamed_source.id != original_source_id
