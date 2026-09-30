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


def test_directory_import_resolves_relative_assets_with_library_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    directory = root / "volume"
    directory.mkdir(parents=True)
    first = directory / "01.mp3"
    second = directory / "02.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    resource = {
        "payload": {"title": "Volume"},
        "assets": [
            {"relativePath": "volume/01.mp3", "size": 5},
            {"relativePath": "volume/02.mp3", "size": 6},
        ],
        "importTasks": [
            {
                "sourcePath": "volume",
                "assetPaths": ["volume/01.mp3", "volume/02.mp3"],
            }
        ],
    }
    snapshot = {"rootPath": str(root), "resources": [resource]}
    preparation = {
        "operationId": "writeback-1",
        "resourceId": "resource-1",
        "snapshotJson": json.dumps(snapshot),
    }

    targets = prepare_targets_from_snapshot(preparation)

    assert [target.source_path for target in targets] == [str(first), str(second)]
    assert [json.loads(target.payload_json)["sourceSize"] for target in targets] == [
        5,
        6,
    ]

    # Preparations queued before rootPath was stored use the claimed book's root.
    preparation["snapshotJson"] = json.dumps({"resources": [resource]})
    preparation["rootPath"] = str(root)
    assert [
        target.source_path for target in prepare_targets_from_snapshot(preparation)
    ] == [
        str(first),
        str(second),
    ]


def test_relative_writeback_path_cannot_escape_library_root(tmp_path: Path) -> None:
    snapshot = {
        "rootPath": str(tmp_path),
        "resources": [{"assets": [{"relativePath": "../outside.mp3"}]}],
    }
    with pytest.raises(ValueError, match="invalid library-relative writeback path"):
        prepare_targets_from_snapshot(
            {
                "operationId": "writeback-1",
                "resourceId": "resource-1",
                "snapshotJson": json.dumps(snapshot),
            }
        )
