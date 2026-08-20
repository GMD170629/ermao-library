from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

import app.modules.imports.infrastructure.orchestration_services as services_module
from app.core.config import Settings
from app.modules.imports.application.errors import (
    AudioTrackLimitExceededError,
    ImportExecutionError,
)
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)


class _ReleasedSession:
    def in_transaction(self) -> bool:
        return False


def test_audio_track_limit_is_translated_at_infrastructure_boundary(
    monkeypatch,
) -> None:
    def reject_bundle(_path: Path):
        raise AudioTrackLimitExceededError(
            path="/books/overflow",
            limit=10_000,
            observed_count=10_001,
        )

    monkeypatch.setattr(services_module, "inspect_audio_bundle", reject_bundle)
    services = SessionImportOrchestrationServices(
        cast(Session, _ReleasedSession()), cast(Settings, object())
    )

    with pytest.raises(ImportExecutionError) as raised:
        services.inspect_audio_bundle(Path("/books/overflow"))

    assert raised.value.code == "AUDIO_TRACK_LIMIT_EXCEEDED"
    assert raised.value.retryable is False
    assert "10000" in str(raised.value)


def test_import_preferences_are_prepared_after_read_transaction_release(
    db_session, test_settings, monkeypatch
) -> None:
    observed_transaction_states: list[bool] = []
    prepare = services_module.prepare_import_preferences

    def observe_prepare(projection):
        observed_transaction_states.append(db_session.in_transaction())
        return prepare(projection)

    monkeypatch.setattr(services_module, "prepare_import_preferences", observe_prepare)

    result = SessionImportOrchestrationServices(
        db_session, test_settings
    ).load_preferences()

    assert observed_transaction_states == [False]
    assert result.allowed_extensions


def test_local_metadata_priority_is_prepared_after_read_transaction_release(
    db_session, test_settings, monkeypatch
) -> None:
    observed_transaction_states: list[bool] = []
    prepare = services_module.prepare_local_metadata_priority

    def observe_prepare(projection):
        observed_transaction_states.append(db_session.in_transaction())
        return prepare(projection)

    monkeypatch.setattr(
        services_module, "prepare_local_metadata_priority", observe_prepare
    )

    result = SessionImportOrchestrationServices(
        db_session, test_settings
    ).load_local_metadata_priority()

    assert observed_transaction_states == [False]
    assert result
