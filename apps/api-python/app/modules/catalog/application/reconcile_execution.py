"""Synchronous bounded execution of one durable targeted reconcile intent."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.catalog.application.ports import Clock, OutboxEvent
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryIssue,
    DiscoveryIssueCode,
    PathCollision,
    ScanLibrarySnapshot,
    SourceObservation,
    SourcePathBinding,
    StagingRevision,
    TargetedPathAbsent,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryDiscoveryOperationalError,
    DirectoryDiscoveryPort,
    DirectoryDiscoverySession,
    MonotonicClock,
)
from app.modules.catalog.application.scan_runtime_policy import scan_lease_deadline
from app.modules.catalog.application.source_admission_ports import (
    SourceAdmissionOperationalError,
    SourceAdmissionPort,
    SourceChangedDuringProbe,
)
from app.modules.catalog.application.watcher_dto import (
    BoundTopologyStageBatch,
    BoundTopologyUnitPlan,
    DirectoryPresenceEpoch,
    FullRescanTransition,
    PendingSourceObservation,
    ProvenMoveEvidence,
    ReconcileFence,
    ReconcileIntent,
    ReconcileIntentPhase,
    ReconcileRunDisposition,
    ReconcileRunResult,
    RunNextReconcileSubtreeCommand,
    SourceRebindDisposition,
    required_topology_source_paths,
)
from app.modules.catalog.application.watcher_ports import (
    WatcherUnitOfWork,
    WatcherUowFactory,
)
from app.modules.catalog.domain.admission import (
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
    is_system_noise_name,
    parse_disc_component,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRuleKind
from app.modules.catalog.domain.layouts import interpret_layout
from app.modules.catalog.domain.library import LibraryControlState
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    ProbedEntry,
    ViolationCode,
)
from app.modules.catalog.domain.ordering import comparison_component
from app.modules.catalog.domain.scan import (
    MAX_AUDIO_TRACKS,
    MAX_STRUCTURAL_ENTRIES_PER_UNIT,
    ScanDiagnostic,
    ScanObservationCode,
    TopologyActivationGroup,
    TopologyUnitPlan,
    build_topology_activation_groups,
    collision_unit_path,
    iter_stage_batches,
)
from app.modules.catalog.domain.watcher import (
    MAX_PRESENCE_FOLD_ROWS,
    FullRescanReason,
    ReconcileConflict,
    ReconcileLeaseLost,
    ReconcileNotFound,
    ReconcileRootIdentityChanged,
    ReconcileStale,
    WatcherMovedEntryType,
)

_MAX_CANDIDATES_PER_SLICE = 500
_MAX_OBSERVATIONS_PER_SLICE = 5_000
_MAX_SLICE_SECONDS = 0.250


@dataclass(frozen=True, slots=True)
class _ClaimedIntent:
    intent: ReconcileIntent
    library: ScanLibrarySnapshot
    presence_generation: int


class _CollisionRecheckRequired(Exception):
    """Stop this attempt after its directory slot became colliding."""


@dataclass(slots=True)
class _BoundedLayoutEntries:
    """Retain only the bounded layout facts needed by one topology unit."""

    entries: list[ProbedEntry] = field(default_factory=list)
    audio_track_count: int = 0
    structural_entry_count: int = 0
    overflow_code: ViolationCode | ScanObservationCode | None = None

    def retain(self, entry: ProbedEntry | None) -> bool:
        if entry is None or self.overflow_code is not None:
            return False
        if entry.admission is AdmissionKind.AUDIO_TRACK:
            self.audio_track_count += 1
            if self.audio_track_count > MAX_AUDIO_TRACKS:
                self.overflow_code = ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED
        if entry.entry_type in {
            EntryType.DIRECTORY,
            EntryType.SYMLINK,
            EntryType.JUNCTION,
        }:
            self.structural_entry_count += 1
            if self.structural_entry_count > MAX_STRUCTURAL_ENTRIES_PER_UNIT:
                self.overflow_code = (
                    ScanObservationCode.TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED
                )
        if len(self.entries) >= MAX_AUDIO_TRACKS + MAX_STRUCTURAL_ENTRIES_PER_UNIT:
            self.overflow_code = ScanObservationCode.TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED
        if self.overflow_code is not None:
            self.entries.clear()
            return False
        self.entries.append(entry)
        return True


def _same_structure(
    intent: ReconcileIntent,
    library: ScanLibrarySnapshot,
) -> bool:
    return (
        intent.library_id == library.library_id
        and intent.root_path_snapshot == library.canonical_root
        and intent.organization_mode is library.organization_mode
        and intent.topology_version == library.topology_version
        and intent.path_comparison is library.path_comparison
    )


def _full_scan_reason(
    intent: ReconcileIntent,
    library: ScanLibrarySnapshot,
) -> FullRescanReason:
    if intent.root_path_snapshot != library.canonical_root:
        return FullRescanReason.ROOT_CHANGED
    return FullRescanReason.UNTRUSTED


def _append_full_scan_required(
    uow: WatcherUnitOfWork,
    transition: FullRescanTransition,
) -> None:
    if not transition.newly_required:
        return
    state = transition.state
    if state.full_rescan_reason is None or state.overflow_through_sequence is None:
        raise ReconcileStale()
    uow.outbox.append(
        OutboxEvent(
            "LIBRARY_FULL_SCAN_REQUIRED",
            state.library_id,
            "SYSTEM",
            (
                ("reason", state.full_rescan_reason.value),
                ("throughSequence", state.overflow_through_sequence),
            ),
        )
    )


def _iter_bound_batches(
    plan: BoundTopologyUnitPlan,
) -> Iterator[BoundTopologyStageBatch]:
    for batch in iter_stage_batches(plan.plan):
        yield BoundTopologyStageBatch(
            first_row=batch.first_row,
            rows=batch.rows,
            bindings=plan.projections[
                batch.first_row : batch.first_row + len(batch.rows)
            ],
            complete=batch.complete,
        )


class RunNextReconcileSubtree:
    """Claim and synchronously reconcile one ordered top-level intent."""

    def __init__(
        self,
        *,
        unit_of_work_factory: WatcherUowFactory,
        discovery: DirectoryDiscoveryPort,
        admission: SourceAdmissionPort,
        clock: Clock,
        monotonic_clock: MonotonicClock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._discovery = discovery
        self._admission = admission
        self._clock = clock
        self._monotonic_clock = monotonic_clock

    def execute(self, command: RunNextReconcileSubtreeCommand) -> ReconcileRunResult:
        claimed = self._claim(command)
        if isinstance(claimed, ReconcileRunResult):
            return claimed
        try:
            with self._discovery.open(
                canonical_root=claimed.intent.root_path_snapshot
            ) as session:
                if session.root_identity != claimed.intent.root_identity_snapshot:
                    raise ReconcileRootIdentityChanged()
                execution = _ReconcileExecution(
                    unit_of_work_factory=self._unit_of_work_factory,
                    admission=self._admission,
                    clock=self._clock,
                    monotonic_clock=self._monotonic_clock,
                    session=session,
                    claimed=claimed,
                    lease_seconds=command.lease_seconds,
                )
                return execution.execute()
        except ReconcileRootIdentityChanged:
            return self._force_owned_full_scan(
                claimed,
                FullRescanReason.ROOT_CHANGED,
            )
        except (DirectoryDiscoveryOperationalError, SourceAdmissionOperationalError):
            return self._force_owned_full_scan(
                claimed,
                FullRescanReason.UNTRUSTED,
            )

    def _claim(
        self, command: RunNextReconcileSubtreeCommand
    ) -> _ClaimedIntent | ReconcileRunResult:
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            library = uow.libraries.get_for_reconcile_for_update(command.library_id)
            if library is None:
                raise ReconcileNotFound()
            presence_generation = library.last_successful_generation
            if (
                library.control_state is not LibraryControlState.ACTIVE
                or presence_generation is None
            ):
                return ReconcileRunResult(
                    ReconcileRunDisposition.NO_WORK,
                    None,
                    0,
                )
            watcher_state = uow.watcher.get_state_for_update(command.library_id)
            if watcher_state is None:
                raise ReconcileStale()
            if watcher_state.full_rescan_reason is not None:
                return ReconcileRunResult(
                    ReconcileRunDisposition.NO_WORK,
                    None,
                    0,
                )
            running = uow.watcher.get_running_for_update(command.library_id)
            if running is not None:
                return self._claim_running(
                    uow,
                    running,
                    library,
                    command,
                    presence_generation=presence_generation,
                    now=now,
                    lease_expires_at=lease_expires_at,
                )
            pending = uow.watcher.get_next_pending_for_update(
                command.library_id,
                now=now,
            )
            if pending is None:
                return ReconcileRunResult(
                    ReconcileRunDisposition.NO_WORK,
                    None,
                    0,
                )
            if not _same_structure(pending, library):
                transition = uow.watcher.force_full_rescan_from_pending(
                    pending,
                    library,
                    reason=_full_scan_reason(pending, library),
                    observed_at=now,
                )
                if transition is None:
                    raise ReconcileStale()
                _append_full_scan_required(uow, transition)
                uow.commit()
                return ReconcileRunResult(
                    ReconcileRunDisposition.FULL_SCAN_REQUIRED,
                    pending.intent_id,
                    0,
                )
            writer_fence = uow.libraries.reserve_reconcile_writer(
                library.library_id,
                expected_topology_writer_fence=library.topology_writer_fence,
            )
            if writer_fence is None:
                raise ReconcileConflict()
            intent = uow.watcher.claim(
                pending,
                library,
                owner_token=command.owner_token,
                topology_writer_fence=writer_fence,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            if intent is None:
                raise ReconcileConflict()
            uow.commit()
            return _ClaimedIntent(
                intent,
                library,
                presence_generation,
            )

    def _claim_running(
        self,
        uow: WatcherUnitOfWork,
        running: ReconcileIntent,
        library: ScanLibrarySnapshot,
        command: RunNextReconcileSubtreeCommand,
        *,
        presence_generation: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> _ClaimedIntent | ReconcileRunResult:
        if not _same_structure(running, library):
            transition = uow.watcher.force_full_rescan_from_invalidated(
                running,
                library,
                reason=_full_scan_reason(running, library),
                observed_at=now,
            )
            if transition is None:
                raise ReconcileStale()
            _append_full_scan_required(uow, transition)
            uow.commit()
            return ReconcileRunResult(
                ReconcileRunDisposition.FULL_SCAN_REQUIRED,
                running.intent_id,
                0,
            )
        if running.config_revision != library.config_revision:
            restarted = uow.watcher.restart_invalidated(
                running,
                library,
                owner_token=command.owner_token,
                now=now,
                lease_expires_at=lease_expires_at,
            )
        elif running.lease_expires_at is not None and running.lease_expires_at <= now:
            restarted = uow.watcher.take_over_expired(
                running,
                library,
                owner_token=command.owner_token,
                now=now,
                lease_expires_at=lease_expires_at,
            )
        else:
            raise ReconcileConflict()
        if restarted is None:
            raise ReconcileConflict()
        uow.commit()
        return _ClaimedIntent(
            restarted,
            library,
            presence_generation,
        )

    def _force_owned_full_scan(
        self,
        claimed: _ClaimedIntent,
        reason: FullRescanReason,
    ) -> ReconcileRunResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            transition = uow.watcher.force_full_rescan_from_running(
                claimed.intent.fence(presence_generation=claimed.presence_generation),
                reason=reason,
                observed_at=now,
            )
            if transition is None:
                raise ReconcileLeaseLost()
            _append_full_scan_required(uow, transition)
            uow.commit()
        return ReconcileRunResult(
            ReconcileRunDisposition.FULL_SCAN_REQUIRED,
            claimed.intent.intent_id,
            0,
        )


class _ReconcileExecution:
    def __init__(
        self,
        *,
        unit_of_work_factory: WatcherUowFactory,
        admission: SourceAdmissionPort,
        clock: Clock,
        monotonic_clock: MonotonicClock,
        session: DirectoryDiscoverySession,
        claimed: _ClaimedIntent,
        lease_seconds: int,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._admission = admission
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._session = session
        self.intent = claimed.intent
        self.library = claimed.library
        self._presence_generation = claimed.presence_generation
        self._lease_seconds = lease_seconds
        self._ignored_names = frozenset(
            comparison_component(rule.pattern, self.intent.path_comparison)
            for rule in self.library.ignore_rules
            if rule.enabled and rule.kind is IgnoreRuleKind.NAME
        )
        self._ignored_paths = frozenset(
            "/".join(
                comparison_component(component, self.intent.path_comparison)
                for component in rule.pattern.split("/")
            )
            for rule in self.library.ignore_rules
            if rule.enabled and rule.kind is IgnoreRuleKind.PATH
        )
        self._pending_observations: list[PendingSourceObservation] = []
        self._pending_diagnostics: list[ScanDiagnostic] = []
        self._source_bindings: dict[tuple[str, ...], SourcePathBinding] = {}
        self._bounded_binding_paths: set[tuple[str, ...]] | None = None
        self._slice_observation_count = 0
        self._slice_candidate_count = 0
        self._slice_started = monotonic_clock.seconds()
        self._collision_seen = False
        self._units_activated = 0

    @property
    def fence(self) -> ReconcileFence:
        return self.intent.fence(presence_generation=self._presence_generation)

    def execute(self) -> ReconcileRunResult:
        self._require_root()
        if self.intent.phase is ReconcileIntentPhase.FOLD:
            return self._fold_and_complete()
        self._attempt_proven_move()
        try:
            for scope in self.intent.scopes:
                self._reconcile_scope(scope.relative_path)
                self._discard_source_bindings_under(scope.relative_path)
        except _CollisionRecheckRequired:
            return self._force_collision_recheck()
        self._flush(force=True)
        if self._collision_seen:
            return self._force_collision_recheck()
        return self._begin_fold_and_complete()

    def _reconcile_scope(self, relative_path: tuple[str, ...]) -> None:
        observed = self._session.observe_path(relative_path)
        self._slice_observation_count += 1
        if isinstance(observed, TargetedPathAbsent):
            self._confirm_absent(relative_path)
            return
        if self._ignored(observed.relative_path):
            self._exclude_observed_top_level(observed)
            return
        if self.intent.organization_mode is OrganizationMode.FLAT:
            self._process_sources(((observed, None),))
        elif self.intent.organization_mode is OrganizationMode.VOLUMES:
            self._reconcile_volumes_work(observed)
        else:
            self._reconcile_audiobook_work(observed)

    def _confirm_absent(self, relative_path: tuple[str, ...]) -> None:
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if uow.watcher.has_overlapping_successor(self.fence, self.intent.scopes):
                updated = self._heartbeat_in_uow(uow, now)
                uow.commit()
                self.intent = updated
                return
            uow.sources.confirm_top_level_absent(
                self.fence,
                relative_path,
                confirmed_at=now,
            )
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated

    def _exclude_observed_top_level(self, source: DiscoveredSource) -> None:
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if uow.watcher.has_overlapping_successor(self.fence, self.intent.scopes):
                updated = self._heartbeat_in_uow(uow, now)
                uow.commit()
                self.intent = updated
                return
            uow.sources.exclude_observed_top_level(
                self.fence,
                source,
                excluded_at=now,
            )
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated

    def _reconcile_volumes_work(self, work: DiscoveredSource) -> None:
        if work.entry_type is not DiscoveryEntryType.DIRECTORY:
            self._process_sources(((work, None),))
            return
        work_entry, work_epoch = self._begin_directory(work, None)
        for observation in self._session.iter_directory(work.relative_path):
            child = self._source_or_issue(observation)
            if child is None or self._ignored(child.relative_path):
                continue
            if child.entry_type is not DiscoveryEntryType.DIRECTORY:
                child_entry = self._observe(child, work_epoch.proposed_epoch)
                self._process_entries(
                    tuple(
                        value
                        for value in (work_entry, child_entry)
                        if value is not None
                    )
                )
                self._discard_source_bindings_under(child.relative_path)
                continue
            version_entry, version_epoch = self._begin_directory(
                child,
                work_epoch.proposed_epoch,
            )
            for volume_observation in self._session.iter_directory(child.relative_path):
                volume = self._source_or_issue(volume_observation)
                if volume is None or self._ignored(volume.relative_path):
                    continue
                if volume.entry_type is DiscoveryEntryType.DIRECTORY:
                    bundle = self._collect_bundle(
                        volume,
                        version_epoch.proposed_epoch,
                    )
                    if bundle is not None:
                        self._process_entries((work_entry, version_entry, *bundle))
                else:
                    volume_entry = self._observe(
                        volume,
                        version_epoch.proposed_epoch,
                    )
                    self._process_entries(
                        tuple(
                            value
                            for value in (work_entry, version_entry, volume_entry)
                            if value is not None
                        )
                    )
                self._discard_source_bindings_under(volume.relative_path)
            self._finish_directory(version_epoch)
            self._discard_source_bindings_under(child.relative_path)
        self._finish_directory(work_epoch)

    def _collect_bundle(
        self,
        volume: DiscoveredSource,
        parent_epoch: int,
    ) -> tuple[ProbedEntry, ...] | None:
        retained = _BoundedLayoutEntries()
        self._begin_bounded_binding_retention(volume.relative_path)
        try:
            self._allow_bounded_binding(volume.relative_path)
            volume_entry, volume_epoch = self._begin_directory(volume, parent_epoch)
            self._retain_bounded_binding(
                retained,
                volume_entry,
                relative_path=volume.relative_path,
                unit_root=volume.relative_path,
            )
            for observation in self._session.iter_directory(volume.relative_path):
                child = self._source_or_issue(observation)
                if child is None or self._ignored(child.relative_path):
                    continue
                self._allow_bounded_binding(child.relative_path)
                if (
                    child.entry_type is DiscoveryEntryType.DIRECTORY
                    and parse_disc_component(child.relative_path[-1]) is not None
                ):
                    disc_entry, disc_epoch = self._begin_directory(
                        child,
                        volume_epoch.proposed_epoch,
                    )
                    self._retain_bounded_binding(
                        retained,
                        disc_entry,
                        relative_path=child.relative_path,
                        unit_root=volume.relative_path,
                    )
                    for nested_observation in self._session.iter_directory(
                        child.relative_path
                    ):
                        nested = self._source_or_issue(nested_observation)
                        if nested is None or self._ignored(nested.relative_path):
                            continue
                        self._allow_bounded_binding(nested.relative_path)
                        entry = self._observe(nested, disc_epoch.proposed_epoch)
                        self._retain_bounded_binding(
                            retained,
                            entry,
                            relative_path=nested.relative_path,
                            unit_root=volume.relative_path,
                        )
                    self._finish_directory(disc_epoch)
                else:
                    entry = self._observe(child, volume_epoch.proposed_epoch)
                    self._retain_bounded_binding(
                        retained,
                        entry,
                        relative_path=child.relative_path,
                        unit_root=volume.relative_path,
                    )
            self._finish_directory(volume_epoch)
            if retained.overflow_code is not None:
                self._pending_diagnostics.append(
                    ScanDiagnostic(
                        retained.overflow_code,
                        volume.relative_path,
                        (volume.relative_path,),
                    )
                )
                self._flush(force=True)
                self._discard_source_bindings_under(volume.relative_path)
                return None
            return tuple(retained.entries)
        finally:
            self._end_bounded_binding_retention()

    def _reconcile_audiobook_work(self, work: DiscoveredSource) -> None:
        if work.entry_type is not DiscoveryEntryType.DIRECTORY:
            self._process_sources(((work, None),))
            return
        retained = _BoundedLayoutEntries()
        self._begin_bounded_binding_retention(work.relative_path)
        try:
            self._walk_audio_directory(
                work,
                parent_epoch=None,
                depth=0,
                retained=retained,
                unit_root=work.relative_path,
            )
            if retained.overflow_code is not None:
                self._pending_diagnostics.append(
                    ScanDiagnostic(
                        retained.overflow_code,
                        work.relative_path,
                        (work.relative_path,),
                    )
                )
                self._flush(force=True)
                self._discard_source_bindings_under(work.relative_path)
                return
            self._process_entries(tuple(retained.entries))
        finally:
            self._end_bounded_binding_retention()

    def _walk_audio_directory(
        self,
        directory: DiscoveredSource,
        *,
        parent_epoch: int | None,
        depth: int,
        retained: _BoundedLayoutEntries,
        unit_root: tuple[str, ...],
    ) -> None:
        self._allow_bounded_binding(directory.relative_path)
        directory_entry, epoch = self._begin_directory(directory, parent_epoch)
        self._retain_bounded_binding(
            retained,
            directory_entry,
            relative_path=directory.relative_path,
            unit_root=unit_root,
        )
        for observation in self._session.iter_directory(directory.relative_path):
            child = self._source_or_issue(observation)
            if child is None or self._ignored(child.relative_path):
                continue
            may_descend = child.entry_type is DiscoveryEntryType.DIRECTORY and (
                depth == 0
                or (
                    depth == 1
                    and parse_disc_component(child.relative_path[-1]) is not None
                )
            )
            if may_descend:
                self._walk_audio_directory(
                    child,
                    parent_epoch=epoch.proposed_epoch,
                    depth=depth + 1,
                    retained=retained,
                    unit_root=unit_root,
                )
            else:
                self._allow_bounded_binding(child.relative_path)
                entry = self._observe(child, epoch.proposed_epoch)
                self._retain_bounded_binding(
                    retained,
                    entry,
                    relative_path=child.relative_path,
                    unit_root=unit_root,
                )
        self._finish_directory(epoch)
        if retained.overflow_code is not None:
            self._discard_source_bindings_under(unit_root)

    def _process_sources(
        self,
        sources: tuple[tuple[DiscoveredSource, int | None], ...],
    ) -> None:
        entries = tuple(
            entry
            for source, pending_epoch in sources
            if (entry := self._observe(source, pending_epoch)) is not None
        )
        self._process_entries(entries)

    def _process_entries(self, entries: tuple[ProbedEntry, ...]) -> None:
        if not entries:
            return
        result = interpret_layout(
            self.intent.organization_mode,
            entries,
            path_comparison=self.intent.path_comparison,
        )
        self._pending_diagnostics.extend(
            ScanDiagnostic(
                violation.code,
                violation.unit_path,
                violation.related_paths,
            )
            for violation in result.violations
        )
        self._flush(force=True)
        if self._collision_seen:
            return
        groups = build_topology_activation_groups(
            self.intent.organization_mode,
            result.candidates,
            path_comparison=self.intent.path_comparison,
        )
        for group in groups:
            self._units_activated += self._materialize_group(group)

    def _observe(
        self,
        source: DiscoveredSource,
        pending_parent_epoch: int | None,
    ) -> ProbedEntry | None:
        admission: SourceAdmissionEvidence | SourceAdmissionRejection | None
        if source.entry_type is DiscoveryEntryType.DIRECTORY:
            admission = None
            entry = ProbedEntry(
                source.relative_path,
                EntryType.DIRECTORY,
                AdmissionKind.IGNORED,
            )
        elif source.entry_type in {
            DiscoveryEntryType.SYMLINK,
            DiscoveryEntryType.JUNCTION,
        }:
            admission = None
            entry = ProbedEntry(
                source.relative_path,
                EntryType.SYMLINK
                if source.entry_type is DiscoveryEntryType.SYMLINK
                else EntryType.JUNCTION,
                AdmissionKind.IGNORED,
            )
        elif source.entry_type is DiscoveryEntryType.SPECIAL:
            admission = None
            entry = None
            self._pending_diagnostics.append(
                ScanDiagnostic(
                    ScanObservationCode.UNSUPPORTED_ENTRY_TYPE,
                    source.relative_path,
                    (source.relative_path,),
                )
            )
        else:
            try:
                admission = self._admission.probe(
                    canonical_root=self.intent.root_path_snapshot,
                    relative_path=source.relative_path,
                    expected_stat=source.expected_stat,
                )
            except SourceChangedDuringProbe:
                admission = None
                entry = None
                self._pending_diagnostics.append(
                    ScanDiagnostic(
                        ScanObservationCode.SOURCE_CHANGED_DURING_SCAN,
                        source.relative_path,
                        (source.relative_path,),
                    )
                )
            else:
                if isinstance(admission, SourceAdmissionRejection):
                    self._pending_diagnostics.append(
                        ScanDiagnostic(
                            admission.reason,
                            source.relative_path,
                            (source.relative_path,),
                        )
                    )
                elif not isinstance(admission, SourceAdmissionEvidence):
                    raise TypeError("source admission returned an unsupported result")
                entry = admission.to_probed_entry()
        self._pending_observations.append(
            PendingSourceObservation(
                SourceObservation(
                    source,
                    self._presence_generation,
                    admission,
                ),
                pending_parent_epoch,
            )
        )
        if entry is not None and entry.admission in {
            AdmissionKind.PRIMARY,
            AdmissionKind.AUDIO_TRACK,
        }:
            self._slice_candidate_count += 1
        self._flush(force=False)
        if entry is None or entry.admission in {
            AdmissionKind.SIDECAR,
            AdmissionKind.UNSUPPORTED,
            AdmissionKind.IGNORED,
        }:
            return (
                entry
                if entry is not None and entry.entry_type is not EntryType.FILE
                else None
            )
        return entry

    def _source_or_issue(
        self,
        observation: DiscoveredSource | DiscoveryIssue,
    ) -> DiscoveredSource | None:
        self._slice_observation_count += 1
        if isinstance(observation, DiscoveredSource):
            return observation
        if observation.code is DiscoveryIssueCode.PATH_NAME_UNSUPPORTED:
            unit_path = observation.parent_path or ("$root",)
            self._pending_diagnostics.append(
                ScanDiagnostic(
                    ScanObservationCode.PATH_NAME_UNSUPPORTED,
                    unit_path,
                    (unit_path,),
                )
            )
        self._flush(force=False)
        return None

    def _ignored(self, path: tuple[str, ...]) -> bool:
        if is_system_noise_name(path[-1]):
            self._flush(force=False)
            return True
        compared = tuple(
            comparison_component(component, self.intent.path_comparison)
            for component in path
        )
        ignored = (
            compared[-1] in self._ignored_names
            or "/".join(compared) in self._ignored_paths
        )
        if ignored:
            self._flush(force=False)
        return ignored

    def _begin_directory(
        self,
        source: DiscoveredSource,
        pending_parent_epoch: int | None,
    ) -> tuple[ProbedEntry, DirectoryPresenceEpoch]:
        entry = self._observe(source, pending_parent_epoch)
        if entry is None:
            raise ReconcileStale()
        collisions = self._flush(force=True)
        if any(
            source.relative_path in collision.related_paths for collision in collisions
        ):
            raise _CollisionRecheckRequired
        binding = self._source_bindings.get(source.relative_path)
        if binding is None:
            raise ReconcileStale()
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            epoch = uow.sources.begin_directory_presence(
                self.fence,
                binding,
                observed_at=now,
            )
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated
        return entry, epoch

    def _finish_directory(self, epoch: DirectoryPresenceEpoch) -> None:
        self._flush(force=True)
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            successor = uow.watcher.has_overlapping_successor(
                self.fence,
                self.intent.scopes,
            )
            if not successor and not uow.sources.flip_directory_presence(
                self.fence,
                epoch,
                completed_at=now,
            ):
                raise ReconcileStale()
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated

    def _flush(self, *, force: bool) -> tuple[PathCollision, ...]:
        elapsed = self._monotonic_clock.seconds() - self._slice_started
        if not force and (
            self._slice_candidate_count < _MAX_CANDIDATES_PER_SLICE
            and self._slice_observation_count < _MAX_OBSERVATIONS_PER_SLICE
            and elapsed < _MAX_SLICE_SECONDS
        ):
            return ()
        if (
            not self._pending_observations
            and not self._pending_diagnostics
            and self._slice_observation_count == 0
        ):
            self._reset_slice()
            return ()
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            collisions: tuple[PathCollision, ...] = ()
            bindings: tuple[SourcePathBinding, ...] = ()
            if self._pending_observations:
                outcome = uow.sources.upsert_reconcile_observations(
                    self.fence,
                    tuple(self._pending_observations),
                    observed_at=now,
                )
                collisions = outcome.collisions
                bindings = outcome.bindings
            collision_diagnostics = tuple(
                ScanDiagnostic(
                    ViolationCode.PATH_NORMALIZATION_COLLISION,
                    collision_unit_path(
                        self.intent.organization_mode,
                        collision.related_paths[0],
                    ),
                    collision.related_paths,
                )
                for collision in collisions
            )
            diagnostics = (*self._pending_diagnostics, *collision_diagnostics)
            if diagnostics:
                uow.diagnostics.record(self.fence, diagnostics, observed_at=now)
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated
        if collisions:
            self._collision_seen = True
        self._source_bindings.update(
            (binding.relative_path, binding)
            for binding in bindings
            if self._bounded_binding_paths is None
            or binding.relative_path in self._bounded_binding_paths
        )
        self._pending_observations.clear()
        self._pending_diagnostics.clear()
        self._reset_slice()
        return collisions

    def _reset_slice(self) -> None:
        self._slice_observation_count = 0
        self._slice_candidate_count = 0
        self._slice_started = self._monotonic_clock.seconds()

    def _attempt_proven_move(self) -> None:
        move = self.intent.move_evidence
        if move is None:
            return
        source = self._session.observe_path(move.source_path)
        destination = self._session.observe_path(move.destination_path)
        if not isinstance(source, TargetedPathAbsent) or not isinstance(
            destination, DiscoveredSource
        ):
            return
        expected_entry_type = (
            DiscoveryEntryType.FILE
            if move.entry_type is WatcherMovedEntryType.FILE
            else DiscoveryEntryType.DIRECTORY
        )
        if (
            destination.entry_type is not expected_entry_type
            or destination.filesystem_identity is None
        ):
            return
        evidence = ProvenMoveEvidence(
            move.source_path,
            move.destination_path,
            destination.filesystem_identity,
            move.entry_type,
            source,
        )
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            if uow.watcher.has_overlapping_successor(
                self.fence,
                self.intent.scopes,
            ):
                updated = self._heartbeat_in_uow(uow, now)
                uow.commit()
                self.intent = updated
                return
            result = uow.sources.apply_proven_move(
                self.fence,
                evidence,
                observed_at=now,
            )
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated
        if (
            result.disposition is not SourceRebindDisposition.NOT_PROVEN
            and result.binding is not None
        ):
            self._source_bindings[result.binding.relative_path] = result.binding

    def _materialize_group(self, group: TopologyActivationGroup) -> int:
        if sum(len(unit.rows) for unit in group.units) <= 500:
            return self._materialize_group_atomic(group)
        staged = tuple(
            revision
            for plan in group.units
            if (revision := self._stage_unit(plan)) is not None
        )
        if not staged:
            return 0
        self._activate_group(staged)
        return len(staged)

    def _bound_plan(
        self,
        uow: WatcherUnitOfWork,
        plan: TopologyUnitPlan,
    ) -> BoundTopologyUnitPlan:
        try:
            bindings = tuple(
                self._source_bindings[path]
                for path in required_topology_source_paths(plan)
            )
        except KeyError as error:
            raise ReconcileStale() from error
        bound = uow.topology.bind_plan(self.fence, plan, bindings)
        if bound is None:
            raise ReconcileStale()
        return bound

    def _materialize_group_atomic(self, group: TopologyActivationGroup) -> int:
        self._require_root()
        now = self._clock.now()
        staged: list[StagingRevision] = []
        with self._unit_of_work_factory() as uow:
            for plan in group.units:
                bound = self._bound_plan(uow, plan)
                uow.topology.abandon_incomplete(
                    self.fence,
                    unit_id=bound.unit_id,
                    abandoned_at=now,
                )
                active = uow.topology.get_active_revision_id(
                    self.intent.library_id,
                    unit_id=bound.unit_id,
                )
                revision = uow.topology.begin_staging(
                    self.fence,
                    bound,
                    expected_active_revision_id=active,
                    created_at=now,
                )
                if revision is None:
                    continue
                batch = next(iter(_iter_bound_batches(bound)))
                revision = uow.topology.append_staging_batch(
                    self.fence,
                    revision,
                    batch,
                    staged_at=now,
                )
                staged.append(revision)
            if not staged:
                updated = self._heartbeat_in_uow(uow, now)
                uow.commit()
                self.intent = updated
                return 0
            updated = self._heartbeat_in_uow(uow, now)
            if not uow.topology.activate_staging_group(
                self.fence,
                tuple(staged),
                activated_at=now,
            ):
                raise ReconcileStale()
            self._append_activation_outboxes(uow, tuple(staged))
            uow.commit()
            self.intent = updated
            return len(staged)

    def _stage_unit(self, plan: TopologyUnitPlan) -> StagingRevision | None:
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            bound = self._bound_plan(uow, plan)
            batches = iter(_iter_bound_batches(bound))
            first_batch = next(batches)
            uow.topology.abandon_incomplete(
                self.fence,
                unit_id=bound.unit_id,
                abandoned_at=now,
            )
            active = uow.topology.get_active_revision_id(
                self.intent.library_id,
                unit_id=bound.unit_id,
            )
            staging = uow.topology.begin_staging(
                self.fence,
                bound,
                expected_active_revision_id=active,
                created_at=now,
            )
            if staging is None:
                updated = self._heartbeat_in_uow(uow, now)
                uow.commit()
                self.intent = updated
                return None
            staging = uow.topology.append_staging_batch(
                self.fence,
                staging,
                first_batch,
                staged_at=now,
            )
            updated = self._heartbeat_in_uow(uow, now)
            uow.commit()
            self.intent = updated
        for batch in batches:
            self._require_root()
            now = self._clock.now()
            with self._unit_of_work_factory() as uow:
                staging = uow.topology.append_staging_batch(
                    self.fence,
                    staging,
                    batch,
                    staged_at=now,
                )
                updated = self._heartbeat_in_uow(uow, now)
                uow.commit()
                self.intent = updated
        return staging

    def _activate_group(self, staging: tuple[StagingRevision, ...]) -> None:
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            updated = self._heartbeat_in_uow(uow, now)
            if not uow.topology.activate_staging_group(
                self.fence,
                staging,
                activated_at=now,
            ):
                raise ReconcileStale()
            self._append_activation_outboxes(uow, staging)
            uow.commit()
            self.intent = updated

    def _append_activation_outboxes(
        self,
        uow: WatcherUnitOfWork,
        staging: tuple[StagingRevision, ...],
    ) -> None:
        for revision in staging:
            uow.outbox.append(
                OutboxEvent(
                    "CATALOG_TOPOLOGY_UNIT_ACTIVATED",
                    self.intent.library_id,
                    "SYSTEM",
                    (
                        ("reconcileIntentId", self.intent.intent_id),
                        ("throughSequence", self.intent.through_sequence),
                        ("unitId", revision.unit_id),
                        ("unitRevisionId", revision.revision_id),
                    ),
                )
            )

    def _begin_fold_and_complete(self) -> ReconcileRunResult:
        self._require_root()
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            updated = uow.watcher.begin_fold(self.fence, now=now)
            if updated is None:
                raise ReconcileLeaseLost()
            updated = self._heartbeat_in_uow(uow, now, intent=updated)
            uow.commit()
            self.intent = updated
        return self._fold_and_complete()

    def _fold_and_complete(self) -> ReconcileRunResult:
        while True:
            self._require_root()
            now = self._clock.now()
            with self._unit_of_work_factory() as uow:
                page = uow.sources.fold_effective_presence(
                    self.fence,
                    after_source_entry_id=self.intent.fold_after_source_entry_id,
                    limit=MAX_PRESENCE_FOLD_ROWS,
                    folded_at=now,
                )
                if page.complete:
                    if not uow.watcher.complete_delete(
                        self.fence,
                        completed_at=now,
                    ):
                        raise ReconcileLeaseLost()
                    uow.outbox.append(
                        OutboxEvent(
                            "LIBRARY_RECONCILE_COMPLETED",
                            self.intent.library_id,
                            "SYSTEM",
                            (
                                ("intentId", self.intent.intent_id),
                                ("throughSequence", self.intent.through_sequence),
                            ),
                        )
                    )
                    uow.commit()
                    return ReconcileRunResult(
                        ReconcileRunDisposition.COMPLETED,
                        self.intent.intent_id,
                        self._units_activated,
                    )
                updated = uow.watcher.advance_fold_cursor(
                    self.fence,
                    after_source_entry_id=page.next_source_entry_id,
                    now=now,
                )
                if updated is None:
                    raise ReconcileLeaseLost()
                updated = self._heartbeat_in_uow(uow, now, intent=updated)
                uow.commit()
                self.intent = updated

    def _force_collision_recheck(self) -> ReconcileRunResult:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            transition = uow.watcher.force_full_rescan_from_running(
                self.fence,
                reason=FullRescanReason.COLLISION_RECHECK,
                observed_at=now,
            )
            if transition is None:
                raise ReconcileLeaseLost()
            _append_full_scan_required(uow, transition)
            uow.commit()
        return ReconcileRunResult(
            ReconcileRunDisposition.FULL_SCAN_REQUIRED,
            self.intent.intent_id,
            self._units_activated,
        )

    def _heartbeat_in_uow(
        self,
        uow: WatcherUnitOfWork,
        now: datetime,
        *,
        intent: ReconcileIntent | None = None,
    ) -> ReconcileIntent:
        current = self.intent if intent is None else intent
        updated = uow.watcher.heartbeat(
            current.fence(presence_generation=self._presence_generation),
            now=now,
            lease_expires_at=scan_lease_deadline(now, self._lease_seconds),
        )
        if updated is None:
            raise ReconcileLeaseLost()
        return updated

    def _require_root(self) -> None:
        if (
            self._session.revalidate_root_identity()
            != self.intent.root_identity_snapshot
        ):
            raise ReconcileRootIdentityChanged()

    def _discard_source_bindings_under(
        self,
        relative_path: tuple[str, ...],
    ) -> None:
        for path in tuple(self._source_bindings):
            if path[: len(relative_path)] == relative_path:
                del self._source_bindings[path]

    def _begin_bounded_binding_retention(
        self,
        unit_root: tuple[str, ...],
    ) -> None:
        if self._bounded_binding_paths is not None:
            raise RuntimeError("bounded binding retention cannot be nested")
        self._bounded_binding_paths = {
            unit_root[:depth] for depth in range(1, len(unit_root) + 1)
        }

    def _end_bounded_binding_retention(self) -> None:
        self._bounded_binding_paths = None

    def _allow_bounded_binding(self, relative_path: tuple[str, ...]) -> None:
        if self._bounded_binding_paths is None:
            raise RuntimeError("bounded binding retention is not active")
        self._bounded_binding_paths.add(relative_path)

    def _retain_bounded_binding(
        self,
        retained: _BoundedLayoutEntries,
        entry: ProbedEntry | None,
        *,
        relative_path: tuple[str, ...],
        unit_root: tuple[str, ...],
    ) -> None:
        if retained.retain(entry):
            return
        if self._bounded_binding_paths is None:
            raise RuntimeError("bounded binding retention is not active")
        self._bounded_binding_paths.discard(relative_path)
        self._discard_source_bindings_under(relative_path)
        if retained.overflow_code is not None:
            self._bounded_binding_paths.clear()
            self._discard_source_bindings_under(unit_root)


__all__ = ["RunNextReconcileSubtree"]
