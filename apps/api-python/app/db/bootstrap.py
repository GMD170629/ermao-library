"""Database bootstrap: fresh-install schema via Alembic, then baseline seed data."""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.runner import _apply_schema_once, apply_schema
from app.db.seed import seed_baseline_data

__all__ = [
    "_apply_schema_once",
    "apply_schema",
    "bootstrap_database",
    "seed_baseline_data",
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
