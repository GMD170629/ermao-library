from tests.support.log_events import log_records, one_log

"""Failed health states retain facts even when no lower exception is available."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exception_diagnostics import (
    configure_exception_storage,
    reset_exception_storage,
)
from app.db.base import Base
from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.infrastructure import health_runs, runtime


@pytest.fixture
def health_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    configure_exception_storage(factory)
    try:
        yield factory
    finally:
        reset_exception_storage()
        engine.dispose()


def create_run(factory, settings):
    with factory() as db:
        prepared = health_runs.prepare_health_run_creation(db, settings, "health-actor")
        with SystemWriteTransaction(db):
            health_runs.write_prepared_health_run_creation(db, prepared)
    return str(prepared.snapshot["runId"])


def test_startup_recovery_records_observed_abandoned_state(health_database, test_settings, caplog):
    factory = health_database
    run_id = create_run(factory, test_settings)
    with factory() as db:
        assert runtime.fail_abandoned_health_runs(db) == 1
        snapshot = health_runs.health_run_snapshot(db, run_id)
        assert snapshot["status"] == "failed"
        assert all(item["status"] == "error" for item in snapshot["items"])
    with factory() as db:
        event = one_log([row for row in log_records() if row.action == 'system.health_run_recovery_required'])
    assert "taskId" not in event.metadata_json
    diagnostic = event.metadata_json["diagnostics"]
    assert diagnostic["exceptionType"].endswith(".HealthCheckFailure")
    assert diagnostic["causeProvided"] is False
    assert "preceding process failure reason was not provided" in diagnostic["message"]
    assert event.message in caplog.text


def test_nonterminal_item_records_actual_state_before_marking_failed(health_database, test_settings, monkeypatch, caplog):
    factory = health_database
    run_id = create_run(factory, test_settings)
    monkeypatch.setattr(health_runs, "_execute_item", lambda *_args: ("pending", "health.test.pending", {}))
    health_runs.run_health_checks(factory, True, test_settings, run_id)
    with factory() as db:
        snapshot = health_runs.health_run_snapshot(db, run_id)
        events = [row for row in log_records() if row.action == 'system.health_item_incomplete']
    assert len(events) == len(snapshot["items"])
    assert all(item["status"] == "error" for item in snapshot["items"])
    assert all("resourceId" not in event.metadata_json for event in events)
    for event in events:
        assert "taskId" not in event.metadata_json
        assert "remained pending" in event.metadata_json["diagnostics"]["message"]
        assert event.message in caplog.text
