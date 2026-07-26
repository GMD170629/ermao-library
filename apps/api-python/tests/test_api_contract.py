from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from appv2.composition.api import create_app
from appv2.platform.config import Settings


def test_openapi_is_v2_only_and_reports_release_version(tmp_path: Path) -> None:
    settings = Settings(
        app_version="0.4.0",
        database_url=SecretStr("postgresql+psycopg://unused:unused@127.0.0.1:65432/unused"),
        session_secret=SecretStr("test-session-secret"),
        storage_root=tmp_path,
        monitor_root=tmp_path / "monitor",
    )
    app = create_app(settings)
    schema = app.openapi()
    assert schema["info"]["version"] == "0.4.0"
    assert schema["paths"]
    assert all(path.startswith("/api/v2/") for path in schema["paths"])
    assert "/api/v2/operations/health" in schema["paths"]
    assert "/api/v2/reading/editions/{edition_id}/resource" in schema["paths"]
    work_query = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/api/v2/catalog/works"]["get"]["parameters"]
    }
    assert work_query["sort"]["schema"]["enum"] == [
        "recent_read",
        "recent_import",
        "title",
        "author",
        "publisher",
        "series",
    ]
    assert work_query["sortDirection"]["schema"]["enum"] == ["asc", "desc"]
    reporting_query = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/api/v2/reporting/library"]["get"]["parameters"]
    }
    assert reporting_query["readingStatus"]["schema"]["anyOf"][0]["type"] == "string"
    assert reporting_query["filters"]["schema"]["anyOf"][0]["type"] == "string"
    assert "/api/v2/reporting/library/filter-schema" in schema["paths"]
    app.state.container.close()


def test_missing_legacy_route_uses_problem_details(tmp_path: Path) -> None:
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://unused:unused@127.0.0.1:65432/unused"),
        session_secret=SecretStr("test-session-secret"),
        storage_root=tmp_path,
        monitor_root=None,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/api/health")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["traceId"]
