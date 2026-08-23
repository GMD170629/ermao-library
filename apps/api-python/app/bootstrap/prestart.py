"""Fresh-install schema bootstrap and runtime schema barrier."""

from __future__ import annotations

import sys

from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.runner import head_revision
from app.db.session import engine


class SchemaBarrierError(RuntimeError):
    """The API or worker cannot start against a non-current schema."""


def verify_current_schema(active_engine: Engine) -> None:
    """Require the single fresh-install baseline revision."""

    expected_revision = head_revision(active_engine)
    with active_engine.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision != expected_revision:
        raise SchemaBarrierError(
            "database schema is not current: "
            f"expected {expected_revision!r}, found {current_revision!r}"
        )
    print(
        f"schema_barrier outcome=ready revision={current_revision}",
        file=sys.stdout,
        flush=True,
    )


def main() -> None:
    """Create the fresh schema and seed current baseline data before startup."""

    print("prestart outcome=started", file=sys.stdout, flush=True)
    try:
        settings = get_settings()
        bootstrap_database(engine, settings)
        verify_current_schema(engine)
    except Exception:
        print("prestart outcome=failed", file=sys.stderr, flush=True)
        raise
    print("prestart outcome=success", file=sys.stdout, flush=True)


__all__ = ["SchemaBarrierError", "main", "verify_current_schema"]


if __name__ == "__main__":
    main()
