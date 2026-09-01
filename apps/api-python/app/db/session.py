from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.sqlite import SHORT_WRITE_OPERATION_LIMIT_SECONDS, create_sqlite_engine

settings = get_settings()

engine = create_sqlite_engine(settings.database_path)
background_engine = create_sqlite_engine(
    settings.database_path,
    timeout_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
    transaction_time_budget_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
)
heartbeat_engine = create_sqlite_engine(
    settings.database_path,
    timeout_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
    transaction_time_budget_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
)
metadata_maintenance_engine = create_sqlite_engine(
    settings.database_path,
    timeout_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
    transaction_time_budget_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
BackgroundSessionLocal = sessionmaker(
    bind=background_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
HeartbeatSessionLocal = sessionmaker(
    bind=heartbeat_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
MetadataMaintenanceSessionLocal = sessionmaker(
    bind=metadata_maintenance_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_short_write_db() -> Generator[Session, None, None]:
    """Yield a low-priority writer that defers quickly under SQLite contention."""

    db = BackgroundSessionLocal()
    try:
        yield db
    finally:
        db.close()
