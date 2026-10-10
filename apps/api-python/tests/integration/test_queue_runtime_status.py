from unittest.mock import Mock

from sqlalchemy.orm import sessionmaker

from app.models import QueueRuntimeState
from app.modules.system.infrastructure.queue_runtime import QueueHeartbeatPump
from tests.support.log_events import log_records


def test_periodic_heartbeat_preserves_paused_status(db_session):
    pump = QueueHeartbeatPump(
        sessionmaker(bind=db_session.get_bind()),
        queue_name="metadata",
        instance_id="test",
        poll_interval_seconds=1,
    )
    pump.pulse(status="paused", error="recovery:paused:RuntimeError")
    pump.pulse()
    row = db_session.get(QueueRuntimeState, "metadata")
    assert row.status == "paused"
    assert row.last_error == "recovery:paused:RuntimeError"
    pump.pulse(status="running", processed=True)
    db_session.refresh(row)
    assert row.status == "running"
    assert row.last_error is None


def test_dead_consumer_cannot_report_healthy_from_heartbeat_thread(db_session):
    pump = QueueHeartbeatPump(
        sessionmaker(bind=db_session.get_bind()),
        queue_name="metadata",
        instance_id="test",
        poll_interval_seconds=1,
    )
    pump._owner_thread = Mock()
    pump._owner_thread.is_alive.return_value = False
    pump._stop_event = Mock()
    pump._stop_event.wait.return_value = False
    pump._run()
    row = db_session.get(QueueRuntimeState, "metadata")
    assert row.status == "failed"
    assert row.last_error == "consumer-thread-exited"


def test_every_heartbeat_write_failure_retains_real_database_cause(
    db_session, monkeypatch, caplog
):
    from app.modules.system.infrastructure.log_files import save_log_settings
    save_log_settings(3, "debug")
    import sqlite3

    from sqlalchemy.exc import OperationalError

    from app.modules.system.infrastructure import queue_runtime

    factory = sessionmaker(bind=db_session.get_bind())
    pump = QueueHeartbeatPump(
        factory,
        queue_name="metadata",
        instance_id="heartbeat-diag-test",
        poll_interval_seconds=1,
    )
    observed = sqlite3.OperationalError("database is locked")
    observed.sqlite_errorcode = sqlite3.SQLITE_BUSY
    observed.sqlite_errorname = "SQLITE_BUSY"

    def fail_write(*_args):
        raise OperationalError("UPDATE QueueRuntimeState", {}, observed)

    monkeypatch.setattr(queue_runtime, "write_prepared_queue_runtime", fail_write)
    pump.pulse()
    pump.pulse()
    with factory() as _db:
        events = [row for row in log_records() if row.action == 'queue.heartbeat_deferred']
    assert len(events) == 2
    assert len({event.id for event in events}) == 2
    assert all("taskId" not in event.metadata_json for event in events)
    for event in events:
        cause = event.metadata_json["diagnostics"]["rootCause"]
        assert cause["databaseCode"] == sqlite3.SQLITE_BUSY
        assert cause["databaseErrorName"] == "SQLITE_BUSY"
        assert cause["message"] == "database is locked"
    assert len([record for record in caplog.records if "UPDATE QueueRuntimeState" in record.getMessage()]) == 2
