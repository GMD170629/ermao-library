"""Scan-independent diagnostics emitted by targeted reconciliation."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.application.watcher_dto import ReconcileFence
from app.modules.catalog.domain.scan import ScanDiagnostic

from .models import LayoutDiagnostic
from .reconcile_fencing import require_live_reconcile
from .scan_fencing import enum_value, stable_id

_RELATED_PATH_LIMIT = 32


class SqlAlchemyReconcileDiagnosticRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        fence: ReconcileFence,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None:
        require_live_reconcile(self._session, fence, now=observed_at)
        for diagnostic in diagnostics:
            code = enum_value(diagnostic.code)
            scope = "/".join(diagnostic.unit_path)
            related = tuple("/".join(path) for path in diagnostic.related_paths)
            related_digest = hashlib.sha256(
                "\0".join(related).encode("utf-8")
            ).hexdigest()
            diagnostic_id = stable_id(
                "reconcile_diagnostic",
                fence.library_id,
                fence.intent_id,
                scope,
                code,
                related_digest,
            )
            row = self._session.scalar(
                select(LayoutDiagnostic).where(
                    LayoutDiagnostic.id == diagnostic_id,
                    LayoutDiagnostic.library_id == fence.library_id,
                    LayoutDiagnostic.reconcile_origin_id == fence.intent_id,
                )
            )
            parameters: dict[str, object] = {
                "relatedPaths": list(related[:_RELATED_PATH_LIMIT]),
                "relatedPathCount": len(related),
                "relatedPathsDigest": related_digest,
            }
            if row is None:
                self._session.add(
                    LayoutDiagnostic(
                        id=diagnostic_id,
                        library_id=fence.library_id,
                        scan_run_id=None,
                        reconcile_origin_id=fence.intent_id,
                        generation=fence.presence_generation,
                        config_revision=fence.config_revision,
                        scope_relative_path=scope,
                        code=code,
                        severity="WARNING",
                        parameters=parameters,
                        first_observed_at=observed_at,
                        last_observed_at=observed_at,
                    )
                )
            else:
                row.last_observed_at = observed_at
                row.resolved_at = None
                row.parameters = parameters
        self._session.flush()


__all__ = ["SqlAlchemyReconcileDiagnosticRepository"]
