"""Named ORM writes for import media persistence.

Replaces the transitional model-CRUD helper. Call sites pass
explicit column maps built at the application boundary; this adapter never owns
transactions.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import bindparam, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.schema import Table

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.import_pipeline import ImportAsset, ImportLog, ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.modules.imports.application.transactions import (
    ImportWriteTarget,
    PreparedImportInsert,
    PreparedImportUpdate,
    PreparedImportWriteBatch,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.services.system_events import write_prepared_system_events


@dataclass(frozen=True, slots=True)
class _PreparedSqlExecution:
    statement: Executable
    parameters: tuple[dict[str, object], ...] | None = None


class SqlAlchemyLibraryImportStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _table_for_target(target: ImportWriteTarget) -> Table:
        tables: dict[ImportWriteTarget, Table] = {
            ImportWriteTarget.IMPORT_TASK: ImportTask.__table__,
            ImportWriteTarget.IMPORT_ASSET: ImportAsset.__table__,
            ImportWriteTarget.IMPORT_LOG: ImportLog.__table__,
            ImportWriteTarget.LIBRARY_WORK: LibraryWork.__table__,
            ImportWriteTarget.LIBRARY_VERSION: LibraryVersion.__table__,
            ImportWriteTarget.LIBRARY_MEDIA_VERSION: LibraryMediaVersion.__table__,
            ImportWriteTarget.LIBRARY_VOLUME: LibraryVolume.__table__,
            ImportWriteTarget.LIBRARY_FILE: LibraryFile.__table__,
            ImportWriteTarget.LIBRARY_READING_UNIT: LibraryReadingUnit.__table__,
            ImportWriteTarget.LIBRARY_METADATA: LibraryMetadata.__table__,
            ImportWriteTarget.LIBRARY_READING_PROGRESS: (
                LibraryReadingProgress.__table__
            ),
            ImportWriteTarget.ORGANIZE_JOB: OrganizeJob.__table__,
            ImportWriteTarget.METADATA_LOOKUP_TASK: MetadataLookupTask.__table__,
        }
        return tables[target]

    @staticmethod
    def _filtered_columns(
        table: Table, columns: Mapping[str, object]
    ) -> dict[str, object]:
        allowed = {column.name for column in table.columns}
        values = {key: value for key, value in columns.items() if key in allowed}
        if table is LibraryFile.__table__ and isinstance(values.get("path"), str):
            values["pathKey"] = source_key(str(values["path"]))
        return values

    def _prepare_bulk_upsert_by_id(
        self, table: Table, rows: tuple[Mapping[str, object], ...]
    ) -> tuple[_PreparedSqlExecution, ...]:
        grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            values = self._filtered_columns(table, row)
            if not values:
                continue
            grouped[tuple(sorted(values))].append(values)
        executions: list[_PreparedSqlExecution] = []
        for keys, values in grouped.items():
            statement = sqlite_insert(table)
            update_values = {
                key: statement.excluded[key]
                for key in keys
                if key not in {"id", "createdAt"}
            }
            executable = (
                statement.on_conflict_do_update(
                    index_elements=[table.c.id], set_=update_values
                )
                if update_values
                else statement.on_conflict_do_nothing(index_elements=[table.c.id])
            )
            for chunk in sqlite_parameter_chunks(
                values, parameters_per_row=max(1, len(keys))
            ):
                executions.append(_PreparedSqlExecution(executable, tuple(chunk)))
        return tuple(executions)

    @staticmethod
    def _group_inserts(
        inserts: tuple[PreparedImportInsert, ...], target: ImportWriteTarget
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(row.columns for row in inserts if row.target == target)

    @staticmethod
    def _group_updates(
        updates: tuple[PreparedImportUpdate, ...], target: ImportWriteTarget
    ) -> tuple[tuple[str, Mapping[str, object]], ...]:
        return tuple(
            (row.target_id, row.columns) for row in updates if row.target == target
        )

    def _prepare_target_inserts(
        self, prepared: PreparedImportWriteBatch, target: ImportWriteTarget
    ) -> tuple[_PreparedSqlExecution, ...]:
        rows = self._group_inserts(prepared.inserts, target)
        return (
            self._prepare_bulk_upsert_by_id(self._table_for_target(target), rows)
            if rows
            else ()
        )

    def _prepare_target_updates(
        self, prepared: PreparedImportWriteBatch, target: ImportWriteTarget
    ) -> tuple[_PreparedSqlExecution, ...]:
        rows = self._group_updates(prepared.updates, target)
        return (
            self._prepare_bulk_update_by_id(self._table_for_target(target), rows)
            if rows
            else ()
        )

    def _execute_prepared_sql(
        self, executions: tuple[_PreparedSqlExecution, ...]
    ) -> None:
        for execution in executions:
            if execution.parameters is None:
                self._db.execute(execution.statement)
            else:
                self._db.execute(execution.statement, list(execution.parameters))

    def apply_import_checkpoint(self, prepared: PreparedImportWriteBatch) -> None:
        """Execute one prepared import checkpoint using collection statements only."""

        executions: list[_PreparedSqlExecution] = []
        for chunk in sqlite_parameter_chunks(
            prepared.reading_unit_ids_to_delete, parameters_per_row=1
        ):
            executions.append(
                _PreparedSqlExecution(
                    delete(LibraryReadingUnit).where(LibraryReadingUnit.id.in_(chunk))
                )
            )
        for chunk in sqlite_parameter_chunks(
            prepared.reading_unit_file_ids_to_reset, parameters_per_row=1
        ):
            executions.append(
                _PreparedSqlExecution(
                    delete(LibraryReadingUnit).where(
                        LibraryReadingUnit.file_id.in_(chunk)
                    )
                )
            )
        for chunk in sqlite_parameter_chunks(
            prepared.metadata_volume_ids_to_reset, parameters_per_row=1
        ):
            executions.append(
                _PreparedSqlExecution(
                    delete(LibraryMetadata).where(LibraryMetadata.volume_id.in_(chunk))
                )
            )

        parent_targets = (
            ImportWriteTarget.IMPORT_TASK,
            ImportWriteTarget.LIBRARY_WORK,
            ImportWriteTarget.LIBRARY_VERSION,
            ImportWriteTarget.LIBRARY_MEDIA_VERSION,
            ImportWriteTarget.LIBRARY_VOLUME,
            ImportWriteTarget.LIBRARY_FILE,
        )
        for target in parent_targets:
            executions.extend(self._prepare_target_inserts(prepared, target))
            executions.extend(self._prepare_target_updates(prepared, target))

        executions.extend(
            self._prepare_bulk_update_by_id(
                LibraryReadingUnit.__table__,
                tuple(
                    (row.target_id, row.columns)
                    for row in prepared.reading_unit_pre_updates
                ),
            )
        )
        executions.extend(
            self._prepare_target_updates(
                prepared, ImportWriteTarget.LIBRARY_READING_UNIT
            )
        )
        executions.extend(
            self._prepare_target_inserts(
                prepared, ImportWriteTarget.LIBRARY_READING_UNIT
            )
        )

        remaining_targets = (
            ImportWriteTarget.LIBRARY_METADATA,
            ImportWriteTarget.IMPORT_ASSET,
            ImportWriteTarget.IMPORT_LOG,
            ImportWriteTarget.LIBRARY_READING_PROGRESS,
            ImportWriteTarget.ORGANIZE_JOB,
            ImportWriteTarget.METADATA_LOOKUP_TASK,
        )
        for target in remaining_targets:
            executions.extend(self._prepare_target_inserts(prepared, target))
            executions.extend(self._prepare_target_updates(prepared, target))
        self._execute_prepared_sql(tuple(executions))
        write_prepared_system_events(self._db, prepared.system_events)

    def _prepare_bulk_update_by_id(
        self,
        table: Table,
        updates: tuple[tuple[str, Mapping[str, object]], ...],
    ) -> tuple[_PreparedSqlExecution, ...]:
        grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
        allowed = {column.name for column in table.columns}
        for target_id, columns in updates:
            keys = tuple(sorted(key for key in columns if key in allowed))
            if not keys:
                continue
            grouped[keys].append(
                {
                    "_target_id": target_id,
                    **{f"_value_{key}": columns[key] for key in keys},
                }
            )
        executions: list[_PreparedSqlExecution] = []
        for keys, values in grouped.items():
            statement = (
                table.update()
                .where(table.c.id == bindparam("_target_id"))
                .values({table.c[key]: bindparam(f"_value_{key}") for key in keys})
            )
            for chunk in sqlite_parameter_chunks(
                values, parameters_per_row=len(keys) + 1
            ):
                executions.append(_PreparedSqlExecution(statement, tuple(chunk)))
        return tuple(executions)

    def apply_import_completion(
        self,
        *,
        task_updates: tuple[tuple[str, Mapping[str, object]], ...],
        volume_updates: tuple[tuple[str, Mapping[str, object]], ...],
    ) -> None:
        executions = [
            *self._prepare_bulk_update_by_id(ImportTask.__table__, task_updates),
            *self._prepare_bulk_update_by_id(LibraryVolume.__table__, volume_updates),
        ]
        self._execute_prepared_sql(tuple(executions))

    def find_library_version(
        self, work_id: str, source_key: str
    ) -> dict[str, object] | None:
        existing = (
            self._db.execute(
                select(LibraryVersion.__table__).where(
                    LibraryVersion.work_id == work_id,
                    LibraryVersion.source_key == source_key,
                )
            )
            .mappings()
            .first()
        )
        return dict(existing) if existing is not None else None

    def find_library_media_version(
        self, work_id: str, media_kind: str
    ) -> dict[str, object] | None:
        existing = (
            self._db.execute(
                select(LibraryMediaVersion.__table__).where(
                    LibraryMediaVersion.work_id == work_id,
                    LibraryMediaVersion.media_kind == media_kind,
                )
            )
            .mappings()
            .first()
        )
        return dict(existing) if existing is not None else None

    def get_library_volume_import_status(self, volume_id: str) -> str | None:
        status = self._db.scalar(
            select(LibraryVolume.import_status).where(LibraryVolume.id == volume_id)
        )
        return str(status) if status is not None else None

    def find_library_file_import_target(self, path: str) -> dict[str, object] | None:
        existing = (
            self._db.execute(
                select(
                    LibraryFile.id,
                    LibraryVolume.import_status.label("importStatus"),
                )
                .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
                .where(LibraryFile.path == path)
                .limit(1)
            )
            .mappings()
            .first()
        )
        return dict(existing) if existing is not None else None

    def get_library_file(self, file_id: str) -> dict[str, object] | None:
        row = (
            self._db.execute(
                select(LibraryFile.__table__).where(LibraryFile.id == file_id)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def get_library_reading_unit(self, unit_id: str) -> dict[str, object] | None:
        row = (
            self._db.execute(
                select(LibraryReadingUnit.__table__).where(
                    LibraryReadingUnit.id == unit_id
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None
