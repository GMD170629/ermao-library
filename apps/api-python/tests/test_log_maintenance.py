from unittest.mock import Mock

from app.services.log_maintenance import SystemEventMaintenanceWorker


def test_system_event_maintenance_run_once_uses_committed_pruning(
    monkeypatch,
    db_session,
):
    prune = Mock()
    monkeypatch.setattr("app.services.log_maintenance.prune_system_events", prune)
    worker = SystemEventMaintenanceWorker(lambda: db_session)

    worker.run_once()

    prune.assert_called_once_with(db_session, commit=True)
