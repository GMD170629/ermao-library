"""Official-source payloads through the existing registry and database config."""

import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from app.modules.metadata.infrastructure import bibliographic_providers as api
from app.services import metadata_provider_registry as registry
from app.services.organize_service import (
    bangumi_candidates,
    normalize_douban_candidate,
    parse_douban_subject_html,
)


@pytest.fixture(autouse=True)
def seed_providers(db_session):
    from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS
    from app.modules.metadata.infrastructure.sources import (
        prepare_builtin_provider_seed_rows,
        write_builtin_provider_seed_rows,
    )
    write_builtin_provider_seed_rows(db_session, prepare_builtin_provider_seed_rows(BUILTIN_MANIFESTS))
    db_session.commit()


class Response:
    def __init__(self, value):
        self.data = json.dumps(value).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, limit=-1):
        return self.data[:limit] if limit >= 0 else self.data


def context(execution="MANUAL", explicit=True):
    return {"book": {"title": "Example", "author": "First / Second"},
        "identity": {"execution": execution, "targetId": "resource-1", "targetType": "resource", "libraryId": "test-library", "isbn": "0306406152"},
        "explicitManualQuery": explicit}


def enable(db, provider, config=None):
    registry.update_metadata_provider(db, provider, {"config": config or {}})
    registry.update_metadata_provider_order(db, [{"providerId": provider, "enabled": True}])


def test_google_saved_key_survives_old_order_and_session_reload(db_session, monkeypatch):
    assert not registry.get_metadata_provider(db_session, "google-books")["enabled"]
    enable(db_session, "google-books", {"apiKey": "test-secret"})
    registry.update_metadata_provider_order(db_session, [{"providerId": "douban", "enabled": False}, {"providerId": "bangumi", "enabled": False}, {"providerId": "ai", "enabled": False}])
    db_session.close()
    public = registry.get_metadata_provider(db_session, "google-books")
    assert public["enabled"] and public["configuredSecrets"]["apiKey"]
    assert "test-secret" not in repr(public)
    calls = []
    def request(req, **kwargs):
        assert not db_session.in_transaction()
        calls.append(req)
        assert parse_qs(urlsplit(req.full_url).query)["key"] == ["test-secret"]
        return Response({"items": [{"id": "volume1", "volumeInfo": {"title": "Example", "authors": ["First", "Second"], "publishedDate": "2001-02", "industryIdentifiers": [{"type": "ISBN_10", "identifier": "0306406152"}], "categories": ["Science"]}}]})
    monkeypatch.setattr(api, "urlopen", request)
    result = registry.search_with_metadata_provider(db_session, context(), "google-books")
    candidate = result["candidates"][0]
    assert candidate["isbn"] == "9780306406157" and candidate["isbnScope"] == "EDITION"
    assert candidate["publishedAt"] == "2001-02" and candidate["authors"] == ["First", "Second"]
    assert candidate["tags"] == [] and candidate["coverUrl"] is None
    assert parse_qs(urlsplit(calls[0].full_url).query)["q"] == ["isbn:9780306406157"]
    assert registry.search_with_metadata_provider(db_session, context(), "google-books")["cacheHit"]
    assert len(calls) == 1


@pytest.mark.parametrize("execution,explicit", [("AUTOMATIC", True), ("MANUAL", False), ("BATCH", True)])
def test_open_library_rejects_non_explicit_manual_requests(db_session, monkeypatch, execution, explicit):
    enable(db_session, "open-library")
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: pytest.fail("forbidden Open Library request"))
    result = registry.search_with_metadata_provider(db_session, context(execution, explicit), "open-library")
    assert result["enabled"] is False and result["candidates"] == []
    assert "open-library" not in registry.enabled_metadata_provider_ids(db_session)


def test_open_library_work_drops_aggregated_edition_fields(db_session, monkeypatch):
    enable(db_session, "open-library")
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: Response({"docs": [{"key": "/works/OL1W", "title": "Example", "author_name": ["First"], "isbn": ["9780306406157"], "publisher": ["Many"], "language": ["eng", "chi"]}]}))
    result = registry.search_with_metadata_provider(db_session, context(), "open-library", "Example")
    value = result["candidates"][0]
    assert value["matchLevel"] == "WORK" and value["isbnScope"] == "UNKNOWN"
    assert not value.get("isbn") and not value.get("publisher") and not value.get("language")


def test_open_library_isbn_uses_only_returned_edition_identifier(monkeypatch):
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: Response({"ISBN:9780306406157": {"key": "/books/OL1M", "title": "Example", "authors": [{"name": "First"}], "identifiers": {"isbn_10": ["0306406152"]}, "publishers": [{"name": "Publisher"}], "publish_date": "2001"}}))
    value = api.search_open_library(context(), {"userAgent": "Test/contact@example.org"}, "0306406152", None)["candidates"][0]
    assert value["matchLevel"] == "EDITION" and value["isbn"] == "9780306406157"
    assert value["publishedAt"] == "2001"


@pytest.mark.parametrize("status", [404, 429])
def test_google_detail_missing_or_throttled(monkeypatch, status):
    def request(req, **kwargs):
        assert "/volumes/volume-1?" in req.full_url
        raise HTTPError(req.full_url, status, "status", {}, None)
    monkeypatch.setattr(api, "urlopen", request)
    if status == 404:
        assert api.search_google(context(), {"apiKey": "key"}, "id:volume-1", None)["candidates"] == []
    else:
        with pytest.raises(HTTPError):
            api.search_google(context(), {"apiKey": "key"}, "id:volume-1", None)


def test_missing_key_and_disabled_source_make_no_request(db_session, monkeypatch):
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: pytest.fail("unconfigured request"))
    assert api.search_google(context(), {}, "Example", None)["error"] == "CONFIG_REQUIRED"
    assert not registry.search_with_metadata_provider(db_session, context(), "google-books")["enabled"]


def test_manual_only_is_enforced_even_if_source_enabled(db_session, monkeypatch):
    enable(db_session, "google-books", {"apiKey": "key", "participation": "MANUAL_ONLY"})
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: pytest.fail("automatic request"))
    assert not registry.search_with_metadata_provider(db_session, context("AUTOMATIC"), "google-books")["enabled"]
    assert "google-books" not in registry.enabled_metadata_provider_ids(db_session)


def test_bangumi_keeps_roles_without_inventing_series():
    item = bangumi_candidates({"data": [{"id": 123, "name": "Example 第2卷", "infobox": [{"key": "原作", "value": "Author"}, {"key": "作画", "value": "Artist"}, {"key": "别名", "value": [{"v": "Alias"}]}]}]}, 0.9)[0]
    assert item["author"] == "Author" and item["seriesName"] is None
    assert item["authors"] == [{"name": "Author", "role": "author"}, {"name": "Artist", "role": "illustrator"}]
    assert item["matchLevel"] == "VOLUME" and "Alias" in item["titleAliases"]


def test_douban_preserves_month_precision_and_bibliographic_scope():
    html = '''<meta property="og:url" content="https://book.douban.com/subject/1234/">
    <script type="application/ld+json">{"@type":"Book","name":"Example","isbn":"0306406152","author":[{"name":"First"},{"name":"Second"}]}</script>
    <div id="info"><span class="pl">出版社:</span> Publisher<br><span class="pl">出版年:</span> 2001-02<br></div>'''
    value = normalize_douban_candidate(parse_douban_subject_html(html))
    assert value["author"] == "First / Second"
    assert value["publishedAt"] == "2001-02" and value["isbnScope"] == "EDITION"
