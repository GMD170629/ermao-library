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
        matching = "candidates" in summary
        assert summary["title"] == (new_title if matching else title)
        assert summary["author"] == ((new_author or "") if matching else (author or ""))
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
                                        "needsReview": new_author is None and not matching,
                                        "reason": "controlled test",
                                        **({"primaryCandidateId": None if conflicting_author else "bangumi:site-entry",
                                            "relatedCandidateIds": []} if matching else {}),
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
    assert data["identity"]["needsReview"] is False
    assert data["selectedId"] == (
        "bangumi:site-entry" if not conflicting_author else "ai-identity"
    )
    assert queries == [new_title]
    if conflicting_author:
        source = next(item for item in data["candidates"] if item["id"] == "bangumi:site-entry")
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
        assert data["selectedId"] == "bangumi:site-entry"
        assert queries == [new_title, "乙书"]
        new_title, expected_author = "乙书", "作者乙"
    candidate = data["selectedMetadata"]
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
    assert len(calls) == (2 if new_author is None or conflicting_author else 1)


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


@pytest.mark.parametrize("scenario", ["name-variant", "different-author", "uncertain", "wrong-A", "related", "source-failure", "manual", "no-match", "invalid-id"])
def test_semantic_match_selects_real_record_and_persists(client, db_session, monkeypatch, scenario, caplog):
    from app.modules.library.infrastructure import (
        source_node_metadata_recognition as adapter,
    )
    from app.services.organize_service import choose_metadata_candidate

    _add_book(db_session, book_id="semantic")
    metadata = db_session.get(LibraryBookMetadata, "semantic")
    metadata.title, metadata.author = "卡夫卡 下载版", "错误作者"
    db_session.add(Source(id="semantic-ai", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://model.test/v1", "model": "test"})))
    db_session.add(Source(id="semantic-site", name="Site", kind="metadata", provider_type="bangumi", enabled=True, config="{}"))
    db_session.add(Source(id="semantic-related", name="Related", kind="metadata", provider_type="douban", enabled=True, config="{}"))
    db_session.commit()
    initial_title = "挪威的森林" if scenario == "wrong-A" else "海边的卡夫卡"
    initial_author = None if scenario == "uncertain" else "村上春树"
    primary = {"id": "same-id", "title": "海辺のカフカ", "author": "村上春樹",
               "description": None if scenario == "related" else "主来源实际简介", "tags": [],
               "publisher": "主出版社", "isbn": "9780000000001"}
    if scenario == "different-author":
        primary.update(title=initial_title, author="另一作者")
    secondary = {"id": "same-id", "title": "Kafka on the Shore", "author": "Haruki Murakami",
                 "description": "关联来源实际简介", "tags": ["小说"], "publisher": "其他出版社", "isbn": "9780000000002"}
    assert choose_metadata_candidate([primary], initial_title, initial_author or "")[0] is None
    queries = []
    def search(db, context, provider, query):
        queries.append((provider, query))
        if scenario == "source-failure" and provider == "bangumi":
            raise OSError("controlled source unavailable")
        records = ([] if scenario == "no-match" else [dict(primary)]) if provider == "bangumi" else (
            [dict(secondary)] if scenario in {"related", "source-failure"} else [])
        return {"enabled": True, "candidates": records}
    monkeypatch.setattr(adapter, "search_with_metadata_provider", search)
    prompts = []
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        prompts.append(prompt)
        if "candidates" not in prompt:
            result = {"title": initial_title, "author": initial_author, "needsReview": scenario == "uncertain", "reason": "A controlled"}
        else:
            assert prompt["candidates"][0]["title"] == (secondary["title"] if scenario == "source-failure" else primary["title"])
            assert prompt["localAuthor"] == "错误作者"
            if scenario == "manual":
                assert prompt["manualQuery"] and prompt["title"] == "人工关键词"
            result = {"title": "海边的卡夫卡", "author": "村上春树", "needsReview": scenario == "different-author",
                      "reason": "B controlled semantic match",
                      "primaryCandidateId": "douban:invented" if scenario == "invalid-id" else None if scenario == "different-author" else ("douban:same-id" if scenario == "source-failure" else "bangumi:same-id"),
                      "relatedCandidateIds": ["douban:same-id"] if scenario == "related" else []}
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model)
    _login(client, db_session, role="admin")
    response = client.post("/api/books/semantic/source-nodes/semantic-root/metadata/search",
                           json={"providerId": "bangumi", "query": "人工关键词" if scenario == "manual" else metadata.title,
                                 "manualQuery": scenario == "manual"})
    if scenario == "invalid-id":
        assert response.status_code == 502
        assert "AI_MATCH_UNKNOWN_CANDIDATE" in caplog.text
        assert "metadata_search.provider_failed" in caplog.text
        assert db_session.get(LibraryBookMetadata, "semantic").author == "错误作者"
        return
    if scenario == "source-failure":
        assert "controlled source unavailable" in caplog.text
        assert "metadata.source_search_failed" in caplog.text
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert all(query == ("人工关键词" if scenario == "manual" else initial_title) for _, query in queries)
    assert result["query"] == ("人工关键词" if scenario == "manual" else initial_title)
    selected = result["selectedMetadata"]
    if scenario in {"no-match", "different-author"}:
        assert selected["source"] == "ai" and selected["description"] is None
    else:
        assert selected["source"] == ("douban" if scenario == "source-failure" else "bangumi")
        assert selected["description"] == ("关联来源实际简介" if scenario in {"related", "source-failure"} else "主来源实际简介")
        assert not result["identity"]["needsReview"]
        if scenario == "related":
            assert selected["publisher"] == "主出版社" and selected["isbn"] == "9780000000001"
        raw = next(item for item in result["candidates"] if item["id"] == result["selectedId"])
        assert raw["title"] != selected["title"]
        assert raw["author"] != selected["author"]
    fields = ["book.title", "book.author"]
    if selected["description"]:
        fields.append("book.description")
    saved = client.post("/api/books/semantic/metadata/apply", json={"scope": "book", "candidate": selected, "fields": fields})
    assert saved.status_code == 200, saved.text
    detail = client.get("/api/books/semantic").json()["data"]["book"]
    assert detail["title"] == selected["title"] and detail["author"] == selected["author"]
    if selected["description"]:
        assert detail["description"] == selected["description"]
    assert len(prompts) == (1 if scenario in {"manual", "no-match"} else 2)
