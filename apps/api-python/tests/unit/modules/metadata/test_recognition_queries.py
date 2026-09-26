import pytest

from app.modules.metadata.application.queries import (
    candidate_cache_key,
    recognition_queries,
)
from app.modules.metadata.application.rate_limits import (
    RecognitionRequestBudget,
    RecognitionRequestStopped,
)


def test_isbn_query_precedes_title_author_and_override_is_preserved():
    context = {"book": {"title": "示例书 第2卷", "author": "作者"},
               "identity": {"isbn": "0306406152"}}
    assert recognition_queries(context, "douban") == ("9780306406157", "示例书 第2卷 作者")
    assert recognition_queries(context, "bangumi") == ("示例书 第2卷",)
    assert recognition_queries(context, "douban", "查找别名") == ("查找别名",)
    assert context["book"]["title"] == "示例书 第2卷"


def test_cache_isolates_author_volume_model_and_credentials():
    context = {"book": {"title": "Same", "author": "A"}}
    key = candidate_cache_key(context, "ai", "Same", {"model": "one", "apiKey": "secret"})
    assert "secret" not in key
    assert key != candidate_cache_key(context, "ai", "Same", {"model": "two"})
    assert key != candidate_cache_key({"book": {"title": "Same", "author": "B"}}, "ai", "Same", {"model": "one", "apiKey": "secret"})
    assert key != candidate_cache_key({**context, "identity": {"volume": 2}}, "ai", "Same", {"model": "one", "apiKey": "secret"})


def test_request_budget_counts_every_attempt_and_cancellation():
    active = True
    budget = RecognitionRequestBudget(lambda: active)
    for _ in range(8):
        budget.wait("douban")
    with pytest.raises(RecognitionRequestStopped, match="BUDGET"):
        budget.wait("bangumi")
    budget.wait("ai")
    budget.wait("ai")
    with pytest.raises(RecognitionRequestStopped, match="AI_BUDGET"):
        budget.wait("ai")
    active = False
    with pytest.raises(RecognitionRequestStopped, match="CANCELLED"):
        budget.wait("douban")
