from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.backup.infrastructure.archive import BACKUP_TABLES
from app.modules.backup.infrastructure.persistence import (
    TABLE_MODELS,
    prepare_table_records,
    table_dependency_order,
    validate_restore_relationships,
)


def test_prepare_table_records_filters_unknown_fields_and_converts_timestamps() -> None:
    records = prepare_table_records(
        "SystemSetting",
        [
            {
                "key": "backup.test",
                "value": "enabled",
                "updatedAt": "2026-08-11T12:00:00+00:00",
                "unknown": "discarded",
            }
        ],
    )

    assert records == (
        {
            "key": "backup.test",
            "value": "enabled",
            "updatedAt": datetime.fromisoformat("2026-08-11T12:00:00+00:00"),
        },
    )


def test_prepare_table_records_rejects_invalid_resource_asset_scalar_type() -> None:
    with pytest.raises(
        ValueError,
        match="BACKUP_FIELD_TYPE_INVALID:LibraryResourceAsset.sequenceIndex",
    ):
        prepare_table_records(
            "LibraryResourceAsset",
            [{"id": "asset-invalid", "sequenceIndex": "not-an-integer"}],
        )


def test_validate_restore_relationships_rejects_dangling_resource_book() -> None:
    records_by_table = {
        "Library": ({"id": "library-a"},),
        "LibraryBook": ({"id": "book-a", "libraryId": "library-a"},),
        "LibraryReadableResource": (
            {
                "id": "resource-a",
                "bookId": "missing-book",
                "libraryId": "library-a",
            },
        ),
    }

    with pytest.raises(
        ValueError,
        match="BACKUP_FOREIGN_KEY_INVALID:LibraryReadableResource.bookId",
    ):
        validate_restore_relationships(records_by_table)


def test_backup_covers_source_tree_and_asset_metadata_owners() -> None:
    exported_tables = {table_name for _export_key, table_name in BACKUP_TABLES}

    assert {
        "LibrarySourceNode",
        "LibrarySourceNodeMetadata",
        "LibrarySourceNodeInterpretation",
        "LibraryResourceAssetMetadata",
    } <= exported_tables
    assert {
        "LibrarySourceNode",
        "LibrarySourceNodeMetadata",
        "LibrarySourceNodeInterpretation",
        "LibraryResourceAssetMetadata",
    } <= TABLE_MODELS.keys()

    for table_name in exported_tables:
        for constraint in TABLE_MODELS[table_name].__table__.foreign_key_constraints:
            assert constraint.referred_table.name in exported_tables, (
                f"{table_name} has an unowned backup FK to "
                f"{constraint.referred_table.name}"
            )

    ordered = table_dependency_order(exported_tables)
    positions = {table_name: ordered.index(table_name) for table_name in ordered}
    assert positions["Library"] < positions["LibrarySourceNode"]
    assert positions["LibrarySourceNode"] < positions["LibraryBook"]
    assert positions["LibraryBook"] < positions["LibraryReadableResource"]
    assert positions["LibraryReadableResource"] < positions["LibraryResourceAsset"]
    assert positions["LibraryResourceAsset"] < positions["LibraryResourceAssetMetadata"]


def test_validate_restore_relationships_rejects_dangling_source_node() -> None:
    with pytest.raises(
        ValueError,
        match="BACKUP_FOREIGN_KEY_INVALID:LibraryBook.sourceNodeId",
    ):
        validate_restore_relationships(
            {
                "Library": ({"id": "library-a"},),
                "LibraryBook": (
                    {
                        "id": "book-a",
                        "libraryId": "library-a",
                        "sourceNodeId": "missing-source-node",
                    },
                ),
                "LibrarySourceNode": (),
            }
        )


def test_validate_restore_relationships_checks_composite_library_owner() -> None:
    with pytest.raises(
        ValueError,
        match="BACKUP_FOREIGN_KEY_INVALID:LibraryBook.sourceNodeId",
    ):
        validate_restore_relationships(
            {
                "Library": ({"id": "library-a"}, {"id": "library-b"}),
                "LibrarySourceNode": (
                    {
                        "id": "source-a",
                        "libraryId": "library-a",
                        "physicalKind": "DIRECTORY",
                    },
                ),
                "LibraryBook": (
                    {
                        "id": "book-a",
                        "libraryId": "library-b",
                        "sourceNodeId": "source-a",
                    },
                ),
            }
        )


def test_validate_restore_relationships_ignores_unhashable_non_relationship_payloads() -> (
    None
):
    validate_restore_relationships(
        {
            "SystemSetting": (
                {
                    "key": "backup-json",
                    "value": {"title": "JSON metadata", "subjects": ["one", "two"]},
                },
            )
        }
    )
