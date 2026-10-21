from datetime import timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.metadata import maintain_external_metadata_cache
from app.core.auth import utcnow
from app.models.library import ExternalMetadataCache
from app.modules.metadata.application.cache_maintenance import (
    prune_expired_metadata_cache,
)
from app.modules.metadata.infrastructure.external_cache import (
    SqlAlchemyExpiredMetadataCacheStore,
    get_cached_raw_json,
)
from app.services import log_maintenance


def seed(db, count, expiry, prefix="expired"):
    db.add_all([
        ExternalMetadataCache(
            id=f"{prefix}-{i:06d}", provider=f"source-{i % 2}",
            query_key=f"{prefix}-{i}", raw_json='{"candidates":[]}',
            expires_at=expiry,
        )
        for i in range(count)
    ])
    db.commit()


def remaining(db):
    return set(db.scalars(select(ExternalMetadataCache.id)))


def test_expiry_boundary_and_unvisited_entries_are_deleted(db_session):
    now = utcnow()
    seed(db_session, 3, now - timedelta(seconds=1))
    seed(db_session, 1, now, "boundary")
    seed(db_session, 1, now + timedelta(days=1), "valid")
    seed(db_session, 1, None, "permanent")
    assert prune_expired_metadata_cache(
        SqlAlchemyExpiredMetadataCacheStore(db_session),
        unit_of_work=db_session, now=now, cancelled=lambda: False,
    ) == 4
    with Session(db_session.get_bind()) as check:
        assert remaining(check) == {"valid-000000", "permanent-000000"}
        assert get_cached_raw_json(check, provider="source-0", query_key="valid-0")
        assert get_cached_raw_json(check, provider="source-0", query_key="expired-0") is None


def test_batches_commit_and_leave_bounded_backlog(db_session):
    now = utcnow()
    seed(db_session, 1100, now - timedelta(days=1))
    commits = []
    event.listen(db_session, "after_commit", lambda _: commits.append(True))
    assert maintain_external_metadata_cache(db_session, cancelled=lambda: False) == 1024
    assert len(commits) == 8
    with Session(db_session.get_bind()) as check:
        assert len(remaining(check)) == 76
    assert maintain_external_metadata_cache(db_session, cancelled=lambda: False) == 76
    assert not db_session.in_transaction()


def test_cancellation_between_batches_preserves_remaining_rows(db_session):
    seed(db_session, 260, utcnow() - timedelta(days=1))
    cancelled = [False]
    event.listen(db_session, "after_commit", lambda _: cancelled.__setitem__(0, True))
    assert maintain_external_metadata_cache(
        db_session, cancelled=lambda: cancelled[0]
    ) == 128
    with Session(db_session.get_bind()) as check:
        assert len(remaining(check)) == 132


def test_failed_batch_rolls_back_without_losing_committed_batches(db_session, monkeypatch):
    seed(db_session, 260, utcnow() - timedelta(days=1))
    store = SqlAlchemyExpiredMetadataCacheStore(db_session)
    delete = store.delete_expired_batch
    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        count = delete(**kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted batch")
        return count

    monkeypatch.setattr(store, "delete_expired_batch", fail_second)
    with pytest.raises(RuntimeError, match="interrupted batch"):
        prune_expired_metadata_cache(
            store, unit_of_work=db_session, now=utcnow(), cancelled=lambda: False
        )
    assert not db_session.in_transaction()
    with Session(db_session.get_bind()) as check:
        assert len(remaining(check)) == 132
    assert maintain_external_metadata_cache(db_session, cancelled=lambda: False) == 132


def test_concurrent_refresh_is_preserved(db_session):
    now = utcnow()
    seed(db_session, 1, now - timedelta(days=1))
    # A separate writer renews the row before the atomic prune statement.
    with Session(db_session.get_bind()) as writer:
        row = writer.get(ExternalMetadataCache, "expired-000000")
        row.expires_at = now + timedelta(days=1)
        row.raw_json = '{"candidates":["refreshed"]}'
        writer.commit()
    assert prune_expired_metadata_cache(
        SqlAlchemyExpiredMetadataCacheStore(db_session),
        unit_of_work=db_session, now=now, cancelled=lambda: False,
    ) == 0
    with Session(db_session.get_bind()) as check:
        assert get_cached_raw_json(check, provider="source-0", query_key="expired-0") == '{"candidates":["refreshed"]}'


def test_startup_and_daily_maintenance_persist_cleanup(db_session, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(log_maintenance, "monotonic", lambda: clock[0])
    factory = sessionmaker(bind=db_session.get_bind())
    worker = log_maintenance.SystemEventMaintenanceWorker(factory)
    seed(db_session, 2, utcnow() - timedelta(days=1))
    monkeypatch.setattr(worker._stop, "wait", lambda _: True)
    worker._run()
    with factory() as check:
        assert remaining(check) == set()
    seed(db_session, 3, utcnow() - timedelta(days=1))
    for elapsed in (0, 15 * 60, 24 * 60 * 60 - 1):
        clock[0] = 1000.0 + elapsed
        assert worker.run_once()["expiredMetadataCacheDeleted"] == 0
        with factory() as check:
            assert len(remaining(check)) == 3
    clock[0] = 1000.0 + 24 * 60 * 60
    assert worker.run_once()["expiredMetadataCacheDeleted"] == 3
    with factory() as check:
        assert remaining(check) == set()
    assert worker._interval_seconds == 15 * 60


def test_cache_failure_does_not_block_other_maintenance(db_session, monkeypatch, caplog):
    clock = [1000.0]
    monkeypatch.setattr(log_maintenance, "monotonic", lambda: clock[0])
    worker = log_maintenance.SystemEventMaintenanceWorker(
        sessionmaker(bind=db_session.get_bind())
    )
    calls = []
    attempts = []

    def fail(*args, **kwargs):
        attempts.append(clock[0])
        raise RuntimeError("cache cleanup unavailable")

    monkeypatch.setattr(log_maintenance, "maintain_external_metadata_cache", fail)
    monkeypatch.setattr(log_maintenance, "maintain_system_events", lambda db: calls.append("logs") or {"deleted": 0})
    monkeypatch.setattr(log_maintenance, "delete_expired_or_disabled_sessions", lambda *a, **kw: calls.append("sessions") or 0)
    monkeypatch.setattr(worker._stop, "wait", lambda _: True)
    worker._run()
    assert worker._startup_pending == set()
    assert worker.run_once()["expiredMetadataCacheDeleted"] == 0
    assert calls == ["sessions", "logs"]
    clock[0] += 15 * 60
    worker.run_once()
    assert attempts == [1000.0]
    clock[0] = 1000.0 + 24 * 60 * 60
    worker.run_once()
    assert attempts == [1000.0, clock[0]]
    assert calls == ["sessions", "logs"] * 3
    assert "cache cleanup unavailable" in caplog.text
