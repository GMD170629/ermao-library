from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings


def test_api_lifespan_does_not_yield_when_data_migration_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    worker_started = False

    def fail_migration(*unused: object) -> None:
        del unused
        raise RuntimeError("required comic migration failed")

    def observe_worker_start(*unused: object) -> None:
        nonlocal worker_started
        del unused
        worker_started = True

    monkeypatch.setattr(main_module, "bootstrap_database", lambda *unused: None)
    monkeypatch.setattr(
        main_module,
        "run_library_facet_index_data_migration",
        lambda *unused: None,
    )
    monkeypatch.setattr(
        main_module,
        "run_comic_page_index_data_migration",
        fail_migration,
    )
    monkeypatch.setattr(
        main_module,
        "start_download_queue_worker",
        observe_worker_start,
    )

    with pytest.raises(RuntimeError, match="required comic migration failed"):
        with TestClient(main_module.create_app(settings)):
            pass

    assert worker_started is False


def test_api_lifespan_does_not_run_later_migrations_when_facet_migration_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    comic_migration_started = False

    def fail_facet_migration(*unused: object) -> None:
        del unused
        raise RuntimeError("required facet migration failed")

    def observe_comic_migration(*unused: object) -> None:
        nonlocal comic_migration_started
        del unused
        comic_migration_started = True

    monkeypatch.setattr(main_module, "bootstrap_database", lambda *unused: None)
    monkeypatch.setattr(
        main_module,
        "run_library_facet_index_data_migration",
        fail_facet_migration,
    )
    monkeypatch.setattr(
        main_module,
        "run_comic_page_index_data_migration",
        observe_comic_migration,
    )

    with pytest.raises(RuntimeError, match="required facet migration failed"):
        with TestClient(main_module.create_app(settings)):
            pass

    assert comic_migration_started is False
