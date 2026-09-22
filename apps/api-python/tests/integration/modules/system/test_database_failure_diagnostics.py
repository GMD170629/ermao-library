"""Real write-lock release and independent cause preservation at DB cleanup."""

import errno
import logging
import sqlite3

import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core import exception_diagnostics as diagnostics
from app.db.session import DiagnosticSession
from app.models.settings import SystemEvent, SystemSetting
from app.services import organize_service


@pytest.fixture
def database(tmp_path):
    url = f"sqlite:///{tmp_path / 'diagnostic.sqlite'}"
    engine = create_engine(url, connect_args={"timeout": 0.1})
    SystemEvent.__table__.create(engine)
    SystemSetting.__table__.create(engine)
    recorder = sessionmaker(bind=engine)
    diagnostics.configure_exception_storage(recorder)
    try:
        yield engine, recorder
    finally:
        diagnostics.reset_exception_storage()
        engine.dispose()


def test_real_business_write_is_released_before_event_insert(database, caplog):
    engine, recorder = database
    sequence = []
    with DiagnosticSession(engine) as session:
        event.listen(session, "after_rollback", lambda _: sequence.append("rollback"))
        event.listen(
            engine,
            "before_cursor_execute",
            lambda conn, cur, sql, *args: (
                sequence.append("insert_event")
                if 'INSERT INTO "SystemEvent"' in sql
                else None
            ),
        )
        session.execute(
            insert(SystemSetting).values(key="business", value="rollback me")
        )
        try:
            raise OSError(
                errno.EROFS, "read-only filesystem", "/private/library/title.epub"
            )
        except OSError:
            session.rollback()
    with recorder() as check:
        events = check.scalars(select(SystemEvent)).all()
        assert len(events) == 1
        assert check.get(SystemSetting, "business") is None
        metadata = events[0].metadata_json
        assert metadata["diagnostics"]["rootCause"]["errno"] == errno.EROFS
        assert events[0].id in caplog.text
    assert sequence == ["rollback", "insert_event"]
    assert "/private/library" not in caplog.text


def test_rollback_failure_keeps_original_and_secondary(database, monkeypatch, caplog):
    engine, recorder = database
    session = DiagnosticSession(engine)
    session.execute(insert(SystemSetting).values(key="business", value="rollback me"))
    original_rollback = Session.rollback

    def broken(self):
        raise OSError(errno.EIO, "rollback channel failed")

    monkeypatch.setattr(Session, "rollback", broken)
    try:
        with pytest.raises(OSError, match="rollback channel"):
            try:
                raise RuntimeError("original task failure")
            except RuntimeError:
                session.rollback()
    finally:
        monkeypatch.setattr(Session, "rollback", original_rollback)
        session.close()
    with recorder() as check:
        events = check.scalars(select(SystemEvent)).all()
    assert len(events) == 2
    first = next(row for row in events if row.message == "original task failure")
    secondary = next(row for row in events if "rollback channel failed" in row.message)
    assert secondary.metadata_json["parentDiagnosticId"] == first.id
    assert "original task failure" in caplog.text
    assert "rollback channel failed" in caplog.text


def test_broken_diagnostics_cannot_prevent_cleanup(database, monkeypatch, capsys):
    engine, _ = database
    session = DiagnosticSession(engine)
    session.execute(insert(SystemSetting).values(key="business", value="rollback me"))

    def broken(*args, **kwargs):
        raise TypeError("diagnostic adapter broken")

    monkeypatch.setattr("app.db.diagnostic_session.prepare_exception_diagnostic", broken)
    try:
        raise RuntimeError("original task failure")
    except RuntimeError:
        session.rollback()
    assert not session.in_transaction()
    session.close()
    output = capsys.readouterr().err
    assert "original task failure" in output
    assert "diagnostic adapter broken" in output


def test_each_busy_attempt_has_runtime_and_event(database, caplog):
    engine, recorder = database
    with diagnostics.exception_diagnostic_boundary(
        logging.getLogger(__name__), "test.task", context={"task_id": "retry-1"}
    ):
        for attempt in (1, 2):
            with DiagnosticSession(engine) as session:
                try:
                    raise OSError(errno.EAGAIN, "busy this attempt")
                except OSError as error:
                    diagnostics.record_exception(
                        logging.getLogger(__name__),
                        "retry",
                        error,
                        context={"attempt": attempt},
                    )
                    session.rollback()
    with recorder() as check:
        events = check.scalars(select(SystemEvent)).all()
    assert len(events) == 2
    assert {row.metadata_json["attempt"] for row in events} == {1, 2}
    assert all(row.metadata_json["taskId"] == "retry-1" for row in events)
    assert all(row.id in caplog.text for row in events)


def test_metadata_cache_busy_fallback_retains_actual_database_reason(
    database, monkeypatch, caplog
):
    engine, recorder = database
    cause = sqlite3.OperationalError("database is locked")
    cause.sqlite_errorcode = sqlite3.SQLITE_BUSY
    cause.sqlite_errorname = "SQLITE_BUSY"

    def fail(_db, _prepared):
        raise OperationalError("INSERT cache VALUES (?)", ("private query",), cause)

    monkeypatch.setattr(
        organize_service.metadata_cache, "write_prepared_cache_entry", fail
    )
    with Session(engine) as db:
        organize_service.external_metadata_cache_put(
            db,
            "douban",
            "query-key",
            {"candidates": [{"title": "Title"}]},
            cache_ready=True,
        )
    with recorder() as db:
        rows = db.scalars(select(SystemEvent)).all()
    assert len(rows) == 1
    assert (
        rows[0].metadata_json["diagnostics"]["rootCause"]["databaseCode"]
        == sqlite3.SQLITE_BUSY
    )
    assert rows[0].id in caplog.text
    assert "database is locked" in caplog.text
    assert "private query" not in caplog.text


def test_short_writer_rollback_error_preserves_original_cache_failure(
    database, monkeypatch, caplog
):
    engine, recorder = database

    def fail(_db, _prepared):
        raise ValueError("original cache adapter defect")

    def rollback_failed(_db):
        raise OSError(errno.EIO, "short writer rollback failed")

    monkeypatch.setattr(
        organize_service.metadata_cache, "write_prepared_cache_entry", fail
    )
    with monkeypatch.context() as patch:
        patch.setattr(Session, "rollback", rollback_failed)
        with (
            Session(engine) as db,
            pytest.raises(OSError, match="short writer rollback"),
        ):
            organize_service.external_metadata_cache_put(
                db,
                "douban",
                "query-key",
                {"candidates": [{"title": "Title"}]},
                cache_ready=True,
            )
    with recorder() as db:
        rows = db.scalars(select(SystemEvent)).all()
    first = next(row for row in rows if row.message == "original cache adapter defect")
    secondary = next(
        row for row in rows if "short writer rollback failed" in row.message
    )
    assert secondary.metadata_json["parentDiagnosticId"] == first.id
    assert first.id in caplog.text and secondary.id in caplog.text
