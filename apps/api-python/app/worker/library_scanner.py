from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.bootstrap.imports import (
    LibraryConfig,
    library_config,
    library_state_repository,
    persist_import_scan_requests,
)
from app.modules.imports.application.scan_jobs import prepare_import_scan_job
from app.services.import_preferences import (
    DEFAULT_STABILITY_CHECK_ENABLED,
    IMPORT_ALLOWED_EXTENSIONS_KEY,
    IMPORT_IGNORE_PATTERNS_KEY,
    IMPORT_PREFERENCE_KEYS,
    IMPORT_STABILITY_ENABLED_KEY,
    IMPORT_STABILITY_SECONDS_KEY,
    ImportPreferences,
    default_stability_seconds,
    normalize_allowed_extensions,
    normalize_ignore_patterns,
    normalize_import_setting_value,
    normalize_stability_seconds,
)
from app.worker.path_security import PathSecurityError, PathSecurityService

get_system_settings = library_state_repository.get_system_settings
list_enabled_libraries = library_state_repository.list_enabled_libraries

WORKER_REFRESH_SETTING_KEYS = tuple(sorted(IMPORT_PREFERENCE_KEYS))


@dataclass(frozen=True, slots=True)
class WorkerRefreshProjection:
    libraries: tuple[LibraryConfig, ...]


class WorkerManager:
    def __init__(self, db_factory) -> None:
        self.db_factory = db_factory
        self.security = PathSecurityService()
        self._imports_paused = False

    def refresh_worker_state(self) -> None:
        try:
            with self.db_factory() as db:
                library_rows = tuple(list_enabled_libraries(db))
                setting_values = get_system_settings(db, WORKER_REFRESH_SETTING_KEYS)
            libraries = library_scan_configs(library_rows, setting_values)
            projection = WorkerRefreshProjection(
                libraries=libraries,
            )
        except SQLAlchemyError as exc:
            print(
                f"[import-worker] scan projection unavailable, retrying later: {exc}",
                flush=True,
            )
            return
        self.schedule_library_scans(projection.libraries)

    def schedule_library_scans(self, libraries: tuple[LibraryConfig, ...]) -> int:
        """Queue one deduplicated root scan per enabled library."""

        if self._imports_paused:
            return 0
        checkpoint_at = datetime.now(UTC)
        prepared_jobs = []
        for library in libraries:
            try:
                real_path = self.security.validate_library_root(
                    library.root_path
                ).real_path
            except PathSecurityError as exc:
                print(
                    f"[import-worker] library scan skipped {library.root_path}: {exc}",
                    flush=True,
                )
                continue
            prepared_jobs.append(
                prepare_import_scan_job(
                    job_id=f"scan_{uuid4().hex}",
                    work_item_id=f"work_{uuid4().hex}",
                    library_id=library.id,
                    actor_user_id=None,
                    canonical_root_path=str(real_path),
                    trigger="PERIODIC",
                    available_at=None,
                    created_at=checkpoint_at,
                )
            )
        try:
            with self.db_factory() as db:
                created_count = persist_import_scan_requests(
                    db, tuple(prepared_jobs), ()
                )
        except SQLAlchemyError as exc:
            print(
                f"[import-worker] library scan scheduling deferred: {exc}",
                flush=True,
            )
            return 0
        if created_count:
            print(
                f"[import-worker] scheduled {created_count} library root scan(s)",
                flush=True,
            )
        return created_count

    def shutdown(self) -> None:
        """The scanner owns no process-external resources."""

    def pause_import_scheduling(self) -> None:
        self._imports_paused = True

    def resume_import_scheduling(self) -> None:
        self._imports_paused = False


def library_scan_configs(
    rows: tuple[Mapping[str, object], ...],
    setting_values: Mapping[str, str],
) -> tuple[LibraryConfig, ...]:
    """Map detached SQL projections into root-scanner configuration."""

    stability_enabled = normalize_import_setting_value(
        IMPORT_STABILITY_ENABLED_KEY,
        setting_values.get(IMPORT_STABILITY_ENABLED_KEY),
    )
    preferences = ImportPreferences(
        stability_check_enabled=(
            stability_enabled
            if isinstance(stability_enabled, bool)
            else DEFAULT_STABILITY_CHECK_ENABLED
        ),
        stability_check_seconds=(
            normalize_stability_seconds(setting_values[IMPORT_STABILITY_SECONDS_KEY])
            if IMPORT_STABILITY_SECONDS_KEY in setting_values
            else default_stability_seconds()
        ),
        allowed_extensions=normalize_allowed_extensions(
            setting_values.get(IMPORT_ALLOWED_EXTENSIONS_KEY)
        ),
        ignore_patterns=normalize_ignore_patterns(
            setting_values.get(IMPORT_IGNORE_PATTERNS_KEY)
        ),
    )
    return tuple(library_config(row, preferences=preferences) for row in rows)
