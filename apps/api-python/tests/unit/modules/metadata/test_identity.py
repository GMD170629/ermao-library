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
