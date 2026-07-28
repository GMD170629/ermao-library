from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL


def create_sqlite_engine(database_path: Path, *, timeout_seconds: float = 10) -> Engine:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={"timeout": timeout_seconds},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()

    return engine
