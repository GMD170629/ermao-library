"""Provider failures retain the observed external cause after a failed result."""

import json
import ssl
from urllib.error import HTTPError

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exception_diagnostics import (
    configure_exception_storage,
    exception_diagnostic_boundary,
    reset_exception_storage,
)
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.settings import SystemEvent, SystemSetting
from app.services import metadata_provider_registry as providers


@pytest.fixture
def provider_database(tmp_path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    factory = sessionmaker(bind=engine)
    configure_exception_storage(factory)
    try:
        yield engine, factory
    finally:
        reset_exception_storage()
        engine.dispose()


@pytest.mark.parametrize(
    ("failure", "expected_type", "expected_reason"),
    [
        (
            TimeoutError("upstream read timed out"),
            "TimeoutError",
            "upstream read timed out",
        ),
        (
            ssl.SSLCertVerificationError(1, "certificate verify failed"),
            "ssl.SSLCertVerificationError",
            "certificate verify failed",
        ),
        (
            HTTPError(
                "https://upstream.invalid/?token=private-token",
                503,
                "Service Unavailable",
                {},
                None,
            ),
            "urllib.error.HTTPError",
            "503",
        ),
        (
            json.JSONDecodeError("response JSON malformed", "private-response-body", 3),
            "json.decoder.JSONDecodeError",
            "response JSON malformed",
        ),
        (
            ValueError("unexpected provider implementation bug"),
            "ValueError",
            "unexpected provider implementation bug",
        ),
    ],
)
def test_provider_failure_result_has_real_runtime_and_event_cause(
    provider_database, monkeypatch, caplog, failure, expected_type, expected_reason
):
    engine, factory = provider_database
    plugin = providers.metadata_provider_registry().require("douban")
    with Session(engine) as db:

        def fail(_config):
            assert not db.in_transaction()
            raise failure

        monkeypatch.setattr(plugin, "test", fail)
        with exception_diagnostic_boundary(
            providers.LOGGER,
            "provider.request_failed",
            context={"request_id": "provider-request-1"},
        ):
            result, provider = providers.test_metadata_provider(db, "douban")
            db.close()

    assert result["ok"] is False
    assert provider["lastTestStatus"] == "failed"
    with factory() as observer:
        rows = observer.scalars(
            select(SystemEvent).where(
                SystemEvent.action
                == "services.metadata_provider_registry.test_metadata_provider.failed"
            )
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert result["diagnosticId"] == row.id
        assert expected_reason not in result["message"]
        details = row.metadata_json
        facts = details["diagnostics"]["directException"]
        assert facts["type"] == expected_type
        assert expected_reason in facts["message"]
        assert details["requestId"] == "provider-request-1"
        assert row.id in caplog.text
        assert expected_reason in caplog.text
        if isinstance(failure, HTTPError):
            assert facts["protocolStatus"] == 503
        serialized = json.dumps(details)
    assert "private-token" not in serialized + caplog.text
    assert "private-response-body" not in serialized + caplog.text


@pytest.mark.parametrize(("locale", "message"), [("zh-CN", "连接测试失败"), ("en-US", "Provider test failed")])
def test_failed_provider_result_without_exception_records_only_observed_reason(
    provider_database, monkeypatch, caplog, locale, message
):
    engine, factory = provider_database
    plugin = providers.metadata_provider_registry().require("douban")
    monkeypatch.setattr(plugin, "test", lambda _: {"ok": False})
    with Session(engine) as db:
        db.merge(SystemSetting(key="language", value=locale))
        db.commit()
        result, _provider = providers.test_metadata_provider(db, "douban")
    assert result["ok"] is False
    assert result["message"] == message
    with factory() as observer:
        row = observer.scalars(
            select(SystemEvent).where(
                SystemEvent.action == "metadata_provider.test_rejected"
            )
        ).one()
        facts = row.metadata_json["diagnostics"]
        assert result["diagnosticId"] == row.id
        assert facts["causeStatus"] == "NOT_PROVIDED"
        assert "ok=false" in facts["message"]
        assert row.id in caplog.text
