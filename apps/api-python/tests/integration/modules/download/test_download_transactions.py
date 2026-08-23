from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

import app.bootstrap.download as download_bootstrap
from app.bootstrap.system import prepare_system_event
from app.models import LibraryBook, LibrarySourceNode
from app.models.import_pipeline import DownloadTask
from app.models.settings import SystemEvent, SystemSetting
from app.modules.download.application.dto import CreateDownloadTask
from tests.conftest import recreate_application_schema
from tests.support.sqlalchemy import StatementRecorder


def _prepare_schema(db_session) -> None:
    db_session.rollback()
    recreate_application_schema(db_session.get_bind())


def _seed_book(db_session) -> None:
    node = LibrarySourceNode(
        id="download-book-node",
        library_id="test-library",
        relative_path="download-book",
        path_key="v1:" + "a" * 64,
        name="download-book",
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    db_session.add(node)
    db_session.flush()
    db_session.add(
        LibraryBook(
            id="download-book",
            library_id="test-library",
            source_node_id=node.id,
        )
    )
    db_session.commit()


def _command(task_id: str) -> CreateDownloadTask:
    return CreateDownloadTask(
        id=task_id,
        source_id=None,
        search_record_id=None,
        book_id="download-book",
        task_type="http",
        status="queued",
        display_name="Prepared download",
        remote_ref="{}",
        save_path="/tmp/downloads",
        file_path=None,
        error_message=None,
        progress=0,
    )


def _event(task_id: str):
    return prepare_system_event(
        source="download",
        action="created",
        target_type="downloadTask",
        target_id=task_id,
        message="Download task created",
    )


def test_create_download_task_is_three_set_based_writes(db_session) -> None:
    _prepare_schema(db_session)
    _seed_book(db_session)
    command = _command("download-set-write")

    with StatementRecorder(db_session.get_bind()) as recorder:
        recorder.reset_after_warmup()
        result = download_bootstrap.create_download_task_command(
            db_session,
            command,
            last_target_path=command.save_path,
            event=_event(command.id),
        )

    assert result.id == command.id
    assert recorder.dml_count == 3
    task = db_session.get(DownloadTask, command.id)
    assert task is not None
    assert task.book_id == "download-book"
    assert (
        db_session.scalar(
            select(SystemSetting.value).where(
                SystemSetting.key == "library.lastDownloadTargetPath"
            )
        )
        == '"/tmp/downloads"'
    )
    assert db_session.scalar(
        select(SystemEvent.id).where(SystemEvent.target_id == command.id)
    )


def test_create_download_task_rolls_back_state_when_event_write_fails(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_schema(db_session)
    _seed_book(db_session)
    command = _command("download-atomic-rollback")

    def fail_event_write(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("event failure")

    monkeypatch.setattr(
        download_bootstrap,
        "write_prepared_system_events",
        fail_event_write,
    )

    with pytest.raises(RuntimeError, match="event failure"):
        download_bootstrap.create_download_task_command(
            db_session,
            command,
            last_target_path=command.save_path,
            event=_event(command.id),
        )

    assert db_session.get(DownloadTask, command.id) is None
    assert db_session.get(SystemSetting, "library.lastDownloadTargetPath") is None
