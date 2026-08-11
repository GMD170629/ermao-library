"""Blocking startup boundary for the historical work-facet data migration."""

from __future__ import annotations

import logging
import sys
from time import monotonic

from sqlalchemy.orm import Session, sessionmaker

from app.modules.library.application.facet_index import RebuildFacetIndexBatch
from app.modules.library.domain.facets import CURRENT_FACET_INDEX_VERSION
from app.modules.library.infrastructure.uow import SqlAlchemyFacetIndexUnitOfWork

LOGGER = logging.getLogger(__name__)
FACET_INDEX_MIGRATION_BATCH_SIZE = 50
MIGRATION_PROGRESS_LOG_INTERVAL_SECONDS = 5.0


class LibraryFacetIndexDataMigrationError(RuntimeError):
    """The required work-facet migration could not make forward progress."""


def _log_migration_info(message: str, *arguments: object) -> None:
    """Keep lifecycle records visible in API and standalone worker containers."""

    if LOGGER.isEnabledFor(logging.INFO) and LOGGER.hasHandlers():
        LOGGER.info(message, *arguments)
        return
    print(message % arguments, file=sys.stdout, flush=True)


def run_library_facet_index_data_migration(
    session_factory: sessionmaker[Session],
    *,
    batch_size: int = FACET_INDEX_MIGRATION_BATCH_SIZE,
) -> None:
    """Complete all pending facet rows before API/worker readiness."""

    migration = RebuildFacetIndexBatch(
        lambda: SqlAlchemyFacetIndexUnitOfWork(session_factory)
    )
    started_at = monotonic()
    last_progress_at = started_at
    batches = 0
    processed_total = 0
    _log_migration_info(
        "library_facet_index_data_migration outcome=started version=%s "
        "batch_size=%s",
        CURRENT_FACET_INDEX_VERSION,
        batch_size,
    )
    try:
        while True:
            result = migration.execute(limit=batch_size)
            if not result.processed:
                if result.may_have_more:
                    raise LibraryFacetIndexDataMigrationError(
                        "work-facet migration could not make forward progress"
                    )
                break
            batches += 1
            processed_total += result.processed
            progress_at = monotonic()
            if (
                batches == 1
                or progress_at - last_progress_at
                >= MIGRATION_PROGRESS_LOG_INTERVAL_SECONDS
            ):
                _log_migration_info(
                    "library_facet_index_data_migration outcome=progress "
                    "batch=%s processed=%s total_processed=%s duration_ms=%s",
                    batches,
                    result.processed,
                    processed_total,
                    round((progress_at - started_at) * 1000),
                )
                last_progress_at = progress_at
            if not result.may_have_more:
                break
    except Exception:
        LOGGER.exception(
            "library_facet_index_data_migration outcome=failed version=%s "
            "batches=%s processed=%s duration_ms=%s",
            CURRENT_FACET_INDEX_VERSION,
            batches,
            processed_total,
            round((monotonic() - started_at) * 1000),
        )
        raise
    _log_migration_info(
        "library_facet_index_data_migration outcome=success version=%s "
        "batches=%s processed=%s duration_ms=%s",
        CURRENT_FACET_INDEX_VERSION,
        batches,
        processed_total,
        round((monotonic() - started_at) * 1000),
    )


__all__ = [
    "LibraryFacetIndexDataMigrationError",
    "run_library_facet_index_data_migration",
]
