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


def test_prepare_table_records_rejects_invalid_scalar_type() -> None:
    with pytest.raises(
        ValueError,
        match="BACKUP_FIELD_TYPE_INVALID:LibraryWork.hidden",
    ):
        prepare_table_records(
            "LibraryWork",
            [{"id": "work-invalid", "hidden": "not-a-boolean"}],
        )


def test_validate_restore_relationships_rejects_dangling_foreign_key() -> None:
    records_by_table = {
        "LibraryWork": ({"id": "work-a"},),
        "LibraryVersion": (
            {"id": "version-a", "workId": "missing-work", "sourceKey": "version:a"},
        ),
    }

    with pytest.raises(
        ValueError,
        match="BACKUP_FOREIGN_KEY_INVALID:LibraryVersion.workId",
    ):
        validate_restore_relationships(records_by_table)


def test_validate_restore_relationships_ignores_unhashable_json_payloads() -> None:
    validate_restore_relationships(
        {
            "ImportTask": (
                {
                    "id": "import-json",
                    "recognizedMetadata": {
                        "title": "JSON metadata",
                        "subjects": ["one", "two"],
                    },
                },
            )
        }
    )
