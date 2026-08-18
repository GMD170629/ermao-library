from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError

from app.db.current.engine import create_current_engine
from app.db.current.runner import current_alembic_config, upgrade_current_schema

REVISION_0002 = "0002_catalog_scan_topology"
REVISION_0003 = "0003_catalog_watcher_reconcile"


def _upgrade_to(database_path: Path, revision: str) -> None:
    engine = create_current_engine(database_path)
    try:
        with engine.begin() as connection:
            config = current_alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def _version(database_path: Path) -> str:
    engine = create_current_engine(database_path)
    try:
        version_table = Table("alembic_version_v2", MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            value = connection.scalar(select(version_table.c.version_num))
            assert isinstance(value, str)
            return value
    finally:
        engine.dispose()


def _library_values(now: datetime) -> dict[str, object]:
    return {
        "id": "library-1",
        "name": "Library",
        "rootPath": "/library",
        "rootPathKey": "/library",
        "organizationMode": "FLAT",
        "topologyVersion": 1,
        "pathComparison": "SENSITIVE",
        "writePolicy": "READ_ONLY",
        "controlState": "ACTIVE",
        "observedHealth": "HEALTHY",
        "configRevision": 1,
        "topologyWriterFence": 0,
        "sourceMutationFence": 0,
        "nextScanGeneration": 1,
        "lastSuccessfulGeneration": None,
        "lastSuccessfulScanAt": None,
        "createdAt": now,
        "updatedAt": now,
    }


def _source_values(
    now: datetime,
    *,
    source_id: str,
    parent_id: str | None,
    local_name: str,
    local_name_key: str,
    entry_type: str,
    slot_state: str = "ACTIVE",
) -> dict[str, object]:
    return {
        "id": source_id,
        "libraryId": "library-1",
        "parentEntryId": parent_id,
        "localName": local_name,
        "localNameKey": local_name_key,
        "entryType": entry_type,
        "filesystemIdentity": f"identity:{source_id}",
        "sizeBytes": None,
        "modifiedNs": None,
        "lastSeenGeneration": 1,
        "absenceConfirmedAt": None,
        "childrenPresenceEpoch": 0,
        "nextChildrenPresenceEpoch": 0,
        "observedParentPresenceEpoch": None if parent_id is None else 0,
        "pendingObservedParentPresenceEpoch": None,
        "layoutState": "PRESENT",
        "slotState": slot_state,
        "createdAt": now,
        "updatedAt": now,
    }


def test_fresh_head_has_bounded_watcher_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)

    engine = create_current_engine(database_path)
    try:
        inspector = inspect(engine)
        assert {"LibraryWatcherState", "LibraryReconcileIntent"}.issubset(
            inspector.get_table_names()
        )
        source_columns = {
            value["name"] for value in inspector.get_columns("LibrarySourceEntry")
        }
        assert {
            "nextChildrenPresenceEpoch",
            "pendingObservedParentPresenceEpoch",
        }.issubset(source_columns)
        scan_columns = {
            value["name"] for value in inspector.get_columns("LibraryScanRun")
        }
        assert "watcherSequenceWatermark" in scan_columns
        revision_columns = {
            value["name"] for value in inspector.get_columns("TopologyUnitRevision")
        }
        assert "reconcileOriginId" in revision_columns

        intent_indexes = {
            value["name"]: value
            for value in inspector.get_indexes("LibraryReconcileIntent")
        }
        assert intent_indexes["LibraryReconcileIntent_one_running_idx"]["unique"]
        assert intent_indexes["LibraryReconcileIntent_one_pending_key_idx"]["unique"]
        source_indexes = {
            value["name"]: value
            for value in inspector.get_indexes("LibrarySourceEntry")
        }
        assert source_indexes["LibrarySourceEntry_live_raw_slot_idx"]["unique"]
    finally:
        engine.dispose()

    assert _version(database_path) == REVISION_0003


def test_explicit_empty_0002_upgrade_reaches_0003_and_is_repeatable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "current.sqlite3"
    _upgrade_to(database_path, REVISION_0002)
    assert _version(database_path) == REVISION_0002

    _upgrade_to(database_path, REVISION_0003)
    _upgrade_to(database_path, "head")

    assert _version(database_path) == REVISION_0003


def test_watcher_and_presence_constraints_reject_impossible_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    metadata = MetaData()
    library = Table("CatalogLibrary", metadata, autoload_with=engine)
    watcher = Table("LibraryWatcherState", metadata, autoload_with=engine)
    source = Table("LibrarySourceEntry", metadata, autoload_with=engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(insert(library).values(**_library_values(now)))
            connection.execute(
                insert(watcher).values(
                    libraryId="library-1",
                    latestSequence=0,
                    overflowThroughSequence=None,
                    fullRescanReason=None,
                    updatedAt=now,
                )
            )
            connection.execute(
                insert(source).values(
                    **_source_values(
                        now,
                        source_id="root",
                        parent_id=None,
                        local_name="$root",
                        local_name_key="$root",
                        entry_type="SYNTHETIC_ROOT",
                    )
                )
            )
            connection.execute(
                insert(source).values(
                    **_source_values(
                        now,
                        source_id="live",
                        parent_id="root",
                        local_name="Book",
                        local_name_key="book",
                        entry_type="FILE",
                    )
                )
            )
            connection.execute(
                insert(source).values(
                    **_source_values(
                        now,
                        source_id="retired",
                        parent_id="root",
                        local_name="Book",
                        local_name_key="book",
                        entry_type="FILE",
                        slot_state="RETIRED",
                    )
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                update(watcher)
                .where(watcher.c.libraryId == "library-1")
                .values(
                    overflowThroughSequence=1,
                    fullRescanReason="JOURNAL_CAPACITY",
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(source).values(
                    **_source_values(
                        now,
                        source_id="colliding-duplicate",
                        parent_id="root",
                        local_name="Book",
                        local_name_key="book",
                        entry_type="FILE",
                        slot_state="COLLIDING",
                    )
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                update(source)
                .where(source.c.id == "root")
                .values(
                    childrenPresenceEpoch=2,
                    nextChildrenPresenceEpoch=1,
                )
            )
    finally:
        engine.dispose()


def test_offline_0003_upgrade_contains_typed_schema_operations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(
        current_alembic_config(),
        f"{REVISION_0002}:{REVISION_0003}",
        sql=True,
    )
    output = capsys.readouterr().out

    for name in (
        "LibraryWatcherState",
        "LibraryReconcileIntent",
        "LibrarySourceEntry_presence_epoch_ck",
        "TopologyUnitRevision_origin_ck",
        "LibraryScanRun_watcher_watermark_ck",
    ):
        assert name in output
    assert REVISION_0003 in output
