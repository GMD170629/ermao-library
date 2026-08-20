from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import String, create_engine, event, func, insert, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.models.import_pipeline import ImportTask
from app.modules.imports.application.dto import ImportResult
from app.modules.imports.application.ports import LibraryImportStore
from app.modules.imports.application.transactions import (
    BoundedLibraryImportStore,
    BufferedImportPersistence,
    ImportCompletion,
    ImportCompletionWriter,
    ImportTransactionController,
    ImportWriteTarget,
    PreparedImportWriteBatch,
    PreparedImportWriteBuffer,
    persist_import_completion,
)
from app.modules.imports.infrastructure.library_import_store import (
    SqlAlchemyLibraryImportStore,
)
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork


class ProbeBase(DeclarativeBase):
    pass


class TransactionProbe(ProbeBase):
    __tablename__ = "TransactionProbe"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)


class RecordingUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.releases = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def release(self) -> None:
        self.releases += 1


class CompletionStore:
    def __init__(self) -> None:
        self.task_updates: list[tuple[str, dict[str, object]]] = []
        self.volume_updates: list[tuple[str, dict[str, object]]] = []
        self.import_logs: list[dict[str, object]] = []

    def update_import_task(self, task_id: str, *, columns: dict[str, object]) -> None:
        self.task_updates.append((task_id, columns))

    def apply_import_completion(
        self,
        *,
        task_updates: tuple[tuple[str, Mapping[str, object]], ...],
        volume_updates: tuple[tuple[str, Mapping[str, object]], ...],
    ) -> None:
        self.task_updates.extend(
            (task_id, dict(columns)) for task_id, columns in task_updates
        )
        self.volume_updates.extend(
            (volume_id, dict(columns)) for volume_id, columns in volume_updates
        )

    def update_library_volume(
        self, volume_id: str, *, columns: dict[str, object]
    ) -> None:
        self.volume_updates.append((volume_id, columns))

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]:
        self.import_logs.append(columns)
        return columns

    def get_library_volume_import_status(self, volume_id: str) -> str | None:
        del volume_id
        return None

    def apply_import_checkpoint(self, prepared: PreparedImportWriteBatch) -> None:
        for row in prepared.inserts:
            columns = dict(row.columns)
            if row.target == ImportWriteTarget.LIBRARY_READING_UNIT:
                cast(ReadingUnitStore, self).insert_library_reading_unit(
                    columns=columns
                )
            elif row.target == ImportWriteTarget.IMPORT_LOG:
                self.insert_import_log(columns=columns)


class ReadingUnitStore(CompletionStore):
    def __init__(self) -> None:
        super().__init__()
        self.inserted_units = 0

    def insert_library_reading_unit(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        self.inserted_units += 1
        return columns


class ProbeBatchWriter:
    def __init__(self, session: Session) -> None:
        self._session = session

    def apply_import_checkpoint(self, prepared: PreparedImportWriteBatch) -> None:
        rows = [
            {"id": str(row.columns["id"])}
            for row in prepared.inserts
            if row.target == ImportWriteTarget.IMPORT_TASK
        ]
        if rows:
            self._session.execute(insert(TransactionProbe), rows)


def test_import_transaction_controller_never_commits_from_write_count() -> None:
    unit_of_work = RecordingUnitOfWork()
    transactions = ImportTransactionController(unit_of_work)

    transactions.note_write(401)
    assert unit_of_work.commits == 0


def test_reading_units_commit_only_at_explicit_completion_boundary() -> None:
    unit_of_work = RecordingUnitOfWork()
    transactions = ImportTransactionController(unit_of_work)
    concrete_store = ReadingUnitStore()
    store = BoundedLibraryImportStore(
        cast(BufferedImportPersistence, concrete_store),
        transactions,
        ImportCompletion(),
    )
    for index in range(401):
        store.insert_library_reading_unit(
            columns={
                "id": f"unit-{index}",
                "volumeId": "volume-1",
                "unitType": "page",
                "sortOrder": index,
            }
        )

    assert concrete_store.inserted_units == 0
    assert unit_of_work.commits == 0

    transactions.begin_completion()
    assert concrete_store.inserted_units == 401
    assert unit_of_work.commits == 1


def test_terminal_import_state_is_deferred_until_final_transaction() -> None:
    unit_of_work = RecordingUnitOfWork()
    transactions = ImportTransactionController(unit_of_work)
    completion = ImportCompletion()
    concrete_store = CompletionStore()
    store = BoundedLibraryImportStore(
        cast(BufferedImportPersistence, concrete_store),
        transactions,
        completion,
    )

    store.update_library_volume(
        "volume-1",
        columns={"importStatus": "COMPLETED", "coverPath": "cover.jpg"},
    )
    store.update_library_volume(
        "volume-1",
        columns={"coverPath": "sidecar-cover.jpg"},
    )
    assert unit_of_work.commits == 0

    store.update_import_task(
        "task-1",
        columns={"status": "COMPLETED", "progress": 100},
    )

    assert concrete_store.volume_updates == []
    assert concrete_store.task_updates == []
    assert unit_of_work.commits == 1

    store.insert_import_log(columns={"id": "log-1", "message": "completed"})
    assert concrete_store.import_logs == []
    assert unit_of_work.commits == 1

    prepared = completion.prepare(
        ImportResult(
            "work-1",
            "work-1",
            "media-1",
            "volume-1",
            "Book",
            "ebook",
            "epub",
            1,
            "completed",
            False,
            False,
            "new",
        ),
    )
    transactions.flush_into_current_transaction()
    persist_import_completion(cast(ImportCompletionWriter, concrete_store), prepared)

    assert concrete_store.volume_updates == [
        (
            "volume-1",
            {"importStatus": "COMPLETED", "coverPath": "sidecar-cover.jpg"},
        )
    ]
    assert concrete_store.task_updates == [
        ("task-1", {"status": "COMPLETED", "progress": 100})
    ]
    assert concrete_store.import_logs == [{"id": "log-1", "message": "completed"}]


def test_import_completion_updates_a_task_batch_with_one_statement(db_session) -> None:
    tasks = [
        ImportTask(
            id=f"completion-task-{index}",
            origin="MANUAL",
            status="PARSING",
            source_path=f"/tmp/completion-{index}.epub",
        )
        for index in range(100)
    ]
    db_session.add_all(tasks)
    db_session.commit()
    statements: list[str] = []

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        SqlAlchemyLibraryImportStore(db_session).apply_import_completion(
            task_updates=tuple(
                (task.id, {"status": "COMPLETED", "progress": 100}) for task in tasks
            ),
            volume_updates=(),
        )
        db_session.commit()
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    update_statements = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("UPDATE")
        and '"ImportTask"' in statement
    ]
    assert len(update_statements) == 1
    assert db_session.scalar(
        select(func.count())
        .select_from(ImportTask)
        .where(ImportTask.status == "COMPLETED")
    ) == len(tasks)


def test_import_checkpoint_buffers_task_updates_without_creating_tasks(
    db_session,
) -> None:
    statements: list[str] = []

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement)

    transactions = ImportTransactionController(SqlAlchemyImportUnitOfWork(db_session))
    store = BoundedLibraryImportStore(
        cast(BufferedImportPersistence, SqlAlchemyLibraryImportStore(db_session)),
        transactions,
        ImportCompletion(),
    )
    db_session.add_all(
        [
            ImportTask(
                id=f"buffered-task-{index}",
                origin="SCAN",
                status="PROCESSING",
                source_path=f"/tmp/buffered-task-{index}.epub",
            )
            for index in range(100)
        ]
    )
    db_session.commit()
    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        for index in range(100):
            task_id = f"buffered-task-{index}"
            store.update_import_task(
                task_id, columns={"status": "PARSING", "progress": 5}
            )

        assert not any(
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            for statement in statements
        )

        transactions.commit()
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert not any(
        statement.lstrip().upper().startswith("INSERT") and '"ImportTask"' in statement
        for statement in statements
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ImportTask)
            .where(ImportTask.status == "PARSING")
        )
        == 100
    )


def test_import_file_overlay_returns_buffered_row_without_writing(db_session) -> None:
    statements: list[str] = []

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement)

    transactions = ImportTransactionController(SqlAlchemyImportUnitOfWork(db_session))
    store = BoundedLibraryImportStore(
        cast(BufferedImportPersistence, SqlAlchemyLibraryImportStore(db_session)),
        transactions,
        ImportCompletion(),
    )
    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        inserted = store.insert_library_file(
            columns={
                "id": "buffered-file",
                "volumeId": "buffered-volume",
                "path": "/tmp/buffered.epub",
            }
        )
        loaded = store.get_library_file("buffered-file")
    finally:
        transactions.rollback()
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert loaded == inserted
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )


def test_released_import_transaction_with_large_backlog_does_not_block_writer(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "short-transactions.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"timeout": 10},
    )
    ProbeBase.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(
            insert(TransactionProbe),
            [{"id": f"pending-{index:05d}"} for index in range(20_000)],
        )
        session.commit()
    external_io_started = threading.Event()
    worker_error: list[Exception] = []

    def run_import_file_stage() -> None:
        try:
            with Session(engine) as session:
                session.add(TransactionProbe(id="import-progress"))
                session.flush()
                transactions = ImportTransactionController(
                    SqlAlchemyImportUnitOfWork(session)
                )
                transactions.release_for_external_io()
                assert not session.in_transaction()
                external_io_started.set()
                time.sleep(2)
        except Exception as exc:  # noqa: BLE001 - thread-boundary assertion handoff
            worker_error.append(exc)
            external_io_started.set()

    worker = threading.Thread(target=run_import_file_stage)
    worker.start()
    assert external_io_started.wait(timeout=1)

    started_at = time.monotonic()
    with Session(engine) as session:
        session.add(TransactionProbe(id="api-write"))
        session.commit()
    elapsed = time.monotonic() - started_at
    worker.join(timeout=3)

    assert worker_error == []
    assert elapsed < 0.5
    with Session(engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(TransactionProbe)) == 20_002
        )


def test_blocked_import_preparation_does_not_block_an_independent_writer(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "buffered-import-preparation.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"timeout": 10},
    )
    ProbeBase.metadata.create_all(engine)
    preparation_started = threading.Event()
    finish_preparation = threading.Event()
    worker_error: list[Exception] = []

    def run_import_preparation() -> None:
        try:
            with Session(engine) as session:
                transactions = ImportTransactionController(
                    SqlAlchemyImportUnitOfWork(session)
                )
                writes = PreparedImportWriteBuffer()
                transactions.attach_write_buffer(writes, ProbeBatchWriter(session))
                writes.insert(
                    ImportWriteTarget.IMPORT_TASK,
                    {"id": "prepared-import-row"},
                )
                preparation_started.set()
                assert finish_preparation.wait(timeout=2)
                transactions.commit()
        except Exception as exc:  # noqa: BLE001 - thread-boundary assertion handoff
            worker_error.append(exc)
            preparation_started.set()

    worker = threading.Thread(target=run_import_preparation)
    worker.start()
    assert preparation_started.wait(timeout=1)

    started_at = time.monotonic()
    with Session(engine) as session:
        session.add(TransactionProbe(id="independent-api-write"))
        session.commit()
    elapsed = time.monotonic() - started_at
    finish_preparation.set()
    worker.join(timeout=3)

    assert worker_error == []
    assert elapsed < 0.5
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TransactionProbe)) == 2


def test_import_persistence_exposes_no_directory_topology_creation_writes() -> None:
    forbidden_methods = {
        "insert_library_work",
        "ensure_library_version",
        "ensure_library_media_version",
        "insert_library_volume",
        "update_library_media_version",
    }
    assert forbidden_methods.isdisjoint(LibraryImportStore.__dict__)
    assert forbidden_methods.isdisjoint(BoundedLibraryImportStore.__dict__)
    assert "library_version" not in {target.value for target in ImportWriteTarget}
    assert "library_media_version" not in {target.value for target in ImportWriteTarget}


@pytest.mark.parametrize(
    "target",
    [ImportWriteTarget.LIBRARY_WORK, ImportWriteTarget.LIBRARY_VOLUME],
)
def test_import_write_buffer_rejects_directory_topology_inserts(
    target: ImportWriteTarget,
) -> None:
    with pytest.raises(ValueError, match="directory topology owns library structure"):
        PreparedImportWriteBuffer().insert(target, {"id": "structural-row"})


def test_import_completion_does_not_reference_volume_version_id() -> None:
    completion_source = inspect.getsource(
        SqlAlchemyLibraryImportStore.apply_import_completion
    )
    persist_source = inspect.getsource(persist_import_completion)
    assert "version_id" not in completion_source
    assert "versionId" not in completion_source
    assert "media_versions_to_prune" not in completion_source
    assert "media_versions_to_prune" not in persist_source
