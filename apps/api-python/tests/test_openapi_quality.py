from __future__ import annotations

from collections.abc import Iterator
from typing import Never, NoReturn

from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.contracts.http_errors import return_contract_type
from app.core.config import Settings
from app.main import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _schema_children(
    schema: dict[str, object],
    location: str,
) -> Iterator[tuple[dict[str, object], str]]:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            if isinstance(child, dict):
                yield child, f"{location}.properties.{name}"
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        yield additional, f"{location}.additionalProperties"
    items = schema.get("items")
    if isinstance(items, dict) and schema.get("maxItems") != 0:
        yield items, f"{location}.items"
    for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
        variants = schema.get(keyword)
        if isinstance(variants, list):
            for index, child in enumerate(variants):
                if isinstance(child, dict):
                    yield child, f"{location}.{keyword}[{index}]"


def _unconstrained_schema_locations(
    schema: dict[str, object],
    location: str,
    components: dict[str, object],
    visited_refs: frozenset[str] = frozenset(),
) -> Iterator[str]:
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
        if reference in visited_refs:
            return
        name = reference.rsplit("/", 1)[-1]
        target = components.get(name)
        if isinstance(target, dict):
            yield from _unconstrained_schema_locations(
                target,
                reference,
                components,
                visited_refs | {reference},
            )
        else:
            yield f"{location} (unresolved {reference})"
        return
    if not schema:
        yield location
        return
    if schema.get("additionalProperties") is True:
        yield f"{location}.additionalProperties"
    if schema.get("type") == "object":
        has_properties = bool(schema.get("properties"))
        additional = schema.get("additionalProperties")
        if (
            not has_properties
            and additional not in (False,)
            and not isinstance(
                additional,
                dict,
            )
        ):
            yield location
    if (
        schema.get("type") == "array"
        and schema.get("maxItems") != 0
        and not isinstance(schema.get("items"), dict)
    ):
        yield f"{location}.items"
    for child, child_location in _schema_children(schema, location):
        yield from _unconstrained_schema_locations(
            child,
            child_location,
            components,
            visited_refs,
        )


def test_backend_documentation_endpoints_share_generated_schema(client) -> None:
    schema_response = client.get("/openapi.json")
    assert schema_response.status_code == 200
    assert schema_response.headers["content-type"].startswith("application/json")

    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 200
        assert "/openapi.json" in response.text


def test_every_json_route_has_a_concrete_inferred_response_model(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    missing: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        status_code = route.status_code or 200
        if status_code == 204:
            assert route.response_field is None, route.path
            continue
        response_class = route.response_class
        if isinstance(response_class, DefaultPlaceholder):
            response_class = response_class.value
        is_json_route = issubclass(response_class, JSONResponse)
        return_type = return_contract_type(route.endpoint)
        if (
            is_json_route
            and route.response_field is None
            and return_type not in {Never, NoReturn}
        ):
            methods = ",".join(sorted(route.methods or ()))
            missing.append(f"{methods} {route.path}")
        if not is_json_route and not response_class.media_type:
            methods = ",".join(sorted(route.methods or ()))
            missing.append(
                f"{methods} {route.path} (non-JSON media type is not declared)"
            )
    assert missing == [], "JSON routes without inferred response models:\n" + "\n".join(
        missing
    )


def test_generated_openapi_contains_no_free_form_response_schema(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    schema = app.openapi()
    failures: list[str] = []
    operation_ids: list[str] = []
    components = schema.get("components", {}).get("schemas", {})
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_ids.append(operation["operationId"])
            for status_code, response in operation["responses"].items():
                for media_type, media in response.get("content", {}).items():
                    response_schema = media.get("schema")
                    if not isinstance(response_schema, dict):
                        failures.append(
                            f"{method.upper()} {path} {status_code} {media_type}: missing schema"
                        )
                        continue
                    failures.extend(
                        _unconstrained_schema_locations(
                            response_schema,
                            f"{method.upper()} {path} {status_code} {media_type}",
                            components,
                        )
                    )

    assert len(operation_ids) == len(set(operation_ids))
    assert schema["info"]["title"] == test_settings.app_name
    assert schema["info"]["version"] == test_settings.app_version
    assert failures == [], "Unconstrained OpenAPI response schemas:\n" + "\n".join(
        failures
    )
