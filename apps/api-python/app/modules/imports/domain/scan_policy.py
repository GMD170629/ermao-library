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


def path_contains(container: str, child: str) -> bool:
    """True when ``child`` is the same path or lives below ``container``."""
    return (
        container == ""
        or child == container
        or child.startswith(container + "/")
    )


def paths_intersect(left: str, right: str) -> bool:
    """True when scanning one path can change the other path's member set."""
    return path_contains(left, right) or path_contains(right, left)


def scope_covers_path(scope: ScanScope, path: str) -> bool:
    """Python twin of the SQL scope-coverage rule for read-only projections."""
    return path_contains(path, scope.relative_path) or (
        scope.recursive and path_contains(scope.relative_path, path)
    )


def scopes_cover_path(
    scopes: tuple[ScanScope, ...] | None, path: str
) -> bool:
    if scopes is None:
        return True
    return any(scope_covers_path(scope, path) for scope in scopes)


def completed_scope_resolves(
    completed: ScanScope, pending: ScanScope
) -> bool:
    """Whether a successfully completed scope covers an incomplete range.

    A recursive completion enumerates the whole subtree, so it resolves any
    range at or below its path. A non-recursive completion only lists direct
    children, so it resolves an equally non-recursive range at the same path.
    An ancestor is never resolved by a descendant completion.
    """
    if completed.recursive:
        if completed.relative_path == "":
            return True
        return pending.relative_path == completed.relative_path or (
            pending.relative_path.startswith(completed.relative_path + "/")
        )
    return (
        pending.relative_path == completed.relative_path and not pending.recursive
    )


def remove_scan_scopes(
    pending: tuple[ScanScope, ...] | None,
    completed: tuple[ScanScope, ...] | None,
) -> tuple[ScanScope, ...]:
    """Drop pending ranges that a completed scope actually enumerated."""
    if not pending or not completed:
        return pending or ()
    return tuple(
        item
        for item in pending
        if not any(completed_scope_resolves(done, item) for done in completed)
    )


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
