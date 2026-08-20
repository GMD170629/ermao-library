"""Short-lived query boundary for import decisions after buffered writes."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.query_ports import ImportLibraryQueries, Record
from app.modules.imports.application.transactions import (
    ImportDependencyProjection,
    ImportTransactionController,
)


class CheckpointingImportLibraryQueries:
    def __init__(
        self,
        queries: ImportLibraryQueries,
        transactions: ImportTransactionController,
    ) -> None:
        self._queries = queries
        self._projection = ImportDependencyProjection(transactions)

    def existing_file_import_snapshot(self, path: Path) -> Record | None:
        with self._projection:
            return self._queries.existing_file_import_snapshot(path)

    def find_work_cover_volume(self, work_id: str) -> Record | None:
        with self._projection:
            return self._queries.find_work_cover_volume(work_id)

    def get_import_asset_by_task_and_path(
        self, task_id: str, source_path: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_import_asset_by_task_and_path(task_id, source_path)

    def get_import_task_by_id(self, task_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_import_task_by_id(task_id)

    def get_volume_context_by_id(self, volume_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_volume_context_by_id(volume_id)

    def get_work_by_id(self, work_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_work_by_id(work_id)

    def has_generated_cover_path(self, work_id: str, cover_path: str) -> bool:
        with self._projection:
            return self._queries.has_generated_cover_path(work_id, cover_path)

    def list_file_volumes_by_paths(self, paths: list[str]) -> list[Record]:
        with self._projection:
            return self._queries.list_file_volumes_by_paths(paths)

    def list_audio_volume_files(self, volume_id: str) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_volume_files(volume_id)

    def list_audio_volume_units(self, volume_id: str) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_volume_units(volume_id)

    def list_volume_cover_paths_for_version(
        self, version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_volume_cover_paths_for_version(version_id)
