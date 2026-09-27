"""Controlled model transport tests; these do not establish real model accuracy."""

import json
from io import BytesIO

import pytest

from app.contracts.local_metadata_snapshot import (
    LocalMetadataObservation,
    encode_observations,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.models import LibraryBookMetadata, LibraryResourceAsset
from app.models.import_pipeline import Source
from app.modules.metadata.infrastructure import ai_client
from app.services import organize_service
from tests.contract.api.test_recognized_metadata_api import _add_book, _login


@pytest.mark.parametrize(
    "provider,title,author,new_title,new_author",
    [
        ("bangumi", "三体 刘慈欣 完整版", "刘慈欣", "三体", "刘慈欣"),
        ("bangumi", "活着", None, "活着", None),
        ("bangumi", "活着", "鲁迅", "活着", "余华"),
        ("bangumi", "活着", "余华", "活着", "余华"),
        ("ai", "活着 完整版", "鲁迅", "活着", "余华"),
    ],
)
def test_dirty_database_search_apply_reopen(
    client, db_session, monkeypatch, provider, title, author, new_title, new_author
):
    _add_book(db_session, book_id="dirty-identity")
    metadata = db_session.get(LibraryBookMetadata, "dirty-identity")
    metadata.title, metadata.author = title, author
    metadata.normalized_title, metadata.normalized_author = title, author or ""
    expected_author = new_author or "余华"
    db_session.add(
        LibraryResourceAsset(
            id="identity-asset",
            library_id="test-library",
            resource_id="dirty-identity-resource",
            source_node_id="dirty-identity-resource-node",
            role="PRIMARY",
            local_metadata_candidates=encode_observations(
                (
                    LocalMetadataObservation(
                        "EMBEDDED",
                        PublicationMetadata(
                            title=new_title, authors=(expected_author,)
                        ),
                    ),
                )
            ),
        )
    )
    db_session.add(
        Source(
            id="identity-model",
            name="AI",
            kind="metadata",
            provider_type="ai",
            enabled=True,
            config=json.dumps(
                {"baseUrl": "http://model.test/v1", "model": "test-model"}
            ),
        )
    )
    db_session.add(
        Source(
            id="identity-site",
            name="Bangumi",
            kind="metadata",
            provider_type="bangumi",
            enabled=True,
            config=json.dumps({"baseUrl": "http://website.test"}),
        )
    )
    db_session.commit()
    calls = []

    def model(request, **kwargs):
        assert not db_session.in_transaction()
        summary = json.loads(json.loads(request.data)["messages"][1]["content"])
        calls.append(summary)
        assert summary["title"] == title and summary["author"] == (author or "")
        assert summary["embeddedMetadata"] == [
            {"title": new_title, "author": expected_author}
        ]
        assert request.get_header("Authorization") is None
        return BytesIO(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": new_title,
                                        "author": new_author,
                                        "needsReview": False,
                                        "reason": "controlled test",
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()
        )

    queries = []

    def website(request, **kwargs):
        assert not db_session.in_transaction()
        assert request.full_url == "http://website.test/v0/search/subjects"
        queries.append(json.loads(request.data)["keyword"])
        return BytesIO(
            json.dumps(
                {
                    "data": [
                        {
                            "id": "site-entry",
                            "name_cn": new_title,
                            "infobox": [{"key": "作者", "value": expected_author}],
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(ai_client, "urlopen", model)
    monkeypatch.setattr(organize_service, "urlopen", website)
    _login(client, db_session, role="admin")
    response = client.post(
        "/api/books/dirty-identity/source-nodes/dirty-identity-root/metadata/search",
        json={"providerId": provider, "query": title},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["identity"]["title"] == new_title
    assert data["selectedId"] == (
        "site-entry" if provider == "bangumi" else "ai-identity"
    )
    assert queries == ([new_title] if provider == "bangumi" else [])
    candidate = next(
        item for item in data["candidates"] if item["id"] == data["selectedId"]
    )
    response = client.post(
        "/api/books/dirty-identity/metadata/apply",
        json={
            "scope": "book",
            "candidate": candidate,
            "fields": ["book.title", "book.author"],
        },
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    stored = db_session.get(LibraryBookMetadata, "dirty-identity")
    assert (stored.title, stored.author) == (new_title, expected_author)
    detail = client.get("/api/books/dirty-identity")
    assert detail.status_code == 200, detail.text
    reopened = detail.json()["data"]["book"]
    assert (reopened["title"], reopened["author"]) == (new_title, expected_author)
    assert len(calls) == 1


def test_actual_model_test_http_contract(client, db_session, monkeypatch):
    db_session.add(
        Source(
            id="identity-model",
            name="AI",
            kind="metadata",
            provider_type="ai",
            enabled=True,
            config=json.dumps(
                {"baseUrl": "http://model.test/v1", "model": "test-model"}
            ),
        )
    )
    db_session.commit()
    calls = []

    def model(request, **kwargs):
        calls.append(request.full_url)
        return BytesIO(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": None,
                                        "author": None,
                                        "needsReview": True,
                                        "reason": "No clues",
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(ai_client, "urlopen", model)
    _login(client, db_session, role="admin")
    result = client.post("/api/metadata/providers/ai/test")
    assert result.status_code == 200, result.text
    assert result.json()["data"]["result"]["ok"] is True
    assert calls == ["http://model.test/v1/chat/completions"]
