"""Database resource failures captured before rollback or close can replace them."""

import logging
import sys
from uuid import uuid4

from sqlalchemy.orm import Session

from app.contracts.library_file_activity import LibraryFileActivityBusy
from app.core.exception_diagnostics import (
    DiagnosticSnapshot,
    emergency_diagnostic,
    persist_exception_diagnostic,
    prepare_exception_diagnostic,
)


class DiagnosticSession(Session):
    """Preserve failures before SQLAlchemy rollback/close can replace them.

    Application transaction ports remain unchanged. This storage adapter only
    records diagnostics; its SQLAlchemy commit/rollback/close semantics stay
    intact. The independent diagnostic writer marks its own sessions to avoid
    recursing if that writer fails.
    """

    def _capture_failure(
        self,
        error: BaseException | None,
        step: str,
        parent: DiagnosticSnapshot | None = None,
    ) -> DiagnosticSnapshot | None:
        if self.info.get("diagnostics_storage") or not isinstance(error, Exception):
            return None
        if isinstance(error, LibraryFileActivityBusy):
            return None
        # An exception being unwound may originate anywhere in the operation.
        # Observing it here does not make it a database or cleanup failure.
        observing_original = step in {"transaction", "session"}
        action = (
            "operation.failed_before_cleanup"
            if observing_original
            else f"database.{step}_failed"
        )
        try:
            snapshot = prepare_exception_diagnostic(
                logging.getLogger(__name__),
                action,
                error,
                context={
                    "step": f"before_{step}_cleanup" if observing_original else step,
                    "parent_diagnostic_id": parent.diagnostic_id if parent else None,
                },
            )
            self.info.setdefault("pending_diagnostics", {})[snapshot.diagnostic_id] = (
                snapshot
            )
            return snapshot
        except Exception as diagnostic_error:  # noqa: BLE001 - diagnostics cannot prevent transaction cleanup
            diagnostic_id = f"diag_{uuid4().hex}"
            emergency_diagnostic(
                action, error, diagnostic_id=diagnostic_id
            )
            emergency_diagnostic(
                "database.diagnostic_capture_failed",
                diagnostic_error,
                diagnostic_id=f"diag_{uuid4().hex}",
                parent_diagnostic_id=diagnostic_id,
            )
            return None

    def _flush_diagnostics(self) -> None:
        if self.in_transaction():
            return
        for snapshot in self.info.pop("pending_diagnostics", {}).values():
            try:
                persist_exception_diagnostic(logging.getLogger(__name__), snapshot)
            except Exception as error:  # noqa: BLE001 - transaction result must remain unchanged
                emergency_diagnostic(
                    "database.diagnostic_persist_failed",
                    error,
                    diagnostic_id=f"diag_{uuid4().hex}",
                    parent_diagnostic_id=snapshot.diagnostic_id,
                )

    def commit(self) -> None:
        try:
            super().commit()
        except Exception as error:
            self._capture_failure(error, "commit")
            raise
        finally:
            self._flush_diagnostics()

    def rollback(self) -> None:
        original = self._capture_failure(sys.exception(), "transaction")
        try:
            super().rollback()
        except Exception as error:
            self._capture_failure(error, "rollback", original)
            raise
        finally:
            self._flush_diagnostics()

    def close(self) -> None:
        original = self._capture_failure(sys.exception(), "session")
        try:
            super().close()
        except Exception as error:
            self._capture_failure(error, "close", original)
            raise
        finally:
            self._flush_diagnostics()
