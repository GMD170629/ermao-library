from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.backup.infrastructure.persistence import (
    prepare_table_records,
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
