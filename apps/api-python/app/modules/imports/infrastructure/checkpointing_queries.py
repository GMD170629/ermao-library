"""Short-lived query boundary for import decisions that depend on buffered writes."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.query_ports import ImportLibraryQueries, Record
from app.modules.imports.application.transactions import (
    ImportDependencyProjection,
    ImportTransactionController,
)


class CheckpointingImportLibraryQueries:
    """Flush prepared rows before each dependent query, then release its read lock."""

    def __init__(
        self,
        queries: ImportLibraryQueries,
        transactions: ImportTransactionController,
    ) -> None:
        self._queries = queries
        self._projection = ImportDependencyProjection(transactions)

    def copy_shelf_links_to_work(
        self, source_work_ids: list[str], target_work_id: str
    ) -> None:
        with self._projection:
            self._queries.copy_shelf_links_to_work(source_work_ids, target_work_id)

    def count_audio_chapters_for_media_version(self, media_version_id: str) -> int:
        with self._projection:
            return self._queries.count_audio_chapters_for_media_version(
                media_version_id
            )

    def count_audio_chapters_for_volume(self, volume_id: str) -> int:
        with self._projection:
            return self._queries.count_audio_chapters_for_volume(volume_id)

    def count_audio_files_for_media_version(self, media_version_id: str) -> int:
        with self._projection:
            return self._queries.count_audio_files_for_media_version(
                media_version_id
            )

    def count_audiobook_media_kind_media_versions(
        self, work_id: str, media_kind: str
    ) -> int:
        with self._projection:
            return self._queries.count_audiobook_media_kind_media_versions(
                work_id, media_kind
            )

    def count_media_versions_for_work(
        self, work_id: str, *, media_kind: str | None = None
    ) -> int:
        with self._projection:
            return self._queries.count_media_versions_for_work(
                work_id, media_kind=media_kind
            )

    def count_primary_audiobook_media_versions_for_work(
        self, work_id: str, *, exclude_media_version_id: str
    ) -> int:
        with self._projection:
            return self._queries.count_primary_audiobook_media_versions_for_work(
                work_id, exclude_media_version_id=exclude_media_version_id
            )

    def count_visible_media_versions_for_work(self, work_id: str) -> int:
        with self._projection:
            return self._queries.count_visible_media_versions_for_work(work_id)

    def count_visible_volumes_for_work(self, work_id: str) -> int:
        with self._projection:
            return self._queries.count_visible_volumes_for_work(work_id)

    def count_volumes_for_media_version(self, media_version_id: str) -> int:
        with self._projection:
            return self._queries.count_volumes_for_media_version(media_version_id)

    def delete_audio_metadata_sources(self, media_version_id: str) -> None:
        with self._projection:
            self._queries.delete_audio_metadata_sources(media_version_id)

    def detach_audio_chapters_for_media_version(
        self, media_version_id: str
    ) -> None:
        with self._projection:
            self._queries.detach_audio_chapters_for_media_version(media_version_id)

    def detach_audio_chapters_for_media_version_or_files(
        self, media_version_id: str, file_ids: list[str]
    ) -> None:
        with self._projection:
            self._queries.detach_audio_chapters_for_media_version_or_files(
                media_version_id, file_ids
            )

    def existing_file_import_snapshot(self, path: Path) -> Record | None:
        with self._projection:
            return self._queries.existing_file_import_snapshot(path)

    def fail_import_assets_for_task(
        self,
        *,
        task_id: str,
        error_code: str,
        error_summary: str,
        updated_at: object,
    ) -> None:
        with self._projection:
            self._queries.fail_import_assets_for_task(
                task_id=task_id,
                error_code=error_code,
                error_summary=error_summary,
                updated_at=updated_at,
            )

    def find_audio_media_version_by_resource_key(
        self, resource_key: str
    ) -> Record | None:
        with self._projection:
            return self._queries.find_audio_media_version_by_resource_key(resource_key)

    def find_deferred_source_volume(
        self, *, source_path: str, work_id: str, result_volume_id: str | None
    ) -> Record | None:
        with self._projection:
            return self._queries.find_deferred_source_volume(
                source_path=source_path,
                work_id=work_id,
                result_volume_id=result_volume_id,
            )

    def find_media_version_resource_key_conflict(
        self, work_id: str, resource_key: str, exclude_media_version_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.find_media_version_resource_key_conflict(
                work_id, resource_key, exclude_media_version_id
            )

    def find_work_cover_media_version(self, work_id: str) -> Record | None:
        with self._projection:
            return self._queries.find_work_cover_media_version(work_id)

    def get_conversion_by_import_task_id(
        self, import_task_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_conversion_by_import_task_id(import_task_id)

    def get_first_volume_for_media_version(
        self, media_version_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_first_volume_for_media_version(media_version_id)

    def get_import_asset_by_task_and_path(
        self, task_id: str, source_path: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_import_asset_by_task_and_path(
                task_id, source_path
            )

    def get_import_task_by_id(self, task_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_import_task_by_id(task_id)

    def get_latest_audio_tags_metadata(
        self, media_version_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_latest_audio_tags_metadata(media_version_id)

    def get_media_version_by_id(self, media_version_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_media_version_by_id(media_version_id)

    def get_media_version_cover_path(
        self, media_version_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_media_version_cover_path(media_version_id)

    def get_media_version_format(self, media_version_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_media_version_format(media_version_id)

    def get_metadata_lookup_task_id_by_import(
        self, import_task_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_metadata_lookup_task_id_by_import(import_task_id)

    def get_organize_job_for_work_media_version(
        self, work_id: str, media_version_id: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_organize_job_for_work_media_version(
                work_id, media_version_id
            )

    def get_pending_import_task_for_source(
        self, source_path: str
    ) -> Record | None:
        with self._projection:
            return self._queries.get_pending_import_task_for_source(source_path)

    def get_volume_context_by_id(self, volume_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_volume_context_by_id(volume_id)

    def get_work_by_id(self, work_id: str) -> Record | None:
        with self._projection:
            return self._queries.get_work_by_id(work_id)

    def get_work_by_merge_key(self, merge_key: str) -> Record | None:
        with self._projection:
            return self._queries.get_work_by_merge_key(merge_key)

    def get_work_by_normalized_title(self, normalized_title: str) -> Record | None:
        with self._projection:
            return self._queries.get_work_by_normalized_title(normalized_title)

    def has_generated_cover_path(self, work_id: str, cover_path: str) -> bool:
        with self._projection:
            return self._queries.has_generated_cover_path(work_id, cover_path)

    def list_audio_chapter_units_for_file_ordered(
        self, file_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_chapter_units_for_file_ordered(file_id)

    def list_audio_chapters_for_file(self, file_id: str) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_chapters_for_file(file_id)

    def list_audio_chapters_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_chapters_for_media_version(
                media_version_id
            )

    def list_audio_files_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_files_for_media_version(media_version_id)

    def list_audio_files_for_volume(
        self, media_version_id: str, volume_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_audio_files_for_volume(
                media_version_id, volume_id
            )

    def list_audiobook_consumption_for_works(
        self, work_ids: list[str]
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_audiobook_consumption_for_works(work_ids)

    def list_file_volumes_by_paths(self, paths: list[str]) -> list[Record]:
        with self._projection:
            return self._queries.list_file_volumes_by_paths(paths)

    def list_library_files_by_paths(self, paths: list[str]) -> list[Record]:
        with self._projection:
            return self._queries.list_library_files_by_paths(paths)

    def list_media_versions_by_ids(
        self, media_version_ids: list[str]
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_media_versions_by_ids(media_version_ids)

    def list_reading_progress_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_reading_progress_for_media_version(
                media_version_id
            )

    def list_reading_progress_for_media_versions(
        self, media_version_ids: list[str]
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_reading_progress_for_media_versions(
                media_version_ids
            )

    def list_reflowable_chapters_for_volume(
        self, volume_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_reflowable_chapters_for_volume(volume_id)

    def list_reflowable_chapters_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_reflowable_chapters_for_media_version(
                media_version_id
            )

    def list_unassigned_audio_chapters_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_unassigned_audio_chapters_for_media_version(
                media_version_id
            )

    def list_visible_media_versions_for_work_and_format(
        self, work_id: str, fmt: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_visible_media_versions_for_work_and_format(
                work_id, fmt
            )

    def list_volume_cover_paths_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_volume_cover_paths_for_media_version(
                media_version_id
            )

    def list_volume_ordering_for_media_version(
        self, media_version_id: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_volume_ordering_for_media_version(
                media_version_id
            )

    def list_works_by_merge_key_prefix(
        self, merge_key_prefix: str
    ) -> list[Record]:
        with self._projection:
            return self._queries.list_works_by_merge_key_prefix(merge_key_prefix)

    def sum_audio_duration_for_media_version(self, media_version_id: str) -> int:
        with self._projection:
            return self._queries.sum_audio_duration_for_media_version(
                media_version_id
            )

    def sum_audio_duration_for_volume(self, volume_id: str) -> int:
        with self._projection:
            return self._queries.sum_audio_duration_for_volume(volume_id)

    def sum_audio_file_size_for_media_version(self, media_version_id: str) -> int:
        with self._projection:
            return self._queries.sum_audio_file_size_for_media_version(
                media_version_id
            )

    def sum_file_size_bytes_for_media_version(self, media_version_id: str) -> int:
        with self._projection:
            return self._queries.sum_file_size_bytes_for_media_version(
                media_version_id
            )

    def sum_volume_chapter_count_for_media_version(
        self, media_version_id: str
    ) -> int:
        with self._projection:
            return self._queries.sum_volume_chapter_count_for_media_version(
                media_version_id
            )

    def sum_volume_page_count_for_media_version(
        self, media_version_id: str
    ) -> int:
        with self._projection:
            return self._queries.sum_volume_page_count_for_media_version(
                media_version_id
            )
