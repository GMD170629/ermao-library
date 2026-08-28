from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.modules.publications.domain.model import PublicationResourceTooLargeError
from app.modules.publications.infrastructure.snapshot_cache import (
    PublicationSnapshotCache,
    SnapshotKey,
)


def key(name: str, version: int = 1) -> SnapshotKey:
    return (name, 10, version, "Book", None)


def test_concurrent_cold_opens_share_one_parse_and_release_on_close() -> None:
    parsed: list[object] = []
    released: list[object] = []
    cache: PublicationSnapshotCache[object] = PublicationSnapshotCache(
        dispose=released.append
    )
    ready = Barrier(4)

    def parse() -> object:
        publication = object()
        parsed.append(publication)
        return publication

    def read(_: int) -> object:
        ready.wait()
        with cache.lease(key("book"), parse, 10) as publication:
            return publication

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(read, range(4)))
    assert len(parsed) == 1
    assert all(result is parsed[0] for result in results)
    cache.close()
    cache.close()
    assert released == parsed


def test_versions_capacity_and_expiration_release_owned_snapshots() -> None:
    clock = [0.0]
    released: list[str] = []
    cache: PublicationSnapshotCache[str] = PublicationSnapshotCache(
        maximum_entries=2,
        maximum_weight=20,
        dispose=released.append,
        clock=lambda: clock[0],
    )
    assert cache.get(key("a"), lambda: "a1", 10) == "a1"
    assert cache.get(key("a", 2), lambda: "a2", 10) == "a2"
    assert released == ["a1"]
    cache.get(key("b"), lambda: "b", 10)
    cache.get(key("c"), lambda: "c", 10)
    assert released == ["a1", "a2"]
    clock[0] = 301
    cache.get(key("d"), lambda: "d", 10)
    assert released == ["a1", "a2", "b", "c"]
    cache.close()
    assert released[-1] == "d"


def test_oversized_parser_budget_fails_before_loading_and_never_reparses() -> None:
    cache: PublicationSnapshotCache[str] = PublicationSnapshotCache(maximum_weight=10)

    def parse() -> str:
        pytest.fail("An over-budget parse must not start")

    for _ in range(3):
        with pytest.raises(PublicationResourceTooLargeError):
            cache.get(key("large"), parse, 11)


def test_failed_parse_can_be_retried_without_publishing_partial_state() -> None:
    cache: PublicationSnapshotCache[str] = PublicationSnapshotCache()

    def parse() -> str:
        raise OSError("parser failed")

    with pytest.raises(OSError, match="parser failed"):
        cache.get(key("book"), parse, 1)
    assert cache.get(key("book"), lambda: "parsed", 1) == "parsed"
