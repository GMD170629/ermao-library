"""Application port for automatic metadata-provider request pacing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class AutomaticMetadataRequestGate(Protocol):
    def wait(self, provider_id: str) -> None:
        """Wait until the next automatic remote request may start."""


class RecognitionRequestStopped(RuntimeError):
    """The request budget, cancellation or current source policy stopped work."""


class RecognitionRequestBudget:
    def __init__(self, active: Callable[[], bool] = lambda: True,
                 attempts: int = 0, ai_attempts: int = 0) -> None:
        self.attempts = attempts
        self.ai_attempts = ai_attempts
        self._active = active

    def wait(self, provider_id: str) -> None:
        self.check_active()
        if provider_id == "ai":
            if self.ai_attempts >= 2:
                raise RecognitionRequestStopped("AI_BUDGET_EXHAUSTED")
            self.ai_attempts += 1
        else:
            if self.attempts >= 8:
                raise RecognitionRequestStopped("REQUEST_BUDGET_EXHAUSTED")
            self.attempts += 1

    def check_active(self) -> None:
        if not self._active():
            raise RecognitionRequestStopped("CANCELLED")
