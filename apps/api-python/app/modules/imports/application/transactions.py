"""Explicit short-transaction coordination for one import attempt."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Protocol, Self, TypeVar

from app.modules.imports.application.dto import ImportResult
from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent

ResultT = TypeVar("ResultT")


class ImportWriteTarget(StrEnum):
    IMPORT_TASK = "import_task"
    IMPORT_ASSET = "import_asset"
    IMPORT_LOG = "import_log"
    LIBRARY_WORK = "library_work"
    LIBRARY_VOLUME = "library_volume"
    LIBRARY_FILE = "library_file"
    LIBRARY_READING_UNIT = "library_reading_unit"
    LIBRARY_METADATA = "library_metadata"
    LIBRARY_READING_PROGRESS = "library_reading_progress"


_IMPORT_INSERT_TARGETS = frozenset(
    {
        ImportWriteTarget.IMPORT_TASK,
        ImportWriteTarget.IMPORT_ASSET,
        ImportWriteTarget.IMPORT_LOG,
        ImportWriteTarget.LIBRARY_FILE,
        ImportWriteTarget.LIBRARY_READING_UNIT,
        ImportWriteTarget.LIBRARY_METADATA,
        ImportWriteTarget.LIBRARY_READING_PROGRESS,
    }
)


@dataclass(frozen=True, slots=True)
class PreparedImportInsert:
    target: ImportWriteTarget
    columns: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PreparedImportUpdate:
    target: ImportWriteTarget
    target_id: str
    columns: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PreparedImportWriteBatch:
    """Rows fully constructed before the first write statement of a checkpoint."""

    inserts: tuple[PreparedImportInsert, ...]
    reading_unit_pre_updates: tuple[PreparedImportUpdate, ...]
    updates: tuple[PreparedImportUpdate, ...]
    reading_unit_ids_to_delete: tuple[str, ...]
    reading_unit_file_ids_to_reset: tuple[str, ...]
    metadata_volume_ids_to_reset: tuple[str, ...]
    system_events: tuple[PreparedSystemEvent, ...]

    @property
    def empty(self) -> bool:
        return not (
            self.inserts
            or self.reading_unit_pre_updates
            or self.updates
            or self.reading_unit_ids_to_delete
            or self.reading_unit_file_ids_to_reset
            or self.metadata_volume_ids_to_reset
            or self.system_events
        )


class PreparedImportBatchWriter(Protocol):
    def apply_import_checkpoint(self, prepared: PreparedImportWriteBatch) -> None: ...


class ImportDependencyProjectionReader(Protocol):
    def find_library_file_import_target(
        self, path: str
    ) -> dict[str, object] | None: ...

    def get_library_file(self, file_id: str) -> dict[str, object] | None: ...

    def get_library_reading_unit(self, unit_id: str) -> dict[str, object] | None: ...


class BufferedImportPersistence(
    PreparedImportBatchWriter, ImportDependencyProjectionReader, Protocol
):
    pass


class ImportCompletionWriter(Protocol):
    def apply_import_completion(
        self,
        *,
        task_updates: tuple[tuple[str, Mapping[str, object]], ...],
        volume_updates: tuple[tuple[str, Mapping[str, object]], ...],
    ) -> None: ...

    def get_library_volume_import_status(self, volume_id: str) -> str | None: ...


@dataclass
class PreparedImportWriteBuffer:
    """Application-side import write set with read-your-writes overlays."""

    _inserts: dict[tuple[ImportWriteTarget, str], dict[str, object]] = field(
        default_factory=dict
    )
    _updates: dict[tuple[ImportWriteTarget, str], dict[str, object]] = field(
        default_factory=dict
    )
    _reading_unit_pre_updates: dict[str, dict[str, object]] = field(
        default_factory=dict
    )
    _reading_unit_ids_to_delete: set[str] = field(default_factory=set)
    _reading_unit_file_ids_to_reset: set[str] = field(default_factory=set)
    _metadata_volume_ids_to_reset: set[str] = field(default_factory=set)
    _system_events: list[PreparedSystemEvent] = field(default_factory=list)

    def insert(
        self, target: ImportWriteTarget, columns: Mapping[str, object]
    ) -> dict[str, object]:
        if target not in _IMPORT_INSERT_TARGETS:
            raise ValueError(
                f"import cannot create {target.value}; directory topology owns "
                "library structure"
            )
        values = dict(columns)
        target_id = str(values["id"])
        key = (target, target_id)
        values.update(self._updates.pop(key, {}))
        self._inserts[key] = {**self._inserts.get(key, {}), **values}
        return dict(self._inserts[key])

    def update(
        self,
        target: ImportWriteTarget,
        target_id: str,
        columns: Mapping[str, object],
    ) -> None:
        if not columns:
            return
        key = (target, target_id)
        if key in self._inserts:
            self._inserts[key].update(columns)
            return
        current = self._updates.get(key)
        if (
            target == ImportWriteTarget.LIBRARY_READING_UNIT
            and current is not None
            and "sortOrder" in current
            and "sortOrder" in columns
            and int(current["sortOrder"]) < 0 <= int(columns["sortOrder"])
        ):
            self._reading_unit_pre_updates[target_id] = dict(current)
        self._updates[key] = {**self._updates.get(key, {}), **columns}

    def inserted(
        self, target: ImportWriteTarget, target_id: str
    ) -> dict[str, object] | None:
        values = self._inserts.get((target, target_id))
        return dict(values) if values is not None else None

    def delete_reading_unit(self, unit_id: str) -> None:
        key = (ImportWriteTarget.LIBRARY_READING_UNIT, unit_id)
        if self._inserts.pop(key, None) is None:
            self._updates.pop(key, None)
            self._reading_unit_ids_to_delete.add(unit_id)

    def reset_reading_units_for_file(self, file_id: str) -> None:
        self._reading_unit_file_ids_to_reset.add(file_id)

    def reset_metadata_for_volume(self, volume_id: str) -> None:
        self._metadata_volume_ids_to_reset.add(volume_id)

    def stage_system_event(self, event: PreparedSystemEvent) -> None:
        self._system_events.append(event)

    def prepare(self) -> PreparedImportWriteBatch:
        return PreparedImportWriteBatch(
            inserts=tuple(
                PreparedImportInsert(target, MappingProxyType(dict(columns)))
                for (target, _target_id), columns in self._inserts.items()
            ),
            reading_unit_pre_updates=tuple(
                PreparedImportUpdate(
                    ImportWriteTarget.LIBRARY_READING_UNIT,
                    target_id,
                    MappingProxyType(dict(columns)),
                )
                for target_id, columns in self._reading_unit_pre_updates.items()
            ),
            updates=tuple(
                PreparedImportUpdate(target, target_id, MappingProxyType(dict(columns)))
                for (target, target_id), columns in self._updates.items()
            ),
            reading_unit_ids_to_delete=tuple(sorted(self._reading_unit_ids_to_delete)),
            reading_unit_file_ids_to_reset=tuple(
                sorted(self._reading_unit_file_ids_to_reset)
            ),
            metadata_volume_ids_to_reset=tuple(
                sorted(self._metadata_volume_ids_to_reset)
            ),
            system_events=tuple(self._system_events),
        )

    def clear(self) -> None:
        self._inserts.clear()
        self._reading_unit_pre_updates.clear()
        self._updates.clear()
        self._reading_unit_ids_to_delete.clear()
        self._reading_unit_file_ids_to_reset.clear()
        self._metadata_volume_ids_to_reset.clear()
        self._system_events.clear()

    @property
    def empty(self) -> bool:
        return self.prepare().empty


def normalized_import_source_key(value: str | Path) -> str:
    """Return the stable, platform-neutral source identity used by retries."""

    raw = str(value).strip().replace("\\", "/")
    return "/".join(part for part in raw.split("/") if part not in {"", "."})


def stable_import_resource_id(task_id: str, role: str, source_key: str) -> str:
    """Build a deterministic record ID for one task-owned import resource."""

    normalized_role = role.strip().casefold()
    normalized_source = normalized_import_source_key(source_key)
    digest = hashlib.sha256(
        f"{task_id}|{normalized_role}|{normalized_source}".encode()
    ).hexdigest()
    return f"imp_{digest[:40]}"


@dataclass(frozen=True, slots=True)
class PreparedImport:
    """Immutable hand-off from media preparation to terminal persistence."""

    result: ImportResult
    task_updates: tuple[tuple[str, Mapping[str, object]], ...]
    volume_updates: tuple[tuple[str, Mapping[str, object]], ...]


@dataclass
class ImportTransactionController:
    """Own explicit persistence checkpoints for one import attempt."""

    unit_of_work: ImportUnitOfWork
    _pending_writes: int = 0
    _completion_phase: bool = False
    _write_buffer: PreparedImportWriteBuffer | None = None
    _checkpoint_writer: PreparedImportBatchWriter | None = None

    def attach_write_buffer(
        self,
        write_buffer: PreparedImportWriteBuffer,
        checkpoint_writer: PreparedImportBatchWriter,
    ) -> None:
        self._write_buffer = write_buffer
        self._checkpoint_writer = checkpoint_writer

    def note_write(self, count: int = 1) -> None:
        if count < 1:
            return
        self._pending_writes += count

    def commit(self) -> None:
        self.flush_into_current_transaction()
        self.unit_of_work.commit()
        self._pending_writes = 0

    def rollback(self) -> None:
        self.unit_of_work.rollback()
        if self._write_buffer is not None:
            self._write_buffer.clear()
        self._pending_writes = 0
        self._completion_phase = False

    def begin_completion(self) -> None:
        """Commit prepared rows before collecting the final atomic state change."""

        if self._completion_phase:
            return
        self.commit()
        self._completion_phase = True

    def release_for_external_io(self) -> None:
        """Commit pending work and return the checked-out connection to the pool."""

        self.flush_into_current_transaction()
        self.unit_of_work.release()
        self._pending_writes = 0
        self._completion_phase = False

    def release(self) -> None:
        self.release_for_external_io()

    def flush_into_current_transaction(self) -> None:
        """Execute one already-prepared collection batch without committing it."""

        if self._write_buffer is None or self._checkpoint_writer is None:
            return
        prepared = self._write_buffer.prepare()
        if prepared.empty:
            return
        self._checkpoint_writer.apply_import_checkpoint(prepared)
        self._write_buffer.clear()

    def prepare_for_dependency_read(self) -> None:
        """Checkpoint buffered writes before a named dependency projection."""
        if self._write_buffer is not None and not self._write_buffer.empty:
            self.commit()

    def finish_dependency_read(self) -> None:
        """End the read-only transaction immediately after its projection."""
        self.unit_of_work.release()


class ImportDependencyProjection:
    """Bound one named import projection to a short read transaction."""

    def __init__(self, transactions: ImportTransactionController) -> None:
        self._transactions = transactions

    def __enter__(self) -> Self:
        self._transactions.prepare_for_dependency_read()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if exc_type is None:
            self._transactions.finish_dependency_read()
        else:
            self._transactions.rollback()
        return False


@dataclass
class ImportCompletion:
    """Terminal writes deliberately held for the final short transaction."""

    task_updates: dict[str, dict[str, object]] = field(default_factory=dict)
    volume_updates: dict[str, dict[str, object]] = field(default_factory=dict)

    def defer_task(self, task_id: str, columns: dict[str, object]) -> None:
        self.task_updates[task_id] = {
            **self.task_updates.get(task_id, {}),
            **columns,
        }

    def defer_volume(self, volume_id: str, columns: dict[str, object]) -> None:
        self.volume_updates[volume_id] = {
            **self.volume_updates.get(volume_id, {}),
            **columns,
        }

    def has_volume(self, volume_id: str) -> bool:
        return volume_id in self.volume_updates

    def prepare(self, result: ImportResult) -> PreparedImport:
        return PreparedImport(
            result=result,
            task_updates=tuple(
                (task_id, MappingProxyType(dict(columns)))
                for task_id, columns in self.task_updates.items()
            ),
            volume_updates=tuple(
                (volume_id, MappingProxyType(dict(columns)))
                for volume_id, columns in self.volume_updates.items()
            ),
        )


def persist_import_completion(
    store: ImportCompletionWriter,
    prepared: PreparedImport,
) -> None:
    store.apply_import_completion(
        task_updates=prepared.task_updates,
        volume_updates=prepared.volume_updates,
    )


class BoundedLibraryImportStore:
    """Application-owned store decorator enforcing bounded import writes.

    The infrastructure repository remains transaction-agnostic. This decorator
    is part of the import use case and is therefore the explicit owner of batch
    commits and terminal-state deferral.
    """

    def __init__(
        self,
        store: BufferedImportPersistence,
        transactions: ImportTransactionController,
        completion: ImportCompletion,
        write_buffer: PreparedImportWriteBuffer | None = None,
    ) -> None:
        self._transactions = transactions
        self._completion = completion
        self._writes = write_buffer or PreparedImportWriteBuffer()
        self._projection_reader = store
        self._task_id: str | None = None
        self._source_key: str | None = None
        self._transactions.attach_write_buffer(self._writes, store)

    def set_import_scope(self, task_id: str, source_path: Path) -> None:
        self._task_id = task_id
        self._source_key = normalized_import_source_key(source_path.resolve())

    def _scoped_columns(
        self,
        role: str,
        resource_key: object,
        columns: dict[str, object],
    ) -> dict[str, object]:
        if self._task_id is None or self._source_key is None:
            return columns
        values = dict(columns)
        values["id"] = stable_import_resource_id(
            self._task_id,
            role,
            f"{self._source_key}|{resource_key}",
        )
        return values

    def _written(self, result: ResultT) -> ResultT:
        self._transactions.note_write()
        return result

    def _insert(
        self, target: ImportWriteTarget, columns: Mapping[str, object]
    ) -> dict[str, object]:
        return self._written(self._writes.insert(target, columns))

    def _update(
        self,
        target: ImportWriteTarget,
        target_id: str,
        columns: Mapping[str, object],
    ) -> None:
        self._writes.update(target, target_id, columns)
        self._transactions.note_write()

    def update_import_task(self, task_id: str, *, columns: dict[str, object]) -> None:
        if columns.get("status") == "COMPLETED":
            # The terminal task update is emitted only after media preparation.
            # Commit remaining intermediate rows now; the following log/event and
            # completion writes then share the final short transaction.
            self._transactions.begin_completion()
            self._completion.defer_task(task_id, columns)
            return
        self._update(ImportWriteTarget.IMPORT_TASK, task_id, columns)

    def insert_import_asset(self, *, columns: dict[str, object]) -> dict[str, object]:
        values = self._scoped_columns("asset", columns.get("sourcePath"), columns)
        return self._insert(ImportWriteTarget.IMPORT_ASSET, values)

    def update_import_asset(self, asset_id: str, *, columns: dict[str, object]) -> None:
        self._update(ImportWriteTarget.IMPORT_ASSET, asset_id, columns)

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]:
        return self._insert(ImportWriteTarget.IMPORT_LOG, columns)

    def update_library_work(self, work_id: str, *, columns: dict[str, object]) -> None:
        self._update(ImportWriteTarget.LIBRARY_WORK, work_id, columns)

    def update_library_volume(
        self, volume_id: str, *, columns: dict[str, object]
    ) -> None:
        if columns.get("importStatus") == "COMPLETED" or self._completion.has_volume(
            volume_id
        ):
            self._completion.defer_volume(volume_id, columns)
            return
        self._update(ImportWriteTarget.LIBRARY_VOLUME, volume_id, columns)

    def insert_library_file(self, *, columns: dict[str, object]) -> dict[str, object]:
        values = self._scoped_columns("file", columns.get("path"), columns)
        path = values.get("path")
        if isinstance(path, str):
            self._transactions.prepare_for_dependency_read()
            try:
                existing = self._projection_reader.find_library_file_import_target(path)
            finally:
                self._transactions.finish_dependency_read()
            if existing is not None and str(existing["importStatus"]) not in {
                "COMPLETED",
                "IMPORTED",
                "READY",
            }:
                existing_id = str(existing["id"])
                replacement = {
                    key: value
                    for key, value in values.items()
                    if key not in {"id", "createdAt"}
                }
                self._writes.reset_reading_units_for_file(existing_id)
                self._update(ImportWriteTarget.LIBRARY_FILE, existing_id, replacement)
                return {**values, "id": existing_id}
        return self._insert(ImportWriteTarget.LIBRARY_FILE, values)

    def update_library_file(self, file_id: str, *, columns: dict[str, object]) -> None:
        self._update(ImportWriteTarget.LIBRARY_FILE, file_id, columns)

    def get_library_file(self, file_id: str) -> dict[str, object] | None:
        buffered = self._writes.inserted(ImportWriteTarget.LIBRARY_FILE, file_id)
        if buffered is not None:
            return buffered
        self._transactions.prepare_for_dependency_read()
        try:
            return self._projection_reader.get_library_file(file_id)
        finally:
            self._transactions.finish_dependency_read()

    def insert_library_reading_unit(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        resource_key = "|".join(
            str(columns.get(name) or "")
            for name in ("volumeId", "fileId", "unitType", "sortOrder")
        )
        values = self._scoped_columns("reading-unit", resource_key, columns)
        return self._insert(ImportWriteTarget.LIBRARY_READING_UNIT, values)

    def update_library_reading_unit(
        self, unit_id: str, *, columns: dict[str, object]
    ) -> None:
        self._update(ImportWriteTarget.LIBRARY_READING_UNIT, unit_id, columns)

    def get_library_reading_unit(self, unit_id: str) -> dict[str, object] | None:
        buffered = self._writes.inserted(
            ImportWriteTarget.LIBRARY_READING_UNIT, unit_id
        )
        if buffered is not None:
            return buffered
        self._transactions.prepare_for_dependency_read()
        try:
            return self._projection_reader.get_library_reading_unit(unit_id)
        finally:
            self._transactions.finish_dependency_read()

    def delete_library_reading_unit(self, unit_id: str) -> None:
        self._writes.delete_reading_unit(unit_id)
        self._transactions.note_write()

    def insert_library_metadata(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        resource_key = f"{columns.get('volumeId')}|{columns.get('source')}"
        values = self._scoped_columns("metadata", resource_key, columns)
        return self._insert(ImportWriteTarget.LIBRARY_METADATA, values)

    def update_library_reading_progress(
        self,
        progress_id: str,
        *,
        columns: dict[str, object],
    ) -> None:
        self._update(ImportWriteTarget.LIBRARY_READING_PROGRESS, progress_id, columns)
