"""Persist explicit user ownership, including deliberate empty values."""

from collections.abc import Iterable

from pydantic import TypeAdapter

_FIELDS = TypeAdapter(list[str])


def protected_fields(value: str | None) -> frozenset[str]:
    fields = set(_FIELDS.validate_json(value or "[]"))
    for field, derived in (
        ("title", "normalized_title"),
        ("author", "normalized_author"),
        ("cover_path", "cover_status"),
    ):
        if field in fields:
            fields.add(derived)
    return frozenset(fields)


def protect_fields(value: str | None, fields: Iterable[str]) -> str:
    return _FIELDS.dump_json(sorted(protected_fields(value).union(fields))).decode()
