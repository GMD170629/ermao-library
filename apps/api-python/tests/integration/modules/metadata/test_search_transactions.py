from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import select, update
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
    blocker_engine = create_sqlite_engine(database_path)
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

    def successful_provider(*_args, **_kwargs):
        network_observations.append(source.in_transaction())
        return {
            "provider": "douban",
            "enabled": True,
            "cacheHit": False,
            "candidates": [{"title": "Prepared result"}],
        }

    monkeypatch.setattr(
        "app.services.organize_service.run_douban_metadata_provider", successful_provider
    )
    blocker = Session(blocker_engine)
    try:
        blocker.execute(
            update(ExternalMetadataCache)
            .where(ExternalMetadataCache.id == "cache-lock-row")
            .values(raw_json='{"candidates": [{"title": "locked"}]}')
        )
        started = monotonic()
        result = metadata_search_candidates(source, context, "douban", config={})
        elapsed = monotonic() - started

        assert result["candidates"][0]["title"] == "Prepared result"
        assert network_observations == [False]
        assert elapsed < 1.0
        with Session(source_engine) as verify:
            assert (
                verify.scalar(
                    select(ExternalMetadataCache.id).where(
                        ExternalMetadataCache.query_key == "shorttransactionsearch"
                    )
                )
                is None
            )
    finally:
        blocker.rollback()
        blocker.close()
        source.close()

    with Session(source_engine) as retry:
        metadata_search_candidates(retry, context, "douban", config={})
    with Session(source_engine) as verify:
        assert verify.scalar(
            select(ExternalMetadataCache.id).where(
                ExternalMetadataCache.query_key == "shorttransactionsearch"
            )
        )

    source_engine.dispose()
    blocker_engine.dispose()
