"""Pure watcher-journal and targeted-reconcile contracts."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from app.modules.catalog.domain.model import PathComparison

MAX_PENDING_RECONCILE_INTENTS = 2_000
MAX_RECONCILE_SCOPES = 2
MAX_PRESENCE_FOLD_ROWS = 5_000


class CatalogWatcherError(RuntimeError):
    code = "CATALOG_WATCHER_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class WatcherStale(CatalogWatcherError):
    code = "WATCHER_STALE"


class ReconcileNotFound(CatalogWatcherError):
    code = "RECONCILE_NOT_FOUND"


class ReconcileConflict(CatalogWatcherError):
    code = "RECONCILE_CONFLICT"


class ReconcileLeaseLost(CatalogWatcherError):
    code = "RECONCILE_LEASE_LOST"


class ReconcileStale(CatalogWatcherError):
    code = "RECONCILE_STALE"


class ReconcileRootIdentityChanged(CatalogWatcherError):
    code = "RECONCILE_ROOT_IDENTITY_CHANGED"


def _relative_path(value: tuple[str, ...], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    for component in value:
        if not isinstance(component, str):
            raise TypeError(f"{field_name} components must be strings")
        if (
            not component
            or component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError(f"{field_name} contains an invalid component")
        try:
            component.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError(f"{field_name} components must be strict UTF-8") from error


def _identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


class WatcherPathEventKind(StrEnum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"


class WatcherEntryHint(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    UNKNOWN = "UNKNOWN"


class WatcherMovedEntryType(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class WatcherTrustLostReason(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    BACKEND_OVERFLOW = "BACKEND_OVERFLOW"
    UNTRUSTED = "UNTRUSTED"
    ROOT_BINDING_LOST = "ROOT_BINDING_LOST"


class FullRescanReason(StrEnum):
    JOURNAL_CAPACITY = "JOURNAL_CAPACITY"
    COLLISION_RECHECK = "COLLISION_RECHECK"
    DISCONNECTED = "DISCONNECTED"
    BACKEND_OVERFLOW = "BACKEND_OVERFLOW"
    UNTRUSTED = "UNTRUSTED"
    ROOT_CHANGED = "ROOT_CHANGED"


@dataclass(frozen=True, slots=True)
class WatcherPathEvent:
    kind: WatcherPathEventKind
    relative_path: tuple[str, ...]
    entry_hint: WatcherEntryHint

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WatcherPathEventKind):
            raise TypeError("kind must be a WatcherPathEventKind")
        _relative_path(self.relative_path, "relative_path")
        if not isinstance(self.entry_hint, WatcherEntryHint):
            raise TypeError("entry_hint must be a WatcherEntryHint")


@dataclass(frozen=True, slots=True)
class WatcherMoveEvent:
    source_path: tuple[str, ...]
    destination_path: tuple[str, ...]
    entry_type: WatcherMovedEntryType

    def __post_init__(self) -> None:
        _relative_path(self.source_path, "source_path")
        _relative_path(self.destination_path, "destination_path")
        if self.source_path == self.destination_path:
            raise ValueError("a move must change the preserved path")
        if not isinstance(self.entry_type, WatcherMovedEntryType):
            raise TypeError("entry_type must be a WatcherMovedEntryType")


@dataclass(frozen=True, slots=True)
class WatcherTrustLost:
    reason: WatcherTrustLostReason

    def __post_init__(self) -> None:
        if not isinstance(self.reason, WatcherTrustLostReason):
            raise TypeError("reason must be a WatcherTrustLostReason")


WatcherEvent: TypeAlias = WatcherPathEvent | WatcherMoveEvent | WatcherTrustLost


@dataclass(frozen=True, slots=True)
class ReconcileScope:
    """One preserved top-level scope and its comparison-normalized key."""

    relative_path: tuple[str, ...]
    comparison_key: str

    def __post_init__(self) -> None:
        _relative_path(self.relative_path, "relative_path")
        if len(self.relative_path) != 1:
            raise ValueError("a reconcile scope must be one top-level component")
        _identifier(self.comparison_key, "comparison_key")


@dataclass(frozen=True, slots=True)
class ReconcileMoveEvidence:
    """Exact raw watcher move pair retained independently from queue scopes."""

    source_path: tuple[str, ...]
    destination_path: tuple[str, ...]
    entry_type: WatcherMovedEntryType

    def __post_init__(self) -> None:
        _relative_path(self.source_path, "source_path")
        _relative_path(self.destination_path, "destination_path")
        if self.source_path == self.destination_path:
            raise ValueError("move evidence must change the preserved path")
        if not isinstance(self.entry_type, WatcherMovedEntryType):
            raise TypeError("entry_type must be a WatcherMovedEntryType")


def reconcile_scope(
    relative_path: tuple[str, ...], path_comparison: PathComparison
) -> ReconcileScope:
    """Return the top-level raw scope without using it as public identity."""

    _relative_path(relative_path, "relative_path")
    if not isinstance(path_comparison, PathComparison):
        raise TypeError("path_comparison must be a PathComparison")
    raw_scope = relative_path[:1]
    normalized = unicodedata.normalize("NFC", raw_scope[0])
    if path_comparison is PathComparison.INSENSITIVE:
        normalized = normalized.casefold()
    encoded = normalized.encode("utf-8")
    return ReconcileScope(
        relative_path=raw_scope,
        comparison_key=f"{len(encoded)}:{encoded.hex()}",
    )


def event_reconcile_scopes(
    event: WatcherPathEvent | WatcherMoveEvent,
    path_comparison: PathComparison,
) -> tuple[ReconcileScope, ...]:
    """Derive one or two raw top-level scopes for a trusted path event."""

    paths = (
        (event.relative_path,)
        if isinstance(event, WatcherPathEvent)
        else (event.source_path, event.destination_path)
    )
    scopes: list[ReconcileScope] = []
    for path in paths:
        scope = reconcile_scope(path, path_comparison)
        if scope not in scopes:
            scopes.append(scope)
    if not 1 <= len(scopes) <= MAX_RECONCILE_SCOPES:
        raise ValueError("a watcher event must affect one or two scopes")
    return tuple(scopes)


def merge_reconcile_scopes(
    existing: tuple[tuple[ReconcileScope, ...], ...],
    incoming: tuple[ReconcileScope, ...],
) -> tuple[ReconcileScope, ...] | None:
    """Merge raw scopes; ``None`` means a constant-size full scan is required."""

    groups = (*existing, incoming)
    if any(
        not isinstance(group, tuple)
        or not group
        or any(not isinstance(scope, ReconcileScope) for scope in group)
        for group in groups
    ):
        raise TypeError("scope groups must contain ReconcileScope values")
    merged: list[ReconcileScope] = []
    for group in groups:
        for scope in group:
            if scope not in merged:
                merged.append(scope)
                if len(merged) > MAX_RECONCILE_SCOPES:
                    return None
    return tuple(merged)


def full_rescan_reason(reason: WatcherTrustLostReason) -> FullRescanReason:
    if not isinstance(reason, WatcherTrustLostReason):
        raise TypeError("reason must be a WatcherTrustLostReason")
    return {
        WatcherTrustLostReason.DISCONNECTED: FullRescanReason.DISCONNECTED,
        WatcherTrustLostReason.BACKEND_OVERFLOW: FullRescanReason.BACKEND_OVERFLOW,
        WatcherTrustLostReason.UNTRUSTED: FullRescanReason.UNTRUSTED,
        WatcherTrustLostReason.ROOT_BINDING_LOST: FullRescanReason.ROOT_CHANGED,
    }[reason]


__all__ = [
    "MAX_PENDING_RECONCILE_INTENTS",
    "MAX_PRESENCE_FOLD_ROWS",
    "MAX_RECONCILE_SCOPES",
    "CatalogWatcherError",
    "FullRescanReason",
    "ReconcileConflict",
    "ReconcileLeaseLost",
    "ReconcileMoveEvidence",
    "ReconcileNotFound",
    "ReconcileRootIdentityChanged",
    "ReconcileScope",
    "ReconcileStale",
    "WatcherEntryHint",
    "WatcherEvent",
    "WatcherMoveEvent",
    "WatcherMovedEntryType",
    "WatcherPathEvent",
    "WatcherPathEventKind",
    "WatcherStale",
    "WatcherTrustLost",
    "WatcherTrustLostReason",
    "event_reconcile_scopes",
    "full_rescan_reason",
    "merge_reconcile_scopes",
    "reconcile_scope",
]
