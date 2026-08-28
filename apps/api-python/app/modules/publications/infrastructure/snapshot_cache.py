"""Bounded parser snapshots owned and closed by the publication runtime."""

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import RLock
from time import monotonic
from typing import Generic, TypeVar

from app.modules.publications.domain.model import PublicationOnlineLimitError

SnapshotKey = tuple[str, int, int] | tuple[str, int, int, str, str | None]
V = TypeVar("V")


class PublicationSnapshotCache(Generic[V]):
    def __init__(
        self,
        *,
        maximum_entries: int = 8,
        maximum_weight: int = 128 * 1024 * 1024,
        dispose: Callable[[V], None] = lambda _value: None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if maximum_entries < 1 or maximum_weight < 1:
            raise ValueError("Publication cache limits must be positive")
        self._entries: OrderedDict[SnapshotKey, tuple[V, int, float]] = OrderedDict()
        self._lock = RLock()
        self._maximum_entries = maximum_entries
        self._maximum_weight = maximum_weight
        self._dispose = dispose
        self._clock = clock

    @contextmanager
    def lease(
        self, key: SnapshotKey, load: Callable[[], V], weight: int
    ) -> Iterator[V]:
        # A lease protects native parser pointers from concurrent eviction/close.
        # Loading under this lock also coalesces simultaneous cold opens.
        if weight < 1:
            raise ValueError("Publication snapshot weight must be positive")
        if weight > self._maximum_weight:
            raise PublicationOnlineLimitError(
                "Publication parser memory limit exceeded"
            )
        with self._lock:
            now = self._clock()
            for expired in [
                candidate
                for candidate, (_, _, used) in self._entries.items()
                if now - used > 300 or (candidate[0] == key[0] and candidate != key)
            ]:
                self._dispose(self._entries.pop(expired)[0])
            existing = self._entries.pop(key, None)
            # Reserve capacity before parsing, not after allocating another snapshot.
            while self._entries and (
                len(self._entries) >= self._maximum_entries
                or sum(entry[1] for entry in self._entries.values()) + weight
                > self._maximum_weight
            ):
                _, evicted = self._entries.popitem(last=False)
                self._dispose(evicted[0])
            value = existing[0] if existing else load()
            self._entries[key] = (value, weight, now)
            yield value

    def get(self, key: SnapshotKey, load: Callable[[], V], weight: int) -> V:
        """For immutable Python snapshots without native resources only."""
        with self.lease(key, load, weight) as value:
            return value

    def close(self) -> None:
        with self._lock:
            for value, _, _ in self._entries.values():
                self._dispose(value)
            self._entries.clear()
