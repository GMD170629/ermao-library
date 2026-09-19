from unittest.mock import Mock

from sqlalchemy.orm import sessionmaker

from app.models import QueueRuntimeState
from app.modules.system.infrastructure.queue_runtime import QueueHeartbeatPump


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
