"""Database bootstrap: schema migrations via Alembic, then baseline seed data."""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.legacy_bridge import CURRENT_SCHEMA_VERSION
from app.db.runner import _apply_schema_once, apply_schema
from app.db.seed import (
    backfill_library_consumption_states,
    backfill_library_identity_keys,
    migrate_global_kindle_email_to_original_admin,
    migrate_library_reading_statuses,
    reconcile_metadata_lookup_organize_statuses,
    requeue_metadata_no_match_tasks_for_title_aliases,
    seed_baseline_data,
    seed_reader_progress_cursors,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "_apply_schema_once",
    "apply_schema",
    "backfill_library_consumption_states",
    "backfill_library_identity_keys",
    "bootstrap_database",
    "migrate_global_kindle_email_to_original_admin",
    "migrate_library_reading_statuses",
    "reconcile_metadata_lookup_organize_statuses",
    "requeue_metadata_no_match_tasks_for_title_aliases",
    "seed_baseline_data",
    "seed_reader_progress_cursors",
]


def bootstrap_database(engine: Engine, settings: Settings) -> None:
    """Initialize the SQLite schema and baseline data."""

    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    apply_schema(engine, settings)
    with Session(engine) as db:
        seed_baseline_data(db)


def main() -> None:
    from app.db.session import engine

    bootstrap_database(engine, get_settings())


if __name__ == "__main__":
    main()
