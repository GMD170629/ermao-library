from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import cast

from sqlalchemy import String, create_engine, func, insert, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.modules.imports.application.dto import ImportResult
from app.modules.imports.application.ports import LibraryImportStore
from app.modules.imports.application.transactions import (
    IMPORT_PERSISTENCE_BATCH_SIZE,
    BoundedLibraryImportStore,
    ImportCompletion,
    ImportTransactionController,
    persist_import_completion,
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

    def update_library_volume(
        self, volume_id: str, *, columns: dict[str, object]
    ) -> None:
        self.volume_updates.append((volume_id, columns))

    def insert_library_volume(self, *, columns: dict[str, object]) -> dict[str, object]:
        return columns

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]:
        self.import_logs.append(columns)
        return columns


class ReadingUnitStore(CompletionStore):
    def __init__(self) -> None:
        super().__init__()
        self.inserted_units = 0

    def insert_library_reading_unit(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        self.inserted_units += 1
        return columns


def test_import_transaction_controller_commits_at_bounded_batch_size() -> None:
    unit_of_work = RecordingUnitOfWork()
    transactions = ImportTransactionController(unit_of_work)

    transactions.note_write(IMPORT_PERSISTENCE_BATCH_SIZE - 1)
    assert unit_of_work.commits == 0

    transactions.note_write()
    assert unit_of_work.commits == 1

    transactions.note_write(IMPORT_PERSISTENCE_BATCH_SIZE)
    assert unit_of_work.commits == 2


def test_reading_units_are_persisted_in_transactions_of_at_most_200() -> None:
    unit_of_work = RecordingUnitOfWork()
    transactions = ImportTransactionController(unit_of_work)
    concrete_store = ReadingUnitStore()
    store = BoundedLibraryImportStore(
        cast(LibraryImportStore, concrete_store),
        transactions,
        ImportCompletion(),
    )
    store.insert_library_volume(
        columns={
            "id": "volume-1",
            "mediaVersionId": "media-1",
            "importStatus": "COMPLETED",
        }
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

    assert concrete_store.inserted_units == 401
    assert unit_of_work.commits == 2

    transactions.begin_completion()
    assert unit_of_work.commits == 3


def test_terminal_import_state_is_deferred_until_final_transaction() -> None:
    unit_of_work = RecordingUnitOfWork()
    transactions = ImportTransactionController(unit_of_work)
    completion = ImportCompletion()
    concrete_store = CompletionStore()
    store = BoundedLibraryImportStore(
        cast(LibraryImportStore, concrete_store),
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
    assert concrete_store.import_logs == [{"id": "log-1", "message": "completed"}]
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
    persist_import_completion(cast(LibraryImportStore, concrete_store), prepared)

    assert concrete_store.volume_updates == [
        (
            "volume-1",
            {"importStatus": "COMPLETED", "coverPath": "sidecar-cover.jpg"},
        )
    ]
    assert concrete_store.task_updates == [
        ("task-1", {"status": "COMPLETED", "progress": 100})
    ]


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
