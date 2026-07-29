import threading
import time
from types import SimpleNamespace

import pytest

from app.worker import persistent_import_queue


class _Heartbeat:
    def __init__(self, *_args, **_kwargs) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def pulse(self, **_kwargs) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True


class _BlockingRuntime:
    def __init__(self) -> None:
        self.process_started = threading.Event()
        self.release_process = threading.Event()
        self.claims = 0
        self.clears = 0

    def recover(self) -> int:
        return 0

    def claim(self, _worker_id: str, _lease_seconds: int):
        self.claims += 1
        return SimpleNamespace(id="active-task") if self.claims == 1 else None

    def process(self, _task) -> None:
        self.process_started.set()
        self.release_process.wait(timeout=2)

    def fail(self, _task, _error: BaseException) -> bool:
        return False

    def clear_records(self) -> int:
        self.clears += 1
        return 4


def test_queue_clear_waits_for_active_task_and_stops_before_deleting(monkeypatch):
    monkeypatch.setattr(persistent_import_queue, "QueueHeartbeatPump", _Heartbeat)
    runtime = _BlockingRuntime()
    settings = SimpleNamespace(
        import_queue_interval_seconds=0.01,
        ebook_conversion_timeout_seconds=1,
    )
    worker = persistent_import_queue.PersistentImportWorker(
        runtime,
        settings,
        heartbeat_db_factory=lambda: None,
        worker_id="test-worker",
    )

    worker.start()
    assert runtime.process_started.wait(timeout=1)
    worker.request_stop()
    with pytest.raises(RuntimeError, match="must be stopped"):
        worker.clear_records()

    runtime.release_process.set()
    deadline = time.monotonic() + 1
    while worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert worker.is_alive() is False
    assert runtime.claims == 1
    assert worker.clear_records() == 4
    assert runtime.clears == 1
