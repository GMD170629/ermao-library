from __future__ import annotations

from datetime import UTC, datetime
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.contracts import validation_errors
from app.modules.imports.presentation import schemas as import_schemas
from app.modules.library.presentation import schemas as library_schemas
from app.modules.organize.presentation import schemas as organize_schemas
from app.modules.system.presentation import schemas as system_schemas

DTO_MODULES: tuple[ModuleType, ...] = (
    validation_errors,
    import_schemas,
    library_schemas,
    organize_schemas,
    system_schemas,
)


def _response_contracts() -> dict[str, type[BaseModel]]:
    contracts: dict[str, type[BaseModel]] = {}
    for module in DTO_MODULES:
        for name, value in vars(module).items():
            if (
                name.endswith("Response")
                and isinstance(value, type)
                and issubclass(value, BaseModel)
            ):
                contracts[f"{module.__name__}.{name}"] = value
    return contracts


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/"), f"external JSON Schema reference is forbidden: {ref}"
    value: Any = root
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(value, dict)
    return value


def _assert_constrained_schema(
    node: Any,
    *,
    root: dict[str, Any],
    path: str,
    seen_refs: set[str],
) -> None:
    if isinstance(node, list):
        for index, child in enumerate(node):
            _assert_constrained_schema(
                child,
                root=root,
                path=f"{path}[{index}]",
                seen_refs=seen_refs,
            )
        return
    if not isinstance(node, dict):
        return

    ref = node.get("$ref")
    if isinstance(ref, str):
        assert ref.startswith("#/$defs/"), f"{path}: unresolved or external $ref {ref}"
        if ref not in seen_refs:
            _assert_constrained_schema(
                _resolve_ref(root, ref),
                root=root,
                path=ref,
                seen_refs={*seen_refs, ref},
            )

    assert node != {}, f"{path}: empty schema permits arbitrary JSON"
    assert node.get("additionalProperties") is not True, (
        f"{path}: additionalProperties=true permits arbitrary fields"
    )
    if node.get("type") == "object":
        properties = node.get("properties")
        additional = node.get("additionalProperties")
        assert properties or isinstance(additional, dict), (
            f"{path}: object has neither properties nor typed additionalProperties"
        )
    if node.get("type") == "array":
        items = node.get("items")
        if items is None:
            assert node.get("maxItems") == 0, f"{path}: array has no item schema"
        else:
            assert items != {}, f"{path}: array items permit arbitrary JSON"

    for key, child in node.items():
        if key == "$defs":
            continue
        _assert_constrained_schema(
            child,
            root=root,
            path=f"{path}.{key}",
            seen_refs=seen_refs,
        )


@pytest.mark.parametrize("name,model", sorted(_response_contracts().items()))
def test_response_contract_schema_is_fully_constrained(
    name: str,
    model: type[BaseModel],
) -> None:
    schema = TypeAdapter(model).json_schema()
    _assert_constrained_schema(schema, root=schema, path=name, seen_refs=set())


def test_http_contract_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        validation_errors.ValidationInputSummary.model_validate(
            {"kind": "string", "value": "safe", "unexpected": True}
        )


def test_validation_issue_uses_wire_aliases_and_has_no_ctx() -> None:
    issue = validation_errors.RequestValidationIssue.model_validate(
        {
            "loc": ["body", "title"],
            "message": "Field required",
            "type": "missing",
            "input": {"kind": "object", "length": 1, "keys": ["author"]},
        }
    )

    dumped = issue.model_dump(by_alias=True)
    assert dumped["loc"] == ["body", "title"]
    assert dumped["type"] == "missing"
    assert "ctx" not in dumped


def test_datetime_serializes_as_utc_z() -> None:
    event = system_schemas.SystemEvent.model_validate(
        {
            "id": "event-1",
            "level": "info",
            "source": "system",
            "actorType": "system",
            "actorId": None,
            "action": "checked",
            "targetType": None,
            "targetId": None,
            "message": "ok",
            "metadata": {},
            "createdAt": datetime(2026, 7, 28, 3, 4, 5, tzinfo=UTC),
        }
    )

    assert '"createdAt":"2026-07-28T03:04:05Z"' in event.model_dump_json(by_alias=True)


def test_response_dto_wire_schemas_have_no_retired_identity_fields() -> None:
    retired = {
        "workId",
        "versionId",
        "volumeId",
        "fileId",
        "work_id",
        "version_id",
        "volume_id",
        "file_id",
    }

    def property_names(value: Any) -> set[str]:
        if isinstance(value, dict):
            properties = value.get("properties")
            names = set(properties) if isinstance(properties, dict) else set()
            return names | {
                name for child in value.values() for name in property_names(child)
            }
        if isinstance(value, list):
            return {name for child in value for name in property_names(child)}
        return set()

    for name, model in _response_contracts().items():
        assert retired.isdisjoint(property_names(TypeAdapter(model).json_schema())), (
            name
        )


def test_library_resource_asset_schema_accepts_comic_page_fields() -> None:
    asset = library_schemas.ResourceAssetView.model_validate(
        {
            "id": "asset-1",
            "resourceId": "resource-1",
            "sourceNodeId": "source-1",
            "role": "PAGE",
            "mimeType": "image/jpeg",
            "path": "pages/001.jpg",
            "kind": "PAGE",
            "sizeBytes": 1024,
            "size": "1 KB",
            "mtimeMs": 0,
            "sortOrder": 1,
            "url": "/api/assets/asset-1",
        }
    )

    assert asset.model_dump(by_alias=True, exclude_none=True) == {
        "id": "asset-1",
        "resourceId": "resource-1",
        "sourceNodeId": "source-1",
        "role": "PAGE",
        "mimeType": "image/jpeg",
        "path": "pages/001.jpg",
        "kind": "PAGE",
        "sizeBytes": 1024,
        "size": "1 KB",
        "mtimeMs": 0,
        "sortOrder": 1,
        "url": "/api/assets/asset-1",
    }
