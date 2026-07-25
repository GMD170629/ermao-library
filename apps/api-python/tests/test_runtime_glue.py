from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from appv2.composition.adapters import ApplicationQueueOverview
from appv2.entrypoints import migrate as migrate_entrypoint
from appv2.entrypoints import restore as restore_entrypoint
from appv2.entrypoints import worker as worker_entrypoint
from appv2.platform.config import get_settings
from appv2.platform.database.locks import advisory_lock, hold_advisory_lock
from appv2.platform.database.migrations import migrate
from appv2.platform.database.uow import SqlAlchemyUnitOfWork
from appv2.platform.observability import configure_logging


def scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def queue_uow(repository_name: str, counts: dict[str, int]) -> MagicMock:
    unit = MagicMock()
    unit.__enter__.return_value = unit
    repository = MagicMock()
    repository.queue_counts.return_value = counts
    setattr(unit, repository_name, repository)
    return unit


def test_application_queue_overview_is_the_only_cross_module_aggregator() -> None:
    ingestion = queue_uow("ingestion", {"queued": 2})
    metadata = queue_uow("metadata", {"failed": 1})
    discovery = queue_uow("discovery", {})
    delivery = queue_uow("delivery", {"running": 1})
    operations = MagicMock()
    operations.__enter__.return_value = operations
    operations.operations.list_backups.return_value = [
        SimpleNamespace(status="ready"),
        SimpleNamespace(status="ready"),
        SimpleNamespace(status="queued"),
    ]
    overview = ApplicationQueueOverview(
        ingestion_uow=lambda: ingestion,
        metadata_uow=lambda: metadata,
        discovery_uow=lambda: discovery,
        delivery_uow=lambda: delivery,
        operations_uow=lambda: operations,
    )

    snapshots = overview.snapshots()

    assert [value.name for value in snapshots] == [
        "ingestion",
        "metadata",
        "discovery",
        "delivery",
        "backups",
    ]
    assert snapshots[-1].counts == {"ready": 2, "queued": 1}


def test_advisory_lock_acquired_released_and_rejected() -> None:
    connection = MagicMock()
    connection.execute.side_effect = [scalar_result(True), scalar_result(True)]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    with advisory_lock(engine, 42) as acquired:
        assert acquired is True
    assert connection.execute.call_count == 2

    connection.reset_mock()
    connection.execute.side_effect = None
    connection.execute.return_value = scalar_result(False)
    with advisory_lock(engine, 42) as acquired:
        assert acquired is False
    assert connection.execute.call_count == 1
    connection.execute.return_value = scalar_result(True)
    assert hold_advisory_lock(connection, 42) is True


def test_database_migration_requires_postgresql_18_and_upgrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    create_engine = MagicMock(return_value=engine)
    upgrade = MagicMock()
    monkeypatch.setattr(
        "appv2.platform.database.migrations.create_engine",
        create_engine,
    )
    monkeypatch.setattr(
        "appv2.platform.database.migrations.command.upgrade",
        upgrade,
    )
    connection.execute.return_value = scalar_result("18.4")
    migrate("postgresql+psycopg://app@postgres/app", tmp_path)
    upgrade.assert_called_once()
    engine.dispose.assert_called_once()

    connection.execute.return_value = scalar_result("17.9")
    with pytest.raises(RuntimeError, match="PostgreSQL 18"):
        migrate("postgresql+psycopg://app@postgres/app", tmp_path)
    assert engine.dispose.call_count == 2


def test_sqlalchemy_unit_of_work_commit_rollback_and_context_paths() -> None:
    session = MagicMock()
    factory = MagicMock(return_value=session)
    unit = SqlAlchemyUnitOfWork(factory)
    with unit:
        unit.commit()
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_called_once()

    session.reset_mock()
    with SqlAlchemyUnitOfWork(factory):
        pass
    session.rollback.assert_called_once()
    session.reset_mock()
    with pytest.raises(ValueError), SqlAlchemyUnitOfWork(factory):
        raise ValueError("rollback")
    session.rollback.assert_called_once()

    empty = SqlAlchemyUnitOfWork(factory)
    with pytest.raises(RuntimeError):
        empty.commit()
    with pytest.raises(RuntimeError):
        empty.rollback()
    entered = SqlAlchemyUnitOfWork(factory)
    entered.__enter__()
    entered.rollback()
    session.rollback.assert_called()
    entered.__exit__(None, None, None)


def test_entrypoints_delegate_and_always_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = MagicMock()
    monkeypatch.setattr(migrate_entrypoint, "migrate_database", migration)
    settings = SimpleNamespace(database_dsn="postgresql://app@postgres/app")
    monkeypatch.setattr(migrate_entrypoint, "get_settings", lambda: settings)
    migrate_entrypoint.migrate()
    migration.assert_called_once()
    migrate_entrypoint.main()
    assert migration.call_count == 2

    container = MagicMock()
    monkeypatch.setattr(restore_entrypoint, "configure_logging", MagicMock())
    monkeypatch.setattr(restore_entrypoint, "build_container", lambda: container)
    restore_entrypoint.main()
    container.restore_service.run_once.assert_called_once()
    container.close.assert_called_once()

    configure_logging()
    monkeypatch.setenv("LOG_LEVEL", "not-a-real-level")
    configure_logging()

    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    api_module = importlib.import_module("appv2.entrypoints.api")
    assert api_module.app.version == "0.4.0"
    api_module.app.state.container.close()
    get_settings.cache_clear()


def test_worker_entrypoint_lock_contention_and_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = MagicMock()
    container.settings.worker_lock_id = 42
    container.settings.worker_poll_seconds = 0.01
    monkeypatch.setattr(worker_entrypoint, "configure_logging", MagicMock())
    monkeypatch.setattr(worker_entrypoint, "build_container", lambda: container)

    @contextmanager
    def rejected_lock(*_args: object, **_kwargs: object):
        yield False

    monkeypatch.setattr(worker_entrypoint, "advisory_lock", rejected_lock)
    with pytest.raises(RuntimeError, match="another appv2 scheduler"):
        worker_entrypoint.main()
    container.close.assert_called_once()

    container.reset_mock()

    @contextmanager
    def acquired_lock(*_args: object, **_kwargs: object):
        yield True

    runtime = MagicMock()
    runtime.run_once.side_effect = [False, KeyboardInterrupt]
    monkeypatch.setattr(worker_entrypoint, "advisory_lock", acquired_lock)
    monkeypatch.setattr(worker_entrypoint, "WorkerRuntime", lambda **_kwargs: runtime)
    sleep = MagicMock()
    monkeypatch.setattr(worker_entrypoint.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        worker_entrypoint.main()
    sleep.assert_called_once_with(0.01)
    container.close.assert_called_once()
