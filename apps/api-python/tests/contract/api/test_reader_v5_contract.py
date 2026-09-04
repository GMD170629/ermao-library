from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.modules.reader.application.v5_locator import MAX_OPAQUE_LOCATOR_BYTES
from app.modules.reader.presentation.v5_schemas import (
    ReaderV5Bookmark,
    ReaderV5Position,
    ReaderV5Presentation,
    ReaderV5ProgressPut,
    ReaderV5ProgressSnapshot,
    ReaderV5ProgressWriteResponse,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_SCHEMA_PATH = (
    _REPOSITORY_ROOT / "packages/reader-contracts/schemas/reader-v5.schema.json"
)
_FIXTURES_PATH = _REPOSITORY_ROOT / "packages/reader-contracts/fixtures/reader-v5"


def _contract() -> dict[str, object]:
    value = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _contract_definition(name: str) -> dict[str, object]:
    definitions = _contract()["$defs"]
    assert isinstance(definitions, dict)
    definition = definitions[name]
    assert isinstance(definition, dict)
    return definition


def _model_schema(model: type) -> dict[str, object]:
    schema = model.model_json_schema(by_alias=True)
    assert isinstance(schema, dict)
    return schema


def _required_and_properties(schema: dict[str, object]) -> tuple[set[str], set[str]]:
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    assert isinstance(required, list)
    assert isinstance(properties, dict)
    return set(required), set(properties)


@pytest.mark.parametrize(
    ("model", "definition"),
    (
        (ReaderV5ProgressPut, "progressPutRequest"),
        (ReaderV5ProgressSnapshot, "progressSnapshot"),
        (ReaderV5Position, "positionReport"),
        (ReaderV5Presentation, "presentation"),
        (ReaderV5Bookmark, "bookmark"),
    ),
)
def test_v5_pydantic_fields_match_authoritative_schema(
    model: type, definition: str
) -> None:
    model_required, model_properties = _required_and_properties(_model_schema(model))
    contract_required, contract_properties = _required_and_properties(
        _contract_definition(definition)
    )

    assert model_required == contract_required
    assert model_properties == contract_properties


def test_v5_contract_fixtures_validate_at_the_http_boundary() -> None:
    fixture_paths = sorted(_FIXTURES_PATH.glob("*.json"))
    assert fixture_paths

    for fixture_path in fixture_paths:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        ReaderV5ProgressPut.model_validate(payload)


def test_v5_openapi_uses_the_same_write_and_snapshot_shapes() -> None:
    openapi = create_app().openapi()
    components = openapi["components"]["schemas"]
    assert isinstance(components, dict)
    request_ref = openapi["paths"]["/api/reader/v5/resources/{resource_id}/progress"][
        "put"
    ]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    response_ref = openapi["paths"]["/api/reader/v5/resources/{resource_id}/progress"][
        "put"
    ]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = components[request_ref.rsplit("/", 1)[-1]]
    response_schema = components[response_ref.rsplit("/", 1)[-1]]
    assert _required_and_properties(request_schema) == _required_and_properties(
        _model_schema(ReaderV5ProgressPut)
    )
    assert _required_and_properties(response_schema) == _required_and_properties(
        _model_schema(ReaderV5ProgressWriteResponse)
    )
    assert request_schema["properties"]["schemaVersion"]["const"] == 5
    assert "baseRevision" not in request_schema["properties"]


def test_v5_contract_declares_locator_budget_and_finite_numeric_boundaries() -> None:
    locator = _contract_definition("opaqueLocator")
    assert locator["x-maxSerializedUtf8Bytes"] == MAX_OPAQUE_LOCATOR_BYTES

    presentation = _contract_definition("presentation")
    properties = presentation["properties"]
    assert properties["displayPercent"]["minimum"] == 0
    assert properties["displayPercent"]["maximum"] == 100
    assert properties["totalProgression"]["minimum"] == 0
    assert properties["totalProgression"]["maximum"] == 1

    invalid = {
        "schemaVersion": 5,
        "clientId": "contract-test",
        "mutationId": "00000000-0000-4000-8000-000000000001",
        "capturedAtEpochMillis": 0,
        "position": {
            "locator": {},
            "presentation": {
                "displayPercent": 101,
                "totalProgression": 0,
                "currentHref": None,
                "chapter": None,
                "page": None,
                "playback": None,
            },
        },
    }
    with pytest.raises(ValidationError):
        ReaderV5ProgressPut.model_validate(invalid)
