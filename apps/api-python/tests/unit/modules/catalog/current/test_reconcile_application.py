from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self

import pytest

from app.modules.catalog.application import (
    reconcile_execution as reconcile_execution_module,
)
from app.modules.catalog.application.ports import OutboxEvent
from app.modules.catalog.application.reconcile_execution import (
    RunNextReconcileSubtree,
)
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryObservation,
    PathCollision,
    ScanLibrarySnapshot,
    SourceObservationOutcome,
    SourcePathBinding,
    TargetedPathAbsent,
    TargetedPathObservation,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)
from app.modules.catalog.application.watcher_dto import (
    DirectoryPresenceEpoch,
    FullRescanTransition,
    PendingSourceObservation,
    PresenceFoldPage,
    ProvenMoveEvidence,
    ReconcileIntent,
    ReconcileIntentPhase,
    ReconcileIntentState,
    ReconcileRunDisposition,
    RunNextReconcileSubtreeCommand,
    SourceRebindDisposition,
    SourceRebindRejectionReason,
    SourceRebindResult,
    WatcherState,
)
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    AudioCodec,
    AudioEvidence,
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
    SourceFormat,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule, IgnoreRuleKind
from app.modules.catalog.domain.library import LibraryControlState, LibraryHealth
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    PathComparison,
    ProbedEntry,
)
from app.modules.catalog.domain.scan import MAX_AUDIO_TRACKS, ScanDiagnostic
from app.modules.catalog.domain.watcher import (
    FullRescanReason,
    ReconcileConflict,
    ReconcileMoveEvidence,
    ReconcileScope,
    ReconcileStale,
    WatcherMovedEntryType,
    reconcile_scope,
)

NOW = datetime(2026, 8, 18, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _MonotonicClock:
    def seconds(self) -> float:
        return 0.0


class _Outbox:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    def append(self, event: OutboxEvent) -> None:
        self.events.append(event)


class _AbsentDiscovery:
    def __init__(
        self,
        *,
        root_revalidations: tuple[str, ...] = ("dev:root",),
    ) -> None:
        self._root_revalidations = list(root_revalidations)
        self.observe_calls: list[tuple[str, ...]] = []
        self.iter_calls: list[tuple[str, ...]] = []

    @property
    def root_identity(self) -> str:
        return "dev:root"

    def open(self, *, canonical_root: str) -> Self:
        assert canonical_root == "/library"
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> Literal[False]:
        return False

    def observe_path(self, relative_path: tuple[str, ...]) -> TargetedPathObservation:
        self.observe_calls.append(relative_path)
        return TargetedPathAbsent(relative_path)

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]:
        self.iter_calls.append(relative_directory)
        return iter(())

    def revalidate_root_identity(self) -> str:
        if len(self._root_revalidations) > 1:
            return self._root_revalidations.pop(0)
        return self._root_revalidations[0]


class _AdmissionMustNotRun:
    def probe(self, **_arguments: object) -> object:
        raise AssertionError("absent scopes must not be source-probed")


class _AudioAdmission:
    def __init__(self) -> None:
        self.probe_count = 0

    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionEvidence:
        assert canonical_root == "/library" and expected_stat is not None
        self.probe_count += 1
        return SourceAdmissionEvidence(
            relative_path,
            EntryType.FILE,
            AdmissionKind.AUDIO_TRACK,
            SourceFormat.MP3,
            evidence=AudioEvidence(
                SourceFormat.MP3,
                AudioCodec.MPEG_LAYER_III,
                probe_bytes_examined=16,
                probe_byte_budget=16,
            ),
        )


class _RejectedAdmission:
    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionRejection:
        assert canonical_root == "/library" and expected_stat is not None
        return SourceAdmissionRejection(
            relative_path,
            EntryType.FILE,
            AdmissionRejectionReason.UNSUPPORTED_EXTENSION,
        )


class _AudiobookDiscovery(_AbsentDiscovery):
    def __init__(self, track_count: int) -> None:
        super().__init__()
        names = (
            "A.mp3",
            "a.mp3",
            *(f"track-{index}.mp3" for index in range(2, track_count)),
        )
        self._tracks = tuple(
            DiscoveredSource(
                ("Work", name),
                DiscoveryEntryType.FILE,
                f"dev:file-{index}",
                SourceStatExpectation(1, index + 1, 16, 1),
            )
            for index, name in enumerate(names)
        )

    def observe_path(self, relative_path: tuple[str, ...]) -> TargetedPathObservation:
        self.observe_calls.append(relative_path)
        assert relative_path == ("Work",)
        return DiscoveredSource(
            relative_path,
            DiscoveryEntryType.DIRECTORY,
            "dev:work",
            None,
        )

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]:
        self.iter_calls.append(relative_directory)
        assert relative_directory == ("Work",)
        return iter(self._tracks)


class _LazyOversizedUnitDiscovery(_AbsentDiscovery):
    def __init__(self, mode: OrganizationMode, track_count: int) -> None:
        super().__init__()
        self._mode = mode
        self._track_count = track_count

    def observe_path(self, relative_path: tuple[str, ...]) -> TargetedPathObservation:
        self.observe_calls.append(relative_path)
        assert relative_path == ("Work",)
        return DiscoveredSource(
            relative_path,
            DiscoveryEntryType.DIRECTORY,
            "dev:work",
            None,
        )

    def iter_directory(
        self,
        relative_directory: tuple[str, ...],
    ) -> Iterator[DiscoveryObservation]:
        work = ("Work",)
        version = ("Work", "Version")
        volume = ("Work", "Version", "Volume")
        self.iter_calls.append(relative_directory)
        if self._mode is OrganizationMode.AUDIOBOOK and relative_directory == work:
            return (
                DiscoveredSource(
                    ("Work", f"track-{index}.mp3"),
                    DiscoveryEntryType.FILE,
                    f"dev:file-{index}",
                    SourceStatExpectation(1, index + 1, 16, 1),
                )
                for index in range(self._track_count)
            )
        if relative_directory == work:
            return iter(
                (
                    DiscoveredSource(
                        version,
                        DiscoveryEntryType.DIRECTORY,
                        "dev:version",
                        None,
                    ),
                )
            )
        if relative_directory == version:
            return iter(
                (
                    DiscoveredSource(
                        volume,
                        DiscoveryEntryType.DIRECTORY,
                        "dev:volume",
                        None,
                    ),
                )
            )
        if relative_directory == volume:
            return (
                DiscoveredSource(
                    (*volume, f"track-{index}.mp3"),
                    DiscoveryEntryType.FILE,
                    f"dev:file-{index}",
                    SourceStatExpectation(1, index + 1, 16, 1),
                )
                for index in range(self._track_count)
            )
        raise AssertionError(f"unexpected directory: {relative_directory!r}")


class _PresentDirectoryDiscovery(_AbsentDiscovery):
    def observe_path(self, relative_path: tuple[str, ...]) -> TargetedPathObservation:
        self.observe_calls.append(relative_path)
        return DiscoveredSource(
            relative_path,
            DiscoveryEntryType.DIRECTORY,
            "dev:directory",
            None,
        )


class _MoveDiscovery(_AbsentDiscovery):
    def __init__(
        self,
        *,
        source_present: bool = False,
        destination_identity: str = "dev:moved-file",
    ) -> None:
        super().__init__()
        self._source_present = source_present
        self._destination_identity = destination_identity

    def observe_path(self, relative_path: tuple[str, ...]) -> TargetedPathObservation:
        self.observe_calls.append(relative_path)
        if relative_path == ("old.bin",) and not self._source_present:
            return TargetedPathAbsent(relative_path)
        assert relative_path in {("old.bin",), ("new.bin",)}
        identity = (
            "dev:old-still-present"
            if relative_path == ("old.bin",)
            else self._destination_identity
        )
        return DiscoveredSource(
            relative_path,
            DiscoveryEntryType.FILE,
            identity,
            SourceStatExpectation(1, 1, 16, 1),
        )


def _library(
    *,
    config_revision: int = 1,
    mode: OrganizationMode = OrganizationMode.VOLUMES,
    state: LibraryControlState = LibraryControlState.ACTIVE,
    ignore_rules: tuple[IgnoreRule, ...] = (),
) -> ScanLibrarySnapshot:
    return ScanLibrarySnapshot(
        library_id="library-1",
        canonical_root="/library",
        organization_mode=mode,
        topology_version=1,
        path_comparison=PathComparison.INSENSITIVE,
        control_state=state,
        observed_health=LibraryHealth.HEALTHY,
        config_revision=config_revision,
        topology_writer_fence=4,
        next_scan_generation=2,
        last_successful_generation=1,
        ignore_rules=ignore_rules,
    )


def _intent(
    *,
    config_revision: int = 1,
    mode: OrganizationMode = OrganizationMode.VOLUMES,
    state: ReconcileIntentState = ReconcileIntentState.PENDING,
    phase: ReconcileIntentPhase = ReconcileIntentPhase.EXECUTE,
    lease_expires_at: datetime | None = None,
    fold_cursor: str | None = None,
    scopes: tuple[ReconcileScope, ...] | None = None,
    move_evidence: ReconcileMoveEvidence | None = None,
) -> ReconcileIntent:
    running = state is ReconcileIntentState.RUNNING
    return ReconcileIntent(
        intent_id="intent-1",
        library_id="library-1",
        first_sequence=1,
        through_sequence=1,
        scopes=scopes or (reconcile_scope(("Work",), PathComparison.INSENSITIVE),),
        move_evidence=move_evidence,
        state=state,
        phase=phase,
        lease_owner="old-worker" if running else None,
        lease_expires_at=(
            lease_expires_at or NOW + timedelta(seconds=60) if running else None
        ),
        topology_writer_fence=4 if running else None,
        attempt=1 if running else 0,
        available_at=NOW,
        fold_after_source_entry_id=fold_cursor,
        config_revision=config_revision,
        organization_mode=mode,
        topology_version=1,
        path_comparison=PathComparison.INSENSITIVE,
        root_path_snapshot="/library",
        root_identity_snapshot="dev:root",
        created_at=NOW,
        updated_at=NOW,
    )


class _ReconcileStore:
    def __init__(
        self,
        *,
        library: ScanLibrarySnapshot,
        intent: ReconcileIntent,
    ) -> None:
        self.library = library
        self.pending = intent if intent.state is ReconcileIntentState.PENDING else None
        self.running = intent if intent.state is ReconcileIntentState.RUNNING else None
        self.state = WatcherState("library-1", 1, None, None)
        self.libraries = self
        self.watcher = self
        self.sources = self
        self.topology = self
        self.diagnostics = self
        self.outbox = _Outbox()
        self.claimed_config_revisions: list[int] = []
        self.restart_count = 0
        self.takeover_count = 0
        self.abandoned_staging_count = 0
        self.absence_confirmations: list[tuple[str, ...]] = []
        self.excluded_observed_paths: list[tuple[str, ...]] = []
        self.complete_delete_count = 0
        self.upserted_observation_count = 0
        self.diagnostic_count = 0
        self._collision_emitted = False
        self.collision_on_directory_path: tuple[str, ...] | None = None
        self.colliding_paths: set[tuple[str, ...]] = set()
        self.presence_flip_count = 0
        self.overlapping_successor = False
        self.fold_pages = [PresenceFoldPage(0, None, True)]
        self.fold_limits: list[int] = []
        self.advanced_fold_cursors: list[str] = []
        self.path_bindings: dict[tuple[str, ...], SourcePathBinding] = {}
        self.applied_moves: list[ProvenMoveEvidence] = []
        self.commits = 0
        self.rollbacks = 0

    def get_for_reconcile_for_update(
        self, library_id: str
    ) -> ScanLibrarySnapshot | None:
        return self.library if library_id == self.library.library_id else None

    def get_state_for_update(self, library_id: str) -> WatcherState | None:
        return self.state if library_id == self.state.library_id else None

    def get_running_for_update(self, library_id: str) -> ReconcileIntent | None:
        return self.running if library_id == self.library.library_id else None

    def get_next_pending_for_update(
        self, library_id: str, *, now: datetime
    ) -> ReconcileIntent | None:
        assert now == NOW
        return self.pending if library_id == self.library.library_id else None

    def reserve_reconcile_writer(
        self,
        library_id: str,
        *,
        expected_topology_writer_fence: int,
    ) -> int | None:
        assert library_id == self.library.library_id
        if self.library.topology_writer_fence != expected_topology_writer_fence:
            return None
        self.library = replace(
            self.library,
            topology_writer_fence=expected_topology_writer_fence + 1,
        )
        return self.library.topology_writer_fence

    def claim(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        topology_writer_fence: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        if self.pending != intent:
            return None
        self.claimed_config_revisions.append(current_library.config_revision)
        self.pending = None
        self.running = replace(
            intent,
            state=ReconcileIntentState.RUNNING,
            phase=ReconcileIntentPhase.EXECUTE,
            lease_owner=owner_token,
            lease_expires_at=lease_expires_at,
            topology_writer_fence=topology_writer_fence,
            attempt=intent.attempt + 1,
            fold_after_source_entry_id=None,
            config_revision=current_library.config_revision,
            updated_at=now,
        )
        return self.running

    def restart_invalidated(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        if self.running != intent:
            return None
        self.restart_count += 1
        self.library = replace(
            self.library,
            topology_writer_fence=self.library.topology_writer_fence + 1,
        )
        self.running = replace(
            intent,
            phase=ReconcileIntentPhase.EXECUTE,
            lease_owner=owner_token,
            lease_expires_at=lease_expires_at,
            topology_writer_fence=self.library.topology_writer_fence,
            attempt=intent.attempt + 1,
            fold_after_source_entry_id=None,
            config_revision=current_library.config_revision,
            updated_at=now,
        )
        return self.running

    def take_over_expired(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        owner_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        assert current_library == self.library
        if self.running != intent:
            return None
        self.takeover_count += 1
        self.library = replace(
            self.library,
            topology_writer_fence=self.library.topology_writer_fence + 1,
        )
        if intent.phase is ReconcileIntentPhase.EXECUTE:
            self.abandoned_staging_count += 1
        self.running = replace(
            intent,
            phase=(
                ReconcileIntentPhase.EXECUTE
                if intent.phase is ReconcileIntentPhase.EXECUTE
                else intent.phase
            ),
            lease_owner=owner_token,
            lease_expires_at=lease_expires_at,
            topology_writer_fence=self.library.topology_writer_fence,
            attempt=intent.attempt + 1,
            fold_after_source_entry_id=(
                None
                if intent.phase is ReconcileIntentPhase.EXECUTE
                else intent.fold_after_source_entry_id
            ),
            updated_at=now,
        )
        return self.running

    def force_full_rescan_from_pending(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        assert current_library == self.library and observed_at == NOW
        if self.pending != intent:
            return None
        self.pending = None
        return self._require_full_scan(reason, intent.intent_id)

    def force_full_rescan_from_running(
        self,
        fence: object,
        *,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        assert observed_at == NOW
        if self.running is None:
            return None
        intent_id = self.running.intent_id
        self.running = None
        return self._require_full_scan(reason, intent_id)

    def force_full_rescan_from_invalidated(
        self,
        intent: ReconcileIntent,
        current_library: ScanLibrarySnapshot,
        *,
        reason: FullRescanReason,
        observed_at: datetime,
    ) -> FullRescanTransition | None:
        assert current_library == self.library and observed_at == NOW
        if self.running != intent:
            return None
        self.running = None
        return self._require_full_scan(reason, intent.intent_id)

    def _require_full_scan(
        self,
        reason: FullRescanReason,
        intent_id: str,
    ) -> FullRescanTransition:
        self.state = WatcherState("library-1", 1, 1, reason)
        return FullRescanTransition(
            self.state,
            newly_required=True,
            invalidated_running_intent_id=intent_id,
            topology_writer_fence=self.library.topology_writer_fence,
        )

    def heartbeat(
        self,
        fence: object,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ReconcileIntent | None:
        assert now == NOW and self.running is not None
        self.running = replace(
            self.running,
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
        return self.running

    def has_overlapping_successor(
        self,
        fence: object,
        scopes: tuple[ReconcileScope, ...],
    ) -> bool:
        return self.overlapping_successor

    def begin_fold(self, fence: object, *, now: datetime) -> ReconcileIntent | None:
        assert self.running is not None and now == NOW
        self.running = replace(
            self.running,
            phase=ReconcileIntentPhase.FOLD,
            updated_at=now,
        )
        return self.running

    def advance_fold_cursor(
        self,
        fence: object,
        *,
        after_source_entry_id: str | None,
        now: datetime,
    ) -> ReconcileIntent | None:
        assert self.running is not None and after_source_entry_id is not None
        self.advanced_fold_cursors.append(after_source_entry_id)
        self.running = replace(
            self.running,
            fold_after_source_entry_id=after_source_entry_id,
            updated_at=now,
        )
        return self.running

    def complete_delete(self, fence: object, *, completed_at: datetime) -> bool:
        assert self.running is not None and completed_at == NOW
        self.complete_delete_count += 1
        self.running = None
        return True

    def confirm_top_level_absent(
        self,
        fence: object,
        relative_path: tuple[str, ...],
        *,
        confirmed_at: datetime,
    ) -> None:
        assert confirmed_at == NOW
        self.absence_confirmations.append(relative_path)

    def exclude_observed_top_level(
        self,
        fence: object,
        source: DiscoveredSource,
        *,
        excluded_at: datetime,
    ) -> None:
        assert excluded_at == NOW
        self.excluded_observed_paths.append(source.relative_path)

    def upsert_reconcile_observations(
        self,
        fence: object,
        observations: tuple[PendingSourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome:
        assert observed_at == NOW
        self.upserted_observation_count += len(observations)
        sources = tuple(value.observation.source for value in observations)
        pending_epoch_by_path = {
            value.observation.source.relative_path: value.pending_parent_epoch
            for value in observations
        }
        paths = tuple(source.relative_path for source in sources)
        for source in sources:
            existing = self.path_bindings.get(source.relative_path)
            self.path_bindings[source.relative_path] = SourcePathBinding(
                source.relative_path,
                (
                    existing.source_entry_id
                    if existing is not None
                    else "source:" + "/".join(source.relative_path)
                ),
                source.filesystem_identity,
                pending_epoch_by_path[source.relative_path],
            )
        bindings = tuple(self.path_bindings[path] for path in paths)
        collisions: tuple[PathCollision, ...] = ()
        if (
            not self._collision_emitted
            and self.collision_on_directory_path is not None
            and self.collision_on_directory_path in paths
        ):
            collided = self.collision_on_directory_path
            related = (collided, (collided[-1].swapcase(),))
            collisions = (
                PathCollision(
                    collided[:-1],
                    collided[-1].casefold(),
                    related,
                ),
            )
            self.colliding_paths.update(related)
            self._collision_emitted = True
        elif not self._collision_emitted and {
            ("Work", "A.mp3"),
            ("Work", "a.mp3"),
        }.issubset(paths):
            collisions = (
                PathCollision(
                    ("Work",),
                    "a.mp3",
                    (("Work", "A.mp3"), ("Work", "a.mp3")),
                ),
            )
            self._collision_emitted = True
        return SourceObservationOutcome(collisions, bindings)

    def apply_proven_move(
        self,
        fence: object,
        evidence: ProvenMoveEvidence,
        *,
        observed_at: datetime,
    ) -> SourceRebindResult:
        assert observed_at == NOW
        self.applied_moves.append(evidence)
        source = self.path_bindings.get(evidence.source_path)
        if source is None:
            return SourceRebindResult(
                SourceRebindDisposition.NOT_PROVEN,
                None,
                SourceRebindRejectionReason.SOURCE_NOT_FOUND,
            )
        if source.filesystem_identity != evidence.filesystem_identity:
            return SourceRebindResult(
                SourceRebindDisposition.NOT_PROVEN,
                None,
                SourceRebindRejectionReason.IDENTITY_MISMATCH,
            )
        del self.path_bindings[evidence.source_path]
        moved = SourcePathBinding(
            evidence.destination_path,
            source.source_entry_id,
            evidence.filesystem_identity,
        )
        self.path_bindings[evidence.destination_path] = moved
        return SourceRebindResult(
            SourceRebindDisposition.PRESERVED_MOVED_ID,
            moved,
            None,
        )

    def begin_directory_presence(
        self,
        fence: object,
        directory: SourcePathBinding,
        *,
        observed_at: datetime,
    ) -> DirectoryPresenceEpoch:
        assert observed_at == NOW
        if directory.relative_path in self.colliding_paths:
            raise ReconcileStale()
        return DirectoryPresenceEpoch(directory, 0, 1)

    def flip_directory_presence(
        self,
        fence: object,
        epoch: DirectoryPresenceEpoch,
        *,
        completed_at: datetime,
    ) -> bool:
        assert completed_at == NOW
        self.presence_flip_count += 1
        return True

    def record(
        self,
        fence: object,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None:
        assert observed_at == NOW
        self.diagnostic_count += len(diagnostics)

    def fold_effective_presence(
        self,
        fence: object,
        *,
        after_source_entry_id: str | None,
        limit: int,
        folded_at: datetime,
    ) -> PresenceFoldPage:
        assert folded_at == NOW
        self.fold_limits.append(limit)
        return self.fold_pages.pop(0)

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


def _execute(
    store: _ReconcileStore,
    discovery: _AbsentDiscovery | None = None,
    admission: _AdmissionMustNotRun
    | _AudioAdmission
    | _RejectedAdmission
    | None = None,
) -> object:
    return RunNextReconcileSubtree(
        unit_of_work_factory=lambda: store,
        discovery=discovery or _AbsentDiscovery(),
        admission=admission or _AdmissionMustNotRun(),
        clock=_Clock(),
        monotonic_clock=_MonotonicClock(),
    ).execute(RunNextReconcileSubtreeCommand("library-1", "new-worker"))


def test_pending_control_revision_restamps_and_absent_unknown_slot_completes() -> None:
    store = _ReconcileStore(
        library=_library(config_revision=2),
        intent=_intent(config_revision=1),
    )

    result = _execute(store)

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.claimed_config_revisions == [2]
    assert store.absence_confirmations == [("Work",)]
    assert store.complete_delete_count == 1


def test_newer_successor_prevents_stale_absence_marker() -> None:
    store = _ReconcileStore(library=_library(), intent=_intent())
    store.overlapping_successor = True

    result = _execute(store)

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.absence_confirmations == []


def test_pending_structural_mismatch_requires_full_scan_without_opening_root() -> None:
    store = _ReconcileStore(
        library=_library(mode=OrganizationMode.FLAT),
        intent=_intent(mode=OrganizationMode.VOLUMES),
    )
    discovery = _AbsentDiscovery()

    result = _execute(store, discovery)

    assert result.disposition is ReconcileRunDisposition.FULL_SCAN_REQUIRED
    assert store.state.full_rescan_reason is FullRescanReason.UNTRUSTED
    assert discovery.observe_calls == []


def test_present_ignored_directory_is_excluded_without_claiming_absence() -> None:
    store = _ReconcileStore(
        library=_library(
            ignore_rules=(IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="Work"),)
        ),
        intent=_intent(),
    )

    result = _execute(store, _PresentDirectoryDiscovery())

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.excluded_observed_paths == [("Work",)]
    assert store.absence_confirmations == []


def test_trusted_move_uses_fresh_absence_and_identity_to_preserve_source_id() -> None:
    scopes = (
        reconcile_scope(("old.bin",), PathComparison.INSENSITIVE),
        reconcile_scope(("new.bin",), PathComparison.INSENSITIVE),
    )
    store = _ReconcileStore(
        library=_library(mode=OrganizationMode.FLAT),
        intent=_intent(
            mode=OrganizationMode.FLAT,
            scopes=scopes,
            move_evidence=ReconcileMoveEvidence(
                ("old.bin",),
                ("new.bin",),
                WatcherMovedEntryType.FILE,
            ),
        ),
    )
    store.path_bindings[("old.bin",)] = SourcePathBinding(
        ("old.bin",),
        "stable-source-id",
        "dev:moved-file",
    )

    result = _execute(store, _MoveDiscovery(), _RejectedAdmission())

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert len(store.applied_moves) == 1
    assert store.applied_moves[0].source_absence == TargetedPathAbsent(("old.bin",))
    assert store.path_bindings[("new.bin",)].source_entry_id == "stable-source-id"


def test_trusted_move_with_newer_successor_falls_back_before_rebinding_id() -> None:
    scopes = (
        reconcile_scope(("old.bin",), PathComparison.INSENSITIVE),
        reconcile_scope(("new.bin",), PathComparison.INSENSITIVE),
    )
    store = _ReconcileStore(
        library=_library(mode=OrganizationMode.FLAT),
        intent=_intent(
            mode=OrganizationMode.FLAT,
            scopes=scopes,
            move_evidence=ReconcileMoveEvidence(
                ("old.bin",),
                ("new.bin",),
                WatcherMovedEntryType.FILE,
            ),
        ),
    )
    store.path_bindings[("old.bin",)] = SourcePathBinding(
        ("old.bin",),
        "stable-source-id",
        "dev:moved-file",
    )
    store.overlapping_successor = True

    result = _execute(store, _MoveDiscovery(), _RejectedAdmission())

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.applied_moves == []
    assert store.path_bindings[("old.bin",)].source_entry_id == "stable-source-id"
    assert store.path_bindings[("new.bin",)].source_entry_id != "stable-source-id"


def test_move_to_ignored_name_preserves_id_but_records_observed_exclusion() -> None:
    scopes = (
        reconcile_scope(("old.bin",), PathComparison.INSENSITIVE),
        reconcile_scope(("new.bin",), PathComparison.INSENSITIVE),
    )
    store = _ReconcileStore(
        library=_library(
            mode=OrganizationMode.FLAT,
            ignore_rules=(
                IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="new.bin"),
            ),
        ),
        intent=_intent(
            mode=OrganizationMode.FLAT,
            scopes=scopes,
            move_evidence=ReconcileMoveEvidence(
                ("old.bin",),
                ("new.bin",),
                WatcherMovedEntryType.FILE,
            ),
        ),
    )
    store.path_bindings[("old.bin",)] = SourcePathBinding(
        ("old.bin",),
        "stable-source-id",
        "dev:moved-file",
    )

    result = _execute(store, _MoveDiscovery(), _RejectedAdmission())

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.path_bindings[("new.bin",)].source_entry_id == "stable-source-id"
    assert store.excluded_observed_paths == [("new.bin",)]
    assert store.absence_confirmations == [("old.bin",)]


def test_move_with_source_still_present_falls_back_without_id_rebind() -> None:
    scopes = (
        reconcile_scope(("old.bin",), PathComparison.INSENSITIVE),
        reconcile_scope(("new.bin",), PathComparison.INSENSITIVE),
    )
    store = _ReconcileStore(
        library=_library(mode=OrganizationMode.FLAT),
        intent=_intent(
            mode=OrganizationMode.FLAT,
            scopes=scopes,
            move_evidence=ReconcileMoveEvidence(
                ("old.bin",),
                ("new.bin",),
                WatcherMovedEntryType.FILE,
            ),
        ),
    )
    store.path_bindings[("old.bin",)] = SourcePathBinding(
        ("old.bin",),
        "stable-source-id",
        "dev:moved-file",
    )

    result = _execute(
        store,
        _MoveDiscovery(source_present=True),
        _RejectedAdmission(),
    )

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.applied_moves == []
    assert store.path_bindings[("old.bin",)].source_entry_id == "stable-source-id"
    assert store.path_bindings[("new.bin",)].source_entry_id != "stable-source-id"


def test_live_running_control_revision_is_restarted_immediately() -> None:
    store = _ReconcileStore(
        library=_library(config_revision=2),
        intent=_intent(
            config_revision=1,
            state=ReconcileIntentState.RUNNING,
        ),
    )

    result = _execute(store)

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.restart_count == 1
    assert store.takeover_count == 0


def test_live_running_structural_mismatch_uses_invalidated_rescan_cas() -> None:
    store = _ReconcileStore(
        library=_library(mode=OrganizationMode.FLAT),
        intent=_intent(
            mode=OrganizationMode.VOLUMES,
            state=ReconcileIntentState.RUNNING,
        ),
    )
    discovery = _AbsentDiscovery()

    result = _execute(store, discovery)

    assert result.disposition is ReconcileRunDisposition.FULL_SCAN_REQUIRED
    assert store.state.full_rescan_reason is FullRescanReason.UNTRUSTED
    assert discovery.observe_calls == []


def test_exact_live_running_intent_conflicts() -> None:
    store = _ReconcileStore(
        library=_library(),
        intent=_intent(state=ReconcileIntentState.RUNNING),
    )

    with pytest.raises(ReconcileConflict):
        _execute(store)

    assert store.rollbacks == 1


def test_expired_fold_takeover_preserves_phase_and_skips_discovery() -> None:
    store = _ReconcileStore(
        library=_library(),
        intent=_intent(
            state=ReconcileIntentState.RUNNING,
            phase=ReconcileIntentPhase.FOLD,
            lease_expires_at=NOW - timedelta(seconds=1),
            fold_cursor="source-5000",
        ),
    )
    discovery = _AbsentDiscovery()

    result = _execute(store, discovery)

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.takeover_count == 1
    assert store.abandoned_staging_count == 0
    assert discovery.observe_calls == []


def test_expired_execute_takeover_abandons_partial_staging_before_root_restart() -> (
    None
):
    store = _ReconcileStore(
        library=_library(),
        intent=_intent(
            state=ReconcileIntentState.RUNNING,
            phase=ReconcileIntentPhase.EXECUTE,
            lease_expires_at=NOW - timedelta(seconds=1),
        ),
    )

    result = _execute(store)

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.takeover_count == 1
    assert store.abandoned_staging_count == 1


def test_directory_collision_short_circuits_to_full_scan_before_presence_begin() -> (
    None
):
    store = _ReconcileStore(
        library=_library(),
        intent=_intent(),
    )
    store.collision_on_directory_path = ("Work",)

    result = _execute(store, _PresentDirectoryDiscovery())

    assert result.disposition is ReconcileRunDisposition.FULL_SCAN_REQUIRED
    assert result.units_activated == 0
    assert store.state.full_rescan_reason is FullRescanReason.COLLISION_RECHECK


def test_fold_progresses_in_bounded_heartbeat_pages() -> None:
    store = _ReconcileStore(
        library=_library(),
        intent=_intent(
            state=ReconcileIntentState.RUNNING,
            phase=ReconcileIntentPhase.FOLD,
            lease_expires_at=NOW - timedelta(seconds=1),
        ),
    )
    store.fold_pages = [
        PresenceFoldPage(5_000, "source-5000", False),
        PresenceFoldPage(3, None, True),
    ]

    result = _execute(store)

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert store.fold_limits == [5_000, 5_000]
    assert store.advanced_fold_cursors == ["source-5000"]


def test_root_change_before_terminal_delete_requires_full_scan() -> None:
    store = _ReconcileStore(
        library=_library(),
        intent=_intent(
            state=ReconcileIntentState.RUNNING,
            phase=ReconcileIntentPhase.FOLD,
            lease_expires_at=NOW - timedelta(seconds=1),
        ),
    )
    discovery = _AbsentDiscovery(
        root_revalidations=("dev:root", "dev:replacement"),
    )

    result = _execute(store, discovery)

    assert result.disposition is ReconcileRunDisposition.FULL_SCAN_REQUIRED
    assert store.complete_delete_count == 0
    assert store.state.full_rescan_reason is FullRescanReason.ROOT_CHANGED


def test_ten_thousand_audio_tracks_use_linear_bounded_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_count = 0
    original_getattribute = ProbedEntry.__getattribute__

    def count_layout_fact_access(entry: ProbedEntry, name: str) -> object:
        nonlocal access_count
        if name in {"admission", "entry_type"}:
            access_count += 1
        return original_getattribute(entry, name)

    monkeypatch.setattr(ProbedEntry, "__getattribute__", count_layout_fact_access)
    store = _ReconcileStore(
        library=_library(mode=OrganizationMode.AUDIOBOOK),
        intent=_intent(mode=OrganizationMode.AUDIOBOOK),
    )
    discovery = _AudiobookDiscovery(10_000)
    admission = _AudioAdmission()

    result = _execute(store, discovery, admission)

    assert result.disposition is ReconcileRunDisposition.FULL_SCAN_REQUIRED
    assert result.units_activated == 0
    assert admission.probe_count == 10_000
    assert store.upserted_observation_count == 10_001
    assert store.presence_flip_count == 1
    assert store.state.full_rescan_reason is FullRescanReason.COLLISION_RECHECK
    assert access_count < 300_000


@pytest.mark.parametrize(
    "mode",
    (OrganizationMode.AUDIOBOOK, OrganizationMode.VOLUMES),
)
def test_oversized_reconcile_unit_bounds_opaque_binding_cache(
    monkeypatch: pytest.MonkeyPatch,
    mode: OrganizationMode,
) -> None:
    peak_binding_count = 0
    original_flush = reconcile_execution_module._ReconcileExecution._flush

    def track_binding_count(
        execution: reconcile_execution_module._ReconcileExecution,
        *,
        force: bool,
    ) -> tuple[PathCollision, ...]:
        nonlocal peak_binding_count
        collisions = original_flush(execution, force=force)
        peak_binding_count = max(
            peak_binding_count,
            len(execution._source_bindings),
        )
        return collisions

    monkeypatch.setattr(
        reconcile_execution_module._ReconcileExecution,
        "_flush",
        track_binding_count,
    )
    store = _ReconcileStore(
        library=_library(mode=mode),
        intent=_intent(mode=mode),
    )

    result = _execute(
        store,
        _LazyOversizedUnitDiscovery(mode, MAX_AUDIO_TRACKS * 2),
        _AudioAdmission(),
    )

    assert result.disposition is ReconcileRunDisposition.COMPLETED
    assert result.units_activated == 0
    assert store.upserted_observation_count >= MAX_AUDIO_TRACKS * 2
    assert peak_binding_count <= MAX_AUDIO_TRACKS + 500
