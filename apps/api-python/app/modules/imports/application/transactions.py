"""Explicit short-transaction coordination for one import attempt."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

from app.modules.imports.application.dto import ImportResult
from app.modules.imports.application.ports import (
    ImportUnitOfWork,
    LibraryImportStore,
)

IMPORT_PERSISTENCE_BATCH_SIZE = 200

ResultT = TypeVar("ResultT")


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
    media_versions_to_prune: tuple[str, ...]


@dataclass
class ImportTransactionController:
    """Own bounded commits and release the database connection before file I/O."""

    unit_of_work: ImportUnitOfWork
    batch_size: int = IMPORT_PERSISTENCE_BATCH_SIZE
    _pending_writes: int = 0
    _completion_phase: bool = False

    def note_write(self, count: int = 1) -> None:
        if count < 1:
            return
        self._pending_writes += count
        if not self._completion_phase and self._pending_writes >= self.batch_size:
            self.commit()

    def commit(self) -> None:
        self.unit_of_work.commit()
        self._pending_writes = 0

    def rollback(self) -> None:
        self.unit_of_work.rollback()
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

        self.unit_of_work.release()
        self._pending_writes = 0
        self._completion_phase = False

    def release(self) -> None:
        self.release_for_external_io()


@dataclass
class ImportCompletion:
    """Terminal writes deliberately held for the final short transaction."""

    task_updates: dict[str, dict[str, object]] = field(default_factory=dict)
    volume_updates: dict[str, dict[str, object]] = field(default_factory=dict)
    media_versions_to_prune: set[str] = field(default_factory=set)

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

    def defer_media_version_prune(self, media_version_id: str) -> None:
        self.media_versions_to_prune.add(media_version_id)

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
            media_versions_to_prune=tuple(sorted(self.media_versions_to_prune)),
        )


def persist_import_completion(
    store: LibraryImportStore,
    prepared: PreparedImport,
) -> None:
    for volume_id, columns in prepared.volume_updates:
        store.update_library_volume(volume_id, columns=dict(columns))
    for task_id, columns in prepared.task_updates:
        store.update_import_task(task_id, columns=dict(columns))
    for media_version_id in prepared.media_versions_to_prune:
        store.delete_library_media_version_if_empty(media_version_id)


class BoundedLibraryImportStore:
    """Application-owned store decorator enforcing bounded import writes.

    The infrastructure repository remains transaction-agnostic. This decorator
    is part of the import use case and is therefore the explicit owner of batch
    commits and terminal-state deferral.
    """

    def __init__(
        self,
        store: LibraryImportStore,
        transactions: ImportTransactionController,
        completion: ImportCompletion,
    ) -> None:
        self._store = store
        self._transactions = transactions
        self._completion = completion
        self._task_id: str | None = None
        self._source_key: str | None = None

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

    def insert_import_task(self, *, columns: dict[str, object]) -> dict[str, object]:
        return self._written(self._store.insert_import_task(columns=columns))

    def update_import_task(self, task_id: str, *, columns: dict[str, object]) -> None:
        if columns.get("status") == "COMPLETED":
            # The terminal task update is emitted only after media preparation.
            # Commit remaining intermediate rows now; the following log/event and
            # completion writes then share the final short transaction.
            self._transactions.begin_completion()
            self._completion.defer_task(task_id, columns)
            return
        self._store.update_import_task(task_id, columns=columns)
        self._transactions.note_write()

    def insert_import_asset(self, *, columns: dict[str, object]) -> dict[str, object]:
        values = self._scoped_columns("asset", columns.get("sourcePath"), columns)
        return self._written(self._store.insert_import_asset(columns=values))

    def update_import_asset(self, asset_id: str, *, columns: dict[str, object]) -> None:
        self._store.update_import_asset(asset_id, columns=columns)
        self._transactions.note_write()

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]:
        return self._written(self._store.insert_import_log(columns=columns))

    def insert_library_work(self, *, columns: dict[str, object]) -> dict[str, object]:
        values = self._scoped_columns("work", "primary", columns)
        return self._written(self._store.insert_library_work(columns=values))

    def update_library_work(self, work_id: str, *, columns: dict[str, object]) -> None:
        self._store.update_library_work(work_id, columns=columns)
        self._transactions.note_write()

    def ensure_library_media_version(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        resource_key = f"{columns.get('workId')}|{columns.get('mediaKind')}"
        values = self._scoped_columns("media-version", resource_key, columns)
        return self._written(self._store.ensure_library_media_version(columns=values))

    def update_library_media_version(
        self, media_version_id: str, *, columns: dict[str, object]
    ) -> None:
        self._store.update_library_media_version(media_version_id, columns=columns)
        self._transactions.note_write()

    def delete_library_media_version_if_empty(self, media_version_id: str) -> None:
        self._completion.defer_media_version_prune(media_version_id)

    def insert_library_volume(self, *, columns: dict[str, object]) -> dict[str, object]:
        resource_key = columns.get("resourceKey") or columns.get("sourceGroupKey")
        values = self._scoped_columns("volume", resource_key, columns)
        terminal_status = values.get("importStatus")
        if terminal_status == "COMPLETED":
            values["importStatus"] = "PARSING"
        result = self._store.insert_library_volume(columns=values)
        self._transactions.note_write()
        if terminal_status == "COMPLETED":
            self._completion.defer_volume(
                str(result["id"]), {"importStatus": "COMPLETED"}
            )
        return result

    def update_library_volume(
        self, volume_id: str, *, columns: dict[str, object]
    ) -> None:
        if columns.get("importStatus") == "COMPLETED" or self._completion.has_volume(
            volume_id
        ):
            self._completion.defer_volume(volume_id, columns)
            return
        self._store.update_library_volume(volume_id, columns=columns)
        self._transactions.note_write()

    def insert_library_file(self, *, columns: dict[str, object]) -> dict[str, object]:
        values = self._scoped_columns("file", columns.get("path"), columns)
        return self._written(self._store.insert_library_file(columns=values))

    def update_library_file(self, file_id: str, *, columns: dict[str, object]) -> None:
        self._store.update_library_file(file_id, columns=columns)
        self._transactions.note_write()

    def get_library_file(self, file_id: str) -> dict[str, object] | None:
        return self._store.get_library_file(file_id)

    def insert_library_reading_unit(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        resource_key = "|".join(
            str(columns.get(name) or "")
            for name in ("volumeId", "fileId", "unitType", "sortOrder")
        )
        values = self._scoped_columns("reading-unit", resource_key, columns)
        return self._written(self._store.insert_library_reading_unit(columns=values))

    def update_library_reading_unit(
        self, unit_id: str, *, columns: dict[str, object]
    ) -> None:
        self._store.update_library_reading_unit(unit_id, columns=columns)
        self._transactions.note_write()

    def get_library_reading_unit(self, unit_id: str) -> dict[str, object] | None:
        return self._store.get_library_reading_unit(unit_id)

    def delete_library_reading_unit(self, unit_id: str) -> None:
        self._store.delete_library_reading_unit(unit_id)
        self._transactions.note_write()

    def insert_library_metadata(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        resource_key = f"{columns.get('volumeId')}|{columns.get('source')}"
        values = self._scoped_columns("metadata", resource_key, columns)
        return self._written(self._store.insert_library_metadata(columns=values))

    def update_library_reading_progress(
        self,
        progress_id: str,
        *,
        columns: dict[str, object],
    ) -> None:
        self._store.update_library_reading_progress(progress_id, columns=columns)
        self._transactions.note_write()

    def update_user_media_history(
        self,
        history_id: str,
        *,
        columns: dict[str, object],
    ) -> None:
        self._store.update_user_media_history(history_id, columns=columns)
        self._transactions.note_write()

    def insert_organize_job(self, *, columns: dict[str, object]) -> dict[str, object]:
        return self._written(self._store.insert_organize_job(columns=columns))

    def update_organize_job(self, job_id: str, *, columns: dict[str, object]) -> None:
        self._store.update_organize_job(job_id, columns=columns)
        self._transactions.note_write()

    def insert_metadata_lookup_task(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        return self._written(self._store.insert_metadata_lookup_task(columns=columns))

    def update_metadata_lookup_task(
        self, task_id: str, *, columns: dict[str, object]
    ) -> None:
        self._store.update_metadata_lookup_task(task_id, columns=columns)
        self._transactions.note_write()
