from __future__ import annotations

import base64
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.opds.application.dto import (
    BasicCredentialsDto,
    OpdsActorDto,
    OpdsCatalogQueryDto,
    OpdsFeedDto,
    OpdsProgressionDocumentDto,
    OpdsProgressionUpdateResultDto,
)
from app.modules.opds.application.settings import OpdsSettingsSnapshot
from app.modules.opds.domain.errors import OpdsProgressionDateConflict
from app.modules.opds.presentation.http import OpdsHttpDependencies, create_opds_router

NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


class FakeAuthenticator:
    def authenticate(
        self, credentials: BasicCredentialsDto, client_address: str
    ) -> OpdsActorDto | None:
        assert client_address
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


class FakeProgression:
    conflict = False
    stored: OpdsProgressionDocumentDto | None = None

    def get_progression(
        self, actor_id: str, volume_id: str
    ) -> OpdsProgressionDocumentDto | None:
        assert actor_id == "user-1"
        return self.stored

    def update_progression(
        self,
        actor_id: str,
        volume_id: str,
        document: OpdsProgressionDocumentDto,
    ) -> OpdsProgressionUpdateResultDto:
        if self.conflict:
            raise OpdsProgressionDateConflict
        created = self.stored is None
        self.stored = document
        return OpdsProgressionUpdateResultDto(created=created, document=document)


def _client() -> tuple[TestClient, FakeCatalog, FakeProgression]:
    catalog = FakeCatalog()
    progression = FakeProgression()
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
                progression=progression,
            )
        )
    )
    return TestClient(app), catalog, progression


def _authorization() -> dict[str, str]:
    token = base64.b64encode(b"reader@example.com:secret").decode()
    return {"Authorization": f"Basic {token}"}


def _invalid_authorization() -> dict[str, str]:
    token = base64.b64encode(b"reader@example.com:wrong-password").decode()
    return {"Authorization": f"Basic {token}"}


def test_catalog_requires_basic_and_partitions_cache_by_authorization() -> None:
    client, catalog, _ = _client()

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
    assert (
        invalid_credentials.headers["www-authenticate"]
        == 'Basic realm="Shuku OPDS"'
    )
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


def test_progression_create_read_and_date_conflict_contracts() -> None:
    client, _, progression = _client()
    payload = {
        "modified": "2026-08-03T08:00:00Z",
        "device": {"id": "urn:uuid:device-1", "name": "Panels"},
        "progression": 0.5,
        "references": ["pages/4"],
    }

    empty = client.get(
        "/opds/v1.2/volumes/volume-1/progression", headers=_authorization()
    )
    created = client.put(
        "/opds/v1.2/volumes/volume-1/progression",
        headers=_authorization(),
        json=payload,
    )
    fetched = client.get(
        "/opds/v1.2/volumes/volume-1/progression", headers=_authorization()
    )
    progression.conflict = True
    conflict = client.put(
        "/opds/v1.2/volumes/volume-1/progression",
        headers=_authorization(),
        json=payload,
    )

    assert empty.status_code == 200 and empty.content == b""
    assert created.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["device"]["name"] == "Panels"
    assert conflict.status_code == 409
    assert conflict.json()["type"].endswith("#progression-date")


def test_progression_validation_uses_opds_problem_details_instead_of_422() -> None:
    client, _, _ = _client()

    response = client.put(
        "/opds/v1.2/volumes/volume-1/progression",
        headers=_authorization(),
        json={
            "modified": "not-a-date",
            "device": {"id": "not-a-uri", "name": "Panels"},
            "progression": 2,
        },
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("#progression-invalid-payload")
