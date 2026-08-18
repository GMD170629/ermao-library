"""Targeted reconciliation persistence for stable SourceEntry identities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select, tuple_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased

from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    PathCollision,
    ScanFence,
    SourceObservationOutcome,
    SourcePathBinding,
)
from app.modules.catalog.application.watcher_dto import (
    DirectoryPresenceEpoch,
    PendingSourceObservation,
    PresenceFoldPage,
    ProvenMoveEvidence,
    ReconcileFence,
    SourceRebindDisposition,
    SourceRebindRejectionReason,
    SourceRebindResult,
)
from app.modules.catalog.domain.admission import SourceAdmissionEvidence
from app.modules.catalog.domain.ordering import natural_path_key
from app.modules.catalog.domain.watcher import ReconcileStale

from .enums import LayoutState, SlotState, SourceEntryType
from .models import LibrarySourceEntry
from .reconcile_fencing import require_live_reconcile
from .scan_fencing import comparison_components
from .source_path_resolution import (
    SOURCE_QUERY_CHUNK,
    new_opaque_source_id,
    paths_with_ancestors,
    resolve_raw_paths,
)

_PEER_LIMIT = 100


@dataclass(frozen=True, slots=True)
class _PreparedObservation:
    pending: PendingSourceObservation
    entry_id: str
    parent_id: str
    local_name: str
    local_name_key: str


def _binding(path: tuple[str, ...], row: LibrarySourceEntry) -> SourcePathBinding:
    return SourcePathBinding(
        relative_path=path,
        source_entry_id=row.id,
        filesystem_identity=row.filesystem_identity,
        pending_parent_presence_epoch=None,
    )


def _rejected(reason: SourceRebindRejectionReason) -> SourceRebindResult:
    return SourceRebindResult(
        disposition=SourceRebindDisposition.NOT_PROVEN,
        binding=None,
        rejection_reason=reason,
    )


def _is_effectively_present(
    session: Session,
    row: LibrarySourceEntry,
    *,
    generation: int,
) -> bool:
    current = row
    visited: set[str] = set()
    while True:
        if (
            current.id in visited
            or current.slot_state is SlotState.RETIRED
            or current.slot_state is not SlotState.ACTIVE
            or current.layout_state is not LayoutState.PRESENT
            or current.absence_confirmed_at is not None
            or current.last_seen_generation != generation
        ):
            return False
        visited.add(current.id)
        if current.parent_entry_id is None:
            return current.entry_type is SourceEntryType.SYNTHETIC_ROOT
        parent = session.get(LibrarySourceEntry, current.parent_entry_id)
        if parent is None or parent.library_id != current.library_id:
            return False
        if (
            current.observed_parent_presence_epoch != parent.children_presence_epoch
            and current.pending_observed_parent_presence_epoch
            != parent.children_presence_epoch
        ):
            return False
        current = parent


class SqlAlchemyReconcileSourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_synthetic_root_identity(self, library_id: str) -> str | None:
        return self._session.scalar(
            select(LibrarySourceEntry.filesystem_identity).where(
                LibrarySourceEntry.library_id == library_id,
                LibrarySourceEntry.parent_entry_id.is_(None),
                LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
                LibrarySourceEntry.slot_state != SlotState.RETIRED,
            )
        )

    def resolve_path_bindings(
        self,
        fence: ScanFence | ReconcileFence,
        relative_paths: tuple[tuple[str, ...], ...],
    ) -> tuple[SourcePathBinding, ...]:
        rows = resolve_raw_paths(self._session, fence.library_id, relative_paths)
        return tuple(
            _binding(path, rows[path]) for path in relative_paths if path in rows
        )

    def apply_proven_move(
        self,
        fence: ReconcileFence,
        evidence: ProvenMoveEvidence,
        *,
        observed_at: datetime,
    ) -> SourceRebindResult:
        require_live_reconcile(self._session, fence, now=observed_at)
        paths = (evidence.source_path, evidence.destination_path)
        resolved = resolve_raw_paths(
            self._session,
            fence.library_id,
            paths_with_ancestors(paths),
        )
        source = resolved.get(evidence.source_path)
        if source is None:
            return _rejected(SourceRebindRejectionReason.SOURCE_NOT_FOUND)
        if source.filesystem_identity != evidence.filesystem_identity:
            return _rejected(SourceRebindRejectionReason.IDENTITY_MISMATCH)
        if source.entry_type.value != evidence.entry_type.value:
            return _rejected(SourceRebindRejectionReason.IDENTITY_MISMATCH)
        if not _is_effectively_present(
            self._session,
            source,
            generation=fence.presence_generation,
        ):
            return _rejected(SourceRebindRejectionReason.SOURCE_NOT_FOUND)

        identity_peers = tuple(
            self._session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.filesystem_identity
                    == evidence.filesystem_identity,
                    LibrarySourceEntry.id != source.id,
                    LibrarySourceEntry.slot_state != SlotState.RETIRED,
                    LibrarySourceEntry.absence_confirmed_at.is_(None),
                    LibrarySourceEntry.last_seen_generation
                    == fence.presence_generation,
                )
                .order_by(LibrarySourceEntry.id)
                .limit(_PEER_LIMIT + 1)
                .with_for_update()
            )
        )
        if len(identity_peers) > _PEER_LIMIT:
            return _rejected(SourceRebindRejectionReason.IDENTITY_AMBIGUOUS)
        if any(
            _is_effectively_present(
                self._session,
                peer,
                generation=fence.presence_generation,
            )
            for peer in identity_peers
        ):
            return _rejected(SourceRebindRejectionReason.IDENTITY_AMBIGUOUS)

        destination_parent_path = evidence.destination_path[:-1]
        parent_rows = resolve_raw_paths(
            self._session, fence.library_id, (destination_parent_path,)
        )
        destination_parent = parent_rows.get(destination_parent_path)
        if destination_parent is None or destination_parent.entry_type not in {
            SourceEntryType.SYNTHETIC_ROOT,
            SourceEntryType.DIRECTORY,
        }:
            return _rejected(SourceRebindRejectionReason.TARGET_COLLISION)
        if not _is_effectively_present(
            self._session,
            destination_parent,
            generation=fence.presence_generation,
        ):
            return _rejected(SourceRebindRejectionReason.TARGET_COLLISION)
        local_name = evidence.destination_path[-1]
        local_name_key = comparison_components((local_name,), fence.path_comparison)[0]
        normalized_peers = tuple(
            self._session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.parent_entry_id == destination_parent.id,
                    LibrarySourceEntry.local_name_key == local_name_key,
                    LibrarySourceEntry.id != source.id,
                    LibrarySourceEntry.slot_state != SlotState.RETIRED,
                )
                .order_by(LibrarySourceEntry.id)
                .limit(_PEER_LIMIT + 1)
                .with_for_update()
            )
        )
        if len(normalized_peers) > _PEER_LIMIT:
            return _rejected(SourceRebindRejectionReason.TARGET_COLLISION)
        exact_target = next(
            (row for row in normalized_peers if row.local_name == local_name), None
        )
        if any(row.local_name != local_name for row in normalized_peers):
            return _rejected(SourceRebindRejectionReason.TARGET_COLLISION)

        disposition = SourceRebindDisposition.PRESERVED_MOVED_ID
        if exact_target is not None:
            exact_target.slot_state = SlotState.RETIRED
            exact_target.layout_state = LayoutState.INVALID
            exact_target.updated_at = observed_at
            disposition = SourceRebindDisposition.RETIRED_TARGET_AND_PRESERVED_MOVED_ID
            self._session.flush()

        source.parent_entry_id = destination_parent.id
        source.local_name = local_name
        source.local_name_key = local_name_key
        source.absence_confirmed_at = None
        source.last_seen_generation = fence.presence_generation
        source.observed_parent_presence_epoch = (
            destination_parent.children_presence_epoch
        )
        source.pending_observed_parent_presence_epoch = None
        source.layout_state = LayoutState.PRESENT
        source.slot_state = SlotState.ACTIVE
        source.updated_at = observed_at
        self._session.flush()
        return SourceRebindResult(
            disposition=disposition,
            binding=_binding(evidence.destination_path, source),
            rejection_reason=None,
        )

    def begin_directory_presence(
        self,
        fence: ReconcileFence,
        directory: SourcePathBinding,
        *,
        observed_at: datetime,
    ) -> DirectoryPresenceEpoch:
        require_live_reconcile(self._session, fence, now=observed_at)
        row = self._session.scalar(
            select(LibrarySourceEntry)
            .where(
                LibrarySourceEntry.id == directory.source_entry_id,
                LibrarySourceEntry.library_id == fence.library_id,
                LibrarySourceEntry.entry_type.in_(
                    (SourceEntryType.SYNTHETIC_ROOT, SourceEntryType.DIRECTORY)
                ),
                LibrarySourceEntry.filesystem_identity == directory.filesystem_identity,
            )
            .with_for_update()
        )
        if row is None:
            raise ReconcileStale()
        if (
            row.slot_state is not SlotState.ACTIVE
            or row.layout_state is not LayoutState.PRESENT
            or row.absence_confirmed_at is not None
            or row.last_seen_generation != fence.presence_generation
        ):
            raise ReconcileStale()
        if row.parent_entry_id is None:
            if (
                row.entry_type is not SourceEntryType.SYNTHETIC_ROOT
                or directory.pending_parent_presence_epoch is not None
            ):
                raise ReconcileStale()
        else:
            parent = self._session.get(LibrarySourceEntry, row.parent_entry_id)
            if (
                parent is None
                or parent.library_id != fence.library_id
                or parent.entry_type
                not in {SourceEntryType.SYNTHETIC_ROOT, SourceEntryType.DIRECTORY}
            ):
                raise ReconcileStale()
            effective = (
                row.observed_parent_presence_epoch == parent.children_presence_epoch
                or row.pending_observed_parent_presence_epoch
                == parent.children_presence_epoch
            )
            future_proven = (
                directory.pending_parent_presence_epoch is not None
                and directory.pending_parent_presence_epoch
                == row.pending_observed_parent_presence_epoch
                == parent.next_children_presence_epoch
                and parent.next_children_presence_epoch > parent.children_presence_epoch
            )
            if not effective and not future_proven:
                raise ReconcileStale()
        base_epoch = row.children_presence_epoch
        proposed_epoch = row.next_children_presence_epoch + 1
        result = self._session.execute(
            update(LibrarySourceEntry)
            .where(
                LibrarySourceEntry.id == row.id,
                LibrarySourceEntry.library_id == fence.library_id,
                LibrarySourceEntry.children_presence_epoch == base_epoch,
                LibrarySourceEntry.next_children_presence_epoch
                == row.next_children_presence_epoch,
            )
            .values(
                next_children_presence_epoch=proposed_epoch,
                updated_at=observed_at,
            )
        )
        if cast(CursorResult[object], result).rowcount != 1:
            raise ReconcileStale()
        return DirectoryPresenceEpoch(
            directory=directory,
            base_epoch=base_epoch,
            proposed_epoch=proposed_epoch,
        )

    def upsert_reconcile_observations(
        self,
        fence: ReconcileFence,
        observations: tuple[PendingSourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome:
        require_live_reconcile(self._session, fence, now=observed_at)
        prepared = self._prepare_observations(fence, observations)
        existing_by_id, slot_rows_by_key = self._prefetch(fence, prepared)
        original_states = {row.id: row.slot_state for row in existing_by_id.values()}
        collisions: dict[tuple[tuple[str, ...], str], set[tuple[str, ...]]] = {}
        new_rows: list[LibrarySourceEntry] = []
        for value in prepared:
            source_observation = value.pending.observation
            source = source_observation.source
            path = source.relative_path
            parent = existing_by_id.get(value.parent_id)
            if parent is None or parent.entry_type not in {
                SourceEntryType.SYNTHETIC_ROOT,
                SourceEntryType.DIRECTORY,
            }:
                raise ReconcileStale()
            pending_epoch = value.pending.pending_parent_epoch
            if parent.entry_type is SourceEntryType.SYNTHETIC_ROOT:
                valid_parent_epoch = pending_epoch is None
            else:
                valid_parent_epoch = (
                    pending_epoch is not None
                    and pending_epoch == parent.next_children_presence_epoch
                    and pending_epoch > parent.children_presence_epoch
                )
            if not valid_parent_epoch:
                raise ReconcileStale()
            current = existing_by_id.get(value.entry_id)
            slot_key = (value.parent_id, value.local_name_key)
            peers = tuple(
                row
                for row in slot_rows_by_key[slot_key]
                if row.id != value.entry_id and row.slot_state != SlotState.RETIRED
            )
            is_collision = bool(peers)
            if is_collision:
                related = collisions.setdefault(
                    (path[:-1], value.local_name_key), {path}
                )
                for peer in peers:
                    peer.layout_state = LayoutState.INVALID
                    peer.slot_state = SlotState.COLLIDING
                    peer.updated_at = observed_at
                    related.add((*path[:-1], peer.local_name))
            is_present = source.entry_type is DiscoveryEntryType.DIRECTORY or (
                source.entry_type is DiscoveryEntryType.FILE
                and isinstance(source_observation.admission, SourceAdmissionEvidence)
            )
            layout_state = (
                LayoutState.PRESENT
                if is_present and not is_collision
                else LayoutState.INVALID
            )
            slot_state = SlotState.COLLIDING if is_collision else SlotState.ACTIVE
            expectation = source.expected_stat
            if current is None:
                current = LibrarySourceEntry(
                    id=value.entry_id,
                    library_id=fence.library_id,
                    parent_entry_id=value.parent_id,
                    local_name=value.local_name,
                    local_name_key=value.local_name_key,
                    entry_type=SourceEntryType(source.entry_type.value),
                    filesystem_identity=source.filesystem_identity,
                    size_bytes=None if expectation is None else expectation.size_bytes,
                    modified_ns=None
                    if expectation is None
                    else expectation.modified_ns,
                    last_seen_generation=fence.presence_generation,
                    absence_confirmed_at=None,
                    children_presence_epoch=0,
                    next_children_presence_epoch=0,
                    observed_parent_presence_epoch=(
                        parent.children_presence_epoch
                        if pending_epoch is None
                        else None
                    ),
                    pending_observed_parent_presence_epoch=pending_epoch,
                    layout_state=layout_state,
                    slot_state=slot_state,
                    created_at=observed_at,
                    updated_at=observed_at,
                )
                new_rows.append(current)
                existing_by_id[current.id] = current
                slot_rows_by_key[slot_key].append(current)
            else:
                current.entry_type = SourceEntryType(source.entry_type.value)
                current.filesystem_identity = source.filesystem_identity
                current.size_bytes = (
                    None if expectation is None else expectation.size_bytes
                )
                current.modified_ns = (
                    None if expectation is None else expectation.modified_ns
                )
                current.last_seen_generation = fence.presence_generation
                current.absence_confirmed_at = None
                if pending_epoch is None:
                    current.observed_parent_presence_epoch = (
                        parent.children_presence_epoch
                    )
                    current.pending_observed_parent_presence_epoch = None
                else:
                    current.pending_observed_parent_presence_epoch = pending_epoch
                current.layout_state = layout_state
                current.slot_state = slot_state
                current.updated_at = observed_at

        deferred: list[LibrarySourceEntry] = []
        for row in existing_by_id.values():
            original = original_states.get(row.id)
            if (
                original is not None
                and original is not SlotState.ACTIVE
                and row.slot_state is SlotState.ACTIVE
            ):
                deferred.append(row)
                row.slot_state = original
        self._session.flush()
        self._session.add_all(new_rows)
        for row in deferred:
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
                    collisions.items(),
                    key=lambda item: (
                        natural_path_key(item[0][0], fence.path_comparison),
                        item[0][1],
                    ),
                )
            ),
            bindings=tuple(
                SourcePathBinding(
                    relative_path=value.pending.observation.source.relative_path,
                    source_entry_id=value.entry_id,
                    filesystem_identity=(
                        value.pending.observation.source.filesystem_identity
                    ),
                    pending_parent_presence_epoch=(value.pending.pending_parent_epoch),
                )
                for value in prepared
            ),
        )

    def flip_directory_presence(
        self,
        fence: ReconcileFence,
        epoch: DirectoryPresenceEpoch,
        *,
        completed_at: datetime,
    ) -> bool:
        require_live_reconcile(self._session, fence, now=completed_at)
        result = self._session.execute(
            update(LibrarySourceEntry)
            .where(
                LibrarySourceEntry.id == epoch.directory.source_entry_id,
                LibrarySourceEntry.library_id == fence.library_id,
                LibrarySourceEntry.children_presence_epoch == epoch.base_epoch,
                LibrarySourceEntry.next_children_presence_epoch == epoch.proposed_epoch,
                LibrarySourceEntry.filesystem_identity
                == epoch.directory.filesystem_identity,
            )
            .values(
                children_presence_epoch=epoch.proposed_epoch,
                updated_at=completed_at,
            )
        )
        return cast(CursorResult[object], result).rowcount == 1

    def confirm_top_level_absent(
        self,
        fence: ReconcileFence,
        relative_path: tuple[str, ...],
        *,
        confirmed_at: datetime,
    ) -> None:
        require_live_reconcile(self._session, fence, now=confirmed_at)
        if len(relative_path) != 1:
            raise ValueError("absence confirmation is limited to one top-level scope")
        row = resolve_raw_paths(self._session, fence.library_id, (relative_path,)).get(
            relative_path
        )
        if row is None:
            return
        row.absence_confirmed_at = confirmed_at
        row.layout_state = LayoutState.INVALID
        row.updated_at = confirmed_at
        self._session.flush()

    def exclude_observed_top_level(
        self,
        fence: ReconcileFence,
        source: DiscoveredSource,
        *,
        excluded_at: datetime,
    ) -> None:
        require_live_reconcile(self._session, fence, now=excluded_at)
        if len(source.relative_path) != 1:
            raise ValueError("catalog exclusion is limited to one top-level scope")
        row = resolve_raw_paths(
            self._session,
            fence.library_id,
            (source.relative_path,),
        ).get(source.relative_path)
        if row is None:
            return
        root = self._session.get(LibrarySourceEntry, row.parent_entry_id)
        if (
            root is None
            or root.library_id != fence.library_id
            or root.entry_type is not SourceEntryType.SYNTHETIC_ROOT
            or root.filesystem_identity != fence.root_identity
        ):
            raise ReconcileStale()
        expectation = source.expected_stat
        row.entry_type = SourceEntryType(source.entry_type.value)
        row.filesystem_identity = source.filesystem_identity
        row.size_bytes = None if expectation is None else expectation.size_bytes
        row.modified_ns = None if expectation is None else expectation.modified_ns
        row.last_seen_generation = fence.presence_generation
        row.absence_confirmed_at = None
        row.observed_parent_presence_epoch = root.children_presence_epoch
        row.pending_observed_parent_presence_epoch = None
        row.layout_state = LayoutState.INVALID
        row.updated_at = excluded_at
        self._session.flush()

    def fold_effective_presence(
        self,
        fence: ReconcileFence,
        *,
        after_source_entry_id: str | None,
        limit: int,
        folded_at: datetime,
    ) -> PresenceFoldPage:
        if not 1 <= limit <= 5_000:
            raise ValueError("presence fold limit must be between 1 and 5000")
        require_live_reconcile(self._session, fence, now=folded_at)
        parent = aliased(LibrarySourceEntry)
        statement = (
            select(LibrarySourceEntry.id)
            .join(parent, parent.id == LibrarySourceEntry.parent_entry_id)
            .where(
                LibrarySourceEntry.library_id == fence.library_id,
                parent.library_id == fence.library_id,
                LibrarySourceEntry.pending_observed_parent_presence_epoch
                == parent.children_presence_epoch,
            )
            .order_by(LibrarySourceEntry.id)
            .limit(limit + 1)
        )
        if after_source_entry_id is not None:
            statement = statement.where(LibrarySourceEntry.id > after_source_entry_id)
        selected = tuple(self._session.scalars(statement).all())
        page_ids = selected[:limit]
        if page_ids:
            self._session.execute(
                update(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.id.in_(page_ids),
                )
                .values(
                    observed_parent_presence_epoch=LibrarySourceEntry.pending_observed_parent_presence_epoch,
                    pending_observed_parent_presence_epoch=None,
                    updated_at=folded_at,
                )
            )
        complete = len(selected) <= limit
        return PresenceFoldPage(
            folded_count=len(page_ids),
            next_source_entry_id=None if complete or not page_ids else page_ids[-1],
            complete=complete,
        )

    def _prepare_observations(
        self,
        fence: ReconcileFence,
        observations: tuple[PendingSourceObservation, ...],
    ) -> tuple[_PreparedObservation, ...]:
        sorted_observations = sorted(
            observations,
            key=lambda value: (
                len(value.observation.source.relative_path),
                value.observation.source.relative_path,
            ),
        )
        paths = tuple(
            dict.fromkeys(
                value.observation.source.relative_path for value in sorted_observations
            )
        )
        resolved = resolve_raw_paths(
            self._session,
            fence.library_id,
            paths_with_ancestors(paths),
        )
        root = resolve_raw_paths(self._session, fence.library_id, ((),)).get(())
        if root is None or root.filesystem_identity != fence.root_identity:
            raise ReconcileStale()
        path_ids: dict[tuple[str, ...], str] = {(): root.id}
        path_ids.update((path, row.id) for path, row in resolved.items())
        prepared: dict[tuple[str, ...], _PreparedObservation] = {}
        for pending in sorted_observations:
            observation = pending.observation
            if observation.generation != fence.presence_generation:
                raise ReconcileStale()
            path = observation.source.relative_path
            parent_id = path_ids.get(path[:-1])
            if parent_id is None:
                raise ReconcileStale()
            entry_id = path_ids.get(path)
            if entry_id is None:
                entry_id = new_opaque_source_id()
                path_ids[path] = entry_id
            local_name = path[-1]
            prepared[path] = _PreparedObservation(
                pending=pending,
                entry_id=entry_id,
                parent_id=parent_id,
                local_name=local_name,
                local_name_key=comparison_components(
                    (local_name,), fence.path_comparison
                )[0],
            )
        return tuple(prepared.values())

    def _prefetch(
        self,
        fence: ReconcileFence,
        prepared: tuple[_PreparedObservation, ...],
    ) -> tuple[
        dict[str, LibrarySourceEntry],
        dict[tuple[str, str], list[LibrarySourceEntry]],
    ]:
        existing: dict[str, LibrarySourceEntry] = {}
        entry_ids = tuple(
            dict.fromkeys(
                source_id
                for value in prepared
                for source_id in (value.entry_id, value.parent_id)
            )
        )
        for offset in range(0, len(entry_ids), SOURCE_QUERY_CHUNK):
            for row in self._session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    LibrarySourceEntry.id.in_(
                        entry_ids[offset : offset + SOURCE_QUERY_CHUNK]
                    ),
                )
                .with_for_update()
            ):
                existing[row.id] = row
        slot_keys = tuple(
            dict.fromkeys((value.parent_id, value.local_name_key) for value in prepared)
        )
        slots: dict[tuple[str, str], list[LibrarySourceEntry]] = {
            key: [] for key in slot_keys
        }
        for offset in range(0, len(slot_keys), SOURCE_QUERY_CHUNK):
            for row in self._session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == fence.library_id,
                    tuple_(
                        LibrarySourceEntry.parent_entry_id,
                        LibrarySourceEntry.local_name_key,
                    ).in_(slot_keys[offset : offset + SOURCE_QUERY_CHUNK]),
                )
                .with_for_update()
            ):
                existing.setdefault(row.id, row)
                if row.parent_entry_id is not None:
                    slots[(row.parent_entry_id, row.local_name_key)].append(row)
        return existing, slots


__all__ = ["SqlAlchemyReconcileSourceRepository"]
