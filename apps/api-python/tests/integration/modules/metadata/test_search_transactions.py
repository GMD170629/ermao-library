from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Timer
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models.library import ExternalMetadataCache
from app.services.organize_service import metadata_search_candidates


def test_metadata_search_closes_reads_and_defers_busy_cache_write(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "metadata-search.sqlite"
    source_engine = create_sqlite_engine(database_path)
    Base.metadata.create_all(source_engine)
    seeded_at = datetime.now(UTC)
    with Session(source_engine) as seed, seed.begin():
        seed.add(
            ExternalMetadataCache(
                id="cache-lock-row",
                provider="douban",
                query_key="lock-row",
                raw_json='{"candidates": [{"title": "seed"}]}',
                expires_at=seeded_at + timedelta(days=1),
                created_at=seeded_at,
                updated_at=seeded_at,
            )
        )

    context = {
        "book": {"title": "Short transaction search"},
        "resources": [{"format": "EPUB"}],
        "assets": [],
        "metadata": [],
    }
    source = Session(source_engine, autoflush=False, expire_on_commit=False)
    network_observations: list[bool] = []
    lock_acquired = Event()
    release_lock = Event()
    timer = Timer(0.7, release_lock.set)
    timer_started = False

    def successful_provider(*_args, **_kwargs):
        nonlocal timer_started
        network_observations.append(source.in_transaction())
        timer.start()
        timer_started = True
        return {
            "provider": "douban",
            "enabled": True,
            "cacheHit": False,
            "candidates": [{"title": "Prepared result"}],
        }

    monkeypatch.setattr(
        "app.services.organize_service.run_douban_metadata_provider", successful_provider
    )
    def hold_write_lock() -> None:
        with sqlite3.connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                'UPDATE "ExternalMetadataCache" SET "rawJson" = ? WHERE id = ?',
                ('{"candidates": [{"title": "locked"}]}', "cache-lock-row"),
            )
            lock_acquired.set()
            if not release_lock.wait(timeout=10):
                raise TimeoutError("test writer lock was not released")
            connection.rollback()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            blocker = pool.submit(hold_write_lock)
            assert lock_acquired.wait(timeout=5)
            try:
                started = monotonic()
                result = metadata_search_candidates(source, context, "douban", config={})
                elapsed = monotonic() - started
            finally:
                release_lock.set()
                if timer_started:
                    timer.join()
            blocker.result(timeout=5)

        assert result["candidates"][0]["title"] == "Prepared result"
        assert network_observations == [False]
        assert elapsed >= 0.5
        with Session(source_engine) as verify:
            assert verify.scalar(
                select(ExternalMetadataCache.id).where(
                    ExternalMetadataCache.query_key == "shorttransactionsearch"
                )
            ) is not None
    finally:
        release_lock.set()
        source.close()

    source_engine.dispose()
