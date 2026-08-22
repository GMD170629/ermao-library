from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.metadata.application.writeback import (
    prepare_source_node_metadata_writeback_intent,
)
from app.modules.metadata.infrastructure.writeback_queue import (
    prepare_targets_from_snapshot,
)


def test_source_node_writeback_targets_the_directory_with_its_own_metadata() -> None:
    intent = prepare_source_node_metadata_writeback_intent(
        book_id="book-1",
        source_node_id="directory-1",
        source_directory="/library/book/volume-1",
        title="彩色珍藏版",
        description="目录简介",
        cover_path="covers/source-nodes/directory-1.webp",
        source_revision=datetime(2026, 8, 22, tzinfo=UTC),
    )

    snapshot = json.loads(intent.snapshot_json)
    assert snapshot == {
        "resources": [
            {
                "resourceId": "directory-1",
                "payload": {
                    "title": "彩色珍藏版",
                    "description": "目录简介",
                    "coverPath": "covers/source-nodes/directory-1.webp",
                },
                "assets": [],
                "importTasks": [{"sourcePath": "/library/book/volume-1"}],
            }
        ]
    }
    assert intent.book_id == "book-1"
    assert intent.source_node_id == "directory-1"
    assert intent.resource_id is None


def test_null_resource_id_selects_directory_opf_form(tmp_path: Path) -> None:
    source_directory = tmp_path / "volume"
    source_directory.mkdir()
    intent = prepare_source_node_metadata_writeback_intent(
        book_id="book-1",
        source_node_id="directory-1",
        source_directory=str(source_directory),
        title="彩色珍藏版",
        description=None,
        cover_path=None,
        source_revision=datetime(2026, 8, 22, tzinfo=UTC),
    )

    targets = prepare_targets_from_snapshot(
        {
            "operationId": intent.operation_id,
            "resourceId": intent.resource_id,
            "snapshotJson": intent.snapshot_json,
        }
    )

    assert len(targets) == 1
    assert targets[0].format == "DIRECTORY"


def test_null_resource_id_rejects_file_opf_form(tmp_path: Path) -> None:
    source_file = tmp_path / "volume.epub"
    source_file.write_bytes(b"not-an-epub")
    intent = prepare_source_node_metadata_writeback_intent(
        book_id="book-1",
        source_node_id="directory-1",
        source_directory=str(source_file),
        title="彩色珍藏版",
        description=None,
        cover_path=None,
        source_revision=datetime(2026, 8, 22, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="requires a directory target"):
        prepare_targets_from_snapshot(
            {
                "operationId": intent.operation_id,
                "resourceId": intent.resource_id,
                "snapshotJson": intent.snapshot_json,
            }
        )
