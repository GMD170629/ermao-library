from __future__ import annotations

import json
import math
import re
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


CONTRACT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = CONTRACT_ROOT / "schemas" / "reader-v5.schema.json"
FIXTURE_ROOT = CONTRACT_ROOT / "fixtures" / "reader-v5"


class SchemaValidationError(ValueError):
    pass


def _resolve_reference(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise SchemaValidationError(f"unsupported reference: {reference}")
    current: Any = root
    for segment in reference[2:].split("/"):
        current = current[segment.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise SchemaValidationError(f"reference does not resolve to a schema: {reference}")
    return current


def _is_json_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _matches_json_type(value: object, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return _is_json_number(value)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise SchemaValidationError(f"unsupported JSON Schema type: {expected_type!r}")


def _validate_json_schema(
    value: object,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str = "$",
) -> None:
    if "$ref" in schema:
        _validate_json_schema(value, _resolve_reference(root, schema["$ref"]), root, path)
        return

    if "oneOf" in schema:
        matches = 0
        for candidate in schema["oneOf"]:
            try:
                _validate_json_schema(value, candidate, root, path)
            except SchemaValidationError:
                continue
            matches += 1
        if matches != 1:
            raise SchemaValidationError(f"{path}: expected exactly one schema match, got {matches}")
        return

    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(f"{path}: expected constant {schema['const']!r}")

    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        expected_types = (expected_type,)
    elif isinstance(expected_type, list):
        if not expected_type or not all(
            isinstance(item, str) for item in expected_type
        ):
            raise SchemaValidationError(f"{path}: invalid JSON Schema type declaration")
        expected_types = tuple(expected_type)
    elif expected_type is None:
        expected_types = ()
    else:
        raise SchemaValidationError(f"{path}: invalid JSON Schema type declaration")

    if expected_types and not any(
        _matches_json_type(value, candidate) for candidate in expected_types
    ):
        raise SchemaValidationError(f"{path}: expected one of {expected_types!r}")

    if "object" in expected_types and isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise SchemaValidationError(f"{path}: missing required fields {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise SchemaValidationError(f"{path}: unknown fields {sorted(unknown)}")
        for name, child in value.items():
            child_schema = properties.get(name)
            if child_schema is not None:
                _validate_json_schema(child, child_schema, root, f"{path}.{name}")
        maximum_bytes = schema.get("x-maxSerializedUtf8Bytes")
        if maximum_bytes is not None:
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(serialized) > maximum_bytes:
                raise SchemaValidationError(
                    f"{path}: compact JSON exceeds {maximum_bytes} UTF-8 bytes"
                )
    if "string" in expected_types and isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise SchemaValidationError(f"{path}: string is too short")
        if len(value) > schema.get("maxLength", len(value)):
            raise SchemaValidationError(f"{path}: string is too long")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            raise SchemaValidationError(f"{path}: string does not match {pattern!r}")
        if schema.get("format") == "uuid":
            try:
                parsed = uuid.UUID(value)
            except ValueError as error:
                raise SchemaValidationError(f"{path}: invalid UUID") from error
            if str(parsed) != value.lower():
                raise SchemaValidationError(f"{path}: UUID is not canonical")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise SchemaValidationError(f"{path}: invalid date-time") from error

    if (
        ("integer" in expected_types or "number" in expected_types)
        and _is_json_number(value)
    ):
        numeric_value = float(value) if _is_json_number(value) else math.nan
        if "minimum" in schema and numeric_value < schema["minimum"]:
            raise SchemaValidationError(f"{path}: below minimum")
        if "maximum" in schema and numeric_value > schema["maximum"]:
            raise SchemaValidationError(f"{path}: above maximum")


class ReaderV5ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema: dict[str, Any] = json.loads(
            SCHEMA_PATH.read_text(encoding="utf-8")
        )

    def test_schema_declares_opaque_locator_and_no_base_revision(self) -> None:
        request = self.schema["$defs"]["progressPutRequest"]
        locator = self.schema["$defs"]["opaqueLocator"]

        self.assertEqual(5, request["properties"]["schemaVersion"]["const"])
        self.assertNotIn("baseRevision", request["properties"])
        self.assertTrue(locator["additionalProperties"])
        self.assertEqual(65536, locator["x-maxSerializedUtf8Bytes"])

    def test_all_position_fixtures_have_the_complete_presentation(self) -> None:
        expected_fields = {
            "displayPercent",
            "totalProgression",
            "currentHref",
            "chapter",
            "page",
            "playback",
        }
        for path in sorted(FIXTURE_ROOT.glob("*.json")):
            with self.subTest(path=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                _validate_json_schema(fixture, self.schema, self.schema)
                self.assertEqual(5, fixture["schemaVersion"])
                self.assertIsInstance(fixture["position"]["locator"], dict)
                self.assertEqual(
                    expected_fields,
                    set(fixture["position"]["presentation"]),
                )

    def test_empty_highlight_and_unknown_values_survive_json_round_trip(self) -> None:
        fixture = json.loads(
            (FIXTURE_ROOT / "reflowable-empty-highlight.json").read_text(
                encoding="utf-8"
            )
        )
        round_tripped = json.loads(
            json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )

        self.assertEqual(fixture, round_tripped)
        locator = round_tripped["position"]["locator"]
        self.assertEqual("", locator["text"]["highlight"])
        self.assertIsNone(locator["locations"]["vendorExtension"]["nullable"])
        self.assertTrue(locator["unknownExtension"]["preserve"])
        self.assertEqual(0.25, locator["locations"]["totalProgression"])
        self.assertEqual(
            0.99,
            round_tripped["position"]["presentation"]["totalProgression"],
        )

    def test_schema_rejects_invalid_locator_and_presentation_boundaries(self) -> None:
        valid = json.loads(
            (FIXTURE_ROOT / "reflowable-empty-highlight.json").read_text(
                encoding="utf-8"
            )
        )
        invalid_values = []

        valid_type_array_value = json.loads(json.dumps(valid))
        valid_type_array_value["position"]["presentation"]["chapter"][
            "navigationKey"
        ] = "chapter-20"
        _validate_json_schema(valid_type_array_value, self.schema, self.schema)

        non_object = json.loads(json.dumps(valid))
        non_object["position"]["locator"] = []
        invalid_values.append(non_object)

        oversized = json.loads(json.dumps(valid))
        oversized["position"]["locator"] = {"opaque": "x" * 65537}
        invalid_values.append(oversized)

        percent_above_range = json.loads(json.dumps(valid))
        percent_above_range["position"]["presentation"]["displayPercent"] = 100.01
        invalid_values.append(percent_above_range)

        non_finite_progression = json.loads(json.dumps(valid))
        non_finite_progression["position"]["presentation"]["totalProgression"] = math.nan
        invalid_values.append(non_finite_progression)

        invalid_type_array_value = json.loads(json.dumps(valid))
        invalid_type_array_value["position"]["presentation"]["chapter"][
            "navigationKey"
        ] = 123
        invalid_values.append(invalid_type_array_value)

        for invalid in invalid_values:
            with self.subTest(invalid=invalid["position"]):
                with self.assertRaises(SchemaValidationError):
                    _validate_json_schema(invalid, self.schema, self.schema)


if __name__ == "__main__":
    unittest.main()
