"""Connect application failure diagnostics to the existing runtime/event logs."""

import logging
from dataclasses import dataclass
from typing import cast

from app.contracts.diagnostics import DiagnosticContext, DiagnosticHandle
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
        self, error: BaseException, *, event: str, context: DiagnosticContext
    ) -> DiagnosticSnapshot:
        operation_id = context.get("operation_id")
        return prepare_exception_diagnostic(
            self.logger,
            event,
            error,
            context=dict(context),
            source=self.source,
            action=event,
            target_type="operation" if operation_id else None,
            target_id=str(operation_id) if operation_id else None,
        )

    def persist(self, handle: DiagnosticHandle) -> None:
        persist_exception_diagnostic(
            self.logger, cast(DiagnosticSnapshot, handle), self.session_factory
        )
