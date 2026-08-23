import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select

import app.bootstrap.system as system_bootstrap
from app.bootstrap.system import (
    get_setting,
    maintain_system_events,
    persist_system_settings_update,
    prepare_system_event,
    record_system_event,
    set_max_event_bytes,
    system_event_size_bytes,
    upsert_setting,
    upsert_settings,
    write_prepared_system_events,
)
from app.models.settings import SystemEvent


def test_record_system_event_normalizes_level_and_serializes_metadata(db_session):
    event_id = record_system_event(
        db_session,
        source="import",
        action="scan.completed",
        level="warn",
        message="扫描完成",
        metadata={"filesScanned": 3, "path": "/books"},
    )

    event = db_session.get(SystemEvent, event_id)
    assert event is not None
    assert event.level == "warning"
    assert event.source == "import"
    assert event.metadata_json == {"filesScanned": 3, "path": "/books"}


def test_prepared_system_events_use_one_write_and_do_not_commit(db_session):
    prepared = [
        prepare_system_event(
            source="system",
            action=f"batch.{index}",
            message=f"Batch {index}",
            metadata={"index": index},
        )
        for index in range(25)
    ]
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    sqlalchemy_event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        event_ids = write_prepared_system_events(db_session, prepared)
    finally:
        sqlalchemy_event.remove(
            db_session.bind, "before_cursor_execute", capture_statement
        )

    assert event_ids == [item.id for item in prepared]
    assert sum(statement.startswith("INSERT") for statement in statements) == 1
    assert db_session.in_transaction()
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 0


def test_prune_system_events_discards_info_before_protected_error_events(db_session):
    for index in range(3):
        record_system_event(
            db_session,
            source="import",
            action=f"scan.file.detected.{index}",
            message="普通扫描事件" + ("x" * 300),
        )
    protected_id = record_system_event(
        db_session,
        source="library",
        action="deleted",
        level="error",
        message="关键删除审计事件",
    )

    result = maintain_system_events(db_session, max_bytes=250)

    assert result["deleted"] == 3
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SystemEvent)
            .where(SystemEvent.level == "info")
        )
        == 0
    )
    assert db_session.get(SystemEvent, protected_id) is not None


def test_prune_system_events_enforces_hard_limit_after_protected_events(db_session):
    for index in range(3):
        record_system_event(
            db_session,
            source="library",
            action="deleted",
            level="error",
            message=f"关键审计事件 {index}" + ("界" * 300),
        )

    result = maintain_system_events(db_session, max_bytes=300)

    assert result["sizeBytes"] <= 300
    assert result["deleted"] >= 1


def test_prune_system_events_reduces_over_capacity_to_half_limit(db_session):
    for index in range(12):
        record_system_event(
            db_session,
            source="import",
            action=f"scan.file.detected.{index}",
            message="普通扫描事件" + ("x" * 300),
        )

    max_bytes = 1_800
    result = maintain_system_events(db_session, max_bytes=max_bytes)

    assert result["deleted"] >= 1
    assert result["sizeBytes"] <= max_bytes // 2
    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) > 0
    assert get_setting(db_session, "events.lastPrunedAt") is not None


def test_updating_capacity_defers_pruning_to_maintenance_worker(db_session):
    for index in range(20):
        record_system_event(
            db_session,
            source="import",
            action=f"scan.payload.{index}",
            message="大体积日志",
            metadata={"payload": "x" * 64_000},
        )
    db_session.commit()

    set_max_event_bytes(db_session, 1 * 1024 * 1024)
    db_session.commit()

    assert system_event_size_bytes(db_session) > 1 * 1024 * 1024
    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 20
    assert get_setting(db_session, "events.lastPrunedAt") is None


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
        system_bootstrap,
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


def test_system_settings_and_event_use_two_bounded_set_writes(db_session):
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

    assert len(statements) == 2
