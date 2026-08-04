from __future__ import annotations

from typing import Self

import pytest

from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS, AutomaticRateLimit
from app.modules.metadata.infrastructure.automatic_rate_limiter import (
    AutomaticMetadataRequestRateLimiter,
)
from app.services import organize_service


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


class RecordingGate:
    def __init__(self) -> None:
        self.providers: list[str] = []

    def wait(self, provider_id: str) -> None:
        self.providers.append(provider_id)


class JsonResponse:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"data": []}'


def test_builtin_automatic_limits_evenly_space_each_provider_independently() -> None:
    clock = FakeClock()
    limiter = AutomaticMetadataRequestRateLimiter(
        BUILTIN_MANIFESTS,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    limiter.wait("douban")
    limiter.wait("douban")
    limiter.wait("bangumi")
    limiter.wait("bangumi")
    limiter.wait("ai")

    assert clock.delays == [pytest.approx(5.0), pytest.approx(0.25)]


@pytest.mark.parametrize(
    ("requests", "period_seconds"),
    [(0, 1.0), (1, 0.0), (-1, 1.0), (1, -1.0)],
)
def test_automatic_rate_limit_rejects_non_positive_values(
    requests: int, period_seconds: float
) -> None:
    with pytest.raises(ValueError):
        AutomaticRateLimit(requests=requests, period_seconds=period_seconds)


def test_bangumi_gate_is_used_only_when_automatic_lookup_supplies_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RecordingGate()
    context = {"work": {"title": "test"}, "volumes": []}
    monkeypatch.setattr(
        organize_service, "urlopen", lambda *_args, **_kwargs: JsonResponse()
    )

    organize_service.run_bangumi_metadata_provider(context, {})
    organize_service.run_bangumi_metadata_provider(
        context, {}, automatic_request_gate=gate
    )

    assert gate.providers == ["bangumi"]


def test_douban_http_request_uses_automatic_gate_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = RecordingGate()
    monkeypatch.setattr(
        organize_service, "urlopen", lambda *_args, **_kwargs: JsonResponse()
    )

    organize_service.fetch_text("https://example.test", {})
    organize_service.fetch_text(
        "https://example.test",
        {},
        provider_id="douban",
        automatic_request_gate=gate,
    )

    assert gate.providers == ["douban"]
