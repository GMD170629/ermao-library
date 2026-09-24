"""Durable incomplete scan ranges for diagnostics and safe reconciliation."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import LibraryImportScanGap
from app.modules.imports.domain.scan_policy import (
    ScanScope,
    decode_scan_scopes,
    encode_scan_scopes,
    merge_scan_scopes,
    remove_scan_scopes,
)


def record_scan_gaps(
    session: Session, library_id: str, scopes: Iterable[ScanScope]
) -> None:
    normalized = merge_scan_scopes((), tuple(scopes)) or ()
    if not normalized:
        return
    row = session.get(LibraryImportScanGap, library_id)
    existing = decode_scan_scopes(row.scopes) or () if row is not None else ()
    merged = merge_scan_scopes(existing, normalized) or ()
    stored = encode_scan_scopes(merged) if merged else None
    if row is None:
        session.add(LibraryImportScanGap(library_id=library_id, scopes=stored))
    else:
        row.scopes = stored
    session.flush()


def clear_scan_gaps(
    session: Session, library_id: str, completed: Iterable[ScanScope]
) -> None:
    row = session.get(LibraryImportScanGap, library_id)
    if row is None:
        return
    existing = decode_scan_scopes(row.scopes) or ()
    remaining = remove_scan_scopes(existing, tuple(completed))
    row.scopes = encode_scan_scopes(remaining) if remaining else None
    session.flush()


__all__ = ["clear_scan_gaps", "record_scan_gaps"]
