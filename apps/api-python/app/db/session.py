from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.sqlite import create_sqlite_engine

settings = get_settings()

engine = create_sqlite_engine(settings.database_path)
heartbeat_engine = create_sqlite_engine(settings.database_path, timeout_seconds=1)
facet_maintenance_engine = create_sqlite_engine(
    settings.database_path,
    timeout_seconds=0.25,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
HeartbeatSessionLocal = sessionmaker(
    bind=heartbeat_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
FacetMaintenanceSessionLocal = sessionmaker(
    bind=facet_maintenance_engine,
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
