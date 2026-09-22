"""Real file-operation failures retain their observed cause through task state changes."""

import errno
import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.infrastructure.exclusive_rename import exclusive_rename
from app.models import SystemEvent
from app.modules.library.application.file_move_worker import FileMoveWorker
from app.modules.library.infrastructure.file_move_io import SystemMovePublication
from app.modules.metadata.application.standard_writeback_maintenance import (
    MaintainStandardBackups,
)
from tests.integration.modules.automation.test_move_execution import (
    executor,
    failure_diagnostics,
    prepare,
)


def diagnostic_events(db, action):
    db.rollback()
    return list(db.scalars(select(SystemEvent).where(SystemEvent.action == action)))


def test_recovery_snapshot_rollback_failure_keeps_observation_and_secondary_cause(
    db_session, tmp_path, caplog
):
    actor, _root, store = prepare(db_session, tmp_path)
    store.checkpoint("operation", 0, "PREPARING", 3500)
    db_session.commit()

    class UnitOfWork:
        failed = False

        def rollback(self):
            if not self.failed:
                self.failed = True
                raise OSError(errno.EIO, "injected recovery rollback failure")
            db_session.rollback()

        def commit(self):
            db_session.commit()

    worker = FileMoveWorker(
        store,
        executor(db_session, store, SystemMovePublication(), lambda _: actor),
        UnitOfWork(),
        lambda: 4000,
        diagnostics=failure_diagnostics(db_session),
    )
    with pytest.raises(OSError, match="recovery rollback failure"):
        worker.process_once()
    observed = diagnostic_events(db_session, "file_move.previous_result_unavailable")
    secondary = diagnostic_events(db_session, "file_move.worker_failed")
    assert len(observed) == len(secondary) == 1
    details = secondary[0].metadata_json
    assert details["parentDiagnosticId"] == observed[0].id
    assert details["step"] == "release_recovery_snapshot"
    assert details["diagnostics"]["rootCause"]["errno"] == errno.EIO
    assert "injected recovery rollback failure" in caplog.text
    assert store.execution("operation").stages == ("PREPARING",)


@pytest.mark.parametrize(
    "error_number",
    [
        errno.EXDEV,
        errno.EACCES,
        errno.EROFS,
        errno.ENOSPC,
        errno.EIO,
        errno.EEXIST,
        errno.EINVAL,
        errno.ENOSYS,
    ],
)
def test_exclusive_rename_failure_survives_conversion_and_is_queryable(
    db_session, tmp_path, monkeypatch, caplog, error_number
):
    actor, root, store = prepare(db_session, tmp_path)

    def rename(*_args):
        return -1

    monkeypatch.setattr(
        "app.infrastructure.exclusive_rename.ctypes.CDLL",
        lambda *_args, **_kwargs: SimpleNamespace(
            renameat2=rename, renameatx_np=rename
        ),
    )
    monkeypatch.setattr(
        "app.infrastructure.exclusive_rename.ctypes.get_errno", lambda: error_number
    )

    class Files(SystemMovePublication):
        def publish(self, move):
            exclusive_rename(1, "source", 2, "destination")

    executor(db_session, store, Files(), lambda _: actor).execute("operation")
    events = diagnostic_events(db_session, "file_move.target_failed")
    assert len(events) == 1
    event = events[0]
    details = event.metadata_json
    assert details["operationId"] == "operation"
    assert details["targetOrdinal"] == 0
    assert details["step"] == "publish_files"
    assert details["diagnostics"]["rootCause"]["errno"] == error_number
    assert (
        details["diagnostics"]["rootCause"]["errorName"]
        == errno.errorcode[error_number]
    )
    assert details["diagnostics"]["directCause"]["message"] == str(
        OSError(error_number, os.strerror(error_number))
    )
    assert event.id in caplog.text
    assert os.strerror(error_number) in caplog.text
    assert str(root) not in json.dumps(event.metadata_json)
    assert store.execution("operation").stages == ("RECOVERY_REQUIRED",)


def test_reused_exception_for_two_targets_has_distinct_correlated_records(
    db_session, tmp_path, caplog
):
    actor, _, store = prepare(db_session, tmp_path, batch=True)
    failure = OSError(errno.EIO, "injected disk I/O failure")

    class Files(SystemMovePublication):
        calls = 0

        def publish(self, move):
            self.calls += 1
            if self.calls < 3:
                raise failure
            return super().publish(move)

    executor(db_session, store, Files(), lambda _: actor).execute("operation")
    events = diagnostic_events(db_session, "file_move.target_failed")
    assert len(events) == 2
    assert len({event.id for event in events}) == 2
    assert {event.metadata_json["targetOrdinal"] for event in events} == {
        0,
        1,
    }
    assert all(event.id in caplog.text for event in events)
    assert store.execution("operation").stages == (
        "RECOVERY_REQUIRED",
        "RECOVERY_REQUIRED",
        "COMPLETED",
    )


def test_rollback_failure_does_not_erase_original_publication_diagnostic(
    db_session, tmp_path, caplog
):
    actor, _, store = prepare(db_session, tmp_path)
    failed = False

    class Files(SystemMovePublication):
        def publish(self, move):
            nonlocal failed
            failed = True
            raise OSError(errno.ENOSPC, "no space at publication")

    class UnitOfWork:
        def commit(self):
            db_session.commit()

        def rollback(self):
            if failed:
                raise RuntimeError("injected rollback connection failure")
            db_session.rollback()

    command = replace(
        executor(db_session, store, Files(), lambda _: actor), uow=UnitOfWork()
    )
    with pytest.raises(RuntimeError, match="rollback connection"):
        command.execute("operation")
    original = diagnostic_events(db_session, "file_move.target_failed")
    secondary = diagnostic_events(db_session, "file_move.rollback_failed")
    assert len(original) == len(secondary) == 1
    assert secondary[0].metadata_json["parentDiagnosticId"] == original[0].id
    assert (
        original[0].metadata_json["diagnostics"]["rootCause"]["errno"] == errno.ENOSPC
    )
    assert "injected rollback connection failure" in json.dumps(
        secondary[0].metadata_json
    )
    assert original[0].id in caplog.text and secondary[0].id in caplog.text


def test_writeback_backup_cleanup_failure_is_logged_before_retry_state(
    db_session, caplog
):
    class Store:
        failed = None

        def expired_backups(self, _now):
            return (
                (
                    "write-operation",
                    0,
                    SimpleNamespace(targets=[SimpleNamespace(file=object())]),
                    object(),
                ),
            )

        def backup_cleanup_result(self, operation_id, ordinal, now, *, failed):
            self.failed = failed

    class Files:
        def clear_backup(self, target, proof):
            raise PermissionError(errno.EACCES, "backup deletion denied")

    store = Store()
    MaintainStandardBackups(
        store, Files(), db_session, lambda: 1000, failure_diagnostics(db_session)
    ).execute()
    events = diagnostic_events(db_session, "standard_write.backup_cleanup_failed")
    assert store.failed is True and len(events) == 1
    details = events[0].metadata_json
    assert details["operationId"] == "write-operation"
    assert details["step"] == "clear_backup"
    assert details["diagnostics"]["rootCause"]["errno"] == errno.EACCES
    assert events[0].id in caplog.text
