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
from app.modules.imports.application.ports import TextConversionProgressStore
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)
from app.services.text_conversion import ConversionFailure


class _ReleasedSession:
    def in_transaction(self) -> bool:
        return False


def test_conversion_failure_is_translated_at_infrastructure_boundary(
    monkeypatch,
) -> None:
    def fail_conversion(*_args, **_kwargs):
        raise ConversionFailure(
            "CONVERTER_UNAVAILABLE",
            "电子书转换服务不可用",
            retryable=True,
        )

    monkeypatch.setattr(services_module, "convert_to_epub", fail_conversion)
    services = SessionImportOrchestrationServices(
        cast(Session, _ReleasedSession()),
        cast(Settings, object()),
        conversion_progress=cast(TextConversionProgressStore, object()),
    )

    with pytest.raises(ImportExecutionError) as raised:
        services.convert_text("task-1", Path("/tmp/book.mobi"))

    assert raised.value.code == "CONVERTER_UNAVAILABLE"
    assert raised.value.retryable is True
    assert str(raised.value) == "电子书转换服务不可用"


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
