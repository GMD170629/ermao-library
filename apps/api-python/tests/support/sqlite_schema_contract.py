"""Compare ORM business tables while checking migration-owned search tables."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from app.db.base import Base

SEARCH_PROJECTION_TABLES = frozenset(
    {
        "LibraryBookSearch",
        "LibraryBookSearch_data",
        "LibraryBookSearch_idx",
        "LibraryBookSearch_content",
        "LibraryBookSearch_docsize",
        "LibraryBookSearch_config",
    }
)


def assert_current_schema_matches_metadata(connection: Connection) -> None:
    assert SEARCH_PROJECTION_TABLES <= set(inspect(connection).get_table_names())
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "compare_server_default": True,
            # These exact FTS tables are maintained by migrations, not the ORM.
            # Missing search tables and unknown business tables still fail.
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                not (type_ == "table" and name in SEARCH_PROJECTION_TABLES)
            ),
        },
    )
    assert compare_metadata(context, Base.metadata) == []
