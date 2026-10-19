"""Parser snapshots with bounded retention and explicit runtime ownership."""

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Generic, TypeVar

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    reader_safety_budget,
)

SnapshotKey = tuple[str, int, int] | tuple[str, int, int, str, str | None]
V = TypeVar("V")


def publication_snapshot_weight(source_bytes: int) -> int:
    """Estimate retention weight; this never controls parser admission."""
    return max(
        1,
        source_bytes
        * reader_safety_budget(
            ReaderSafetyBudgetName.PARSER_SNAPSHOT_SOURCE_WEIGHT_MULTIPLIER
        ),
    )


@dataclass
class _ActiveSnapshot(Generic[V]):
    value: V
    weight: int
    leases: int = 0
    retain: bool = True


class PublicationSnapshotCache(Generic[V]):
    def __init__(
        self,
        *,
        maximum_entries: int = 8,
        maximum_weight: int = reader_safety_budget(
            ReaderSafetyBudgetName.PARSER_SNAPSHOT_MEMORY_MAX_BYTES
        ),
        dispose: Callable[[V], None] = lambda _value: None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if maximum_entries < 1 or maximum_weight < 1:
            raise ValueError("Publication cache limits must be positive")
        self._entries: OrderedDict[SnapshotKey, tuple[V, int, float]] = OrderedDict()
        self._active: dict[SnapshotKey, _ActiveSnapshot[V]] = {}
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
        with self._lock:
            now = self._clock()
            for expired in [
                candidate
                for candidate, (_, _, used) in self._entries.items()
                if now - used > 300 or (candidate[0] == key[0] and candidate != key)
            ]:
                self._dispose(self._entries.pop(expired)[0])
            for candidate, snapshot in self._active.items():
                if candidate[0] == key[0] and candidate != key:
                    snapshot.retain = False
            active = self._active.get(key)
            if active is None:
                existing = self._entries.pop(key, None)
                active = _ActiveSnapshot(
                    value=existing[0] if existing else load(),
                    weight=weight,
                    retain=weight <= self._maximum_weight,
                )
                self._active[key] = active
            active.leases += 1
            try:
                yield active.value
            finally:
                active.leases -= 1
                if active.leases == 0:
                    del self._active[key]
                    if active.retain:
                        while self._entries and (
                            len(self._entries) >= self._maximum_entries
                            or sum(entry[1] for entry in self._entries.values())
                            + active.weight > self._maximum_weight
                        ):
                            _, evicted = self._entries.popitem(last=False)
                            self._dispose(evicted[0])
                        self._entries[key] = (active.value, active.weight, self._clock())
                    else:
                        self._dispose(active.value)

    def get(self, key: SnapshotKey, load: Callable[[], V], weight: int) -> V:
        """For immutable Python snapshots without native resources only."""
        with self.lease(key, load, weight) as value:
            return value

    def close(self) -> None:
        with self._lock:
            for value, _, _ in self._entries.values():
                self._dispose(value)
            self._entries.clear()
            for active in self._active.values():
                active.retain = False
