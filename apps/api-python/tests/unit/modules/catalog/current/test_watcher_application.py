from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self

import pytest

from app.modules.catalog.application.ports import OutboxEvent
from app.modules.catalog.application.scan_dto import ScanLibrarySnapshot
from app.modules.catalog.application.watcher_dto import (
    FullRescanTransition,
    ReconcileIntent,
    ReconcileIntentPhase,
    ReconcileIntentState,
    RecordWatcherEventCommand,
    WatcherIngestDisposition,
    WatcherState,
)
from app.modules.catalog.application.watcher_ingestion import RecordWatcherEvent
from app.modules.catalog.domain.library import LibraryControlState, LibraryHealth
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.watcher import (
    FullRescanReason,
    ReconcileMoveEvidence,
    ReconcileScope,
    WatcherEntryHint,
    WatcherEvent,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherPathEventKind,
    WatcherStale,
    WatcherTrustLost,
    WatcherTrustLostReason,
    reconcile_scope,
)

NOW = datetime(2026, 8, 18, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def __init__(self) -> None:
        self.next_value = 0

    def new_id(self) -> str:
        self.next_value += 1
        return f"intent-new-{self.next_value}"


class _Outbox:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    def append(self, event: OutboxEvent) -> None:
        self.events.append(event)


def _library(
    state: LibraryControlState = LibraryControlState.ACTIVE,
) -> ScanLibrarySnapshot:
    return ScanLibrarySnapshot(
        library_id="library-1",
        canonical_root="/library",
        organization_mode=OrganizationMode.VOLUMES,
        topology_version=1,
        path_comparison=PathComparison.INSENSITIVE,
        control_state=state,
        observed_health=LibraryHealth.HEALTHY,
        config_revision=1,
        topology_writer_fence=4,
        next_scan_generation=2,
        last_successful_generation=1,
    )


def _intent(
    intent_id: str,
    *,
    sequence: int,
    scopes: tuple[ReconcileScope, ...],
    state: ReconcileIntentState = ReconcileIntentState.PENDING,
) -> ReconcileIntent:
    running = state is ReconcileIntentState.RUNNING
    return ReconcileIntent(
        intent_id=intent_id,
        library_id="library-1",
        first_sequence=sequence,
        through_sequence=sequence,
        scopes=scopes,
        move_evidence=None,
        state=state,
        phase=ReconcileIntentPhase.EXECUTE,
        lease_owner="old-worker" if running else None,
        lease_expires_at=NOW + timedelta(seconds=60) if running else None,
        topology_writer_fence=4 if running else None,
        attempt=1 if running else 0,
        available_at=NOW,
        fold_after_source_entry_id=None,
        config_revision=1,
        organization_mode=OrganizationMode.VOLUMES,
        topology_version=1,
        path_comparison=PathComparison.INSENSITIVE,
        root_path_snapshot="/library",
        root_identity_snapshot="dev:root",
        created_at=NOW,
        updated_at=NOW,
    )


class _Store:
    def __init__(
        self,
        *,
        library: ScanLibrarySnapshot | None = None,
        pending: tuple[ReconcileIntent, ...] = (),
        running: ReconcileIntent | None = None,
    ) -> None:
        self.library = library or _library()
        self.state = WatcherState("library-1", 0, None, None)
        self.pending = list(pending)
        self.running = running
        self.root_identity = "dev:root"
        self.outbox = _Outbox()
        self.libraries = self
        self.watcher = self
        self.sources = self
        self.topology = None
        self.diagnostics = None
        self.commits = 0
        self.rollbacks = 0

    def get_for_reconcile_for_update(
        self, library_id: str
    ) -> ScanLibrarySnapshot | None:
        return self.library if library_id == self.library.library_id else None

    def get_state_for_update(self, library_id: str) -> WatcherState | None:
        return self.state if library_id == self.state.library_id else None

    def get_synthetic_root_identity(self, library_id: str) -> str | None:
        return self.root_identity if library_id == self.library.library_id else None

    def find_overlapping_pending(
        self,
        library_id: str,
        scopes: tuple[ReconcileScope, ...],
        *,
        limit: int,
    ) -> tuple[ReconcileIntent, ...]:
        assert library_id == self.library.library_id
        keys = {scope.comparison_key for scope in scopes}
        return tuple(
            intent
            for intent in self.pending
            if keys.intersection(scope.comparison_key for scope in intent.scopes)
        )[:limit]

    def pending_ids_up_to(self, library_id: str, *, limit: int) -> tuple[str, ...]:
        assert library_id == self.library.library_id
        return tuple(intent.intent_id for intent in self.pending[:limit])

    def append_or_replace(
        self,
        *,
        expected_latest_sequence: int,
        intent: ReconcileIntent,
        replaced_intent_ids: tuple[str, ...],
    ) -> ReconcileIntent | None:
        if self.state.latest_sequence != expected_latest_sequence:
            return None
        self.pending = [
            value
            for value in self.pending
            if value.intent_id not in replaced_intent_ids
        ]
        self.pending.append(intent)
        self.state = replace(self.state, latest_sequence=intent.through_sequence)
        return intent

    def force_full_rescan(
        self,
        library_id: str,
        *,
        expected_latest_sequence: int,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        assert observed_at == NOW and library_id == self.library.library_id
        if self.state.latest_sequence != expected_latest_sequence:
            return None
        sequence = expected_latest_sequence + 1
        newly_required = self.state.full_rescan_reason is None
        retained_reason = self.state.full_rescan_reason or reason
        invalidated = self.running.intent_id if self.running is not None else None
        if self.running is not None:
            self.library = replace(
                self.library,
                topology_writer_fence=self.library.topology_writer_fence + 1,
            )
        self.pending.clear()
        self.running = None
        self.state = WatcherState(
            library_id,
            sequence,
            sequence,
            retained_reason,
        )
        return FullRescanTransition(
            self.state,
            newly_required=newly_required,
            invalidated_running_intent_id=invalidated,
            topology_writer_fence=self.library.topology_writer_fence,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is not None:
            self.rollbacks += 1
        return False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _record(store: _Store, event: WatcherEvent) -> object:
    return RecordWatcherEvent(
        unit_of_work_factory=lambda: store,
        id_generator=_Ids(),
        clock=_Clock(),
    ).execute(RecordWatcherEventCommand("library-1", "dev:root", event))


@pytest.mark.parametrize(
    "state",
    (
        LibraryControlState.ACTIVATING,
        LibraryControlState.ACTIVE,
        LibraryControlState.PAUSED,
    ),
)
def test_record_journals_while_activating_active_or_paused(
    state: LibraryControlState,
) -> None:
    store = _Store(library=_library(state))

    result = _record(
        store,
        WatcherPathEvent(
            WatcherPathEventKind.CREATE,
            ("Work", "book.epub"),
            WatcherEntryHint.FILE,
        ),
    )

    assert result.disposition is WatcherIngestDisposition.QUEUED
    assert result.sequence == 1
    assert store.pending[0].scopes[0].relative_path == ("Work",)
    assert all("Work" not in repr(event.payload) for event in store.outbox.events)
    assert dict(store.outbox.events[0].payload) == {"sequence": 1}


@pytest.mark.parametrize(
    "state",
    (LibraryControlState.DRAFT, LibraryControlState.REMOVING),
)
def test_record_rejects_non_watchable_library_states(
    state: LibraryControlState,
) -> None:
    store = _Store(library=_library(state))

    with pytest.raises(WatcherStale):
        _record(
            store,
            WatcherPathEvent(
                WatcherPathEventKind.MODIFY,
                ("Work",),
                WatcherEntryHint.DIRECTORY,
            ),
        )

    assert store.rollbacks == 1
    assert store.pending == []


def test_record_coalesces_same_scope_and_preserves_first_sequence() -> None:
    scope = reconcile_scope(("Work",), PathComparison.INSENSITIVE)
    existing = _intent("intent-1", sequence=1, scopes=(scope,))
    store = _Store(pending=(existing,))
    store.state = WatcherState("library-1", 1, None, None)

    result = _record(
        store,
        WatcherPathEvent(
            WatcherPathEventKind.MODIFY,
            ("work", "chapter.epub"),
            WatcherEntryHint.FILE,
        ),
    )

    assert result.disposition is WatcherIngestDisposition.COALESCED
    assert len(store.pending) == 1
    assert store.pending[0].first_sequence == 1
    assert store.pending[0].through_sequence == 2


def test_third_raw_scope_becomes_constant_full_scan_fence() -> None:
    move = WatcherMoveEvent(
        ("a", "old.epub"),
        ("b", "new.epub"),
        WatcherMovedEntryType.FILE,
    )
    store = _Store()
    _record(store, move)

    result = _record(
        store,
        WatcherMoveEvent(
            ("b", "new.epub"),
            ("c", "new.epub"),
            WatcherMovedEntryType.FILE,
        ),
    )

    assert result.disposition is WatcherIngestDisposition.FULL_SCAN_REQUIRED
    assert result.full_rescan_reason is FullRescanReason.JOURNAL_CAPACITY
    assert store.pending == []


@pytest.mark.parametrize("move_first", (True, False))
def test_coalescing_preserves_the_only_move_proof(move_first: bool) -> None:
    move = WatcherMoveEvent(
        ("a", "old.epub"),
        ("b", "new.epub"),
        WatcherMovedEntryType.FILE,
    )
    modify = WatcherPathEvent(
        WatcherPathEventKind.MODIFY,
        ("a", "metadata.opf"),
        WatcherEntryHint.FILE,
    )
    store = _Store()

    _record(store, move if move_first else modify)
    _record(store, modify if move_first else move)

    assert store.pending[0].move_evidence == ReconcileMoveEvidence(
        move.source_path,
        move.destination_path,
        move.entry_type,
    )


def test_duplicate_move_keeps_proof_but_distinct_move_clears_it() -> None:
    first = WatcherMoveEvent(
        ("a", "old.epub"),
        ("b", "new.epub"),
        WatcherMovedEntryType.FILE,
    )
    distinct = WatcherMoveEvent(
        ("a", "other-old.epub"),
        ("b", "other-new.epub"),
        WatcherMovedEntryType.FILE,
    )
    store = _Store()

    _record(store, first)
    _record(store, first)
    assert store.pending[0].move_evidence is not None

    result = _record(store, distinct)

    assert result.disposition is WatcherIngestDisposition.COALESCED
    assert store.pending[0].move_evidence is None
    assert store.state.full_rescan_reason is None


def test_trust_loss_invalidates_only_a_running_reconcile_writer() -> None:
    store_without_reconcile = _Store()
    original_fence = store_without_reconcile.library.topology_writer_fence

    _record(
        store_without_reconcile,
        WatcherTrustLost(WatcherTrustLostReason.BACKEND_OVERFLOW),
    )

    assert store_without_reconcile.library.topology_writer_fence == original_fence

    running = _intent(
        "intent-running",
        sequence=1,
        scopes=(reconcile_scope(("Work",), PathComparison.INSENSITIVE),),
        state=ReconcileIntentState.RUNNING,
    )
    store_with_reconcile = _Store(running=running)
    _record(
        store_with_reconcile,
        WatcherTrustLost(WatcherTrustLostReason.DISCONNECTED),
    )

    assert store_with_reconcile.library.topology_writer_fence == 5
    assert store_with_reconcile.running is None


def test_existing_full_scan_fence_advances_without_duplicate_outbox() -> None:
    store = _Store()
    _record(
        store,
        WatcherTrustLost(WatcherTrustLostReason.BACKEND_OVERFLOW),
    )

    result = _record(
        store,
        WatcherPathEvent(
            WatcherPathEventKind.MODIFY,
            ("Work",),
            WatcherEntryHint.DIRECTORY,
        ),
    )

    assert result.sequence == 2
    assert result.full_rescan_reason is FullRescanReason.BACKEND_OVERFLOW
    assert [event.event_type for event in store.outbox.events] == [
        "LIBRARY_FULL_SCAN_REQUIRED"
    ]


def test_pending_cap_fences_the_2001st_event_without_double_sequence() -> None:
    pending = tuple(
        _intent(
            f"intent-{index}",
            sequence=index,
            scopes=(
                reconcile_scope(
                    (f"work-{index}",),
                    PathComparison.INSENSITIVE,
                ),
            ),
        )
        for index in range(1, 2_001)
    )
    store = _Store(pending=pending)
    store.state = WatcherState("library-1", 2_000, None, None)

    result = _record(
        store,
        WatcherPathEvent(
            WatcherPathEventKind.CREATE,
            ("new-work",),
            WatcherEntryHint.DIRECTORY,
        ),
    )

    assert result.sequence == 2_001
    assert store.state.latest_sequence == 2_001
    assert store.pending == []


def test_stale_watcher_root_identity_cannot_fence_the_current_library() -> None:
    store = _Store()

    with pytest.raises(WatcherStale):
        RecordWatcherEvent(
            unit_of_work_factory=lambda: store,
            id_generator=_Ids(),
            clock=_Clock(),
        ).execute(
            RecordWatcherEventCommand(
                "library-1",
                "dev:replacement",
                WatcherPathEvent(
                    WatcherPathEventKind.CREATE,
                    ("Work",),
                    WatcherEntryHint.DIRECTORY,
                ),
            )
        )

    assert store.state.full_rescan_reason is None
    assert store.pending == []
