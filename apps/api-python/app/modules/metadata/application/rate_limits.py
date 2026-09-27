"""Application port for automatic metadata-provider request pacing."""

from __future__ import annotations

from typing import Protocol


class AutomaticMetadataRequestGate(Protocol):
    def wait(self, provider_id: str) -> None:
        """Wait until the next automatic remote request may start."""
