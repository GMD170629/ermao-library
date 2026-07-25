from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from appv2.composition.api import create_app
from appv2.platform.config import Settings, get_settings


@pytest.mark.postgres
def test_setup_login_catalog_and_health_on_postgresql_18(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = os.getenv("APPV2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("APPV2_TEST_DATABASE_URL is not configured")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        major = int(str(connection.execute(text("SHOW server_version")).scalar_one()).split(".")[0])
    assert major == 18

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("SESSION_SECRET", "integration-test-session-secret")
    get_settings.cache_clear()
    backend_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(backend_root / "alembic-v2.ini"), "head")

    settings = Settings(
        database_url=SecretStr(database_url),
        session_secret=SecretStr("integration-test-session-secret"),
        storage_root=tmp_path,
        monitor_root=tmp_path / "monitor",
    )
    email = f"integration-{uuid.uuid4().hex}@example.com"
    with TestClient(create_app(settings)) as client:
        setup = client.post(
            "/api/v2/auth/setup",
            json={
                "email": email,
                "displayName": "Integration Admin",
                "password": "correct horse battery staple",
                "locale": "en-US",
            },
        )
        if setup.status_code == 409:
            pytest.skip("the configured PostgreSQL database is not an isolated test database")
        assert setup.status_code == 201, setup.text
        created = client.post(
            "/api/v2/catalog/works",
            json={
                "title": "Architecture Test Book",
                "author": "Codex",
                "mediaType": "book",
                "metadata": {"source": "integration"},
            },
        )
        assert created.status_code == 201, created.text
        works = client.get("/api/v2/catalog/works?pageSize=24")
        assert works.status_code == 200
        assert works.json()["total"] >= 1
        health = client.get("/api/v2/operations/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"
