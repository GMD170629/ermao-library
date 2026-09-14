"""Policies that control reconciliation after source-tree discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum


class MissingEntryPolicy(str, Enum):
    """Choose whether unseen stored children survive a successful directory scan."""

    PRESERVE = "PRESERVE"
    PRUNE_MISSING = "PRUNE_MISSING"


@dataclass(frozen=True, slots=True)
class ScanScope:
    relative_path: str
    recursive: bool = False

    def __post_init__(self) -> None:
        if self.relative_path and any(
            part in {"", ".", ".."} for part in self.relative_path.split("/")
        ):
            raise ValueError("INVALID_SCAN_SCOPE")
        if "\\" in self.relative_path or "\x00" in self.relative_path:
            raise ValueError("INVALID_SCAN_SCOPE")


def merge_scan_scopes(
    left: tuple[ScanScope, ...] | None, right: tuple[ScanScope, ...] | None
) -> tuple[ScanScope, ...] | None:
    if left is None or right is None:
        return None
    result: list[ScanScope] = []
    for item in sorted(
        set(left + right), key=lambda x: (x.relative_path, not x.recursive)
    ):
        if any(
            parent.relative_path == item.relative_path
            or (
                parent.recursive
                and (
                    not parent.relative_path
                    or item.relative_path.startswith(parent.relative_path + "/")
                )
            )
            for parent in result
        ):
            continue
        result.append(item)
    return tuple(result)


def encode_scan_scopes(scopes: tuple[ScanScope, ...] | None) -> str | None:
    return (
        None
        if scopes is None
        else json.dumps(
            [
                {"relativePath": scope.relative_path, "recursive": scope.recursive}
                for scope in scopes
            ]
        )
    )


def decode_scan_scopes(value: str | None) -> tuple[ScanScope, ...] | None:
    if value is None:
        return None
    data = json.loads(value)
    if not isinstance(data, list) or not data:
        raise ValueError("INVALID_SCAN_SCOPE")
    result = []
    for item in data:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("relativePath"), str)
            or not isinstance(item.get("recursive"), bool)
        ):
            raise TypeError("INVALID_SCAN_SCOPE")
        result.append(ScanScope(item["relativePath"], item["recursive"]))
    return tuple(result)


__all__ = ["MissingEntryPolicy"]
