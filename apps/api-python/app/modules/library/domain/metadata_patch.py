"""Explicit field-level metadata changes, independent from files and transport."""

import math
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal

MetadataTarget = Literal["book", "resource", "source_node"]
MetadataValue = str | float | bool | None | tuple[str, ...]


class MetadataPatchError(ValueError):
    """Stable errors without target values or internal paths."""


@dataclass(frozen=True)
class MetadataField:
    kind: Literal["text", "number", "boolean", "date", "tags"]
    nullable: bool = True
    max_length: int = 2000


TEXT = MetadataField("text")
TITLE = MetadataField("text", nullable=False, max_length=1000)
DESCRIPTION = MetadataField("text", max_length=100_000)
METADATA_FIELDS = MappingProxyType(
    {
        "book": MappingProxyType(
            {
                "title": TITLE,
                "author": TEXT,
                "description": DESCRIPTION,
                "series_name": TEXT,
                "series_index": MetadataField("number"),
                "tags": MetadataField("tags"),
            }
        ),
        "resource": MappingProxyType(
            {
                "title": TITLE,
                "description": DESCRIPTION,
                "publisher": TEXT,
                "published_at": MetadataField("date"),
                "language": MetadataField("text", max_length=64),
                "isbn": MetadataField("text", max_length=64),
                "identifier": TEXT,
                "narrator": TEXT,
                "abridged": MetadataField("boolean"),
                "resource_index": MetadataField("number"),
            }
        ),
        "source_node": MappingProxyType({"title": TITLE, "description": DESCRIPTION}),
    }
)


def validate_value(field: MetadataField, value: MetadataValue) -> MetadataValue:
    if value is None:
        raise MetadataPatchError("USE_CLEAR_FIELDS")
    if field.kind == "text":
        if (
            not isinstance(value, str)
            or len(value) > field.max_length
            or "\x00" in value
        ):
            raise MetadataPatchError("INVALID_FIELD_VALUE")
        if not value.strip():
            raise MetadataPatchError("USE_CLEAR_FIELDS")
        return value.strip()
    if field.kind == "number":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise MetadataPatchError("INVALID_FIELD_VALUE")
        return float(value)
    if field.kind == "boolean":
        if type(value) is not bool:
            raise MetadataPatchError("INVALID_FIELD_VALUE")
        return value
    if field.kind == "date":
        if not isinstance(value, str):
            raise MetadataPatchError("INVALID_FIELD_VALUE")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise MetadataPatchError("INVALID_FIELD_VALUE") from error
        if parsed.tzinfo is None:
            raise MetadataPatchError("DATE_TIMEZONE_REQUIRED")
        return parsed.isoformat()
    if (
        not isinstance(value, tuple)
        or len(value) > 50
        or any(
            not isinstance(tag, str)
            or not tag.strip()
            or len(tag) > 191
            or any(ord(c) < 32 for c in tag)
            for tag in value
        )
    ):
        raise MetadataPatchError("INVALID_FIELD_VALUE")
    if not value:
        raise MetadataPatchError("USE_CLEAR_FIELDS")
    return tuple(dict.fromkeys(tag.strip() for tag in value))


@dataclass(frozen=True)
class MetadataChange:
    target_type: MetadataTarget
    target_id: str
    expected_revision: str
    mode: Literal["patch", "fill_missing"]
    fields: dict[str, MetadataValue]
    clear_fields: frozenset[str] = frozenset()
    override_fields: frozenset[str] = frozenset()


def prepare_metadata_patch(
    change: MetadataChange,
    current: dict[str, MetadataValue],
    protected: frozenset[str],
    *,
    allow_override: bool,
) -> dict[str, MetadataValue]:
    schema = METADATA_FIELDS.get(change.target_type)
    affected = set(change.fields) | change.clear_fields
    if (
        schema is None
        or not affected
        or not affected <= schema.keys()
        or set(change.fields) & change.clear_fields
        or not change.override_fields <= affected
    ):
        raise MetadataPatchError("INVALID_FIELDS")
    if change.mode not in {"patch", "fill_missing"} or (
        change.mode == "fill_missing" and change.clear_fields
    ):
        raise MetadataPatchError("INVALID_MODE")
    if change.override_fields and not allow_override:
        raise MetadataPatchError("OVERRIDE_SCOPE_REQUIRED")
    result: dict[str, MetadataValue] = {}
    for name in affected:
        if name in change.clear_fields:
            if not schema[name].nullable:
                raise MetadataPatchError("FIELD_NOT_NULLABLE")
            value: MetadataValue = () if schema[name].kind == "tags" else None
        else:
            value = validate_value(schema[name], change.fields[name])
        if change.mode == "fill_missing" and (
            name in protected or current.get(name) not in (None, "", ())
        ):
            continue
        # Even assigning the same value is an explicit ownership decision.
        if name in protected and name not in change.override_fields:
            raise MetadataPatchError("PROTECTED_FIELD")
        result[name] = value
    return result
