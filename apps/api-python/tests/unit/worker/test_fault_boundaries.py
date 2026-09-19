import signal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.services import metadata_lookup_queue, organize_scheduler
from app.worker import main as worker_main


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    calls = []
    clock = [0.0]

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, delay):
            clock[0] += max(delay, 5)
            if clock[0] > 30:
                self.set()
            return self.stopped

    monkeypatch.setattr(worker_main.threading, "Event", Stop)
    monkeypatch.setattr(worker_main, "monotonic", lambda: clock[0])
    handlers = {}
    monkeypatch.setattr(
        worker_main.signal, "signal", lambda sig, cb: handlers.setdefault(sig, cb)
    )
    for name in (
        "configure_logging",
        "configure_exception_storage",
        "install_exception_hooks",
        "verify_current_schema",
    ):
        monkeypatch.setattr(worker_main, name, lambda *args: None)
    monkeypatch.setattr(
        worker_main,
        "get_settings",
        lambda: SimpleNamespace(import_queue_interval_seconds=1),
    )
    monkeypatch.setattr(worker_main, "worker_ready_file", lambda: tmp_path / "ready")
    sessions = []

    def session():
        value = Mock()
        sessions.append(value)
        return value

    monkeypatch.setattr(worker_main, "BackgroundSessionLocal", session)
    processor = Mock()
    processor.process_once.return_value = "idle"
    monkeypatch.setattr(
        worker_main,
        "build_readable_resource_pipeline",
        lambda db: SimpleNamespace(request_library_scan=None, uow=None),
    )
    monkeypatch.setattr(
        worker_main, "build_readable_resource_worker", lambda graph: processor
    )
    scanner = Mock()
    monkeypatch.setattr(worker_main, "LibraryScanCoordinator", lambda **kwargs: scanner)
    metadata = Mock()
    metadata.start.side_effect = lambda: calls.append("metadata")
    organizer = Mock()
    organizer.start.side_effect = lambda: calls.append("organizer")
    monkeypatch.setattr(
        metadata_lookup_queue, "MetadataLookupWorker", lambda *a, **kw: metadata
    )
    monkeypatch.setattr(
        organize_scheduler, "OrganizerScheduler", lambda *a, **kw: organizer
    )
    monkeypatch.setattr(
        worker_main, "build_automatic_metadata_request_gate", lambda: None
    )
    monkeypatch.setattr(worker_main, "QueueHeartbeatPump", lambda *a, **kw: Mock())
    diagnostics = Mock()
    monkeypatch.setattr(worker_main, "record_exception", diagnostics)
    return SimpleNamespace(
        processor=processor,
        scanner=scanner,
        metadata=metadata,
        organizer=organizer,
        calls=calls,
        sessions=sessions,
        diagnostics=diagnostics,
        handlers=handlers,
        ready=tmp_path / "ready",
    )


def test_failed_import_recovery_leaves_independent_workers_running(runtime):
    runtime.processor.startup.side_effect = RuntimeError("bad recovery")
    worker_main.main()
    assert runtime.processor.startup.call_count == 1
    runtime.processor.process_once.assert_not_called()
    assert runtime.calls == ["metadata", "organizer"]
    assert all(s.close.called for s in runtime.sessions)
    assert not runtime.ready.exists()


def test_transient_recovery_uses_new_context_before_claim(runtime):
    runtime.processor.startup.side_effect = [
        OperationalError("", {}, RuntimeError("database is locked")),
        OperationalError("", {}, RuntimeError("database is locked")),
        0,
    ]
    worker_main.main()
    assert runtime.processor.startup.call_count == 3
    assert len(runtime.sessions) == 3
    assert runtime.processor.process_once.called


def test_loop_and_rollback_and_diagnostics_failure_do_not_escape(runtime):
    runtime.processor.process_once.side_effect = RuntimeError("original")
    runtime.processor.recover_after_loop_failure.side_effect = RuntimeError("rollback")
    runtime.diagnostics.side_effect = RuntimeError("diagnostics")
    worker_main.main()
    assert runtime.processor.process_once.call_count == 1
    assert runtime.processor.recover_after_loop_failure.call_count == 1
    errors = [call.args[2] for call in runtime.diagnostics.call_args_list]
    assert [str(e) for e in errors] == ["original", "rollback"]
    runtime.metadata.shutdown.assert_called_once()
    runtime.organizer.shutdown.assert_called_once()


def test_scan_bug_does_not_block_import_after_successful_rollback(runtime):
    runtime.scanner.tick.side_effect = RuntimeError("scan bug")
    worker_main.main()
    assert runtime.scanner.tick.call_count == 1
    assert runtime.processor.process_once.called
    runtime.scanner.request_stop.assert_called()


def test_shutdown_failure_does_not_skip_other_resources(runtime):
    runtime.metadata.shutdown.side_effect = RuntimeError("stop bug")
    worker_main.main()
    runtime.organizer.shutdown.assert_called_once()
    runtime.scanner.shutdown.assert_called_once()
    assert all(s.close.called for s in runtime.sessions)


def test_stop_during_startup_prevents_claims(runtime):
    runtime.processor.startup.side_effect = lambda: runtime.handlers[signal.SIGTERM](
        signal.SIGTERM, None
    )
    worker_main.main()
    runtime.processor.process_once.assert_not_called()
    runtime.scanner.tick.assert_not_called()
    runtime.metadata.request_stop.assert_called()
    assert not runtime.ready.exists()
