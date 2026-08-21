from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.bootstrap.system import prepare_system_event
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.organize import MetadataProviderPipeline
from app.models.settings import SystemSetting
from app.services.metadata_provider_registry import (
    get_metadata_provider,
    list_metadata_provider_pipelines,
    list_metadata_providers,
    metadata_provider_registry,
    persist_metadata_provider_update,
    prepare_metadata_provider_update,
    update_metadata_provider_pipeline,
)
from app.services.metadata_provider_registry import (
    test_metadata_provider as run_metadata_provider_test,
)


def test_provider_queries_remain_readable_while_another_writer_holds_lock(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    regular_engine = create_sqlite_engine(settings.database_path)
    reader_engine = create_sqlite_engine(
        settings.database_path,
        timeout_seconds=0.1,
    )
    bootstrap_database(regular_engine, settings)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.lstrip().upper())

    blocker = Session(regular_engine)
    event.listen(reader_engine, "before_cursor_execute", capture_statement)
    try:
        blocker.execute(
            update(SystemSetting)
            .where(SystemSetting.key == "systemName")
            .values(value="writer owns SQLite slot")
        )

        with Session(reader_engine) as reader:
            providers = list_metadata_providers(reader)
            pipelines = list_metadata_provider_pipelines(reader)

        assert {provider["id"] for provider in providers} == {
            "ai",
            "bangumi",
            "douban",
        }
        assert {pipeline["mediaKind"] for pipeline in pipelines} == {
            "AUDIOBOOK",
            "COMIC",
            "EBOOK",
        }
        assert not any(
            statement.startswith(("INSERT", "UPDATE", "DELETE"))
            for statement in statements
        )
        blocker.rollback()

        with Session(regular_engine) as db:
            assert len(db.scalars(select(MetadataProviderPipeline)).all()) == 7
    finally:
        event.remove(reader_engine, "before_cursor_execute", capture_statement)
        blocker.close()
        reader_engine.dispose()
        regular_engine.dispose()


def test_provider_network_test_runs_after_the_read_transaction_is_closed(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    try:
        with Session(engine) as db:
            plugin = metadata_provider_registry().require("douban")

            def test_connection(_config):
                assert db.in_transaction() is False
                return {"ok": True, "message": "连接正常"}

            monkeypatch.setattr(plugin, "test", test_connection)

            result, provider = run_metadata_provider_test(db, "douban")

            assert result == {"ok": True, "message": "连接正常"}
            assert provider["lastTestStatus"] == "ok"
    finally:
        engine.dispose()


def test_pipeline_update_uses_bounded_set_based_dml(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        normalized = statement.lstrip().upper()
        if normalized.startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        with Session(engine) as db:
            pipelines = update_metadata_provider_pipeline(
                db,
                "EBOOK",
                [
                    {"providerId": "douban", "enabled": False},
                    {"providerId": "bangumi", "enabled": False},
                    {"providerId": "ai", "enabled": False},
                ],
            )

        assert len(statements) <= 3
        ebook = next(row for row in pipelines if row["mediaKind"] == "EBOOK")
        assert [provider["providerId"] for provider in ebook["providers"]] == [
            "douban",
            "bangumi",
            "ai",
        ]
        assert all(not provider["enabled"] for provider in ebook["providers"])
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)
        engine.dispose()


def test_provider_state_and_audit_event_roll_back_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    try:
        with Session(engine) as db:
            before = get_metadata_provider(db, "douban")
            assert before is not None
            prepared = prepare_metadata_provider_update(
                db,
                "douban",
                {"priority": 777},
            )
            audit_event = prepare_system_event(
                source="system",
                action="metadata.provider_updated",
                message="test",
            )

            def fail_audit_write(*_args: object, **_kwargs: object) -> None:
                raise RuntimeError("audit unavailable")

            monkeypatch.setattr(
                "app.services.metadata_provider_registry.write_prepared_system_events",
                fail_audit_write,
            )
            with pytest.raises(RuntimeError, match="audit unavailable"):
                persist_metadata_provider_update(db, prepared, event=audit_event)

            after = get_metadata_provider(db, "douban")
            assert after is not None
            assert after["priority"] == before["priority"]
    finally:
        engine.dispose()
