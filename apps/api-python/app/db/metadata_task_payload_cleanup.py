"""Back up and clear obsolete task payloads before the 0042 schema upgrade.

Run with API and workers stopped so old code cannot refill the columns:
python -m app.db.metadata_task_payload_cleanup --database DB --backup BACKUP

Each bounded batch commits separately. An interrupted run can be repeated with
a new backup filename; keep the original backup for complete data recovery.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.db.sqlite import create_sqlite_engine

PAYLOAD_COLUMNS = (
    ("MetadataLookupTask", "candidateRawJson"),
    ("MetadataProviderExecution", "rawResultJson"),
)


def clear_metadata_task_payloads(
    engine: Engine, *, batch_size: int = 128
) -> Iterator[tuple[str, int]]:
    """Yield committed row counts; never change task state or schema."""
    if not 1 <= batch_size <= 128:
        raise ValueError("batch_size must be between 1 and 128")
    for table_name, column_name in PAYLOAD_COLUMNS:
        columns = sa.inspect(engine).get_columns(table_name)
        if not any(column["name"] == column_name for column in columns):
            continue
        table = sa.table(
            table_name, sa.column("id", sa.String(191)),
            sa.column(column_name, sa.Text),
        )
        payload = table.c[column_name]
        last_id: str | None = None
        while True:
            with engine.begin() as connection:
                page = sa.select(table.c.id).where(payload.is_not(None))
                if last_id is not None:
                    page = page.where(table.c.id > last_id)
                ids = list(connection.scalars(page.order_by(table.c.id).limit(batch_size)))
                if not ids:
                    break
                connection.execute(
                    table.update().where(table.c.id.in_(ids)).values({column_name: None})
                )
                last_id = ids[-1]
            yield table_name, len(ids)


def backup_database(engine: Engine, path: Path) -> None:
    """Use SQLite's online backup API, including committed WAL contents."""
    if path.exists():
        raise FileExistsError(f"Backup already exists: {path}")
    incomplete = path.with_name(path.name + ".incomplete")
    with incomplete.open("xb"):
        pass
    incomplete.chmod(0o600)
    destination = create_sqlite_engine(incomplete)
    try:
        with engine.connect() as source, destination.connect() as target:
            source.connection.driver_connection.backup(
                target.connection.driver_connection, pages=256
            )
    finally:
        destination.dispose()
    incomplete.rename(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.resolve(strict=True)
    backup = args.backup.resolve()
    if database == backup:
        parser.error("database and backup must be different files")
    engine = create_sqlite_engine(database)
    try:
        backup_database(engine, backup)
        print(f"Backup complete: {backup}", flush=True)
        totals: dict[str, int] = {}
        for table, count in clear_metadata_task_payloads(engine):
            totals[table] = totals.get(table, 0) + count
            print(f"{table}: cleared {totals[table]} rows", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
