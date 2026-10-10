import json
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta
from multiprocessing import get_context
from pathlib import Path

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select

import app.modules.system.infrastructure.runtime as system_runtime
from app.bootstrap.system import (
    clear_system_events,
    get_setting,
    maintain_system_events,
    persist_system_settings_update,
    prepare_system_event,
    record_system_event,
    system_event_size_bytes,
    upsert_setting,
    upsert_settings,
)
from app.core.exception_diagnostics import (
    capture_exception,
    exception_diagnostic_boundary,
    record_exception,
)
from app.models.settings import SystemEvent
from app.modules.system.infrastructure import log_files
from app.modules.system.infrastructure.events import (
    get_system_event,
    list_system_events_page,
)


def test_default_records_only_error_without_database_statements(db_session):
    statements = []
    sqlalchemy_event.listen(db_session.bind, "before_cursor_execute", lambda *args: statements.append(args[2]))
    for level in ("debug", "info", "warning", "error"):
        record_system_event(db_session, level=level, source="system", action=level, message=level)
    assert not list(log_files.read_log_events())
    db_session.commit()
    assert [event["level"] for event in log_files.read_log_events()] == ["error"]
    assert statements == []
    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 0
    assert log_files.log_settings() == {"retentionDays": 3, "minimumLevel": "error"}


def test_configured_levels_and_full_unicode_messages(db_session):
    log_files.save_log_settings(3, "debug")
    message = "秘密-test-token=/private/path\n" * 30_000
    ids = [record_system_event(db_session, level=level, source="system", action=level,
        message=message, metadata={"payload": message}) for level in ("debug", "info", "warn", "error")]
    db_session.commit()
    assert len(list(log_files.log_directory().glob("api/*.jsonl"))) == 1
    assert [get_system_event(db_session, item)["level"] for item in ids] == ["debug", "info", "warning", "error"]
    for item in ids:
        assert get_system_event(db_session, item)["message"] == message
        assert get_system_event(db_session, item)["metadata"]["payload"] == message
    assert system_event_size_bytes(db_session) > len(message)
    assert clear_system_events(db_session) == 4
    assert list(log_files.read_log_events()) == []


def test_audit_commit_rollback_and_savepoint_semantics(db_session):
    log_files.save_log_settings(3, "info")
    def write(message):
        return record_system_event(db_session, source="system", action="audit", message=message)
    root_id = write("root")
    nested = db_session.begin_nested()
    rolled_back_id = write("nested rollback")
    nested.rollback()
    nested = db_session.begin_nested()
    committed_id = write("nested commit")
    nested.commit()
    assert list(log_files.read_log_events()) == []
    db_session.commit()
    assert {row["id"] for row in log_files.read_log_events()} == {root_id, committed_id}
    assert get_system_event(db_session, rolled_back_id) is None
    write("rollback")
    db_session.rollback()
    assert {row["id"] for row in log_files.read_log_events()} == {root_id, committed_id}
    write("close")
    db_session.close()
    assert {row["id"] for row in log_files.read_log_events()} == {root_id, committed_id}


def test_retention_counts_calendar_days_including_today(db_session):
    today = datetime.now().astimezone().date()
    for runtime in ("api", "web"):
        directory = log_files.log_directory() / runtime
        directory.mkdir(parents=True)
        for age in range(5):
            (directory / f"{today - timedelta(days=age)}.jsonl").write_text("", encoding="utf-8")
        (directory / "unrelated.txt").write_text("keep", encoding="utf-8")
    result = maintain_system_events(db_session)
    assert result["deleted"] == 4
    assert len(list(log_files.log_directory().glob("*/*.jsonl"))) == 6
    assert maintain_system_events(db_session, 1)["deleted"] == 4
    assert len(list(log_files.log_directory().glob("*/*.jsonl"))) == 2
    assert len(list(log_files.log_directory().glob("*/unrelated.txt"))) == 2


@pytest.mark.parametrize("days", [0, -1, 366, True, 2.5])
def test_invalid_retention_does_not_replace_settings(days):
    with pytest.raises(ValueError):
        log_files.save_log_settings(days, "error")
    assert log_files.log_settings()["retentionDays"] == 3


def test_errors_persist_without_opening_database_and_deduplicate():
    def forbidden_factory():
        raise AssertionError("A log must not open a database session")
    message = "raw-secret-test" * 20_000
    logger = logging.getLogger("test.daily")
    with exception_diagnostic_boundary(logger, "test.failed", session_factory=forbidden_factory):
        try:
            raise ValueError(message)
        except ValueError as error:
            capture_exception(error)
            record_exception(logger, "test.failed", error, session_factory=forbidden_factory)
            record_exception(logger, "test.failed", error, session_factory=forbidden_factory)
        assert list(log_files.read_log_events()) == []
    rows = list(log_files.read_log_events())
    assert len(rows) == 1
    assert rows[0]["message"] == message
    assert message in rows[0]["metadata"]["diagnostics"]["traceback"]


def test_required_missing_file_is_an_error_and_optional_probe_is_explicit_debug():
    capture_exception(FileNotFoundError("required source missing"))
    capture_exception(FileNotFoundError("optional sidecar missing"), level="debug")
    assert [row["message"] for row in log_files.read_log_events()] == ["required source missing"]
    log_files.save_log_settings(3, "debug")
    capture_exception(FileNotFoundError("optional sidecar missing"), level="debug")
    assert {row["level"] for row in log_files.read_log_events()} == {"debug", "error"}


def test_file_outlet_failure_cannot_change_business_commit(db_session, monkeypatch, capsys):
    def broken_lock():
        raise OSError("test disk full")
    monkeypatch.setattr(log_files, "log_file_lock", broken_lock)
    prepared = prepare_system_event(source="system", action="audit", message="original raw error", level="error")
    persist_system_settings_update(db_session, setting_values={"committed": True}, clear_keys=(), event=prepared)
    assert get_setting(db_session, "committed") is True
    stderr = capsys.readouterr().err
    assert "test disk full" in stderr and "original raw error" in stderr


def test_parallel_append_preserves_complete_records(db_session):
    from app.modules.system.infrastructure.events import event_record
    def write(index):
        return log_files.append_log_event(event_record(prepare_system_event(
            source="system", action="parallel", level="error", message=f"{index}:" + "长堆栈\n" * 20_000)))
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert all(workers.map(write, range(12)))
    rows = list(log_files.read_log_events())
    assert len(rows) == 12
    assert len({row["id"] for row in rows}) == 12
    assert all(row["message"].endswith("长堆栈\n" * 20_000) for row in rows)


def _append_from_process(storage_root: str, index: int) -> bool:
    from app.modules.system.infrastructure.events import event_record

    log_files.configure_log_directory(Path(storage_root))
    return log_files.append_log_event(event_record(prepare_system_event(
        source="worker" if index % 2 else "api", action="process", level="error",
        message=f"{index}:" + "完整堆栈\n" * 20_000,
    )))


def test_api_worker_processes_share_one_complete_daily_file():
    root = str(log_files.log_directory().parent)
    with ProcessPoolExecutor(max_workers=3, mp_context=get_context("spawn")) as pool:
        assert all(pool.map(_append_from_process, [root] * 9, range(9)))
    rows = list(log_files.read_log_events())
    assert len(rows) == len({row["id"] for row in rows}) == 9
    assert {row["source"] for row in rows} == {"api", "worker"}
    assert all(row["message"].endswith("完整堆栈\n" * 20_000) for row in rows)
    assert len(list(log_files.log_directory().glob("api/*.jsonl"))) == 1


def test_midnight_switches_file_and_first_write_prunes_expired_days(monkeypatch):
    current = datetime(2026, 10, 10, 23, 59, 59).astimezone()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current

    monkeypatch.setattr(log_files, "datetime", Clock)
    for index in range(4):
        assert log_files.append_log_event({"id": str(index), "level": "error", "message": "full"})
        current += timedelta(days=1)
    files = sorted(path.name for path in log_files.log_directory().glob("api/*.jsonl"))
    assert files == ["2026-10-11.jsonl", "2026-10-12.jsonl", "2026-10-13.jsonl"]


def test_file_query_filters_paginates_and_reads_web_records(db_session):
    log_files.save_log_settings(3, "debug")
    for number in range(7):
        record_system_event(db_session, source="system", action="test", level="error", message=f"failure {number}")
    db_session.commit()
    page = list_system_events_page(db_session, page=2, page_size=3, search="failure", level="error")
    assert page.total == 7 and len(page.events) == 3 and page.page == 2
    assert len(list_system_events_page(db_session, page=99, page_size=3).events) == 1
    latest = page.events[0] | {"id": "web-only", "source": "web", "createdAt": datetime.now().astimezone().isoformat()}
    web = log_files.log_directory() / "web"
    web.mkdir()
    (web / f"{datetime.now().astimezone().date()}.jsonl").write_text(json.dumps(latest) + "\n", encoding="utf-8")
    assert get_system_event(db_session, "web-only")["source"] == "web"


def test_system_setting_kv_round_trip(db_session):
    upsert_setting(db_session, "readerTheme", "dark")
    db_session.commit()
    assert get_setting(db_session, "readerTheme") == "dark"


def test_system_settings_batch_uses_one_upsert_statement(db_session):
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    sqlalchemy_event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        upsert_settings(
            db_session,
            {f"batch.setting.{index}": index for index in range(25)},
        )
    finally:
        sqlalchemy_event.remove(
            db_session.bind, "before_cursor_execute", capture_statement
        )

    assert sum(statement.startswith("INSERT") for statement in statements) == 1


def test_system_settings_and_audit_event_commit_atomically(db_session, monkeypatch):
    prepared_event = prepare_system_event(
        source="system",
        action="settings.updated",
        message="Atomic settings update",
    )

    def fail_event_write(db, events):
        raise RuntimeError("event persistence failed")

    monkeypatch.setattr(
        system_runtime,
        "write_prepared_system_events",
        fail_event_write,
    )
    with pytest.raises(RuntimeError, match="event persistence failed"):
        persist_system_settings_update(
            db_session,
            setting_values={"atomic.setting": "new value"},
            clear_keys=(),
            event=prepared_event,
        )

    assert get_setting(db_session, "atomic.setting") is None


def test_system_settings_only_write_business_settings_to_database(db_session):
    prepared_event = prepare_system_event(
        source="system",
        action="settings.updated",
        message="Bulk settings update",
    )
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        if context.isinsert or context.isupdate or context.isdelete:
            statements.append(statement.strip().upper())

    sqlalchemy_event.listen(
        db_session.bind,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        persist_system_settings_update(
            db_session,
            setting_values={f"bulk.setting.{index}": index for index in range(100)},
            clear_keys=(),
            event=prepared_event,
        )
    finally:
        sqlalchemy_event.remove(
            db_session.bind,
            "before_cursor_execute",
            capture_statement,
        )

    assert len(statements) == 1


def test_diagnostic_metadata_retains_complete_causes_without_correlation():
    import errno

    from app.modules.system.domain.events import prepare_event_metadata

    cause = {
        "type": "OSError",
        "message": "No space left on device",
        "errno": errno.ENOSPC,
        "errorName": "ENOSPC",
    }
    metadata = {
        "requestId": "request-id",
        "taskId": "task-id",
        "operationId": "operation-id",
        "targetOrdinal": 7,
        "attempt": 3,
        "parentDiagnosticId": "diag-original",
        "diagnostics": {
            "id": "diag-failed",
            "exceptionType": "FileMoveError",
            "directException": {
                "type": "FileMoveError",
                "message": "FILE_PUBLISH_FAILED",
            },
            "directCause": cause,
            "rootCause": cause,
            "causeStatus": "PROVIDED",
            "contextProvided": True,
            "contextsTruncated": False,
            "contexts": [{"type": "ValueError", "message": "earlier failure", "relationship": "context", "chainIndex": 2, "parentIndex": 0}],
            "traceback": "long trace" * 20000,
        },
    }
    clipped = prepare_event_metadata(metadata)
    assert "truncated" not in clipped
    assert clipped["diagnostics"]["traceback"] == metadata["diagnostics"]["traceback"]
    for key in (
        "requestId",
        "taskId",
        "operationId",
        "parentDiagnosticId",
        "targetOrdinal",
    ):
        assert key not in clipped
    assert clipped["diagnostics"]["directCause"] == cause
    assert clipped["diagnostics"]["rootCause"] == cause
    assert clipped["diagnostics"]["contextProvided"] is True
    assert clipped["diagnostics"]["contextsTruncated"] is False
    assert clipped["diagnostics"]["contexts"] == metadata["diagnostics"]["contexts"]
