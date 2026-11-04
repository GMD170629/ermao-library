"""Index searchable substrings without changing LIKE search semantics."""

import sqlalchemy as sa
from alembic import op

revision = "0057_book_substring_search"
down_revision = "0056_resource_identity_cover"
branch_labels = None
depends_on = None

TABLE = "LibraryBookSearch"
FIELDS = ("bookId", "title", "author", "seriesName", "description")


def upgrade() -> None:
    # This is a derived index. Rebuild it after an interrupted, unversioned
    # migration rather than retaining a partially populated search projection.
    for action in ("insert", "update", "delete"):
        op.execute(sa.DDL(f'DROP TRIGGER IF EXISTS "{TABLE}_{action}"'))
    op.execute(sa.DDL(f'DROP TABLE IF EXISTS "{TABLE}"'))
    op.execute(
        sa.DDL(
            f'CREATE VIRTUAL TABLE "{TABLE}" USING fts5('
            '"bookId" UNINDEXED, title, author, "seriesName", description, '
            "tokenize='trigram', detail=none)"
        )
    )
    source = sa.table("LibraryBookMetadata", *(sa.column(name) for name in FIELDS))
    target = sa.table(TABLE, sa.column("rowid"), *(sa.column(name) for name in FIELDS))
    op.execute(
        target.insert()
        .from_select(
            ["rowid", *FIELDS],
            sa.select(sa.literal_column("rowid"), *(source.c[name] for name in FIELDS)),
        )
        .execution_options(schema_index_build=True)
    )
    columns = ", ".join(f'"{name}"' for name in FIELDS)
    values = ", ".join(f'new."{name}"' for name in FIELDS)
    insertion = (
        f'INSERT INTO "{TABLE}" (rowid, {columns}) VALUES (new.rowid, {values});'
    )
    op.execute(
        sa.DDL(
            f'CREATE TRIGGER "{TABLE}_insert" AFTER INSERT ON "LibraryBookMetadata" BEGIN {insertion} END'
        )
    )
    op.execute(
        sa.DDL(
            f'CREATE TRIGGER "{TABLE}_delete" AFTER DELETE ON "LibraryBookMetadata" BEGIN DELETE FROM "{TABLE}" WHERE rowid=old.rowid; END'
        )
    )
    changes = " OR ".join(f'old."{name}" IS NOT new."{name}"' for name in FIELDS)
    op.execute(
        sa.DDL(
            f'CREATE TRIGGER "{TABLE}_update" AFTER UPDATE OF {columns} ON "LibraryBookMetadata" '
            f'WHEN {changes} BEGIN DELETE FROM "{TABLE}" WHERE rowid=old.rowid; {insertion} END'
        )
    )


def downgrade() -> None:
    for action in ("insert", "update", "delete"):
        op.execute(sa.DDL(f'DROP TRIGGER "{TABLE}_{action}"'))
    op.execute(sa.DDL(f'DROP TABLE "{TABLE}"'))
