from __future__ import annotations

import pytest

import app.bootstrap.startup_data_migrations as migration_entrypoint


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

    migration_entrypoint.main()

    assert calls == ["schema:True:True", "facets:True", "pages:True:True"]
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

    with pytest.raises(RuntimeError, match="facet migration failed"):
        migration_entrypoint.main()

    assert comic_called is False
    output = capsys.readouterr()
    assert "startup_data_migrations outcome=started" in output.out
    assert "startup_data_migrations outcome=failed" in output.err
    assert "outcome=success" not in output.out
