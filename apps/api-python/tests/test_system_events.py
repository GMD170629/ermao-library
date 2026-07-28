import json

from sqlalchemy import func, select

from app.models.settings import SystemEvent
from app.bootstrap.system import (
    get_setting,
    prune_system_events,
    record_system_event,
    upsert_setting,
)


def test_record_system_event_normalizes_level_and_serializes_metadata(db_session):
    event_id = record_system_event(
        db_session,
        source="import",
        action="scan.completed",
        level="warn",
        message="扫描完成",
        metadata={"filesScanned": 3, "path": "/books"},
        commit=True,
    )

    event = db_session.get(SystemEvent, event_id)
    assert event is not None
    assert event.level == "warning"
    assert event.source == "import"
    assert event.metadata_json == {"filesScanned": 3, "path": "/books"}


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

    result = prune_system_events(db_session, max_bytes=250, commit=True)

    assert result["deleted"] == 3
    assert db_session.scalar(select(func.count()).select_from(SystemEvent).where(SystemEvent.level == "info")) == 0
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

    result = prune_system_events(db_session, max_bytes=300, commit=True)

    assert result["sizeBytes"] <= 300
    assert result["deleted"] >= 1


def test_system_setting_kv_round_trip(db_session):
    upsert_setting(db_session, "readerTheme", "dark")
    db_session.commit()
    assert get_setting(db_session, "readerTheme") == "dark"
