"""Explicit Session-bound projections for topology-bound imports."""

from __future__ import annotations

from functools import partial

from sqlalchemy.orm import Session

from app.modules.imports.infrastructure import library_queries


class SqlAlchemyImportLibraryQueries:
    def __init__(self, db: Session) -> None:
        self.existing_file_import_snapshot = partial(
            library_queries.existing_file_import_snapshot, db
        )
        self.find_work_cover_volume = partial(
            library_queries.find_work_cover_volume, db
        )
        self.get_import_asset_by_task_and_path = partial(
            library_queries.get_import_asset_by_task_and_path, db
        )
        self.get_import_task_by_id = partial(library_queries.get_import_task_by_id, db)
        self.get_volume_context_by_id = partial(
            library_queries.get_volume_context_by_id, db
        )
        self.get_work_by_id = partial(library_queries.get_work_by_id, db)
        self.has_generated_cover_path = partial(
            library_queries.has_generated_cover_path, db
        )
        self.list_file_volumes_by_paths = partial(
            library_queries.list_file_volumes_by_paths, db
        )
        self.list_audio_volume_files = partial(
            library_queries.list_audio_volume_files, db
        )
        self.list_audio_volume_units = partial(
            library_queries.list_audio_volume_units, db
        )
        self.list_volume_cover_paths_for_version = partial(
            library_queries.list_volume_cover_paths_for_version, db
        )
