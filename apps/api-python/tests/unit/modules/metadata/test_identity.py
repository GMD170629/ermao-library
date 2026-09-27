import json
from io import BytesIO

import pytest
from pydantic import ValidationError

from app.models.import_pipeline import Source
from app.modules.metadata.infrastructure import ai_client
from app.services.metadata_provider_registry import (
    BuiltinMetadataProvider,
    metadata_provider_registry,
    recognize_metadata_identity,
)


@pytest.mark.parametrize(
    "enabled,config",
    [(False, {"baseUrl": "http://local/v1", "model": "local"}), (True, {})],
)
def test_disabled_or_unconfigured_never_calls_model(
    db_session, monkeypatch, enabled, config
):
    db_session.add(
        Source(
            id="ai",
            name="AI",
            kind="metadata",
            provider_type="ai",
            enabled=enabled,
            config=json.dumps(config),
        )
    )
    db_session.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("Model must not be called")

    monkeypatch.setattr(ai_client, "urlopen", forbidden)
    result = recognize_metadata_identity(
        db_session, book_id="absent", title="dirty", author=None
    )
    if enabled:
        assert result.title is None and result.needs_review
        assert "未配置" in result.reason
    else:
        assert result is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": 3, "author": None, "needsReview": False, "reason": "bad"},
        {"title": None, "author": None, "needsReview": "false", "reason": "bad"},
        {
            "title": "x",
            "author": None,
            "needsReview": False,
            "reason": "bad",
            "score": 1,
        },
    ],
)
def test_identity_rejects_invalid_model_output(monkeypatch, payload):
    monkeypatch.setattr(ai_client, "chat_completion", lambda *args: payload)
    with pytest.raises(ValidationError):
        ai_client.identify_metadata({}, {})


def test_model_test_uses_inference_endpoint_and_optional_auth(monkeypatch):
    requests = []

    def request(req, **kwargs):
        requests.append(req)
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

    monkeypatch.setattr(ai_client, "urlopen", request)
    plugin = metadata_provider_registry().require("ai")
    assert isinstance(plugin, BuiltinMetadataProvider)
    assert plugin.test({"baseUrl": "http://local/v1", "model": "local"})["ok"]
    assert requests[0].full_url == "http://local/v1/chat/completions"
    assert requests[0].get_header("Authorization") is None
    assert json.loads(requests[0].data)["model"] == "local"


@pytest.mark.parametrize("author,source_author,matches", [
    ("作者甲", "作者乙", False), ("作者甲", "作者甲", True),
    ("", "作者乙", True), ("作者甲", None, True),
])
def test_unique_title_does_not_override_conflicting_author(author, source_author, matches):
    from app.services.organize_service import choose_metadata_candidate
    candidate = {"title": "示例书", "author": source_author, "description": "网站简介"}
    original = dict(candidate)
    selected, exact = choose_metadata_candidate([candidate], "示例书", author)
    assert (selected is candidate) is matches
    assert exact == [original] and candidate == original


@pytest.mark.parametrize("primary,related", [("douban:1", []), ("1", []), ("bangumi:1", ["douban:1"]), (None, ["bangumi:1"])])
def test_match_rejects_invented_or_cross_source_keys(db_session, monkeypatch, primary, related):
    from app.contracts.metadata_identity import MetadataIdentity
    from app.modules.metadata.infrastructure import matching
    db_session.add(Source(id="ai-match", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://local/v1", "model": "test"})))
    db_session.commit()
    monkeypatch.setattr(ai_client, "chat_completion", lambda *args: {
        "title": "书", "author": "甲", "needsReview": False, "reason": "test",
        "primaryCandidateId": primary, "relatedCandidateIds": related,
    })
    with pytest.raises(ValueError, match="AI_MATCH_"):
        matching.match_metadata_candidates(db_session, book_id="absent", title="书", author="甲",
            identity=MetadataIdentity("书", "甲", True, "uncertain"),
            candidates=[{"id": "1", "source": "bangumi", "title": "书", "author": "乙"}])


def test_related_fields_never_overwrite_primary_or_mix_publication_data():
    from app.contracts.metadata_identity import MetadataIdentity
    from app.modules.metadata.infrastructure.matching import MetadataMatch
    primary = {"id": "1", "source": "bangumi", "title": "原题", "author": "原作者", "description": "主简介",
               "isbn": None, "publisher": None, "publishedAt": None, "tags": []}
    related = {"id": "1", "source": "douban", "description": "关联简介", "tags": ["小说"], "isbn": "其他ISBN",
               "publisher": "其他出版社", "publishedAt": "2000"}
    match = MetadataMatch(MetadataIdentity("标准题", "标准作者", False, "matched"), "bangumi:1", ("douban:1",))
    applied = match.application_candidate([primary, related])
    assert applied["description"] == "主简介" and applied["tags"] == ["小说"]
    assert applied["isbn"] is None and applied["publisher"] is None and applied["publishedAt"] is None
    assert primary["title"] == "原题" and primary["author"] == "原作者"



def test_empty_match_does_not_certify_an_uncertain_identity(db_session, monkeypatch):
    from app.contracts.metadata_identity import MetadataIdentity
    from app.modules.metadata.infrastructure import matching
    db_session.add(Source(id="empty-match", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://local/v1", "model": "test"})))
    db_session.commit()
    monkeypatch.setattr(ai_client, "chat_completion", lambda *args: {
        "title": None, "author": None, "needsReview": False, "reason": "no matching entry",
        "primaryCandidateId": None, "relatedCandidateIds": [],
    })
    result = matching.match_metadata_candidates(db_session, book_id="absent", title="未定标题", author=None,
        identity=MetadataIdentity("未定标题", None, True, "uncertain"),
        candidates=[{"id": "1", "source": "bangumi", "title": "另一本", "author": "作者"}])
    assert result.primary_candidate_id is None
    assert result.identity.needs_review
    assert result.application_candidate([])["title"] == "未定标题"



def test_multiple_same_work_records_can_be_confirmed_in_source_order(db_session, monkeypatch):
    from app.contracts.metadata_identity import MetadataIdentity
    from app.modules.metadata.infrastructure import matching
    db_session.add(Source(id="multiple-match", name="AI", kind="metadata", provider_type="ai", enabled=True,
                          config=json.dumps({"baseUrl": "http://local/v1", "model": "test"})))
    db_session.commit()
    def response(config, prompt, summary):
        assert [item["id"] for item in summary["candidates"]] == ["bangumi:1", "bangumi:2"]
        return {"title": "同一本", "author": "作者", "needsReview": False, "reason": "two records of one work",
                "primaryCandidateId": "bangumi:1", "relatedCandidateIds": ["bangumi:2"]}
    monkeypatch.setattr(ai_client, "chat_completion", response)
    candidates = [{"id": str(i), "source": "bangumi", "title": "同一本", "author": "作者",
                   "description": f"记录{i}简介"} for i in (1, 2)]
    result = matching.match_metadata_candidates(db_session, book_id="absent", title="同一本", author="作者",
        identity=MetadataIdentity("同一本", "作者", False, "A"), candidates=candidates)
    assert result.primary_candidate_id == "bangumi:1"
    assert result.application_candidate(candidates)["description"] == "记录1简介"


@pytest.mark.parametrize("invalid", [{"primaryCandidateId": 3}, {"relatedCandidateIds": "bangumi:1"}, {"description": "invented"}])
def test_match_response_rejects_invalid_shape_and_generated_fields(monkeypatch, invalid):
    monkeypatch.setattr(ai_client, "chat_completion", lambda *args: {
        "title": "书", "author": "作者", "needsReview": False, "reason": "matched",
        "primaryCandidateId": "bangumi:1", "relatedCandidateIds": [], **invalid,
    })
    with pytest.raises(ValidationError):
        ai_client.match_metadata({}, {})
