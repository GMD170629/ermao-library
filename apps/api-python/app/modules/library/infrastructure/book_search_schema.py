"""SQLite derived search index for the current ORM schema.

Alembic revisions retain their own frozen DDL. These events give ORM-created
schemas the same virtual index and transactional maintenance triggers.
"""

from sqlalchemy import DDL, String, column, event, table

from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBookMetadata,
)

_FIELDS = ("bookId", "title", "author", "seriesName", "description")
book_search_index = table(
    "LibraryBookSearch", *(column(name, String) for name in _FIELDS)
)
_source = LibraryBookMetadata.__table__
_columns = ", ".join(f'"{name}"' for name in _FIELDS)
_values = ", ".join(f'new."{name}"' for name in _FIELDS)
_insert = f'INSERT INTO "LibraryBookSearch" (rowid, {_columns}) VALUES (new.rowid, {_values});'
_changes = " OR ".join(f'old."{name}" IS NOT new."{name}"' for name in _FIELDS)
_create = (
    (
        'CREATE VIRTUAL TABLE "LibraryBookSearch" USING fts5('
        '"bookId" UNINDEXED, title, author, "seriesName", description, '
        "tokenize='trigram', detail=none)"
    ),
    f'CREATE TRIGGER "LibraryBookSearch_insert" AFTER INSERT ON "LibraryBookMetadata" BEGIN {_insert} END',
    'CREATE TRIGGER "LibraryBookSearch_delete" AFTER DELETE ON "LibraryBookMetadata" BEGIN DELETE FROM "LibraryBookSearch" WHERE rowid=old.rowid; END',
    f'CREATE TRIGGER "LibraryBookSearch_update" AFTER UPDATE OF {_columns} ON "LibraryBookMetadata" WHEN {_changes} BEGIN DELETE FROM "LibraryBookSearch" WHERE rowid=old.rowid; {_insert} END',
)
for _statement in _create:
    event.listen(_source, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
event.listen(
    _source,
    "after_drop",
    DDL('DROP TABLE IF EXISTS "LibraryBookSearch"').execute_if(dialect="sqlite"),
)
