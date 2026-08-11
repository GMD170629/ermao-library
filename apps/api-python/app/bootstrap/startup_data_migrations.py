"""Container pre-start entry point for required schema and data migrations."""

from __future__ import annotations

import sys

from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.comic_page_index_migration import (
    comic_page_index_data_migration_is_complete,
    run_comic_page_index_data_migration,
)
from app.bootstrap.library_facet_index import (
    library_facet_index_data_migration_is_complete,
    run_library_facet_index_data_migration,
)
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.runner import head_revision
from app.db.session import SessionLocal, engine


class StartupDataMigrationBarrierError(RuntimeError):
    """The API/worker cannot become ready while required migrations are pending."""

    def __init__(self, incomplete_stages: tuple[str, ...]) -> None:
        self.incomplete_stages = incomplete_stages
        super().__init__(
            "required startup data migrations are incomplete: "
            + ", ".join(incomplete_stages)
        )


def verify_startup_data_migrations_complete(
    active_engine: Engine,
    session_factory: sessionmaker[Session],
) -> None:
    """Perform the read-only readiness check used by API and worker processes."""

    expected_revision = head_revision(active_engine)
    with active_engine.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision != expected_revision:
        raise StartupDataMigrationBarrierError(("schema",))

    incomplete_stages: list[str] = []
    if not library_facet_index_data_migration_is_complete(session_factory):
        incomplete_stages.append("library_facet_index")
    if not comic_page_index_data_migration_is_complete(session_factory):
        incomplete_stages.append("comic_page_index")
    if incomplete_stages:
        raise StartupDataMigrationBarrierError(tuple(incomplete_stages))

    print(
        "startup_data_migration_barrier outcome=ready "
        f"revision={current_revision}",
        file=sys.stdout,
        flush=True,
    )


def main() -> None:
    """Finish every startup prerequisite before the API process is launched."""

    print("startup_data_migrations outcome=started", file=sys.stdout, flush=True)
    try:
        settings = get_settings()
        bootstrap_database(engine, settings)
        run_library_facet_index_data_migration(SessionLocal)
        run_comic_page_index_data_migration(SessionLocal, settings)
        verify_startup_data_migrations_complete(engine, SessionLocal)
    except Exception:
        print("startup_data_migrations outcome=failed", file=sys.stderr, flush=True)
        raise
    print("startup_data_migrations outcome=success", file=sys.stdout, flush=True)


__all__ = [
    "StartupDataMigrationBarrierError",
    "main",
    "verify_startup_data_migrations_complete",
]


if __name__ == "__main__":
    main()
