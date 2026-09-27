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
    client, db_session, monkeypatch, provider, title, author, new_title, new_author,
    conflicting_author=False, manual_second_search=False,
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
                                        "needsReview": new_author is None,
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
                            "name_cn": "乙书" if queries[-1] == "乙书" else new_title,
                            "infobox": [{"key": "作者", "value": "作者乙" if conflicting_author or queries[-1] == "乙书" else expected_author}],
                            "summary": "网站原始简介",
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
    assert data["identity"]["needsReview"] is (new_author is None)
    assert data["selectedId"] == (
        "site-entry" if provider == "bangumi" and not conflicting_author else "ai-identity"
    )
    assert queries == ([new_title] if provider == "bangumi" else [])
    if conflicting_author:
        source = next(item for item in data["candidates"] if item["id"] == "site-entry")
        assert source["author"] == "作者乙"
        assert source["description"] == "网站原始简介"
    if manual_second_search:
        response = client.post(
            "/api/books/dirty-identity/source-nodes/dirty-identity-root/metadata/search",
            json={"providerId": provider, "query": "乙书", "manualQuery": True},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["identity"] is None
        assert data["query"] == "乙书"
        assert data["selectedId"] == "site-entry"
        assert queries == [new_title, "乙书"]
        new_title, expected_author = "乙书", "作者乙"
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
    if conflicting_author:
        assert candidate["description"] is None
        assert stored.description is None
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


def test_manual_query_uses_new_title_without_previous_identity(client, db_session, monkeypatch):
    test_dirty_database_search_apply_reopen(
        client, db_session, monkeypatch, "bangumi", "甲书 完整版", "旧作者",
        "甲书", "作者甲", manual_second_search=True,
    )


def test_conflicting_source_author_stays_original_and_identity_can_save(client, db_session, monkeypatch):
    test_dirty_database_search_apply_reopen(
        client, db_session, monkeypatch, "bangumi", "示例书 完整版", "错误作者",
        "示例书", "作者甲", conflicting_author=True,
    )
