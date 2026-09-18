from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.orm import sessionmaker

from app.core.exception_diagnostics import (
    configure_exception_storage,
    reset_exception_storage,
)
from app.models.settings import SystemEvent, SystemSetting
from app.modules.imports.application.readable_resource.ports import (
    LibraryImportTaskRecord,
)
from app.modules.imports.infrastructure.readable_resource.support import (
    SqlAlchemyUnitOfWork,
)
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine


class _OrderHandler(logging.Handler):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def emit(self, record: logging.LogRecord) -> None:
        if "containment_failure" in record.getMessage():
            self._order.append("log")


class _Queue:
    def __init__(self, task: LibraryImportTaskRecord) -> None:
        self.task = task
        self.failed: str | None = None

    def prepare_book_identifications(self):
        return ()

    def enqueue_book_identifications(self, _prepared):
        return 0

    def next_queued(self):
        return self.task

    def mark_running(self, task_id: str, *, started_at: datetime) -> None:
        self.task = replace(self.task, state="RUNNING")

    def get_task(self, task_id: str):
        return self.task if self.task.state == "RUNNING" else None

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        self.task = replace(self.task, state="SUCCEEDED")

    def mark_failed(
        self, task_id: str, *, error_summary: str, finished_at: datetime
    ) -> None:
        self.failed = error_summary
        self.task = replace(self.task, state="FAILED")

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        return 0


class _LockingScan:
    """Start a real business write, then fail while its transaction is open."""

    def __init__(self, session) -> None:
        self._session = session

    def execute_library(self, *_args, **_kwargs):
        self._session.execute(
            insert(SystemSetting).values(key="business-lock", value="held")
        )
        raise RuntimeError("scan failure under business write lock")


class _ProcessImport:
    def reset_inspection_cache(self) -> None:
        return None


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


def _engines(tmp_path: Path) -> tuple[Engine, Engine]:
    database_path = (tmp_path / "worker-diagnostics.sqlite3").as_posix()
    connect_args = {"timeout": 0.25, "check_same_thread": False}
    business_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}", connect_args=connect_args
    )
    recorder_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}", connect_args=connect_args
    )
    SystemSetting.__table__.create(business_engine)
    SystemEvent.__table__.create(recorder_engine)
    return business_engine, recorder_engine


def test_worker_prepares_then_rolls_back_then_persists(tmp_path: Path) -> None:
    business_engine, recorder_engine = _engines(tmp_path)
    business_factory = sessionmaker(
        bind=business_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    recorder_factory = sessionmaker(
        bind=recorder_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    business = business_factory()
    order: list[str] = []
    event.listen(business, "after_rollback", lambda _session: order.append("rollback"))

    def _capture_event_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith('INSERT INTO "SYSTEMEVENT"'):
            order.append("insert_event")

    event.listen(recorder_engine, "before_cursor_execute", _capture_event_insert)
    pipeline_logger = logging.getLogger("ermao.readable_resource_pipeline")
    handler = _OrderHandler(order)
    pipeline_logger.addHandler(handler)
    previous_level = pipeline_logger.level
    pipeline_logger.setLevel(logging.DEBUG)
    configure_exception_storage(lambda: recorder_factory())
    queue = _Queue(
        LibraryImportTaskRecord(
            id="task-1",
            kind="SCAN_LIBRARY",
            library_id="library-1",
            state="QUEUED",
            resource_id=None,
            source_node_id="node-1",
            role=None,
            error_summary=None,
        )
    )
    try:
        worker = ReadableResourceWorkerProcessor(
            queue=queue,
            scan=_LockingScan(business),
            process_import=_ProcessImport(),
            uow=SqlAlchemyUnitOfWork(business),
            clock=_Clock(),
        )
        outcome = worker.process_once()
    finally:
        pipeline_logger.removeHandler(handler)
        pipeline_logger.setLevel(previous_level)
        reset_exception_storage()
        business.close()

    assert outcome == "error"
    assert queue.failed == "WORKER_ERROR"
    # Prepare (running log) first, then the real rollback releases the business
    # write lock, and only then the independent diagnostic insert happens.
    assert order == ["log", "rollback", "insert_event"], order

    recorder = recorder_factory()
    try:
        persisted = list(
            recorder.scalars(select(SystemEvent).where(SystemEvent.source == "import"))
        )
        assert len(persisted) == 1
        assert persisted[0].target_id == "task-1"
        assert "scan failure under business write lock" in persisted[
            0
        ].metadata_json["diagnostics"]["traceback"]
    finally:
        recorder.close()
        business_engine.dispose()
        recorder_engine.dispose()
