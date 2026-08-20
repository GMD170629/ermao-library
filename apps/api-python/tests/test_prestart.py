from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, Table

import app.bootstrap.prestart as prestart
from app.core.config import Settings
from app.db.sqlite import create_sqlite_engine


def test_prestart_bootstraps_fresh_schema_and_reports_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    monkeypatch.setattr(prestart, "get_settings", lambda: settings)
    monkeypatch.setattr(prestart, "engine", engine)
    try:
        prestart.main()
        output = capsys.readouterr()
        assert "prestart outcome=started" in output.out
        assert "schema_barrier outcome=ready" in output.out
        assert "prestart outcome=success" in output.out
        assert output.err == ""
    finally:
        engine.dispose()


def test_schema_barrier_rejects_noncurrent_database(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    metadata = MetaData()
    Table("NotCurrent", metadata, Column("id", Integer, primary_key=True))
    try:
        metadata.create_all(engine)
        with pytest.raises(prestart.SchemaBarrierError, match="schema is not current"):
            prestart.verify_current_schema(engine)
    finally:
        engine.dispose()
