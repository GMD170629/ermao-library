from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import app.bootstrap.startup_data_migrations as migration_entrypoint
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine


def test_prestart_entrypoint_runs_schema_then_required_data_migrations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    settings = object()
    monkeypatch.setattr(migration_entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(
        migration_entrypoint,
        "bootstrap_database",
        lambda engine, active_settings: calls.append(
            f"schema:{engine is migration_entrypoint.engine}:"
            f"{active_settings is settings}"
        ),
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "run_library_facet_index_data_migration",
        lambda factory: calls.append(
            f"facets:{factory is migration_entrypoint.SessionLocal}"
        ),
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "run_comic_page_index_data_migration",
        lambda factory, active_settings: calls.append(
            f"pages:{factory is migration_entrypoint.SessionLocal}:"
            f"{active_settings is settings}"
        ),
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "verify_startup_data_migrations_complete",
        lambda active_engine, factory: calls.append(
            f"verify:{active_engine is migration_entrypoint.engine}:"
            f"{factory is migration_entrypoint.SessionLocal}"
        ),
    )

    migration_entrypoint.main()

    assert calls == [
        "schema:True:True",
        "facets:True",
        "pages:True:True",
        "verify:True:True",
    ]
    output = capsys.readouterr()
    assert "startup_data_migrations outcome=started" in output.out
    assert "startup_data_migrations outcome=success" in output.out
    assert "outcome=failed" not in output.err


def test_prestart_entrypoint_failure_prevents_later_migrations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    comic_called = False
    monkeypatch.setattr(migration_entrypoint, "get_settings", object)
    monkeypatch.setattr(
        migration_entrypoint,
        "bootstrap_database",
        lambda unused_engine, unused_settings: None,
    )

    def fail_facets(unused_factory: object) -> None:
        raise RuntimeError("facet migration failed")

    def record_comic_call(
        unused_factory: object,
        unused_settings: object,
    ) -> None:
        nonlocal comic_called
        comic_called = True

    monkeypatch.setattr(
        migration_entrypoint,
        "run_library_facet_index_data_migration",
        fail_facets,
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "run_comic_page_index_data_migration",
        record_comic_call,
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "verify_startup_data_migrations_complete",
        lambda unused_engine, unused_factory: None,
    )

    with pytest.raises(RuntimeError, match="facet migration failed"):
        migration_entrypoint.main()

    assert comic_called is False
    output = capsys.readouterr()
    assert "startup_data_migrations outcome=started" in output.out
    assert "startup_data_migrations outcome=failed" in output.err
    assert "outcome=success" not in output.out


def test_prestart_entrypoint_does_not_report_success_when_final_barrier_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(migration_entrypoint, "get_settings", object)
    monkeypatch.setattr(
        migration_entrypoint,
        "bootstrap_database",
        lambda unused_engine, unused_settings: calls.append("schema"),
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "run_library_facet_index_data_migration",
        lambda unused_factory: calls.append("facets"),
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "run_comic_page_index_data_migration",
        lambda unused_factory, unused_settings: calls.append("pages"),
    )

    def fail_final_barrier(
        unused_engine: object,
        unused_factory: object,
    ) -> None:
        calls.append("verify")
        raise RuntimeError("required startup data migration remains pending")

    monkeypatch.setattr(
        migration_entrypoint,
        "verify_startup_data_migrations_complete",
        fail_final_barrier,
    )

    with pytest.raises(RuntimeError, match="remains pending"):
        migration_entrypoint.main()

    assert calls == ["schema", "facets", "pages", "verify"]
    output = capsys.readouterr()
    assert "startup_data_migrations outcome=failed" in output.err
    assert "startup_data_migrations outcome=success" not in output.out


def test_startup_barrier_rejects_database_without_current_schema(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    active_engine = create_sqlite_engine(settings.database_path)
    factory = sessionmaker(bind=active_engine, expire_on_commit=False)

    with pytest.raises(
        migration_entrypoint.StartupDataMigrationBarrierError,
        match="schema",
    ) as raised:
        migration_entrypoint.verify_startup_data_migrations_complete(
            active_engine,
            factory,
        )

    assert raised.value.incomplete_stages == ("schema",)


def test_startup_barrier_rejects_each_pending_data_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    active_engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(active_engine, settings)
    factory = sessionmaker(
        bind=active_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "library_facet_index_data_migration_is_complete",
        lambda unused_factory: False,
    )
    monkeypatch.setattr(
        migration_entrypoint,
        "comic_page_index_data_migration_is_complete",
        lambda unused_factory: False,
    )

    with pytest.raises(
        migration_entrypoint.StartupDataMigrationBarrierError,
        match="library_facet_index, comic_page_index",
    ) as raised:
        migration_entrypoint.verify_startup_data_migrations_complete(
            active_engine,
            factory,
        )

    assert raised.value.incomplete_stages == (
        "library_facet_index",
        "comic_page_index",
    )


def test_startup_barrier_is_read_only_when_every_migration_is_complete(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    active_engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(active_engine, settings)
    factory = sessionmaker(
        bind=active_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    statements: list[str] = []

    def observe_statement(
        unused_connection: object,
        unused_cursor: object,
        statement: str,
        unused_parameters: object,
        unused_context: object,
        unused_executemany: object,
    ) -> None:
        statements.append(statement)

    event.listen(active_engine, "before_cursor_execute", observe_statement)
    try:
        migration_entrypoint.verify_startup_data_migrations_complete(
            active_engine,
            factory,
        )
    finally:
        event.remove(active_engine, "before_cursor_execute", observe_statement)

    assert statements
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )
    output = capsys.readouterr()
    assert "startup_data_migration_barrier outcome=ready" in output.out
