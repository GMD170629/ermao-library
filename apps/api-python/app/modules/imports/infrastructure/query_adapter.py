"""Explicit Session-bound query adapter for import media commands."""

from __future__ import annotations

from functools import partial

from sqlalchemy.orm import Session

from app.modules.imports.infrastructure import library_queries


class SqlAlchemyImportLibraryQueries:
    """Bind ``library_queries`` functions to one Session without exposing it to callers."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self.copy_shelf_links_to_work = partial(
            library_queries.copy_shelf_links_to_work, db
        )
        self.count_audio_chapters_for_media_version = partial(
            library_queries.count_audio_chapters_for_media_version, db
        )
        self.count_audio_chapters_for_volume = partial(
            library_queries.count_audio_chapters_for_volume, db
        )
        self.count_audio_files_for_media_version = partial(
            library_queries.count_audio_files_for_media_version, db
        )
        self.count_audiobook_media_kind_media_versions = partial(
            library_queries.count_audiobook_media_kind_media_versions, db
        )
        self.count_media_versions_for_work = partial(
            library_queries.count_media_versions_for_work, db
        )
        self.count_primary_audiobook_media_versions_for_work = partial(
            library_queries.count_primary_audiobook_media_versions_for_work, db
        )
        self.count_visible_media_versions_for_work = partial(
            library_queries.count_visible_media_versions_for_work, db
        )
        self.count_visible_volumes_for_work = partial(
            library_queries.count_visible_volumes_for_work, db
        )
        self.count_volumes_for_media_version = partial(
            library_queries.count_volumes_for_media_version, db
        )
        self.delete_audio_metadata_sources = partial(
            library_queries.delete_audio_metadata_sources, db
        )
        self.detach_audio_chapters_for_media_version = partial(
            library_queries.detach_audio_chapters_for_media_version, db
        )
        self.detach_audio_chapters_for_media_version_or_files = partial(
            library_queries.detach_audio_chapters_for_media_version_or_files, db
        )
        self.existing_file_import_snapshot = partial(
            library_queries.existing_file_import_snapshot, db
        )
        self.fail_import_assets_for_task = partial(
            library_queries.fail_import_assets_for_task, db
        )
        self.find_audio_media_version_by_resource_key = partial(
            library_queries.find_audio_media_version_by_resource_key, db
        )
        self.find_deferred_source_volume = partial(
            library_queries.find_deferred_source_volume, db
        )
        self.find_media_version_resource_key_conflict = partial(
            library_queries.find_media_version_resource_key_conflict, db
        )
        self.find_volume_conflict = partial(library_queries.find_volume_conflict, db)
        self.find_work_cover_media_version = partial(
            library_queries.find_work_cover_media_version, db
        )
        self.get_conversion_by_import_task_id = partial(
            library_queries.get_conversion_by_import_task_id, db
        )
        self.get_media_version_by_id = partial(
            library_queries.get_media_version_by_id, db
        )
        self.get_media_version_cover_path = partial(
            library_queries.get_media_version_cover_path, db
        )
        self.get_media_version_format = partial(
            library_queries.get_media_version_format, db
        )
        self.get_first_volume_for_media_version = partial(
            library_queries.get_first_volume_for_media_version, db
        )
        self.get_volume_context_by_id = partial(
            library_queries.get_volume_context_by_id, db
        )
        self.get_import_asset_by_task_and_path = partial(
            library_queries.get_import_asset_by_task_and_path, db
        )
        self.get_import_task_by_id = partial(library_queries.get_import_task_by_id, db)
        self.get_latest_audio_tags_metadata = partial(
            library_queries.get_latest_audio_tags_metadata, db
        )
        self.get_metadata_lookup_task_id_by_import = partial(
            library_queries.get_metadata_lookup_task_id_by_import, db
        )
        self.get_organize_job_for_work_media_version = partial(
            library_queries.get_organize_job_for_work_media_version, db
        )
        self.get_pending_import_task_for_source = partial(
            library_queries.get_pending_import_task_for_source, db
        )
        self.get_work_by_id = partial(library_queries.get_work_by_id, db)
        self.get_work_by_merge_key = partial(library_queries.get_work_by_merge_key, db)
        self.has_generated_cover_path = partial(
            library_queries.has_generated_cover_path, db
        )
        self.list_audio_chapter_units_for_file_ordered = partial(
            library_queries.list_audio_chapter_units_for_file_ordered, db
        )
        self.list_audio_chapters_for_media_version = partial(
            library_queries.list_audio_chapters_for_media_version, db
        )
        self.list_audio_chapters_for_file = partial(
            library_queries.list_audio_chapters_for_file, db
        )
        self.list_audio_files_for_media_version = partial(
            library_queries.list_audio_files_for_media_version, db
        )
        self.list_audio_files_for_volume = partial(
            library_queries.list_audio_files_for_volume, db
        )
        self.list_audiobook_consumption_for_works = partial(
            library_queries.list_audiobook_consumption_for_works, db
        )
        self.list_media_version_file_paths_for_work = partial(
            library_queries.list_media_version_file_paths_for_work, db
        )
        self.list_media_versions_by_ids = partial(
            library_queries.list_media_versions_by_ids, db
        )
        self.list_file_volumes_by_paths = partial(
            library_queries.list_file_volumes_by_paths, db
        )
        self.list_library_files_by_paths = partial(
            library_queries.list_library_files_by_paths, db
        )
        self.list_reflowable_chapters_for_media_version = partial(
            library_queries.list_reflowable_chapters_for_media_version, db
        )
        self.list_reflowable_chapters_for_volume = partial(
            library_queries.list_reflowable_chapters_for_volume, db
        )
        self.list_reading_progress_for_media_version = partial(
            library_queries.list_reading_progress_for_media_version, db
        )
        self.list_reading_progress_for_media_versions = partial(
            library_queries.list_reading_progress_for_media_versions, db
        )
        self.list_unassigned_audio_chapters_for_media_version = partial(
            library_queries.list_unassigned_audio_chapters_for_media_version, db
        )
        self.list_visible_media_versions_for_work_and_format = partial(
            library_queries.list_visible_media_versions_for_work_and_format, db
        )
        self.list_volume_cover_paths_for_media_version = partial(
            library_queries.list_volume_cover_paths_for_media_version, db
        )
        self.list_works_by_source_group_suffix = partial(
            library_queries.list_works_by_source_group_suffix, db
        )
        self.sum_audio_duration_for_media_version = partial(
            library_queries.sum_audio_duration_for_media_version, db
        )
        self.sum_audio_duration_for_volume = partial(
            library_queries.sum_audio_duration_for_volume, db
        )
        self.sum_audio_file_size_for_media_version = partial(
            library_queries.sum_audio_file_size_for_media_version, db
        )
        self.sum_file_size_bytes_for_media_version = partial(
            library_queries.sum_file_size_bytes_for_media_version, db
        )
        self.sum_volume_chapter_count_for_media_version = partial(
            library_queries.sum_volume_chapter_count_for_media_version, db
        )
        self.sum_volume_page_count_for_media_version = partial(
            library_queries.sum_volume_page_count_for_media_version, db
        )
