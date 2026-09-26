from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models.library import ExternalMetadataCache
from app.modules.metadata.application.queries import candidate_cache_key
from app.services.organize_service import metadata_search_candidates


def test_metadata_search_closes_reads_and_defers_busy_cache_write(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "metadata-search.sqlite"
    source_engine = create_sqlite_engine(database_path)
    blocker_engine = create_sqlite_engine(database_path)
    Base.metadata.create_all(source_engine)
    seeded_at = datetime.now(UTC)
    with Session(source_engine) as seed, seed.begin():
        seed.add(
            ExternalMetadataCache(
                id="cache-lock-row",
                provider="ai",
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

    def successful_ai(*_args, **_kwargs):
        network_observations.append(source.in_transaction())
        return {
            "provider": "ai",
            "enabled": True,
            "cacheHit": False,
            "suggestions": [
                {
                    "field": "title",
                    "suggestedValue": "Prepared result",
                    "confidence": 0.9,
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.organize_service.run_ai_metadata_provider", successful_ai
    )
    blocker = Session(blocker_engine)
    try:
        blocker.execute(
            update(ExternalMetadataCache)
            .where(ExternalMetadataCache.id == "cache-lock-row")
            .values(raw_json='{"candidates": [{"title": "locked"}]}')
        )
        started = monotonic()
        result = metadata_search_candidates(source, context, "ai", config={})
        elapsed = monotonic() - started

        assert result["candidates"][0]["title"] == "Prepared result"
        assert network_observations == [False]
        assert elapsed < 1.0
        with Session(source_engine) as verify:
            assert (
                verify.scalar(
                    select(ExternalMetadataCache.id).where(
                            ExternalMetadataCache.query_key == candidate_cache_key(context, "ai", "Short transaction search", {})
                    )
                )
                is None
            )
    finally:
        blocker.rollback()
        blocker.close()
        source.close()

    with Session(source_engine) as retry:
        metadata_search_candidates(retry, context, "ai", config={})
    with Session(source_engine) as verify:
        assert verify.scalar(
            select(ExternalMetadataCache.id).where(
                ExternalMetadataCache.query_key == candidate_cache_key(context, "ai", "Short transaction search", {})
            )
        )

    source_engine.dispose()
    blocker_engine.dispose()


def test_shared_rate_reservation_is_atomic_across_processes(tmp_path):
    path = tmp_path / "shared-rate.sqlite"
    engine = create_sqlite_engine(path)
    Base.metadata.create_all(engine)
    script = """
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from app.db.sqlite import create_sqlite_engine
from app.modules.metadata.infrastructure.external_cache import reserve_request_slot
with Session(create_sqlite_engine(Path(sys.argv[1]))) as db:
    slot = reserve_request_slot(db, 'douban', 5.0)
    assert not db.in_transaction()
    print(slot)
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    slots = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        slots.append(float(stdout.strip()))
    assert abs(slots[0] - slots[1]) >= 4.99
    engine.dispose()


def test_successful_empty_result_is_cached_but_errors_are_not(db_session, monkeypatch):
    calls = []
    def empty(*args, **kwargs):
        calls.append(1)
        return {"enabled": True, "candidates": [], "suggestions": []}
    monkeypatch.setattr("app.services.organize_service.run_douban_metadata_provider", empty)
    context = {"book": {"title": "No result"}}
    metadata_search_candidates(db_session, context, "douban", config={})
    assert metadata_search_candidates(db_session, context, "douban", config={})["cacheHit"]
    assert len(calls) == 1
    from app.services.organize_service import external_metadata_result_cacheable
    assert not external_metadata_result_cacheable({"enabled": True, "candidates": [], "error": "HTTP_429"})
