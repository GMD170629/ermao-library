"""Shared typed scan-fence and stable identity primitives."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime
from enum import Enum as PythonEnum
from typing import cast

from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.application.scan_dto import ScanFence
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.scan import ScanStale

from .enums import LibraryControlState, ScanState
from .models import CatalogLibrary, LibraryScanRun

ACTIVE_LIBRARY_STATES = (
    LibraryControlState.ACTIVATING,
    LibraryControlState.ACTIVE,
)
ACTIVE_SCAN_STATES = (
    ScanState.PENDING,
    ScanState.RUNNING,
    ScanState.FINALIZING,
)


def enum_value(value: object) -> str:
    if isinstance(value, PythonEnum):
        return str(value.value)
    return cast(str, value)


def stable_id(prefix: str, *parts: str) -> str:
    payload = "".join(f"{len(part.encode('utf-8'))}:{part}" for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def comparison_components(
    path: tuple[str, ...], comparison: PathComparison
) -> tuple[str, ...]:
    normalized = tuple(unicodedata.normalize("NFC", component) for component in path)
    if comparison is PathComparison.INSENSITIVE:
        return tuple(component.casefold() for component in normalized)
    return normalized


def path_token(path: tuple[str, ...], comparison: PathComparison) -> str:
    return "".join(
        f"{len(component.encode('utf-8'))}:{component}"
        for component in comparison_components(path, comparison)
    )


def raw_path_token(path: tuple[str, ...]) -> str:
    return "".join(
        f"{len(component.encode('utf-8'))}:{component}" for component in path
    )


def source_entry_id(library_id: str, path: tuple[str, ...]) -> str:
    return stable_id("source", library_id, raw_path_token(path))


def library_fence_conditions(
    fence: ScanFence,
) -> tuple[ColumnElement[bool], ...]:
    return (
        CatalogLibrary.id == fence.library_id,
        CatalogLibrary.config_revision == fence.config_revision,
        CatalogLibrary.root_path == fence.root_path_snapshot,
        CatalogLibrary.organization_mode == OrganizationMode(fence.organization_mode),
        CatalogLibrary.topology_version == fence.topology_version,
        CatalogLibrary.path_comparison == PathComparison(fence.path_comparison),
        CatalogLibrary.topology_writer_fence == fence.topology_writer_fence,
        CatalogLibrary.control_state.in_(ACTIVE_LIBRARY_STATES),
    )


def scan_fence_conditions(
    fence: ScanFence,
    *,
    states: tuple[ScanState, ...] = ACTIVE_SCAN_STATES,
) -> tuple[ColumnElement[bool], ...]:
    root_condition = (
        LibraryScanRun.root_identity_snapshot.is_(None)
        if fence.root_identity is None
        else LibraryScanRun.root_identity_snapshot == fence.root_identity
    )
    return (
        LibraryScanRun.id == fence.scan_id,
        LibraryScanRun.library_id == fence.library_id,
        LibraryScanRun.generation == fence.generation,
        LibraryScanRun.config_revision == fence.config_revision,
        LibraryScanRun.root_path_snapshot == fence.root_path_snapshot,
        LibraryScanRun.mode_snapshot == OrganizationMode(fence.organization_mode),
        LibraryScanRun.topology_version_snapshot == fence.topology_version,
        LibraryScanRun.path_comparison_snapshot
        == PathComparison(fence.path_comparison),
        root_condition,
        LibraryScanRun.topology_writer_fence == fence.topology_writer_fence,
        LibraryScanRun.lease_owner == fence.lease_owner,
        LibraryScanRun.state.in_(states),
    )


def library_fence_exists(fence: ScanFence) -> ColumnElement[bool]:
    return exists(select(CatalogLibrary.id).where(*library_fence_conditions(fence)))


def guard_mutation(session: Session, fence: ScanFence, *, now: datetime) -> bool:
    statement = (
        update(LibraryScanRun)
        .where(
            *scan_fence_conditions(fence),
            LibraryScanRun.lease_expires_at.is_not(None),
            LibraryScanRun.lease_expires_at > now,
            library_fence_exists(fence),
        )
        .values(heartbeat_at=LibraryScanRun.heartbeat_at)
    )
    result = session.execute(statement)
    return cast(CursorResult[object], result).rowcount == 1


def require_live_fence(session: Session, fence: ScanFence, *, now: datetime) -> None:
    if not guard_mutation(session, fence, now=now):
        raise ScanStale()


__all__ = [
    "ACTIVE_LIBRARY_STATES",
    "ACTIVE_SCAN_STATES",
    "comparison_components",
    "enum_value",
    "guard_mutation",
    "library_fence_conditions",
    "library_fence_exists",
    "path_token",
    "require_live_fence",
    "scan_fence_conditions",
    "source_entry_id",
    "stable_id",
]
