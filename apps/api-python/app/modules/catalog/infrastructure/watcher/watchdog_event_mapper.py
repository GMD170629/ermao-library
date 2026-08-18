"""Map Watchdog notifications into path-safe, root-relative domain events."""

from __future__ import annotations

import os
from typing import TypeAlias

from watchdog.events import (
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    DirMovedEvent,
    FileMovedEvent,
    FileSystemEvent,
)

from app.modules.catalog.domain.watcher import (
    WatcherEntryHint,
    WatcherEvent,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherTrustLost,
    WatcherTrustLostReason,
)


class _InvalidEventPath(ValueError):
    pass


class _OutsideRoot:
    pass


_OUTSIDE_ROOT = _OutsideRoot()
_MappedPath: TypeAlias = tuple[str, ...] | _OutsideRoot


def _strict_host_path(value: bytes | str) -> str:
    if isinstance(value, bytes):
        try:
            decoded = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise _InvalidEventPath from error
    elif isinstance(value, str):
        decoded = value
        try:
            decoded.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise _InvalidEventPath from error
    else:
        raise _InvalidEventPath
    if not decoded or "\x00" in decoded or not os.path.isabs(decoded):
        raise _InvalidEventPath
    if os.path.normpath(decoded) != decoded:
        raise _InvalidEventPath
    return decoded


def _valid_component(component: str) -> bool:
    return bool(component) and not (
        component in {".", ".."}
        or "/" in component
        or "\\" in component
        or "\x00" in component
    )


class LocalWatchdogEventMapper:
    """Pure lexical mapper; observer lifecycle and durability stay elsewhere."""

    def __init__(self, canonical_root: str) -> None:
        try:
            root = _strict_host_path(canonical_root)
        except _InvalidEventPath as error:
            raise ValueError(
                "canonical_root must be an absolute normalized host path"
            ) from error
        self._canonical_root = root
        self._comparison_root = os.path.normcase(root)

    def map(self, event: object) -> WatcherEvent | None:
        """Return one trusted event, a trust-loss signal, or an ignored duplicate."""

        if (
            not isinstance(event, FileSystemEvent)
            or not isinstance(event.event_type, str)
            or not isinstance(event.is_directory, bool)
            or not isinstance(event.is_synthetic, bool)
        ):
            return self._untrusted()
        if event.is_synthetic:
            return self._map_synthetic(event)
        try:
            if event.event_type == EVENT_TYPE_MOVED:
                return self._map_move(event)
            kind = {
                EVENT_TYPE_CREATED: WatcherPathEventKind.CREATE,
                EVENT_TYPE_MODIFIED: WatcherPathEventKind.MODIFY,
                EVENT_TYPE_DELETED: WatcherPathEventKind.DELETE,
            }.get(event.event_type)
            if kind is None:
                return self._untrusted()
            mapped_path = self._relative_path(event.src_path)
        except _InvalidEventPath:
            return self._untrusted()
        if isinstance(mapped_path, _OutsideRoot):
            return self._untrusted()
        if not mapped_path:
            return self._map_root_event(kind, is_directory=event.is_directory)
        return WatcherPathEvent(
            kind=kind,
            relative_path=mapped_path,
            entry_hint=self._entry_hint(event.is_directory),
        )

    def _map_synthetic(self, event: FileSystemEvent) -> WatcherEvent | None:
        if not isinstance(event, (FileMovedEvent, DirMovedEvent)):
            return self._untrusted()
        try:
            source = self._relative_path(event.src_path)
            destination = self._relative_path(event.dest_path)
        except _InvalidEventPath:
            return self._untrusted()
        source_outside = isinstance(source, _OutsideRoot)
        destination_outside = isinstance(destination, _OutsideRoot)
        if source_outside and destination_outside:
            return self._untrusted()
        if (not source_outside and not source) or (
            not destination_outside and not destination
        ):
            return self._untrusted()
        # Watchdog expands a trusted parent directory move into synthetic child
        # moves. The PR11 runtime must preserve that parent-first ordering; a
        # backend that cannot do so reports UNTRUSTED instead of using this mapper.
        return None

    def _map_move(self, event: FileSystemEvent) -> WatcherEvent:
        try:
            source = self._relative_path(event.src_path)
            destination = self._relative_path(event.dest_path)
        except _InvalidEventPath:
            return self._untrusted()
        source_outside = isinstance(source, _OutsideRoot)
        destination_outside = isinstance(destination, _OutsideRoot)
        if (not source_outside and not source) or (
            not destination_outside and not destination
        ):
            return WatcherTrustLost(WatcherTrustLostReason.ROOT_BINDING_LOST)
        if source_outside and destination_outside:
            return self._untrusted()
        if source_outside:
            assert isinstance(destination, tuple)
            return WatcherPathEvent(
                kind=WatcherPathEventKind.CREATE,
                relative_path=destination,
                entry_hint=self._entry_hint(event.is_directory),
            )
        if destination_outside:
            assert isinstance(source, tuple)
            return WatcherPathEvent(
                kind=WatcherPathEventKind.DELETE,
                relative_path=source,
                entry_hint=self._entry_hint(event.is_directory),
            )
        assert isinstance(source, tuple)
        assert isinstance(destination, tuple)
        if source == destination:
            return self._untrusted()
        return WatcherMoveEvent(
            source_path=source,
            destination_path=destination,
            entry_type=(
                WatcherMovedEntryType.DIRECTORY
                if event.is_directory
                else WatcherMovedEntryType.FILE
            ),
        )

    def _relative_path(self, value: bytes | str) -> _MappedPath:
        event_path = _strict_host_path(value)
        try:
            common_path = os.path.commonpath((self._canonical_root, event_path))
        except ValueError:
            return _OUTSIDE_ROOT
        if os.path.normcase(common_path) != self._comparison_root:
            return _OUTSIDE_ROOT
        relative = os.path.relpath(event_path, self._canonical_root)
        if relative == os.curdir:
            return ()
        components = tuple(relative.split(os.sep))
        if any(not _valid_component(component) for component in components):
            raise _InvalidEventPath
        return components

    @staticmethod
    def _map_root_event(
        kind: WatcherPathEventKind, *, is_directory: bool
    ) -> WatcherEvent | None:
        if kind is WatcherPathEventKind.MODIFY and is_directory:
            return None
        if kind is WatcherPathEventKind.DELETE:
            return WatcherTrustLost(WatcherTrustLostReason.ROOT_BINDING_LOST)
        return WatcherTrustLost(WatcherTrustLostReason.UNTRUSTED)

    @staticmethod
    def _entry_hint(is_directory: bool) -> WatcherEntryHint:
        return WatcherEntryHint.DIRECTORY if is_directory else WatcherEntryHint.FILE

    @staticmethod
    def _untrusted() -> WatcherTrustLost:
        return WatcherTrustLost(WatcherTrustLostReason.UNTRUSTED)


__all__ = ["LocalWatchdogEventMapper"]
