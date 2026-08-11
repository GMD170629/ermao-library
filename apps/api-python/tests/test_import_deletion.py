from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from app.modules.imports.application.deletion import (
    ImportDeletionDatabaseResult,
    PreparedImportDeletion,
    execute_import_deletion,
)
from app.modules.imports.infrastructure.deletion_files import (
    LocalImportDeletionFiles,
)


@dataclass
class RecordingUnitOfWork:
    commits: int = 0
    rollbacks: int = 0
    releases: int = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def release(self) -> None:
        self.releases += 1


class FailingDeletionStore:
    def write(self, prepared: PreparedImportDeletion) -> ImportDeletionDatabaseResult:
        assert prepared.task_id == "task-1"
        raise RuntimeError("database commit failed")


class SuccessfulDeletionStore:
    def write(self, prepared: PreparedImportDeletion) -> ImportDeletionDatabaseResult:
        assert prepared.task_id == "task-1"
        return ImportDeletionDatabaseResult(True, False, False, 0, None)


def test_import_deletion_restores_quarantined_file_when_database_fails(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"book")
    files = LocalImportDeletionFiles(tmp_path, [tmp_path])
    unit_of_work = RecordingUnitOfWork()

    with pytest.raises(RuntimeError, match="database commit failed"):
        execute_import_deletion(
            unit_of_work,
            files,
            FailingDeletionStore(),
            PreparedImportDeletion("task-1", (str(source),), None, ()),
        )

    assert source.read_bytes() == b"book"
    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1
    assert unit_of_work.releases == 1
    assert not (tmp_path / ".import-delete-manifests").exists()


def test_import_deletion_finalizes_files_only_after_database_success(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"book")
    files = LocalImportDeletionFiles(tmp_path, [tmp_path])
    unit_of_work = RecordingUnitOfWork()

    result, cleanup = execute_import_deletion(
        unit_of_work,
        files,
        SuccessfulDeletionStore(),
        PreparedImportDeletion("task-1", (str(source),), None, ()),
    )

    assert result.deleted is True
    assert cleanup.deleted_files == 1
    assert cleanup.failures == ()
    assert not source.exists()
    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 0
    assert unit_of_work.releases == 1


def test_import_deletion_recovery_uses_owner_record_state(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"book")
    files = LocalImportDeletionFiles(tmp_path, [tmp_path])
    files.quarantine("task-1", [str(source)])

    restored, finalized = files.recover_pending(
        database_record_exists=lambda task_id: task_id == "task-1"
    )

    assert (restored, finalized) == (1, 0)
    assert source.read_bytes() == b"book"
