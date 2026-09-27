"""Process-local pacing for automatic metadata-provider HTTP requests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from app.modules.metadata.domain.providers import ProviderManifest


class AutomaticMetadataRequestRateLimiter:
    """Evenly space automatic requests while leaving manual calls untouched."""

    def __init__(
        self,
        manifests: Iterable[ProviderManifest],
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._minimum_intervals = {
            manifest.id: manifest.automatic_rate_limit.minimum_interval_seconds
            for manifest in manifests
            if manifest.automatic_rate_limit is not None
        }
        self._monotonic = monotonic
        self._sleep = sleep
        self._next_request_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, provider_id: str) -> None:
        minimum_interval = self._minimum_intervals.get(provider_id)
        if minimum_interval is None:
            return
        with self._lock:
            now = self._monotonic()
            request_at = max(now, self._next_request_at.get(provider_id, now))
            self._next_request_at[provider_id] = request_at + minimum_interval
        delay = request_at - now
        if delay > 0:
            self._sleep(delay)
