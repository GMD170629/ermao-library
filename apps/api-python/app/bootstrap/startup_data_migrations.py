"""Container pre-start entry point for required schema and data migrations."""

from __future__ import annotations

import sys

from app.bootstrap.comic_page_index_migration import (
    run_comic_page_index_data_migration,
)
from app.bootstrap.library_facet_index import (
    run_library_facet_index_data_migration,
)
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.session import SessionLocal, engine


def main() -> None:
    """Finish every startup prerequisite before the API process is launched."""

    print("startup_data_migrations outcome=started", file=sys.stdout, flush=True)
    try:
        settings = get_settings()
        bootstrap_database(engine, settings)
        run_library_facet_index_data_migration(SessionLocal)
        run_comic_page_index_data_migration(SessionLocal, settings)
    except Exception:
        print("startup_data_migrations outcome=failed", file=sys.stderr, flush=True)
        raise
    print("startup_data_migrations outcome=success", file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()
