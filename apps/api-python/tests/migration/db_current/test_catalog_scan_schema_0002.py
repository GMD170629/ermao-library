from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, inspect, select

from app.db.current.engine import create_current_engine
from app.db.current.runner import current_alembic_config

REVISION_0001 = "0001_system_and_catalog_core"
REVISION_0002 = "0002_catalog_scan_topology"


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
            return connection.scalar(select(version_table.c.version_num))
    finally:
        engine.dispose()


def test_fresh_head_has_catalog_scan_topology_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    _upgrade_to(database_path, REVISION_0002)

    engine = create_current_engine(database_path)
    try:
        inspector = inspect(engine)
        version_columns = {
            column["name"]: column
            for column in inspector.get_columns("TopologyVersionProjection")
        }
        volume_columns = {
            column["name"]: column
            for column in inspector.get_columns("TopologyVolumeProjection")
        }
        scan_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryScanRun")
        }

        assert volume_columns["versionId"]["nullable"] is False
        assert version_columns["sourceName"]["nullable"] is True
        assert scan_columns["pathComparisonSnapshot"]["nullable"] is False

        volume_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "TopologyVolumeProjection"
            )
        }
        assert "TopologyVolumeProjection_revision_key" not in (
            volume_unique_constraints
        )
        assert volume_unique_constraints["TopologyVolumeProjection_parent_key"] == (
            "libraryId",
            "unitRevisionId",
            "volumeId",
        )

        version_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "TopologyVersionProjection"
            )
        }
        assert "TopologyVersionProjection_shape_ck" in version_checks

        source_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("LibrarySourceEntry")
        }
        work_item_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("LibraryScanWorkItem")
        }
        scan_indexes = {
            index["name"]: index for index in inspector.get_indexes("LibraryScanRun")
        }
        assert source_indexes["LibrarySourceEntry_generation_idx"] == (
            "libraryId",
            "lastSeenGeneration",
        )
        assert work_item_indexes["LibraryScanWorkItem_lease_recovery_idx"] == (
            "libraryId",
            "state",
            "leaseExpiresAt",
        )
        active_scan = scan_indexes["LibraryScanRun_one_active_idx"]
        assert active_scan["unique"] == 1
        assert tuple(active_scan["column_names"]) == ("libraryId",)
    finally:
        engine.dispose()

    assert _version(database_path) == REVISION_0002


def test_explicit_empty_0001_upgrade_reaches_0002_and_is_repeatable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "current.sqlite3"
    _upgrade_to(database_path, REVISION_0001)
    assert _version(database_path) == REVISION_0001

    _upgrade_to(database_path, REVISION_0002)
    _upgrade_to(database_path, REVISION_0002)

    assert _version(database_path) == REVISION_0002
    engine = create_current_engine(database_path)
    try:
        indexes = {
            index["name"] for index in inspect(engine).get_indexes("LibraryScanRun")
        }
        assert "LibraryScanRun_one_active_idx" in indexes
    finally:
        engine.dispose()


def test_offline_0002_upgrade_contains_all_new_schema_operations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(
        current_alembic_config(),
        f"{REVISION_0001}:{REVISION_0002}",
        sql=True,
    )
    output = capsys.readouterr().out

    for name in (
        "LibrarySourceEntry_generation_idx",
        "LibraryScanWorkItem_lease_recovery_idx",
        "LibraryScanRun_one_active_idx",
        "TopologyVersionProjection_shape_ck",
    ):
        assert name in output
    assert REVISION_0002 in output
