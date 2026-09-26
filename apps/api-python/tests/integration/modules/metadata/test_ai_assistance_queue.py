import json

import pytest

from app.models import LibraryBookMetadata, MetadataLookupTask
from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS
from app.modules.metadata.infrastructure import ai_assistance as ai_client
from app.modules.metadata.infrastructure.sources import (
    prepare_builtin_provider_seed_rows,
    write_builtin_provider_seed_rows,
)
from app.services import metadata_lookup_queue as queue
from app.services.metadata_provider_registry import test_metadata_provider as model_test
from app.services.metadata_provider_registry import (
    update_metadata_provider,
    update_metadata_provider_order,
)
from tests.test_metadata_lookup_queue import _lookup_task, _seed_lookup_graph
from tests.unit.modules.metadata.test_ai_assistance import Response


def configure(db, mode):
    write_builtin_provider_seed_rows(db, prepare_builtin_provider_seed_rows(BUILTIN_MANIFESTS))
    db.commit()
    update_metadata_provider(db, "ai", {"config": {"baseUrl": "https://model.example/v1", "model": "test-model", "authentication": "none", "assistanceMode": mode}})
    update_metadata_provider_order(db, [{"providerId": "ai", "enabled": True}])


@pytest.mark.parametrize("mode", ["OFF", "SUGGEST_ONLY", "ASSIST_ON_AMBIGUITY"])
def test_automatic_hints_requery_source_and_only_apply_verified_facts(db_session, test_settings, monkeypatch, mode):
    configure(db_session, mode)
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id = task.id
    queries, model_calls = [], []
    def search(db, context, provider, query, gate):
        queries.append(query)
        return {"enabled": True, "candidates": [{"id": "verified", "title": "黑暗坡食人树", "author": "岛田庄司", "matchLevel": "WORK", "description": "Only the source supplies this text"}] if query else []}
    def model(req, **kwargs):
        assert not db_session.in_transaction()
        model_calls.append(req)
        return Response(json.dumps({"title": "黑暗坡食人树", "author": None, "volume": None,
            "evidenceIds": ["target:title"], "queryHints": [{"query": "黑暗坡食人树", "evidenceIds": ["target:title"], "hypothesis": False}], "reason": "metadata title"}))
    monkeypatch.setattr(queue, "_search_provider", search)
    monkeypatch.setattr(ai_client, "urlopen", model)
    result = queue.process_metadata_lookup_task(db_session, test_settings, {"id": task_id, "bookId": book_id, "resourceId": resource_id, "providerOrder": '["douban"]'})
    if mode == "ASSIST_ON_AMBIGUITY":
        assert result == "COMPLETED" and len(model_calls) == 1 and len(queries) == 2
        assert db_session.get(LibraryBookMetadata, book_id).description == "Only the source supplies this text"
        assert json.loads(db_session.get(MetadataLookupTask, task_id).candidate_raw_json)["recognition"]["aiAttempts"] == 1
    else:
        assert result == "NO_MATCH" and model_calls == [] and queries == [None]
        assert db_session.get(LibraryBookMetadata, book_id).description is None


def test_model_test_uses_the_same_structured_request_with_none_auth(db_session, monkeypatch):
    configure(db_session, "SUGGEST_ONLY")
    def response(req, **kwargs):
        assert not db_session.in_transaction()
        assert req.get_header("Authorization") is None
        assert json.loads(req.data)["model"] == "test-model"
        return Response(json.dumps({"title": None, "author": None, "volume": None, "queryHints": [], "evidenceIds": [], "reason": "No inference"}))
    monkeypatch.setattr(ai_client, "urlopen", response)
    result, provider = model_test(db_session, "ai")
    assert result["ok"] and provider["lastTestStatus"] == "ok"



def test_model_selection_cannot_turn_ambiguous_versions_into_automatic_writes(db_session, test_settings, monkeypatch):
    configure(db_session, "ASSIST_ON_AMBIGUITY")
    book, resource = _seed_lookup_graph(db_session)
    book_id, resource_id = book.id, resource.id
    task = _lookup_task(db_session, book, resource, status="RUNNING")
    task_id = task.id
    candidates = [{"id": key, "source": "douban", "title": "黑暗坡食人树", "author": "岛田庄司", "matchLevel": "WORK", "description": key} for key in ("first", "second")]
    monkeypatch.setattr(queue, "_search_provider", lambda *args: {"enabled": True, "candidates": candidates})
    def model(req, **kwargs):
        inputs = json.loads(json.loads(req.data)["messages"][1]["content"])
        key = inputs["candidates"][0]["candidateKey"]
        return Response(json.dumps({"selectedCandidateKey": key, "supportingEvidenceIds": [key + ":title"], "conflictingEvidenceIds": [], "reason": "Model preference is not identity proof"}))
    monkeypatch.setattr(ai_client, "urlopen", model)
    assert queue.process_metadata_lookup_task(db_session, test_settings, {"id": task_id, "bookId": book_id, "resourceId": resource_id, "providerOrder": '["douban"]'}) == "NO_MATCH"
    assert db_session.get(LibraryBookMetadata, book_id).description is None
    stored = json.loads(db_session.get(MetadataLookupTask, task_id).candidate_raw_json)["recognition"]
    assert stored["outcome"] == "AMBIGUOUS" and stored["aiAssistance"]["selectedCandidateKey"]
