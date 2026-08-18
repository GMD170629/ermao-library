"""SQLAlchemy source-observation, collision, and diagnostic repositories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.modules.catalog.application.scan_dto import (
    DiscoveryEntryType,
    PathCollision,
    ScanFence,
    SourceObservation,
    SourceObservationOutcome,
    SourcePathBinding,
)
from app.modules.catalog.domain.admission import SourceAdmissionEvidence
from app.modules.catalog.domain.ordering import natural_path_key
from app.modules.catalog.domain.scan import ScanDiagnostic, ScanStale

from .enums import LayoutState, SlotState, SourceEntryType
from .models import (
    LayoutDiagnostic,
    LibrarySourceEntry,
    PathCollisionObservation,
)
from .scan_fencing import (
    comparison_components as _comparison_components,
)
from .scan_fencing import (
    enum_value as _enum_value,
)
from .scan_fencing import (
    require_live_fence as _require_live_fence,
)
from .scan_fencing import (
    stable_id as _stable_id,
)
from .source_path_resolution import (
    SOURCE_QUERY_CHUNK as _SOURCE_PREFETCH_CHUNK,
)
from .source_path_resolution import (
    new_opaque_source_id,
    paths_with_ancestors,
    resolve_raw_paths,
)

_DIAGNOSTIC_RELATED_PATH_LIMIT = 32


@dataclass(frozen=True, slots=True)
class _PreparedObservation:
    observation: SourceObservation
    entry_id: str
    parent_id: str
    local_name: str
    local_name_key: str


class SqlAlchemySourceObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def bind_synthetic_root(
        self,
        fence: ScanFence,
        *,
        observed_identity: str,
        observed_at: datetime,
    ) -> bool:
        _require_live_fence(self._session, fence, now=observed_at)
        root = self._session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == fence.library_id,
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            )
        )
        if root is None:
            self._session.add(
                LibrarySourceEntry(
                    id=_stable_id("source_root", fence.library_id),
                    library_id=fence.library_id,
                    parent_entry_id=None,
                    local_name="$root",
                    local_name_key="$root",
                    entry_type=SourceEntryType.SYNTHETIC_ROOT,
                    filesystem_identity=observed_identity,
                    last_seen_generation=fence.generation,
                    absence_confirmed_at=None,
                    children_presence_epoch=0,
                    next_children_presence_epoch=0,
                    observed_parent_presence_epoch=None,
                    pending_observed_parent_presence_epoch=None,
                    layout_state=LayoutState.PRESENT,
                    slot_state=SlotState.ACTIVE,
                    created_at=observed_at,
                    updated_at=observed_at,
                )
            )
        else:
            if root.filesystem_identity != observed_identity:
                return False
            root.last_seen_generation = fence.generation
            root.absence_confirmed_at = None
            root.layout_state = LayoutState.PRESENT
            root.slot_state = SlotState.ACTIVE
            root.updated_at = observed_at
        self._session.flush()
        return True

    def upsert_observations(
        self,
        fence: ScanFence,
        observations: tuple[SourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome:
        _require_live_fence(self._session, fence, now=observed_at)
        root = self._session.scalar(
            select(LibrarySourceEntry).where(
                LibrarySourceEntry.library_id == fence.library_id,
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
            )
        )
        if (
            root is None
            or fence.root_identity is None
            or root.filesystem_identity != fence.root_identity
        ):
            raise ScanStale()
        sorted_observations = sorted(
            observations,
            key=lambda value: (
                len(value.source.relative_path),
                value.source.relative_path,
            ),
        )
        paths = tuple(
            dict.fromkeys(value.source.relative_path for value in sorted_observations)
        )
        resolved = resolve_raw_paths(
            self._session,
            fence.library_id,
            paths_with_ancestors(paths),
        )
        prepared_by_path: dict[tuple[str, ...], _PreparedObservation] = {}
        path_ids: dict[tuple[str, ...], str] = {(): root.id}
        path_ids.update((path, row.id) for path, row in resolved.items())
        for observation in sorted_observations:
            if observation.generation != fence.generation:
                raise ScanStale()
            path = observation.source.relative_path
            parent_id = path_ids.get(path[:-1])
            if parent_id is None:
                raise ScanStale()
            entry_id = path_ids.get(path)
            if entry_id is None:
                entry_id = new_opaque_source_id()
                path_ids[path] = entry_id
            local_name = path[-1]
            prepared_by_path[path] = _PreparedObservation(
                observation=observation,
                entry_id=entry_id,
                parent_id=parent_id,
                local_name=local_name,
                local_name_key=_comparison_components(
                    (local_name,), fence.path_comparison
                )[0],
            )
        prepared = tuple(prepared_by_path.values())
        existing_by_id: dict[str, LibrarySourceEntry] = {}
        entry_ids = tuple(
            dict.fromkeys(
                value_id
                for value in prepared
                for value_id in (value.entry_id, value.parent_id)
            )
        )
        for offset in range(0, len(entry_ids), _SOURCE_PREFETCH_CHUNK):
            for existing_entry in self._session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.id.in_(
                        entry_ids[offset : offset + _SOURCE_PREFETCH_CHUNK]
                    ),
                )
                .with_for_update()
            ):
                existing_by_id[existing_entry.id] = existing_entry
        slot_keys = tuple(
            dict.fromkeys((value.parent_id, value.local_name_key) for value in prepared)
        )
        slot_rows_by_key: dict[tuple[str, str], list[LibrarySourceEntry]] = {
            key: [] for key in slot_keys
        }
        for offset in range(0, len(slot_keys), _SOURCE_PREFETCH_CHUNK):
            chunk = slot_keys[offset : offset + _SOURCE_PREFETCH_CHUNK]
            for slot_entry in self._session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    tuple_(
                        LibrarySourceEntry.parent_entry_id,
                        LibrarySourceEntry.local_name_key,
                    ).in_(chunk),
                )
                .with_for_update()
            ):
                existing_by_id.setdefault(slot_entry.id, slot_entry)
                slot_rows_by_key[
                    (slot_entry.parent_entry_id or "", slot_entry.local_name_key)
                ].append(slot_entry)
        original_slot_states = {
            row.id: row.slot_state for row in existing_by_id.values()
        }
        collision_paths: dict[tuple[tuple[str, ...], str], set[tuple[str, ...]]] = {}
        new_rows: list[LibrarySourceEntry] = []
        for value in prepared:
            observation = value.observation
            source = observation.source
            path = source.relative_path
            parent_entry = existing_by_id.get(value.parent_id)
            if parent_entry is None or parent_entry.entry_type not in {
                SourceEntryType.SYNTHETIC_ROOT,
                SourceEntryType.DIRECTORY,
            }:
                raise ScanStale()
            current_entry = existing_by_id.get(value.entry_id)
            expectation = source.expected_stat
            entry_type = SourceEntryType(source.entry_type.value)
            slot_key = (value.parent_id, value.local_name_key)
            slot_rows = tuple(
                candidate
                for candidate in slot_rows_by_key[slot_key]
                if candidate.id != value.entry_id
            )
            current_generation_others = tuple(
                candidate
                for candidate in slot_rows
                if candidate.last_seen_generation == fence.generation
            )
            is_collision = bool(current_generation_others)
            if is_collision:
                related = collision_paths.setdefault(
                    (path[:-1], value.local_name_key), {path}
                )
                for candidate in current_generation_others:
                    candidate.layout_state = LayoutState.INVALID
                    candidate.slot_state = SlotState.COLLIDING
                    candidate.updated_at = observed_at
                    related.add((*path[:-1], candidate.local_name))
            else:
                for candidate in slot_rows:
                    if candidate.slot_state in {
                        SlotState.ACTIVE,
                        SlotState.COLLIDING,
                    }:
                        candidate.slot_state = SlotState.RETIRED
                        candidate.updated_at = observed_at
            is_layout_present = source.entry_type is DiscoveryEntryType.DIRECTORY or (
                source.entry_type is DiscoveryEntryType.FILE
                and isinstance(observation.admission, SourceAdmissionEvidence)
            )
            layout_state = (
                LayoutState.PRESENT
                if is_layout_present and not is_collision
                else LayoutState.INVALID
            )
            slot_state = SlotState.COLLIDING if is_collision else SlotState.ACTIVE
            if current_entry is None:
                current_entry = LibrarySourceEntry(
                    id=value.entry_id,
                    library_id=fence.library_id,
                    parent_entry_id=value.parent_id,
                    local_name=value.local_name,
                    local_name_key=value.local_name_key,
                    entry_type=entry_type,
                    filesystem_identity=source.filesystem_identity,
                    size_bytes=(
                        None if expectation is None else expectation.size_bytes
                    ),
                    modified_ns=(
                        None if expectation is None else expectation.modified_ns
                    ),
                    last_seen_generation=fence.generation,
                    absence_confirmed_at=None,
                    children_presence_epoch=0,
                    next_children_presence_epoch=0,
                    observed_parent_presence_epoch=(
                        parent_entry.children_presence_epoch
                    ),
                    pending_observed_parent_presence_epoch=None,
                    layout_state=layout_state,
                    slot_state=slot_state,
                    created_at=observed_at,
                    updated_at=observed_at,
                )
                new_rows.append(current_entry)
                existing_by_id[current_entry.id] = current_entry
                slot_rows_by_key[slot_key].append(current_entry)
            else:
                current_entry.parent_entry_id = value.parent_id
                current_entry.local_name = value.local_name
                current_entry.local_name_key = value.local_name_key
                current_entry.entry_type = entry_type
                current_entry.filesystem_identity = source.filesystem_identity
                current_entry.size_bytes = (
                    None if expectation is None else expectation.size_bytes
                )
                current_entry.modified_ns = (
                    None if expectation is None else expectation.modified_ns
                )
                current_entry.last_seen_generation = fence.generation
                current_entry.absence_confirmed_at = None
                current_entry.observed_parent_presence_epoch = (
                    parent_entry.children_presence_epoch
                )
                current_entry.pending_observed_parent_presence_epoch = None
                current_entry.layout_state = layout_state
                current_entry.slot_state = slot_state
                current_entry.updated_at = observed_at
        deferred_activations: list[LibrarySourceEntry] = []
        for row in existing_by_id.values():
            original_slot_state = original_slot_states.get(row.id)
            if (
                original_slot_state is not None
                and original_slot_state is not SlotState.ACTIVE
                and row.slot_state is SlotState.ACTIVE
            ):
                deferred_activations.append(row)
                row.slot_state = original_slot_state
        self._session.flush()
        self._session.add_all(new_rows)
        for row in deferred_activations:
            row.slot_state = SlotState.ACTIVE
        self._session.flush()
        return SourceObservationOutcome(
            collisions=tuple(
                PathCollision(
                    parent_path=parent_path,
                    comparison_key=comparison_key,
                    related_paths=tuple(
                        sorted(
                            paths,
                            key=lambda path: natural_path_key(
                                path, fence.path_comparison
                            ),
                        )
                    ),
                )
                for (parent_path, comparison_key), paths in sorted(
                    collision_paths.items(),
                    key=lambda value: (
                        natural_path_key(value[0][0], fence.path_comparison),
                        value[0][1],
                    ),
                )
            ),
            bindings=tuple(
                SourcePathBinding(
                    relative_path=value.observation.source.relative_path,
                    source_entry_id=value.entry_id,
                    filesystem_identity=value.observation.source.filesystem_identity,
                )
                for value in prepared
            ),
        )


class SqlAlchemyPathCollisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        fence: ScanFence,
        collisions: tuple[PathCollision, ...],
        *,
        observed_at: datetime,
    ) -> None:
        _require_live_fence(self._session, fence, now=observed_at)
        prepared: list[tuple[str, str, str, dict[str, object]]] = []
        parent_paths = tuple(
            dict.fromkeys(collision.parent_path for collision in collisions)
        )
        parent_rows = resolve_raw_paths(self._session, fence.library_id, parent_paths)
        for collision in collisions:
            parent = parent_rows.get(collision.parent_path)
            if parent is None:
                raise ScanStale()
            parent_id = parent.id
            collision_group_id = _stable_id(
                "collision_group",
                fence.library_id,
                fence.scan_id,
                parent_id,
                collision.comparison_key,
            )
            evidence: dict[str, object] = {
                "collisionGroupId": collision_group_id,
                "comparisonKey": collision.comparison_key,
                "peerCount": len(collision.related_paths),
            }
            for path in collision.related_paths:
                collision_id = _stable_id(
                    "collision",
                    fence.library_id,
                    fence.scan_id,
                    parent_id,
                    collision.comparison_key,
                    path[-1],
                )
                prepared.append((collision_id, parent_id, path[-1], evidence))
        existing: dict[str, PathCollisionObservation] = {}
        prepared_ids = tuple(row[0] for row in prepared)
        for offset in range(0, len(prepared_ids), _SOURCE_PREFETCH_CHUNK):
            existing.update(
                (
                    row.id,
                    row,
                )
                for row in self._session.scalars(
                    select(PathCollisionObservation).where(
                        PathCollisionObservation.id.in_(
                            prepared_ids[offset : offset + _SOURCE_PREFETCH_CHUNK]
                        )
                    )
                )
            )
        new_rows: list[PathCollisionObservation] = []
        for collision_id, parent_id, local_name, evidence in prepared:
            row = existing.get(collision_id)
            if row is None:
                new_rows.append(
                    PathCollisionObservation(
                        id=collision_id,
                        library_id=fence.library_id,
                        scan_run_id=fence.scan_id,
                        parent_entry_id=parent_id,
                        local_name=local_name,
                        local_name_key=cast(str, evidence["comparisonKey"]),
                        evidence=evidence,
                        observed_at=observed_at,
                    )
                )
            else:
                row.evidence = evidence
                row.observed_at = observed_at
        self._session.add_all(new_rows)
        self._session.flush()


class SqlAlchemyScanDiagnosticRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        fence: ScanFence,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None:
        _require_live_fence(self._session, fence, now=observed_at)
        new_rows: dict[str, LayoutDiagnostic] = {}
        for diagnostic in diagnostics:
            code = _enum_value(diagnostic.code)
            scope = "/".join(diagnostic.unit_path)
            related = tuple("/".join(path) for path in diagnostic.related_paths)
            related_digest = hashlib.sha256(
                "\0".join(related).encode("utf-8")
            ).hexdigest()
            diagnostic_id = _stable_id(
                "diagnostic",
                fence.library_id,
                str(fence.generation),
                scope,
                code,
                related_digest,
            )
            row = new_rows.get(diagnostic_id)
            if row is None:
                row = self._session.get(LayoutDiagnostic, diagnostic_id)
            parameters: dict[str, object] = {
                "relatedPaths": list(related[:_DIAGNOSTIC_RELATED_PATH_LIMIT]),
                "relatedPathCount": len(related),
                "relatedPathsDigest": related_digest,
            }
            if row is None:
                row = LayoutDiagnostic(
                    id=diagnostic_id,
                    library_id=fence.library_id,
                    scan_run_id=fence.scan_id,
                    generation=fence.generation,
                    config_revision=fence.config_revision,
                    scope_relative_path=scope,
                    code=code,
                    severity="WARNING",
                    parameters=parameters,
                    first_observed_at=observed_at,
                    last_observed_at=observed_at,
                )
                new_rows[diagnostic_id] = row
            else:
                row.last_observed_at = observed_at
                row.resolved_at = None
                row.parameters = parameters
        self._session.add_all(new_rows.values())
        self._session.flush()


__all__ = [
    "SqlAlchemyPathCollisionRepository",
    "SqlAlchemyScanDiagnosticRepository",
    "SqlAlchemySourceObservationRepository",
]
