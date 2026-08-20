from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as _models  # noqa: F401
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.bootstrap import apply_schema
from app.db.session import get_db
from app.main import create_app
from app.models.library import Library

_TEST_ORM_TABLES = list(Base.metadata.sorted_tables)


def recreate_application_schema(engine) -> None:
    """Drop ORM tables and alembic_version so apply_schema can rebuild HEAD."""

    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    apply_schema(engine)
    seed_session = sessionmaker(bind=engine)()
    try:
        seed_session.add(
            Library(
                id="test-library",
                name="Test Library",
                root_path="/test-library",
                organization_mode="FLAT",
            )
        )
        seed_session.commit()
    finally:
        seed_session.close()


class TestSettings(Settings):
    """Test-only filesystem root used by upload and import fixtures."""

    @property
    def resolved_library_root(self) -> Path:
        return self.resolved_storage_root.parent / "library"


@pytest.fixture()
def test_settings(tmp_path) -> Settings:
    return TestSettings(
        session_secret="test-secret",
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )


@pytest.fixture()
def db_session(test_settings: Settings) -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    Base.metadata.create_all(bind=engine, tables=_TEST_ORM_TABLES)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    db = TestingSessionLocal()
    db.add(
        Library(
            id="test-library",
            name="Test Library",
            root_path="/test-library",
            organization_mode="FLAT",
        )
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine, tables=_TEST_ORM_TABLES)
        engine.dispose()


@pytest.fixture()
def client(
    test_settings: Settings, db_session: Session
) -> Generator[TestClient, None, None]:
    app = create_app(test_settings, session_factory=lambda: db_session)

    def override_settings() -> Settings:
        return test_settings

    def override_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
