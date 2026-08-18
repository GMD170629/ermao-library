from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, insert, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.current.engine import create_current_engine
from app.db.current.runner import current_alembic_config, upgrade_current_schema

REVISION_0003 = "0003_catalog_watcher_reconcile"
REVISION_0004 = "0004_catalog_content_processing"
_DIGEST = f"sha256:{'a' * 64}"


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


def _library(now: datetime) -> dict[str, object]:
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
        "lastSuccessfulGeneration": 1,
        "lastSuccessfulScanAt": now,
        "createdAt": now,
        "updatedAt": now,
    }


def _volume(volume_id: str, now: datetime, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": volume_id,
        "libraryId": "library-1",
        "readingMorphology": "REFLOWABLE",
        "contentState": "PENDING",
        "contentRevision": 0,
        "requiredManifestRevision": 0,
        "optionalManifestRevision": 0,
        "metadataRevision": 0,
        "requiredManifestDigest": None,
        "publicationFingerprint": None,
        "createdAt": now,
        "updatedAt": now,
    }
    values.update(changes)
    return values


def _source(
    source_id: str,
    now: datetime,
    *,
    parent_id: str | None,
    entry_type: str,
) -> dict[str, object]:
    is_root = parent_id is None
    return {
        "id": source_id,
        "libraryId": "library-1",
        "parentEntryId": parent_id,
        "localName": "$root" if is_root else "book.epub",
        "localNameKey": "$root" if is_root else "book.epub",
        "entryType": entry_type,
        "filesystemIdentity": f"identity:{source_id}",
        "sizeBytes": None if is_root else 123,
        "modifiedNs": None if is_root else 456,
        "lastSeenGeneration": 1,
        "absenceConfirmedAt": None,
        "childrenPresenceEpoch": 0,
        "nextChildrenPresenceEpoch": 0,
        "observedParentPresenceEpoch": None if is_root else 0,
        "pendingObservedParentPresenceEpoch": None,
        "layoutState": "PRESENT",
        "slotState": "ACTIVE",
        "createdAt": now,
        "updatedAt": now,
    }


def _content_fact(now: datetime, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "libraryId": "library-1",
        "sourceEntryId": "source-1",
        "inputRevision": 1,
        "workRevision": 0,
        "digestInputRevision": None,
        "admission": "PRIMARY",
        "sourceFormat": "EPUB",
        "filesystemIdentity": "identity:source-1",
        "deviceId": 1,
        "fileId": 2,
        "sizeBytes": 123,
        "modifiedNs": 456,
        "policyVersion": 1,
        "originKind": "FULL_SCAN",
        "originId": "scan-1",
        "originSequence": 1,
        "availableAt": now,
        "state": "PENDING",
        "contentDigest": None,
        "leaseOwner": None,
        "leaseExpiresAt": None,
        "createdAt": now,
        "updatedAt": now,
    }
    values.update(changes)
    return values


def test_fresh_head_has_content_processing_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)

    engine = create_current_engine(database_path)
    try:
        inspector = inspect(engine)
        assert {
            "ContentTopologyProjectionState",
            "SourceContentFact",
            "VolumeManifestHeader",
            "VolumeManifestEntry",
            "VolumeProcessingFact",
        }.issubset(inspector.get_table_names())
        projection_state_primary_key = inspector.get_pk_constraint(
            "ContentTopologyProjectionState"
        )
        assert projection_state_primary_key["constrained_columns"] == ["libraryId"]
        projection_state_foreign_keys = inspector.get_foreign_keys(
            "ContentTopologyProjectionState"
        )
        assert len(projection_state_foreign_keys) == 1
        assert projection_state_foreign_keys[0]["referred_table"] == ("CatalogLibrary")
        assert projection_state_foreign_keys[0]["options"] == {"ondelete": "CASCADE"}
        projection_state_indexes = {
            value["name"]: value
            for value in inspector.get_indexes("ContentTopologyProjectionState")
        }
        assert "ContentTopologyProjectionState_pending_idx" in projection_state_indexes
        header_indexes = {
            value["name"]: value
            for value in inspector.get_indexes("VolumeManifestHeader")
        }
        assert header_indexes["VolumeManifestHeader_one_active_idx"]["unique"]
        assert header_indexes["VolumeManifestHeader_one_staging_idx"]["unique"]
        header_foreign_keys = inspector.get_foreign_keys("VolumeManifestHeader")
        topology_foreign_key = next(
            value
            for value in header_foreign_keys
            if value["referred_table"] == "TopologyUnitRevision"
        )
        assert topology_foreign_key["options"] == {"ondelete": "RESTRICT"}
        assert {
            value["name"] for value in inspector.get_check_constraints("LibraryVolume")
        }.issuperset(
            {
                "LibraryVolume_publication_fingerprint_ck",
                "LibraryVolume_required_revision_shape_ck",
                "LibraryVolume_revision_vector_ck",
                "volumecontentstate",
            }
        )
    finally:
        engine.dispose()

    assert _version(database_path) == REVISION_0004


def test_explicit_empty_0003_upgrade_is_repeatable(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    _upgrade_to(database_path, REVISION_0003)
    assert _version(database_path) == REVISION_0003

    _upgrade_to(database_path, REVISION_0004)
    _upgrade_to(database_path, "head")

    assert _version(database_path) == REVISION_0004


def test_volume_revision_axes_and_readiness_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    metadata = MetaData()
    library = Table("CatalogLibrary", metadata, autoload_with=engine)
    volume = Table("LibraryVolume", metadata, autoload_with=engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(insert(library).values(**_library(now)))
            connection.execute(
                insert(volume).values(
                    **_volume(
                        "content-ahead",
                        now,
                        contentRevision=2,
                        requiredManifestRevision=1,
                        requiredManifestDigest=_DIGEST,
                    )
                )
            )
            connection.execute(
                insert(volume).values(
                    **_volume(
                        "opening-pending",
                        now,
                        contentRevision=1,
                        requiredManifestRevision=1,
                        requiredManifestDigest=_DIGEST,
                        publicationFingerprint=None,
                    )
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(volume).values(
                    **_volume("invalid-state", now, contentState="BROKEN")
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(volume).values(
                    **_volume(
                        "bad-required-vector",
                        now,
                        contentRevision=0,
                        requiredManifestRevision=1,
                        requiredManifestDigest=f"sha256:{'a' * 64}",
                    )
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(volume).values(
                    **_volume(
                        "zero-with-digest",
                        now,
                        requiredManifestDigest=_DIGEST,
                    )
                )
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(volume).values(
                    **_volume(
                        "bad-fingerprint",
                        now,
                        publicationFingerprint="not-a-sha256",
                    )
                )
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("requested", "claimed", "applied", "cursor"),
    (
        (0, 0, 1, None),
        (1, 2, 0, None),
        (1, 0, 0, "volume-1"),
        (2, 1, 1, "volume-1"),
    ),
)
def test_content_topology_projection_epoch_shape_is_enforced(
    tmp_path: Path,
    requested: int,
    claimed: int,
    applied: int,
    cursor: str | None,
) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    metadata = MetaData()
    library = Table("CatalogLibrary", metadata, autoload_with=engine)
    state = Table("ContentTopologyProjectionState", metadata, autoload_with=engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(insert(library).values(**_library(now)))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(state).values(
                    libraryId="library",
                    requestedEpoch=requested,
                    claimedEpoch=claimed,
                    appliedEpoch=applied,
                    cursorVolumeId=cursor,
                    updatedAt=now,
                )
            )
    finally:
        engine.dispose()


def test_source_content_constraints_reject_impossible_facts(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    metadata = MetaData()
    library = Table("CatalogLibrary", metadata, autoload_with=engine)
    source = Table("LibrarySourceEntry", metadata, autoload_with=engine)
    content = Table("SourceContentFact", metadata, autoload_with=engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(insert(library).values(**_library(now)))
            connection.execute(
                insert(source).values(
                    **_source(
                        "root",
                        now,
                        parent_id=None,
                        entry_type="SYNTHETIC_ROOT",
                    )
                )
            )
            connection.execute(
                insert(source).values(
                    **_source(
                        "source-1",
                        now,
                        parent_id="root",
                        entry_type="FILE",
                    )
                )
            )
            connection.execute(insert(content).values(**_content_fact(now)))

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(content).values(
                    **_content_fact(
                        now,
                        sourceEntryId="source-1",
                        originKind="WATCHER",
                        originId="must-be-null",
                    )
                )
            )

        with engine.begin() as connection:
            connection.execute(
                content.delete().where(content.c.sourceEntryId == "source-1")
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(content).values(
                    **_content_fact(
                        now,
                        state="READY",
                        workRevision=1,
                        digestInputRevision=1,
                        contentDigest=f"sha256:{'A' * 64}",
                    )
                )
            )
    finally:
        engine.dispose()


def test_offline_0004_upgrade_contains_only_typed_schema_operations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(
        current_alembic_config(),
        f"{REVISION_0003}:{REVISION_0004}",
        sql=True,
    )
    output = capsys.readouterr().out

    for name in (
        "ContentTopologyProjectionState",
        "SourceContentFact",
        "VolumeManifestHeader",
        "VolumeManifestEntry",
        "VolumeProcessingFact",
        "VolumeManifestHeader_one_active_idx",
        "LibraryVolume_revision_vector_ck",
    ):
        assert name in output
    assert REVISION_0004 in output


def test_0004_source_does_not_cross_runtime_or_raw_sql_boundaries() -> None:
    revision_path = (
        Path(__file__).parents[3]
        / "app"
        / "db"
        / "alembic_current"
        / "versions"
        / "0004_catalog_content_processing.py"
    )
    source = revision_path.read_text(encoding="utf-8")

    for forbidden in (
        "app.modules",
        "app.models",
        "sqlite3",
        "sqlalchemy.text",
        "exec_driver_sql",
        "cursor(",
    ):
        assert forbidden not in source
