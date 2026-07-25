from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from appv2.modules.accounts.domain import User
from appv2.modules.delivery.domain import Delivery
from appv2.modules.discovery.domain import ExternalSource
from appv2.modules.metadata.domain import CandidateScore
from appv2.modules.reading.domain import ReadingProgress


def test_user_normalization_and_validation() -> None:
    assert User.normalize_email("  USER@Example.COM ") == "user@example.com"
    assert User.normalize_display_name("  Jane   Reader ") == "Jane Reader"
    with pytest.raises(ValueError):
        User.normalize_email("not-an-email")
    with pytest.raises(ValueError):
        User.normalize_display_name(" ")


def test_reading_progress_is_optimistic_and_monotonic() -> None:
    now = datetime.now(UTC)
    progress = ReadingProgress(
        position={"cfi": "epubcfi(/6/2)"},
        percentage=0.25,
        version=3,
        updated_at=now,
    )
    advanced = progress.advance(
        position={"cfi": "epubcfi(/6/4)"},
        percentage=0.5,
        occurred_at=now + timedelta(seconds=1),
        expected_version=3,
    )
    assert advanced.version == 4
    assert advanced.percentage == 0.5
    stale = advanced.advance(
        position={"cfi": "old"},
        percentage=0.1,
        occurred_at=now,
        expected_version=4,
    )
    assert stale == advanced
    with pytest.raises(ValueError, match="version conflict"):
        advanced.advance(
            position={},
            percentage=0.6,
            occurred_at=now + timedelta(seconds=2),
            expected_version=3,
        )


def test_candidate_score_is_clamped() -> None:
    assert CandidateScore(title=1, author=1, identifier=1).total == 1
    assert CandidateScore(title=-2, author=0, identifier=0).total == 0


def test_external_source_rejects_non_http_protocols() -> None:
    source = ExternalSource(
        id=uuid.uuid4(),
        name="unsafe",
        base_url="file:///etc/passwd",
        enabled=True,
    )
    with pytest.raises(ValueError):
        source.validate()


def test_delivery_retry_rules() -> None:
    assert Delivery(status="failed", attempt=1).retry().status == "queued"
    with pytest.raises(ValueError):
        Delivery(status="completed", attempt=1).retry()
    with pytest.raises(ValueError):
        Delivery(status="failed", attempt=5).retry()
