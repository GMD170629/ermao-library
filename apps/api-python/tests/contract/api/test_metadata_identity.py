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


@pytest.mark.parametrize("scope", ["book", "resource"])
def test_audio_identity_keeps_target_resource_directories(
    client, db_session, monkeypatch, scope
):
    from app.models import LibraryReadableResource, LibrarySourceNode
    from tests.contract.api.test_recognized_metadata_api import _path_key

    _add_book(db_session, book_id="audio-set")
    metadata = db_session.get(LibraryBookMetadata, "audio-set")
    metadata.title, metadata.author = "鬼吹灯-全八册", "天下霸唱"
    first = db_session.get(LibrarySourceNode, "audio-set-resource-node")
    first.name, first.relative_path = "01 精绝古城", "audio-set/01 精绝古城"
    first.path_key, first.physical_kind = _path_key(first.relative_path), "DIRECTORY"
    first.observed_size_bytes = None
    for index in range(2, 11):
        path = f"audio-set/{index:02} 分册目录"
        node = LibrarySourceNode(
            id=f"audio-volume-{index}", library_id="test-library",
            relative_path=path, path_key=_path_key(path), name=f"{index:02} 分册目录",
            physical_kind="DIRECTORY", observed_at=first.observed_at, observed_mtime_ns=0,
        )
        db_session.add(node)
        db_session.flush()
        db_session.add(LibraryReadableResource(
            id=f"audio-resource-{index}", library_id="test-library", book_id="audio-set",
            source_node_id=node.id, adapter_id="audio-directory", adapter_version="1",
            format="AUDIO", import_state="READY",
        ))
    for index in range(8):
        path = f"{first.relative_path}/{index:02} 精绝古城.mp3"
        node = LibrarySourceNode(
            id=f"audio-track-{index}", library_id="test-library", relative_path=path,
            path_key=_path_key(path), name=f"{index:02} 精绝古城.mp3",
            physical_kind="REGULAR_FILE", observed_at=first.observed_at, observed_size_bytes=100,
            observed_mtime_ns=0,
        )
        db_session.add(node)
        db_session.flush()
        db_session.add(LibraryResourceAsset(
            id=f"audio-asset-{index}", library_id="test-library",
            resource_id="audio-set-resource", source_node_id=node.id, role="PRIMARY",
        ))
    db_session.add(Source(id="audio-ai", name="AI", kind="metadata", provider_type="ai",
                          enabled=True, config=json.dumps({"baseUrl": "http://model.test", "model": "test"})))
    db_session.add(Source(id="audio-site", name="Bangumi", kind="metadata", provider_type="bangumi",
                          enabled=True, config=json.dumps({"baseUrl": "http://website.test"})))
    db_session.commit()
    expected = "鬼吹灯全集" if scope == "book" else "鬼吹灯之精绝古城"
    summaries = []

    def model(request, **kwargs):
        summary = json.loads(json.loads(request.data)["messages"][1]["content"])
        summaries.append(summary)
        assert len(summary["fileNames"]) == 8
        assert all("精绝古城" in name for name in summary["fileNames"])
        if scope == "book":
            assert "02 分册目录" in summary["directories"]
            assert "08 分册目录" in summary["directories"]
            assert "09 分册目录" not in summary["directories"]
        else:
            assert "02 分册目录" not in summary["directories"]
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({
            "title": expected, "author": "天下霸唱", "needsReview": False, "reason": "controlled context test",
        })}}]}).encode())

    def website(request, **kwargs):
        assert json.loads(request.data)["keyword"] == expected
        return BytesIO(json.dumps({"data": [{"id": "audio-entry", "name_cn": expected,
            "infobox": [{"key": "作者", "value": "天下霸唱"}], "summary": "网站简介"}]}).encode())

    monkeypatch.setattr(ai_client, "urlopen", model)
    monkeypatch.setattr(organize_service, "urlopen", website)
    _login(client, db_session, role="admin")
    node_id = "audio-set-root" if scope == "book" else "audio-set-resource-node"
    response = client.post(f"/api/books/audio-set/source-nodes/{node_id}/metadata/search",
        json={"providerId": "bangumi", "scope": scope,
              **({"resourceId": "audio-set-resource"} if scope == "resource" else {})})
    assert response.status_code == 200, response.text
    assert summaries
    candidate = response.json()["data"]["selectedMetadata"]
    assert candidate["title"] == expected
    if scope == "book":
        applied = client.post("/api/books/audio-set/metadata/apply", json={
            "scope": "book", "candidate": candidate, "fields": ["book.title"],
        })
        assert applied.status_code == 200, applied.text
        assert client.get("/api/books/audio-set").json()["data"]["book"]["title"] == expected


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


def _douban_detail_transport(db_session, monkeypatch, *, failure=False, direct=False, before_detail=None):
    """Only external transports replaced; registry, crawler, matching and cache are real."""
    for provider, config in (
        ("ai", {"baseUrl": "http://model.test/v1", "model": "test"}),
        ("douban", {"baseUrl": "http://douban.test"}),
    ):
        db_session.add(Source(id=f"detail-{provider}", name=provider, kind="metadata",
                              provider_type=provider, enabled=True, config=json.dumps(config)))
    db_session.commit()
    requests, prompts = [], []
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        prompts.append(prompt)
        result = {"title": "海边的卡夫卡", "author": "村上春树", "needsReview": False, "reason": "controlled match"}
        if "candidates" in prompt:
            assert prompt["candidates"][0]["description"] == ("搜索已有简介" if failure else "")
            assert prompt["candidates"][0]["author"] == "村上春樹"
            result.update(primaryCandidateId="douban:12345", relatedCandidateIds=[])
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
    def website(request, **kwargs):
        assert not db_session.in_transaction()
        requests.append(request.full_url)
        if "/subject_search?" in request.full_url:
            items = [{"id": "12345", "tpl_name": "search_subject", "url": "http://untrusted.test/subject/12345/",
                      "title": "海边的卡夫卡" if direct else "海辺のカフカ", "abstract": "村上春树" if direct else "村上春樹",
                      **({"abstract_2": "搜索已有简介"} if failure else {})},
                     {"id": "67890", "tpl_name": "search_subject", "url": "http://douban.test/subject/67890/",
                      "title": "另一作品", "abstract": "另一作者"}]
            return BytesIO(("window.__DATA__ = " + json.dumps({"items": items}) + ";").encode())
        assert request.full_url in {"http://douban.test/subject/12345/", "http://douban.test/subject/67890/"}
        if before_detail:
            before_detail()
        if failure:
            raise OSError("controlled detail connection failure")
        other = "67890" in request.full_url
        html = ('<meta property="og:title" content="' + ("另一作品" if other else "海辺のカフカ") + '">'
                '<meta property="og:url" content="' + request.full_url + '">'
                '<meta property="og:description" content="' + ("另一条目详情简介" if other else "详情才有的简介") + '">')
        return BytesIO(html.encode())
    monkeypatch.setattr(ai_client, "urlopen", model)
    monkeypatch.setattr(organize_service, "urlopen", website)
    return requests, prompts


@pytest.mark.parametrize("direct", [False, True])
def test_selected_douban_detail_http_preview_save_reopen(client, db_session, monkeypatch, direct):
    _add_book(db_session, book_id="detail-book")
    metadata = db_session.get(LibraryBookMetadata, "detail-book")
    metadata.title, metadata.author, metadata.description = "错误下载书名", "错误作者", None
    db_session.commit()
    requests, prompts = _douban_detail_transport(db_session, monkeypatch, direct=direct)
    _login(client, db_session, role="admin")
    path = "/api/books/detail-book/source-nodes/detail-book-root/metadata/search"
    response = client.post(path, json={"providerId": "douban", "query": "错误下载书名"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    raw = next(item for item in data["candidates"] if item["id"] == "douban:12345")
    assert raw["description"] is None
    assert len(prompts) == (1 if direct else 2)
    selected = data["selectedMetadata"]
    assert selected["description"] == "详情才有的简介"
    assert selected["author"] == "村上春树"
    assert len(requests) == 2 and requests[-1] == "http://douban.test/subject/12345/"
    saved = client.post("/api/books/detail-book/metadata/apply", json={"scope": "book", "candidate": selected,
                        "fields": ["book.title", "book.author", "book.description"]})
    assert saved.status_code == 200, saved.text
    reopened = client.get("/api/books/detail-book").json()["data"]["book"]
    assert (reopened["title"], reopened["author"], reopened["description"]) == ("海边的卡夫卡", "村上春树", "详情才有的简介")
    # A switched record uses its own ID and raw identity; no search/model rerun.
    other = next(item for item in data["candidates"] if item["id"] == "douban:67890")
    swapped = client.post(path, json={"providerId": "douban", "query": "人工词", "manualQuery": True, "selectedCandidate": other})
    assert swapped.status_code == 200, swapped.text
    preview = swapped.json()["data"]
    assert preview["query"] == "人工词" and preview["identity"] is None
    assert preview["selectedMetadata"]["description"] == "另一条目详情简介"
    assert preview["selectedMetadata"]["author"] == "另一作者"
    assert requests[-1] == "http://douban.test/subject/67890/"
    again = client.post(path, json={"providerId": "douban", "selectedCandidate": raw})
    assert again.json()["data"]["selectedMetadata"]["description"] == "详情才有的简介"
    assert len(requests) == 3  # Completed detail cache prevents a duplicate request.


def test_selected_douban_detail_failure_preserves_search(client, db_session, monkeypatch, caplog):
    _add_book(db_session, book_id="detail-book")
    requests, _ = _douban_detail_transport(db_session, monkeypatch, failure=True)
    _login(client, db_session, role="admin")
    response = client.post("/api/books/detail-book/source-nodes/detail-book-root/metadata/search", json={"providerId": "douban"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["selectedMetadata"]["description"] == "搜索已有简介"
    assert requests[-1] == "http://douban.test/subject/12345/"
    assert "metadata.subject_detail_failed" in caplog.text
    assert "controlled detail connection failure" in caplog.text


@pytest.mark.parametrize("website_description", [None, "网站简介原文"])
@pytest.mark.parametrize("tags_only", [False, True])
def test_generate_missing_fields_apply_and_reopen(client, db_session, monkeypatch, website_description, tags_only):
    _add_book(db_session, book_id="generated-book")
    metadata = db_session.get(LibraryBookMetadata, "generated-book")
    metadata.title, metadata.author, metadata.description = "活着", "余华", None
    db_session.add(Source(id="generate-ai", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://model.test", "model": "test", "generateEnabled": True})))
    db_session.add(Source(id="generate-site", name="Bangumi", kind="metadata", provider_type="bangumi", enabled=True,
                          config=json.dumps({"baseUrl": "http://site.test"})))
    db_session.commit()
    calls = []
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        calls.append(prompt)
        result = ({"description": None if website_description else "受控生成：关于命运与生活的小说介绍。", "tags": ["小说", "人生"],
                   "needsReview": False, "reason": "生成测试"} if "missingFields" in prompt else
                  {"title": "活着", "author": "余华", "needsReview": False, "reason": "身份确定"})
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
    def site(request, **kwargs):
        return BytesIO(json.dumps({"data": [{"id": "1", "name_cn": "活着", "infobox": [{"key": "作者", "value": "余华"}],
                                             "summary": website_description}] if website_description else []}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model)
    monkeypatch.setattr(organize_service, "urlopen", site)
    _login(client, db_session, role="admin")
    searched = client.post("/api/books/generated-book/source-nodes/generated-book-root/metadata/search", json={"providerId": "bangumi"})
    assert searched.status_code == 200, searched.text
    candidate = searched.json()["data"]["selectedMetadata"]
    expected = ["tags"] if website_description else ["description", "tags"]
    assert calls[-1]["missingFields"] == expected
    assert candidate["generatedFields"] == expected
    assert candidate["generationSource"] == "AI_GENERATED"
    assert candidate["description"] == (website_description or "受控生成：关于命运与生活的小说介绍。")
    saved = client.post("/api/books/generated-book/metadata/apply", json={"scope": "book", "candidate": candidate,
                        "fields": ["book.tags"] if tags_only else ["book.description", "book.tags"]})
    expected = ["tags"] if tags_only else expected
    assert saved.status_code == 200, saved.text
    db_session.expire_all()
    stored = db_session.get(LibraryBookMetadata, "generated-book")
    assert stored.description == (None if tags_only else candidate["description"])
    assert json.loads(stored.generated_fields) == expected
    assert not set(expected) & set(json.loads(stored.protected_fields))
    reopened = client.get("/api/books/generated-book")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["data"]["book"]["generatedFields"] == expected
    assert reopened.json()["data"]["book"]["tags"] == ["小说", "人生"]


@pytest.mark.parametrize("scenario", ["off", "ai-off", "local-full", "protected", "failure", "invalid", "review", "site-failure"])
def test_generation_optional_http_preserves_current_and_source(client, db_session, monkeypatch, caplog, scenario):
    _add_book(db_session, book_id="optional-c")
    metadata = db_session.get(LibraryBookMetadata, "optional-c")
    metadata.title, metadata.author = "活着", "余华"
    metadata.description = "本地介绍" if scenario == "local-full" else None
    if scenario == "protected":
        metadata.protected_fields = '["description", "tags"]'
    db_session.add(Source(id="c-ai", name="AI", kind="metadata", provider_type="ai", enabled=scenario != "ai-off",
                          config=json.dumps({"baseUrl": "http://model.test", "model": "test", "generateEnabled": scenario != "off"})))
    db_session.add(Source(id="c-site", name="Bangumi", kind="metadata", provider_type="bangumi", enabled=True, config='{"baseUrl":"http://site.test"}'))
    db_session.commit()
    calls = []
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        calls.append(prompt)
        if "missingFields" in prompt:
            if scenario == "failure":
                raise TimeoutError("controlled generation timeout")
            result = {"description": None, "tags": ["生成标签"], "needsReview": scenario == "review", "reason": "test"}
            if scenario == "site-failure":
                result["description"] = "来源失败后的受控生成介绍"
            if scenario == "invalid":
                result["isbn"] = "forbidden field"
        else:
            result = {"title": "活着", "author": "余华", "needsReview": False, "reason": "identity"}
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())
    def site(request, **kwargs):
        if scenario == "site-failure":
            raise OSError("controlled source unavailable")
        return BytesIO(json.dumps({"data": [{"id": "1", "name_cn": "活着", "infobox": [{"key": "作者", "value": "余华"}],
                                           "summary": "网站原文", "tags": [{"name": "网站标签"}] if scenario == "local-full" else []}]}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model);monkeypatch.setattr(organize_service, "urlopen", site)
    _login(client, db_session, role="admin")
    response = client.post("/api/books/optional-c/source-nodes/optional-c-root/metadata/search", json={"providerId": "bangumi"})
    assert response.status_code == 200, response.text
    candidate = response.json()["data"]["selectedMetadata"]
    generated_calls = [item for item in calls if "missingFields" in item]
    assert len(generated_calls) == (0 if scenario in {"off", "ai-off", "local-full", "protected"} else 1)
    if scenario == "ai-off": assert calls == []
    if scenario in {"invalid", "failure"}:
        assert candidate["description"] == "网站原文" and candidate["generatedFields"] == []
        assert "metadata.generate_failed" in caplog.text
    if scenario == "review": assert candidate["generationNeedsReview"] is True
    if scenario == "site-failure":
        assert candidate["sourceIssues"] == ["bangumi:search_failed"]
        assert "controlled source unavailable" in caplog.text
        applied = client.post("/api/books/optional-c/metadata/apply", json={"scope": "book", "candidate": candidate, "fields": ["book.description", "book.tags"]})
        assert applied.status_code == 200, applied.text
        reopened = client.get("/api/books/optional-c").json()["data"]["book"]
        assert reopened["description"] == "来源失败后的受控生成介绍" and reopened["generationSource"] == "AI_GENERATED"


def test_manual_edit_and_source_replacement_update_generated_flags(client, db_session, monkeypatch):
    test_generate_missing_fields_apply_and_reopen(client, db_session, monkeypatch, None, False)
    edited = client.patch("/api/books/generated-book", json={"description": "用户改写简介"})
    assert edited.status_code == 200, edited.text
    result = client.get("/api/books/generated-book").json()["data"]["book"]
    assert result["description"] == "用户改写简介" and result["generatedFields"] == ["tags"]
    db_session.expire_all()
    assert "description" in json.loads(db_session.get(LibraryBookMetadata, "generated-book").protected_fields)
    # A subsequent explicit site selection replaces only the still-generated tags.
    response = client.post("/api/books/generated-book/metadata/apply", json={"scope": "book", "candidate": {"id": "bangumi:1", "source": "bangumi", "tags": ["网站标签"]}, "fields": ["book.tags"]})
    assert response.status_code == 200, response.text
    result = client.get("/api/books/generated-book").json()["data"]["book"]
    assert result["generatedFields"] == [] and result["generationSource"] is None
    assert result["description"] == "用户改写简介" and result["tags"] == ["网站标签"]


def test_generation_manual_switch_and_stale_apply(client, db_session, monkeypatch):
    test_generate_missing_fields_apply_and_reopen(client, db_session, monkeypatch, None, True)
    # The book description is still empty; a different selected identity gets its own completion.
    calls = []
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"]);calls.append(prompt)
        assert prompt["title"] == "另一作品" and prompt["author"] == "另一作者"
        assert prompt["missingFields"] == ["description"]
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"description": "另一作品的生成介绍", "tags": [], "needsReview": False, "reason": "new selection"})}}]}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model)
    response = client.post("/api/books/generated-book/source-nodes/generated-book-root/metadata/search", json={"providerId": "bangumi", "query": "本次人工词", "manualQuery": True,
        "selectedCandidate": {"id": "bangumi:2", "source": "bangumi", "title": "另一作品", "author": "另一作者"}})
    assert response.status_code == 200, response.text
    data = response.json()["data"];candidate = data["selectedMetadata"]
    assert data["query"] == "本次人工词" and candidate["description"] == "另一作品的生成介绍" and len(calls) == 1
    edited = client.patch("/api/books/generated-book", json={"description": "模型等待期间的人工改写"})
    assert edited.status_code == 200, edited.text
    response = client.post("/api/books/generated-book/metadata/apply", json={"scope": "book", "candidate": candidate, "fields": ["book.description"]})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["skippedFields"] == ["book.description"]
    assert client.get("/api/books/generated-book").json()["data"]["book"]["description"] == "模型等待期间的人工改写"


def test_generated_resource_description_preserves_book_scope(client, db_session, monkeypatch):
    test_generate_missing_fields_apply_and_reopen(client, db_session, monkeypatch, None, True)
    from app.models import LibraryReadableResourceMetadata
    row = db_session.get(LibraryReadableResourceMetadata, "generated-book-resource")
    row.description = None;db_session.commit()
    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        assert prompt["missingFields"] == ["description"]
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"description": "资源生成介绍", "tags": [], "needsReview": False, "reason": "resource"})}}]}).encode())
    monkeypatch.setattr(ai_client, "urlopen", model)
    response = client.post("/api/books/generated-book/source-nodes/generated-book-resource-node/metadata/search", json={"providerId": "bangumi", "selectedCandidate": {"id": "bangumi:3", "source": "bangumi", "title": "活着", "author": "余华"}})
    assert response.status_code == 200, response.text
    candidate = response.json()["data"]["selectedMetadata"]
    applied = client.post("/api/books/generated-book/metadata/apply", json={"scope": "resource", "resourceId": "generated-book-resource", "candidate": candidate, "fields": ["resource.description"]})
    assert applied.status_code == 200, applied.text
    detail = client.get("/api/books/generated-book").json()["data"]["book"]
    assert detail["description"] is None
    assert detail["resources"][0]["description"] == "资源生成介绍"
    assert detail["resources"][0]["generatedFields"] == ["description"]
    assert detail["resources"][0]["generationSource"] == "AI_GENERATED"


@pytest.mark.parametrize("same_node,book_description,resource_description", [
    (True, None, None), (True, "书级简介保留", None),
    (True, None, "资源已有简介"), (False, "书级简介保留", None),
])
@pytest.mark.parametrize("switch_candidate", [False, True])
def test_explicit_generation_target_search_apply_reopen(
    client, db_session, monkeypatch, same_node, book_description, resource_description, switch_candidate,
):
    test_generate_missing_fields_apply_and_reopen(client, db_session, monkeypatch, None, True)
    from app.models import LibraryReadableResource, LibraryReadableResourceMetadata

    book = db_session.get(LibraryBookMetadata, "generated-book")
    resource = db_session.get(LibraryReadableResource, "generated-book-resource")
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    book.description = book_description
    metadata.description = resource_description
    if same_node:
        resource.source_node_id = "generated-book-root"
    db_session.commit()
    db_session.expire_all()
    node_id = resource.source_node_id
    calls = []

    def model(request, **kwargs):
        prompt = json.loads(json.loads(request.data)["messages"][1]["content"])
        if "missingFields" in prompt:
            calls.append(prompt)
            assert prompt["missingFields"] == ["description"]
            result = {"description": "明确资源生成介绍", "tags": [], "needsReview": False, "reason": "resource"}
        else:
            result = {"title": "活着", "author": "余华", "needsReview": False, "reason": "identity"}
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())

    monkeypatch.setattr(ai_client, "urlopen", model)
    payload = {"providerId": "bangumi", "scope": "resource", "resourceId": resource.id}
    if switch_candidate:
        payload["selectedCandidate"] = {"id": "bangumi:3", "source": "bangumi", "title": "活着", "author": "余华"}
    searched = client.post(f"/api/books/generated-book/source-nodes/{node_id}/metadata/search", json=payload)
    assert searched.status_code == 200, searched.text
    candidate = searched.json()["data"]["selectedMetadata"]
    assert len(calls) == (0 if resource_description else 1)
    if not resource_description:
        db_session.expire_all()
        current_book = db_session.get(LibraryBookMetadata, "generated-book")
        current_resource = db_session.get(LibraryReadableResourceMetadata, resource.id)
        assert candidate["generationRevision"] == current_book.updated_at.isoformat() + "|" + current_resource.updated_at.isoformat()
        applied = client.post("/api/books/generated-book/metadata/apply", json={
            "scope": "resource", "resourceId": resource.id, "candidate": candidate, "fields": ["resource.description"],
        })
        assert applied.status_code == 200, applied.text
        assert applied.json()["data"]["appliedFields"] == ["resource.description"]
    detail = client.get("/api/books/generated-book").json()["data"]["book"]
    assert detail["description"] == book_description
    saved_resource = next(item for item in detail["resources"] if item["id"] == resource.id)
    assert saved_resource["description"] == (resource_description or "明确资源生成介绍")
    assert saved_resource["generatedFields"] == ([] if resource_description else ["description"])


@pytest.mark.parametrize("resource_id", [None, "missing", "other-book-resource", "generated-book-resource"])
def test_generation_target_must_belong_to_book_and_request_node(client, db_session, monkeypatch, resource_id):
    _add_book(db_session, book_id="generated-book")
    _add_book(db_session, book_id="other-book")
    _login(client, db_session, role="admin")
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid target must not call the model")
    monkeypatch.setattr(ai_client, "urlopen", unexpected)
    response = client.post("/api/books/generated-book/source-nodes/generated-book-root/metadata/search", json={
        "providerId": "bangumi", "scope": "resource", "resourceId": resource_id,
    })
    assert response.status_code == 404
