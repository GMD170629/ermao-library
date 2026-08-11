"""Blocking startup boundary for the comic page-index data migration."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy.orm import Session, sessionmaker

from app.contracts.comic_page_index import CURRENT_COMIC_PAGE_INDEX_VERSION
from app.core.config import Settings
from app.modules.media.application.comic_page_index_migration import (
    MigrateComicPageIndexBatch,
)
from app.modules.media.infrastructure.comic_page_index_migration import (
    FileComicPageIndexParser,
    prepare_comic_page_index_write,
)
from app.modules.media.infrastructure.uow import (
    SqlAlchemyComicPageIndexMigrationUnitOfWork,
)

LOGGER = logging.getLogger(__name__)
COMIC_PAGE_INDEX_MIGRATION_BATCH_SIZE = 25
COMIC_PAGE_INDEX_MIGRATION_MAX_PAGE_ROWS = 750
MIGRATION_PROGRESS_LOG_INTERVAL_SECONDS = 5.0


class ComicPageIndexDataMigrationError(RuntimeError):
    """The required startup data migration could not finish safely."""


def _log_migration_info(message: str, *arguments: object) -> None:
    """Keep lifecycle records visible in API and standalone worker containers."""

    if LOGGER.isEnabledFor(logging.INFO) and LOGGER.hasHandlers():
        LOGGER.info(message, *arguments)
        return
    print(message % arguments, file=sys.stdout, flush=True)


def run_comic_page_index_data_migration(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    batch_size: int = COMIC_PAGE_INDEX_MIGRATION_BATCH_SIZE,
    max_page_rows: int = COMIC_PAGE_INDEX_MIGRATION_MAX_PAGE_ROWS,
) -> None:
    """Finish the restartable migration before the API/worker becomes ready."""

    migration = MigrateComicPageIndexBatch(
        lambda: SqlAlchemyComicPageIndexMigrationUnitOfWork(session_factory),
        FileComicPageIndexParser(settings),
        lambda: datetime.now(UTC),
        prepare_comic_page_index_write,
    )
    started_at = monotonic()
    last_progress_at = started_at
    batches = 0
    scanned_total = 0
    processed_total = 0
    inserted_page_rows_total = 0
    cursor: str | None = None
    _log_migration_info(
        "comic_page_index_data_migration outcome=started version=%s "
        "batch_size=%s max_page_rows=%s",
        CURRENT_COMIC_PAGE_INDEX_VERSION,
        batch_size,
        max_page_rows,
    )
    try:
        while True:
            result = migration.execute(
                limit=batch_size,
                max_page_rows=max_page_rows,
                after_file_id=cursor,
            )
            if result.failed_file_ids:
                raise ComicPageIndexDataMigrationError(
                    "comic page-index source parsing failed for file ids: "
                    + ", ".join(result.failed_file_ids)
                )
            if not result.scanned:
                if cursor is not None:
                    cursor = None
                    continue
                break
            batches += 1
            scanned_total += result.scanned
            processed_total += result.processed
            inserted_page_rows_total += result.inserted_page_rows
            cursor = result.last_file_id
            progress_at = monotonic()
            if (
                batches == 1
                or progress_at - last_progress_at
                >= MIGRATION_PROGRESS_LOG_INTERVAL_SECONDS
            ):
                _log_migration_info(
                    "comic_page_index_data_migration outcome=progress batch=%s "
                    "scanned=%s processed=%s inserted_page_rows=%s "
                    "total_processed=%s duration_ms=%s",
                    batches,
                    result.scanned,
                    result.processed,
                    result.inserted_page_rows,
                    processed_total,
                    round((progress_at - started_at) * 1000),
                )
                last_progress_at = progress_at
    except Exception:
        LOGGER.exception(
            "comic_page_index_data_migration outcome=failed version=%s "
            "batches=%s scanned=%s processed=%s inserted_page_rows=%s "
            "duration_ms=%s",
            CURRENT_COMIC_PAGE_INDEX_VERSION,
            batches,
            scanned_total,
            processed_total,
            inserted_page_rows_total,
            round((monotonic() - started_at) * 1000),
        )
        raise
    _log_migration_info(
        "comic_page_index_data_migration outcome=success version=%s "
        "batches=%s scanned=%s processed=%s inserted_page_rows=%s duration_ms=%s",
        CURRENT_COMIC_PAGE_INDEX_VERSION,
        batches,
        scanned_total,
        processed_total,
        inserted_page_rows_total,
        round((monotonic() - started_at) * 1000),
    )


def comic_page_index_data_migration_is_complete(
    session_factory: sessionmaker[Session],
) -> bool:
    """Check the page-index version checkpoint without opening comic files."""

    with SqlAlchemyComicPageIndexMigrationUnitOfWork(
        session_factory
    ) as unit_of_work:
        return not unit_of_work.page_indexes.pending(
            limit=1,
            after_file_id=None,
        )


__all__ = [
    "ComicPageIndexDataMigrationError",
    "comic_page_index_data_migration_is_complete",
    "run_comic_page_index_data_migration",
]
