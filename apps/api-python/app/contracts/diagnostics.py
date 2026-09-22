"""Narrow diagnostic boundary for application-owned failure handling."""

from collections.abc import Mapping
from typing import Protocol

DiagnosticContext = Mapping[str, str | int | bool | None]


class DiagnosticHandle(Protocol):
    @property
    def diagnostic_id(self) -> str: ...


class FailureDiagnostics(Protocol):
    def prepare(
        self, error: BaseException, *, event: str, context: DiagnosticContext
    ) -> DiagnosticHandle:
        """Capture the original failure before rollback or error conversion."""
        ...

    def persist(self, handle: DiagnosticHandle) -> None:
        """Store the capture after the owning business transaction releases."""
        ...
