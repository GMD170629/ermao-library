"""Immutable work scope for one accepted Book import execution."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.modules.imports.domain.scan_policy import ScanScope

_MAX_SCOPES = 64
_MAX_RESOURCES = 128
_MAX_REASONS = 16
_MAX_ENCODED_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class BookWork:
    # None requests a full scan of this Book; () requests no scan.
    scan_scopes: tuple[ScanScope, ...] | None = ()
    # None processes every Resource of this Book through bounded pages.
    resource_ids: tuple[str, ...] | None = ()
    identify: bool = False
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scan_scopes is not None and len(self.scan_scopes) > _MAX_SCOPES:
            raise ValueError("BOOK_WORK_TOO_MANY_SCOPES")
        if self.resource_ids is not None and len(self.resource_ids) > _MAX_RESOURCES:
            raise ValueError("BOOK_WORK_TOO_MANY_RESOURCES")
        if len(self.reasons) > _MAX_REASONS:
            raise ValueError("BOOK_WORK_TOO_MANY_REASONS")
        if self.resource_ids is not None and any(
            not value or len(value) > 191 for value in self.resource_ids
        ):
            raise ValueError("INVALID_BOOK_RESOURCE_ID")
        if self.resource_ids is not None and any(
            not value.isascii()
            or not all(character.isalnum() or character in "-_" for character in value)
            for value in self.resource_ids
        ):
            raise ValueError("INVALID_BOOK_RESOURCE_ID")
        if any(not value or len(value) > 48 for value in self.reasons):
            raise ValueError("INVALID_BOOK_WORK_REASON")
        if any(
            not value.isascii()
            or not all(character.isupper() or character.isdigit() or character == "_" for character in value)
            for value in self.reasons
        ):
            raise ValueError("INVALID_BOOK_WORK_REASON")
        if self.resource_ids is not None and len(set(self.resource_ids)) != len(
            self.resource_ids
        ):
            raise ValueError("DUPLICATE_BOOK_RESOURCE_ID")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("DUPLICATE_BOOK_WORK_REASON")

    @property
    def is_empty(self) -> bool:
        return (
            self.scan_scopes == ()
            and self.resource_ids == ()
            and not self.identify
        )

def encode_book_work(value: BookWork) -> str:
    encoded = json.dumps(
        _work_to_data(value),
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > _MAX_ENCODED_BYTES:
        raise ValueError("BOOK_WORK_TOO_LARGE")
    return encoded


def decode_book_work(value: str) -> BookWork:
    if len(value.encode("utf-8")) > _MAX_ENCODED_BYTES:
        raise ValueError("BOOK_WORK_TOO_LARGE")
    data = json.loads(value)
    if not isinstance(data, dict):
        raise TypeError("INVALID_BOOK_WORK")
    if set(data) == {"active", "pending"}:
        # Historical rows only. Migration 0037 converts accepted pending work.
        active = _work_from_data(data["active"])
        pending = _work_from_data(data["pending"])
        return active if not active.is_empty else pending
    return _work_from_data(data)


def _work_to_data(value: BookWork) -> dict[str, object]:
    return {
        "scanScopes": None
        if value.scan_scopes is None
        else [
            {"relativePath": scope.relative_path, "recursive": scope.recursive}
            for scope in value.scan_scopes
        ],
        "resourceIds": None if value.resource_ids is None else list(value.resource_ids),
        "identify": value.identify,
        "reasons": list(value.reasons),
    }


def _work_from_data(data: object) -> BookWork:
    if not isinstance(data, dict) or set(data) != {
        "scanScopes",
        "resourceIds",
        "identify",
        "reasons",
    }:
        raise ValueError("INVALID_BOOK_WORK")
    raw_scopes = data["scanScopes"]
    scopes: tuple[ScanScope, ...] | None
    if raw_scopes is None:
        scopes = None
    elif isinstance(raw_scopes, list):
        parsed_scopes: list[ScanScope] = []
        for item in raw_scopes:
            if (
                not isinstance(item, dict)
                or set(item) != {"relativePath", "recursive"}
                or not isinstance(item["relativePath"], str)
                or not isinstance(item["recursive"], bool)
            ):
                raise ValueError("INVALID_BOOK_WORK")
            parsed_scopes.append(ScanScope(item["relativePath"], item["recursive"]))
        scopes = tuple(parsed_scopes)
    else:
        raise ValueError("INVALID_BOOK_WORK")
    resources = data["resourceIds"]
    reasons = data["reasons"]
    identify = data["identify"]
    if (
        (resources is not None and not isinstance(resources, list))
        or (isinstance(resources, list) and not all(isinstance(item, str) for item in resources))
        or not isinstance(reasons, list)
        or not all(isinstance(item, str) for item in reasons)
        or not isinstance(identify, bool)
    ):
        raise ValueError("INVALID_BOOK_WORK")
    return BookWork(
        scopes, None if resources is None else tuple(resources), identify, tuple(reasons)
    )


__all__ = ["BookWork", "decode_book_work", "encode_book_work"]
