from __future__ import annotations

from datetime import UTC, datetime, timedelta

import json
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.modules.system.infrastructure.log_files import log_directory
from app.modules.system.application.queries import parse_event_date_bounds
from app.modules.system.infrastructure.events import list_system_events_page


def test_system_event_page_streams_files_without_database_queries(db_session: Session) -> None:
    now = datetime.now(UTC)
    event_count = 100_000
    directory = log_directory() / "api"
    directory.mkdir(parents=True)
    with (directory / f"{now.astimezone().date()}.jsonl").open("w", encoding="utf-8") as stream:
        for index in reversed(range(event_count)):
            stream.write(json.dumps({
                "id": f"event-scale-{index:06d}", "level": "warning" if index % 5 == 0 else "info",
                "source": f"source-{index % 10}", "actorType": "system", "actorId": None,
                "action": "scale.test", "message": "bounded event query", "metadata": {},
                "createdAt": (now - timedelta(seconds=index)).isoformat(),
            }) + "\n")
    select_count = 0
    select_statements: list[str] = []

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1
            select_statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        snapshot = list_system_events_page(
            db_session,
            page=1,
            page_size=40,
            date_from_ms=int((now - timedelta(days=1)).timestamp() * 1000),
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert snapshot.total == 86_401
    assert len(snapshot.events) == 40
    assert snapshot.events[0]["id"] == "event-scale-000000"
    assert sum(item["count"] for item in snapshot.sources) == event_count
    assert sum(item["count"] for item in snapshot.levels) == event_count
    assert snapshot.size_bytes > 0
    assert select_count == 0
    assert select_statements == []
    assert not any("length(" in statement.lower() for statement in select_statements)


def test_event_date_bounds_accept_dates_and_browser_iso_values() -> None:
    date_start, _ = parse_event_date_bounds("2026-08-05", None)
    iso_start, _ = parse_event_date_bounds("2026-08-05T00:00:00.000Z", None)

    assert date_start == iso_start
