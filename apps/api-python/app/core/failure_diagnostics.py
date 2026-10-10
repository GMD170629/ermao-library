"""Connect application failure diagnostics to the existing runtime/event logs."""

import logging
from dataclasses import dataclass
from typing import cast

from app.contracts.diagnostics import DiagnosticHandle
from app.core.exception_diagnostics import (
    DiagnosticSnapshot,
    SessionFactory,
    persist_exception_diagnostic,
    prepare_exception_diagnostic,
)


@dataclass(frozen=True)
class RuntimeFailureDiagnostics:
    logger: logging.Logger
    source: str
    session_factory: SessionFactory | None = None

    def prepare(
        self, error: BaseException, *, event: str
    ) -> DiagnosticSnapshot:
        return prepare_exception_diagnostic(
            self.logger,
            event,
            error,
            source=self.source,
            action=event,

        )

    def persist(self, handle: DiagnosticHandle) -> None:
        persist_exception_diagnostic(
            self.logger, cast(DiagnosticSnapshot, handle), self.session_factory
        )
