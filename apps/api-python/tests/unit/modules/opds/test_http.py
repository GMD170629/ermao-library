from __future__ import annotations

import base64
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.opds.application.dto import (
    OpdsActorDto,
    OpdsAuthenticationRequestDto,
    OpdsCatalogQueryDto,
    OpdsFeedDto,
)
from app.modules.opds.application.settings import OpdsSettingsSnapshot
from app.modules.opds.presentation.http import OpdsHttpDependencies, create_opds_router

NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


class FakeAuthenticator:
    def authenticate(
        self, request: OpdsAuthenticationRequestDto
    ) -> OpdsActorDto | None:
        credentials = request.credentials
        assert request.client_address
        assert request.method in {"GET", "PUT"}
        assert request.path.startswith("/opds/")
        if (
            credentials.username == "reader@example.com"
            and credentials.password == "secret"
        ):
            return OpdsActorDto(user_id="user-1")
        return None


class FakeCatalog:
    query: OpdsCatalogQueryDto | None = None

    def load_feed(self, query: OpdsCatalogQueryDto) -> OpdsFeedDto:
        self.query = query
        return OpdsFeedDto(
            id="urn:catalog",
            title="Catalog",
            updated_at=NOW,
            kind="acquisition",
            self_url="https://books.test/opds/v1.2/catalog",
            start_url="https://books.test/opds/v1.2/catalog",
            entries=(),
            total_results=0,
            start_index=0,
            items_per_page=query.page_size,
        )


def _client() -> tuple[TestClient, FakeCatalog]:
    catalog = FakeCatalog()
    app = FastAPI()
    app.include_router(
        create_opds_router(
            OpdsHttpDependencies(
                settings=lambda: OpdsSettingsSnapshot(
                    enabled=True,
                    configured=True,
                    public_base_url="https://books.test",
                    catalog_url="https://books.test/opds/v1.2/catalog",
                ),
                authenticator=FakeAuthenticator(),
                catalog=catalog,
            )
        )
    )
    return TestClient(app), catalog


def _authorization() -> dict[str, str]:
    token = base64.b64encode(b"reader@example.com:secret").decode()
    return {"Authorization": f"Basic {token}"}


def _invalid_authorization() -> dict[str, str]:
    token = base64.b64encode(b"reader@example.com:wrong-password").decode()
    return {"Authorization": f"Basic {token}"}


def test_catalog_requires_basic_and_partitions_cache_by_authorization() -> None:
    client, catalog = _client()

    unauthorized = client.get("/opds/v1.2/catalog")
    invalid_credentials = client.get(
        "/opds/v1.2/catalog", headers=_invalid_authorization()
    )
    response = client.get("/opds/v1.2/catalog?pageSize=25", headers=_authorization())

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == 'Basic realm="Shuku OPDS"'
    assert unauthorized.headers["content-type"].startswith(
        "application/opds-authentication+json"
    )
    assert invalid_credentials.status_code == 401
    assert invalid_credentials.headers["www-authenticate"] == 'Basic realm="Shuku OPDS"'
    assert response.status_code == 200
    assert response.headers["vary"] == "Authorization"
    assert response.headers["content-type"].startswith("application/atom+xml")
    assert catalog.query == OpdsCatalogQueryDto(
        actor_id="user-1",
        public_base_url="https://books.test",
        search=None,
        page=1,
        page_size=25,
    )


def test_progression_routes_require_authentication_and_are_retired() -> None:
    client, _ = _client()
    path = "/opds/v1.2/resources/resource-1/progression"

    unauthorized_get = client.get(path)
    unauthorized_put = client.put(path, content=b"not-json")
    invalid_get = client.get(path, headers=_invalid_authorization())
    invalid_put = client.put(
        path, headers=_invalid_authorization(), content=b"not-json"
    )
    retired_get = client.get(path, headers=_authorization())
    retired_put = client.put(path, headers=_authorization(), content=b"not-json")

    for response in (unauthorized_get, unauthorized_put, invalid_get, invalid_put):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == 'Basic realm="Shuku OPDS"'

    for response in (retired_get, retired_put):
        assert response.status_code == 410
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["vary"] == "Authorization"
        assert response.json() == {
            "type": "https://shuku.invalid/errors/opds-progression-retired",
            "title": "OPDS progression is no longer supported.",
        }
