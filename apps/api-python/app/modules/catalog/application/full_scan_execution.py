"""Bounded full-scan discovery, admission and topology materialization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from app.modules.catalog.application.ports import (
    Clock,
)
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryIssue,
    DiscoveryIssueCode,
    FailFullLibraryScanCommand,
    FinalizeFullLibraryScanCommand,
    FullScanRun,
    PathCollision,
    RunFullLibraryScanCommand,
    RunFullLibraryScanResult,
    ScanFailureCode,
    ScanFence,
    SourceObservation,
    StagingRevision,
)
from app.modules.catalog.application.scan_lifecycle import (
    FailFullLibraryScan,
    FinalizeFullLibraryScan,
    append_activation_outboxes,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryChangedDuringDiscovery,
    DirectoryDiscoveryOperationalError,
    DirectoryDiscoveryPort,
    DirectoryDiscoverySession,
    DirectoryIoError,
    DirectoryPermissionDenied,
    DirectoryRootUnavailable,
    InvalidDiscoveryRelativePath,
    MonotonicClock,
    ScanUnitOfWork,
    ScanUowFactory,
)
from app.modules.catalog.application.scan_runtime_policy import (
    SCANNABLE_LIBRARY_STATES,
    scan_lease_deadline,
)
from app.modules.catalog.application.source_admission_ports import (
    InvalidSourceRelativePath,
    SourceAdmissionOperationalError,
    SourceAdmissionPort,
    SourceChangedDuringProbe,
    SourceProbePermissionDenied,
    SourceProbeUnavailable,
)
from app.modules.catalog.domain.admission import (
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
    is_system_noise_name,
    parse_disc_component,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule, IgnoreRuleKind
from app.modules.catalog.domain.layouts import interpret_layout
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    ProbedEntry,
    ViolationCode,
    VolumeCandidate,
)
from app.modules.catalog.domain.ordering import comparison_component, comparison_path
from app.modules.catalog.domain.scan import (
    MAX_AUDIO_TRACKS,
    MAX_STRUCTURAL_ENTRIES_PER_UNIT,
    ScanConflict,
    ScanDiagnostic,
    ScanLeaseLost,
    ScanNotFound,
    ScanObservationCode,
    ScanRootIdentityChanged,
    ScanStage,
    ScanStale,
    ScanState,
    TopologyActivationGroup,
    TopologyUnitPlan,
    build_topology_activation_groups,
    collision_unit_path,
    iter_stage_batches,
)

_MAX_CANDIDATES_PER_SLICE = 500
_MAX_OBSERVATIONS_PER_SLICE = 5_000
_MAX_SLICE_SECONDS = 0.250


class RunFullLibraryScan:
    """Synchronously enumerate one full scan through bounded short transactions."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ScanUowFactory,
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

    def execute(self, command: RunFullLibraryScanCommand) -> RunFullLibraryScanResult:
        run, ignore_rules = self._load_owned_run(command)
        activated = 0
        try:
            with self._discovery.open(canonical_root=run.canonical_root) as session:
                run = self._bind_root(command, run, session.root_identity)
                if run.state is not ScanState.FINALIZING:
                    execution = _ScanExecution(
                        unit_of_work_factory=self._unit_of_work_factory,
                        admission=self._admission,
                        clock=self._clock,
                        monotonic_clock=self._monotonic_clock,
                        session=session,
                        run=run,
                        lease_seconds=command.lease_seconds,
                        ignore_rules=ignore_rules,
                    )
                    activated = execution.run_to_finalize_stage()
                    run = execution.run
                if session.revalidate_root_identity() != run.root_identity:
                    raise ScanRootIdentityChanged()
            completed = FinalizeFullLibraryScan(
                unit_of_work_factory=self._unit_of_work_factory,
                discovery=self._discovery,
                clock=self._clock,
            ).execute(
                FinalizeFullLibraryScanCommand(
                    command.library_id, command.scan_id, command.owner_token
                )
            )
            return RunFullLibraryScanResult(completed, activated)
        except SourceChangedDuringProbe:
            raise AssertionError("source drift must be contained per observation")
        except (
            DirectoryDiscoveryOperationalError,
            SourceAdmissionOperationalError,
        ) as error:
            self._mark_failed(command, _failure_code(error))
            raise
        except ScanRootIdentityChanged:
            self._mark_failed(command, ScanFailureCode.ROOT_IDENTITY_CHANGED)
            raise

    def _load_owned_run(
        self, command: RunFullLibraryScanCommand
    ) -> tuple[FullScanRun, tuple[IgnoreRule, ...]]:
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            library = uow.libraries.get_for_scan_for_update(command.library_id)
            run = uow.scans.get_for_update(command.library_id, command.scan_id)
            if library is None or run is None:
                raise ScanNotFound()
            if run.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            if (
                run.state
                not in {ScanState.PENDING, ScanState.RUNNING, ScanState.FINALIZING}
                or library.control_state not in SCANNABLE_LIBRARY_STATES
            ):
                raise ScanConflict()
            work_item = uow.work_items.get_root_for_update(
                command.library_id, command.scan_id
            )
            if work_item is None:
                raise ScanStale()
            if work_item.root_path_snapshot != run.root_path_snapshot:
                raise ScanStale()
            if work_item.state is ScanState.PENDING:
                claimed = uow.work_items.claim_pending_root(
                    run.fence(),
                    work_item_id=work_item.work_item_id,
                    owner_token=command.owner_token,
                    now=now,
                    lease_expires_at=lease_expires_at,
                )
                if claimed is None:
                    raise ScanConflict()
            elif work_item.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            updated = uow.scans.heartbeat(
                run.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
            )
            if updated is None:
                raise ScanLeaseLost()
            if not uow.work_items.heartbeat_root(
                updated.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
                discovered_increment=0,
            ):
                raise ScanLeaseLost()
            uow.commit()
            return updated, library.ignore_rules

    def _bind_root(
        self,
        command: RunFullLibraryScanCommand,
        run: FullScanRun,
        root_identity: str,
    ) -> FullScanRun:
        if run.root_identity is not None:
            if run.root_identity != root_identity:
                raise ScanRootIdentityChanged()
            if run.state is ScanState.RUNNING and run.stage is not ScanStage.DISCOVER:
                return self._restart_from_root(command, run)
            return run
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            current = uow.scans.get_for_update(command.library_id, command.scan_id)
            if current is None or current.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            if not uow.sources.bind_synthetic_root(
                current.fence(),
                observed_identity=root_identity,
                observed_at=now,
            ):
                raise ScanRootIdentityChanged()
            started = uow.scans.start_running(
                current.fence(),
                root_identity=root_identity,
                started_at=now,
                lease_expires_at=lease_expires_at,
            )
            if started is None:
                raise ScanStale()
            if not uow.work_items.heartbeat_root(
                started.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
                discovered_increment=0,
            ):
                raise ScanLeaseLost()
            uow.commit()
            return started

    def _restart_from_root(
        self, command: RunFullLibraryScanCommand, run: FullScanRun
    ) -> FullScanRun:
        now = self._clock.now()
        lease_expires_at = scan_lease_deadline(now, command.lease_seconds)
        with self._unit_of_work_factory() as uow:
            current = uow.scans.get_for_update(command.library_id, command.scan_id)
            if current is None or current.lease_owner != command.owner_token:
                raise ScanLeaseLost()
            restarted = uow.scans.restart_from_root(
                current.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
            )
            if restarted is None:
                raise ScanStale()
            uow.topology.abandon_scan_staging(restarted.fence(), abandoned_at=now)
            if not uow.work_items.set_stage(
                current.fence(),
                expected_stage=current.stage,
                next_stage=ScanStage.DISCOVER,
            ):
                raise ScanStale()
            if not uow.work_items.heartbeat_root(
                restarted.fence(),
                now=now,
                lease_expires_at=lease_expires_at,
                discovered_increment=0,
            ):
                raise ScanLeaseLost()
            uow.commit()
            return restarted

    def _mark_failed(
        self, command: RunFullLibraryScanCommand, failure_code: ScanFailureCode
    ) -> None:
        FailFullLibraryScan(
            unit_of_work_factory=self._unit_of_work_factory,
            clock=self._clock,
        ).execute(
            FailFullLibraryScanCommand(
                command.library_id,
                command.scan_id,
                command.owner_token,
                failure_code,
            )
        )


def _failure_code(error: BaseException) -> ScanFailureCode:
    if isinstance(error, DirectoryRootUnavailable | SourceProbeUnavailable):
        return ScanFailureCode.ROOT_UNAVAILABLE
    if isinstance(error, DirectoryPermissionDenied | SourceProbePermissionDenied):
        return ScanFailureCode.PERMISSION_DENIED
    if isinstance(error, DirectoryChangedDuringDiscovery):
        return ScanFailureCode.DIRECTORY_CHANGED
    if isinstance(error, InvalidDiscoveryRelativePath | InvalidSourceRelativePath):
        return ScanFailureCode.INVALID_RELATIVE_PATH
    if isinstance(error, DirectoryIoError):
        return ScanFailureCode.IO_ERROR
    return ScanFailureCode.IO_ERROR


class _ScanExecution:
    def __init__(
        self,
        *,
        unit_of_work_factory: ScanUowFactory,
        admission: SourceAdmissionPort,
        clock: Clock,
        monotonic_clock: MonotonicClock,
        session: DirectoryDiscoverySession,
        run: FullScanRun,
        lease_seconds: int,
        ignore_rules: tuple[IgnoreRule, ...],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._admission = admission
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._session = session
        self.run = run
        self._lease_seconds = lease_seconds
        self._ignore_rules = ignore_rules
        self._ignored_names = frozenset(
            comparison_component(rule.pattern, run.path_comparison)
            for rule in ignore_rules
            if rule.enabled and rule.kind is IgnoreRuleKind.NAME
        )
        self._ignored_paths = frozenset(
            "/".join(
                comparison_component(component, run.path_comparison)
                for component in rule.pattern.split("/")
            )
            for rule in ignore_rules
            if rule.enabled and rule.kind is IgnoreRuleKind.PATH
        )
        self._pending_observations: list[SourceObservation] = []
        self._pending_diagnostics: list[ScanDiagnostic] = []
        self._slice_observation_count = 0
        self._slice_candidate_count = 0
        self._slice_started = monotonic_clock.seconds()
        self._units_activated = 0
        self._blocked_units: set[tuple[str, ...]] = set()

    def run_to_finalize_stage(self) -> int:
        if self.run.organization_mode is OrganizationMode.FLAT:
            self._scan_flat()
        elif self.run.organization_mode is OrganizationMode.VOLUMES:
            self._scan_volumes()
        else:
            self._scan_audiobook()
        self._flush_slice(force=True)
        self._advance_stage(ScanStage.DISCOVER, ScanStage.RECONCILE)
        self._begin_finalizing()
        return self._units_activated

    def _scan_flat(self) -> None:
        for observation in self._session.iter_directory(()):
            source = self._source_or_issue(observation)
            if source is None or self._ignored(source.relative_path):
                continue
            self._process_layout_unit((source,))

    def _scan_volumes(self) -> None:
        for observation in self._session.iter_directory(()):
            work = self._source_or_issue(observation)
            if work is None or self._ignored(work.relative_path):
                continue
            if work.entry_type is not DiscoveryEntryType.DIRECTORY:
                self._process_layout_unit((work,))
                continue
            work_entry = self._observe(work)
            if work_entry is None:
                continue
            for child_observation in self._session.iter_directory(work.relative_path):
                child = self._source_or_issue(child_observation)
                if child is None or self._ignored(child.relative_path):
                    continue
                if child.entry_type is not DiscoveryEntryType.DIRECTORY:
                    self._process_layout_unit((work, child))
                    continue
                version_entry = self._observe(child)
                if version_entry is None:
                    continue
                for volume_observation in self._session.iter_directory(
                    child.relative_path
                ):
                    volume = self._source_or_issue(volume_observation)
                    if volume is None or self._ignored(volume.relative_path):
                        continue
                    if volume.entry_type is DiscoveryEntryType.DIRECTORY:
                        bundle = self._collect_bundle(volume)
                        if bundle is not None:
                            self._process_probed_unit(
                                (work_entry, version_entry, *bundle)
                            )
                    else:
                        self._process_layout_unit((work, child, volume))
            self._flush_slice(force=False)

    def _scan_audiobook(self) -> None:
        for observation in self._session.iter_directory(()):
            work = self._source_or_issue(observation)
            if work is None or self._ignored(work.relative_path):
                continue
            if work.entry_type is not DiscoveryEntryType.DIRECTORY:
                self._process_layout_unit((work,))
                continue
            work_entry = self._observe(work)
            if work_entry is None:
                continue
            entries: list[ProbedEntry] = [work_entry]
            track_count = 0
            structural_count = 1
            overflow_code: ViolationCode | ScanObservationCode | None = None
            for child in self._walk_audiobook_work(work.relative_path):
                entry = self._observe(child)
                if entry is None:
                    continue
                if overflow_code is not None:
                    continue
                if (
                    entry.admission is AdmissionKind.AUDIO_TRACK
                    and entry.entry_type is EntryType.FILE
                ):
                    track_count += 1
                    if track_count > MAX_AUDIO_TRACKS:
                        overflow_code = ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED
                if entry.entry_type in {
                    EntryType.DIRECTORY,
                    EntryType.SYMLINK,
                    EntryType.JUNCTION,
                }:
                    structural_count += 1
                    if structural_count > MAX_STRUCTURAL_ENTRIES_PER_UNIT:
                        overflow_code = (
                            ScanObservationCode.TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED
                        )
                if len(entries) >= MAX_AUDIO_TRACKS + MAX_STRUCTURAL_ENTRIES_PER_UNIT:
                    overflow_code = (
                        ScanObservationCode.TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED
                    )
                if overflow_code is not None:
                    entries.clear()
                    continue
                entries.append(entry)
            if overflow_code is not None:
                self._pending_diagnostics.append(
                    ScanDiagnostic(
                        overflow_code,
                        work.relative_path,
                        (work.relative_path,),
                    )
                )
                self._flush_slice(force=True)
            else:
                self._process_probed_unit(tuple(entries))

    def _walk_audiobook_work(
        self, work_path: tuple[str, ...]
    ) -> Iterable[DiscoveredSource]:
        for observation in self._session.iter_directory(work_path):
            child = self._source_or_issue(observation)
            if child is None or self._ignored(child.relative_path):
                continue
            yield child
            if child.entry_type is not DiscoveryEntryType.DIRECTORY:
                continue
            for nested_observation in self._session.iter_directory(child.relative_path):
                nested = self._source_or_issue(nested_observation)
                if nested is None or self._ignored(nested.relative_path):
                    continue
                yield nested
                if (
                    nested.entry_type is DiscoveryEntryType.DIRECTORY
                    and parse_disc_component(nested.relative_path[-1]) is not None
                ):
                    for disc_observation in self._session.iter_directory(
                        nested.relative_path
                    ):
                        disc_child = self._source_or_issue(disc_observation)
                        if disc_child is not None and not self._ignored(
                            disc_child.relative_path
                        ):
                            yield disc_child

    def _collect_bundle(
        self, volume: DiscoveredSource
    ) -> tuple[ProbedEntry, ...] | None:
        volume_entry = self._observe(volume)
        if volume_entry is None:
            return ()
        entries: list[ProbedEntry] = [volume_entry]
        track_count = 0
        structural_count = 1
        overflow_code: ViolationCode | ScanObservationCode | None = None

        def retain(entry: ProbedEntry | None) -> None:
            nonlocal track_count, structural_count, overflow_code
            if entry is None or overflow_code is not None:
                return
            if entry.admission is AdmissionKind.AUDIO_TRACK:
                track_count += 1
                if track_count > MAX_AUDIO_TRACKS:
                    overflow_code = ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED
            if entry.entry_type in {
                EntryType.DIRECTORY,
                EntryType.SYMLINK,
                EntryType.JUNCTION,
            }:
                structural_count += 1
                if structural_count > MAX_STRUCTURAL_ENTRIES_PER_UNIT:
                    overflow_code = (
                        ScanObservationCode.TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED
                    )
            if len(entries) >= MAX_AUDIO_TRACKS + MAX_STRUCTURAL_ENTRIES_PER_UNIT:
                overflow_code = ScanObservationCode.TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED
            if overflow_code is not None:
                entries.clear()
                return
            entries.append(entry)

        for observation in self._session.iter_directory(volume.relative_path):
            child = self._source_or_issue(observation)
            if child is None or self._ignored(child.relative_path):
                continue
            entry = self._observe(child)
            retain(entry)
            if (
                child.entry_type is DiscoveryEntryType.DIRECTORY
                and parse_disc_component(child.relative_path[-1]) is not None
            ):
                for disc_observation in self._session.iter_directory(
                    child.relative_path
                ):
                    disc_child = self._source_or_issue(disc_observation)
                    if disc_child is None or self._ignored(disc_child.relative_path):
                        continue
                    disc_entry = self._observe(disc_child)
                    retain(disc_entry)
                    self._flush_slice(force=False)
            self._flush_slice(force=False)
        if overflow_code is not None:
            self._pending_diagnostics.append(
                ScanDiagnostic(
                    overflow_code,
                    volume.relative_path,
                    (volume.relative_path,),
                )
            )
            self._flush_slice(force=True)
            return None
        return tuple(entries)

    def _process_layout_unit(self, sources: tuple[DiscoveredSource, ...]) -> None:
        entries = tuple(entry for source in sources if (entry := self._observe(source)))
        self._process_probed_unit(entries)

    def _process_probed_unit(self, entries: tuple[ProbedEntry, ...]) -> None:
        if not entries:
            return
        result = interpret_layout(
            self.run.organization_mode,
            entries,
            path_comparison=self.run.path_comparison,
        )
        self._pending_diagnostics.extend(
            ScanDiagnostic(
                violation.code,
                violation.unit_path,
                violation.related_paths,
            )
            for violation in result.violations
        )
        self._flush_slice(force=True)
        candidates = tuple(
            candidate
            for candidate in result.candidates
            if not self._candidate_blocked(candidate)
        )
        groups = build_topology_activation_groups(
            self.run.organization_mode,
            candidates,
            path_comparison=self.run.path_comparison,
        )
        for group in groups:
            self._units_activated += self._materialize_group(group)

    def _observe(self, source: DiscoveredSource) -> ProbedEntry | None:
        if source.entry_type is DiscoveryEntryType.DIRECTORY:
            entry = ProbedEntry(
                source.relative_path,
                EntryType.DIRECTORY,
                AdmissionKind.IGNORED,
            )
            self._pending_observations.append(
                SourceObservation(source, self.run.generation, None)
            )
            self._flush_slice(force=False)
            return entry
        if source.entry_type in {
            DiscoveryEntryType.SYMLINK,
            DiscoveryEntryType.JUNCTION,
        }:
            self._pending_observations.append(
                SourceObservation(source, self.run.generation, None)
            )
            entry_type = (
                EntryType.SYMLINK
                if source.entry_type is DiscoveryEntryType.SYMLINK
                else EntryType.JUNCTION
            )
            entry = ProbedEntry(
                source.relative_path,
                entry_type,
                AdmissionKind.IGNORED,
            )
            self._flush_slice(force=False)
            return entry
        if source.entry_type is DiscoveryEntryType.SPECIAL:
            self._pending_observations.append(
                SourceObservation(source, self.run.generation, None)
            )
            self._pending_diagnostics.append(
                ScanDiagnostic(
                    ScanObservationCode.UNSUPPORTED_ENTRY_TYPE,
                    source.relative_path,
                    (source.relative_path,),
                )
            )
            self._flush_slice(force=False)
            return None
        try:
            admission = self._admission.probe(
                canonical_root=self.run.canonical_root,
                relative_path=source.relative_path,
                expected_stat=source.expected_stat,
            )
        except SourceChangedDuringProbe:
            self._pending_observations.append(
                SourceObservation(source, self.run.generation, None)
            )
            self._pending_diagnostics.append(
                ScanDiagnostic(
                    ScanObservationCode.SOURCE_CHANGED_DURING_SCAN,
                    source.relative_path,
                    (source.relative_path,),
                )
            )
            self._flush_slice(force=False)
            return None
        self._pending_observations.append(
            SourceObservation(source, self.run.generation, admission)
        )
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
        if entry.admission in {AdmissionKind.PRIMARY, AdmissionKind.AUDIO_TRACK}:
            self._slice_candidate_count += 1
        self._flush_slice(force=False)
        if entry.admission in {
            AdmissionKind.SIDECAR,
            AdmissionKind.UNSUPPORTED,
            AdmissionKind.IGNORED,
        }:
            return None
        return entry

    def _source_or_issue(
        self, observation: DiscoveredSource | DiscoveryIssue
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
        self._flush_slice(force=False)
        return None

    def _ignored(self, path: tuple[str, ...]) -> bool:
        if is_system_noise_name(path[-1]):
            self._flush_slice(force=False)
            return True
        compared_components = tuple(
            comparison_component(component, self.run.path_comparison)
            for component in path
        )
        ignored = (
            compared_components[-1] in self._ignored_names
            or "/".join(compared_components) in self._ignored_paths
        )
        if ignored:
            self._flush_slice(force=False)
        return ignored

    def _flush_slice(self, *, force: bool) -> None:
        elapsed = self._monotonic_clock.seconds() - self._slice_started
        if not force and (
            self._slice_candidate_count < _MAX_CANDIDATES_PER_SLICE
            and self._slice_observation_count < _MAX_OBSERVATIONS_PER_SLICE
            and elapsed < _MAX_SLICE_SECONDS
        ):
            return
        if (
            not self._pending_observations
            and not self._pending_diagnostics
            and self._slice_observation_count == 0
        ):
            self._slice_started = self._monotonic_clock.seconds()
            self._slice_observation_count = 0
            self._slice_candidate_count = 0
            return
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            fence = self.run.fence()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanLeaseLost()
            collisions: tuple[PathCollision, ...] = ()
            if self._pending_observations:
                outcome = uow.sources.upsert_observations(
                    fence,
                    tuple(self._pending_observations),
                    observed_at=now,
                )
                collisions = outcome.collisions
            collision_diagnostics = tuple(
                ScanDiagnostic(
                    ViolationCode.PATH_NORMALIZATION_COLLISION,
                    collision_unit_path(
                        self.run.organization_mode, collision.related_paths[0]
                    ),
                    collision.related_paths,
                )
                for collision in collisions
            )
            if collisions:
                uow.collisions.record(fence, collisions, observed_at=now)
            diagnostics = (*self._pending_diagnostics, *collision_diagnostics)
            if diagnostics:
                uow.diagnostics.record(
                    fence,
                    diagnostics,
                    observed_at=now,
                )
            updated = self._heartbeat_in_uow(
                uow,
                fence,
                now=now,
                discovered_increment=self._slice_observation_count,
                diagnostic_increment=len(diagnostics),
            )
            uow.commit()
            self.run = updated
        for collision in collisions:
            for related_path in collision.related_paths:
                blocked_unit = collision_unit_path(
                    self.run.organization_mode, related_path
                )
                self._blocked_units.add(
                    comparison_path(blocked_unit, self.run.path_comparison)
                )
        self._pending_observations.clear()
        self._pending_diagnostics.clear()
        self._slice_observation_count = 0
        self._slice_candidate_count = 0
        self._slice_started = self._monotonic_clock.seconds()

    def _candidate_blocked(self, candidate: VolumeCandidate) -> bool:
        candidate_unit = (
            candidate.work_path
            if self.run.organization_mode is OrganizationMode.AUDIOBOOK
            else candidate.volume_path
        )
        candidate_key = comparison_path(candidate_unit, self.run.path_comparison)
        return any(
            candidate_key[: len(blocked)] == blocked
            or blocked[: len(candidate_key)] == candidate_key
            for blocked in self._blocked_units
        )

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

    def _materialize_group_atomic(self, group: TopologyActivationGroup) -> int:
        now = self._clock.now()
        staged = []
        with self._unit_of_work_factory() as uow:
            fence = self.run.fence()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanLeaseLost()
            for plan in group.units:
                uow.topology.abandon_incomplete(
                    fence, unit_key=plan.unit_key, abandoned_at=now
                )
                active = uow.topology.get_active_revision_id(
                    self.run.library_id, unit_key=plan.unit_key
                )
                revision = uow.topology.begin_staging(
                    fence,
                    plan,
                    expected_active_revision_id=active,
                    created_at=now,
                )
                if revision is None:
                    continue
                batch = next(iter(iter_stage_batches(plan)))
                revision = uow.topology.append_staging_batch(
                    fence, revision, batch, staged_at=now
                )
                staged.append(revision)
            if not staged:
                uow.commit()
                return 0
            updated = self._heartbeat_in_uow(uow, fence, now=now)
            if not uow.topology.activate_staging_group(
                fence, tuple(staged), activated_at=now
            ):
                raise ScanStale()
            append_activation_outboxes(
                uow,
                run=self.run,
                staging=tuple(staged),
            )
            uow.commit()
            self.run = updated
            return len(staged)

    def _stage_unit(self, plan: TopologyUnitPlan) -> StagingRevision | None:
        batches = iter(iter_stage_batches(plan))
        first_batch = next(batches)
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            fence = self.run.fence()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanLeaseLost()
            uow.topology.abandon_incomplete(
                fence, unit_key=plan.unit_key, abandoned_at=now
            )
            active = uow.topology.get_active_revision_id(
                self.run.library_id, unit_key=plan.unit_key
            )
            staging = uow.topology.begin_staging(
                fence,
                plan,
                expected_active_revision_id=active,
                created_at=now,
            )
            if staging is None:
                uow.commit()
                return None
            staging = uow.topology.append_staging_batch(
                fence, staging, first_batch, staged_at=now
            )
            updated = self._heartbeat_in_uow(uow, fence, now=now)
            uow.commit()
            self.run = updated
        if first_batch.complete:
            return staging
        for batch in batches:
            now = self._clock.now()
            with self._unit_of_work_factory() as uow:
                fence = self.run.fence()
                if not uow.scans.guard_mutation(fence, now=now):
                    raise ScanLeaseLost()
                staging = uow.topology.append_staging_batch(
                    fence, staging, batch, staged_at=now
                )
                updated = self._heartbeat_in_uow(uow, fence, now=now)
                uow.commit()
                self.run = updated
        return staging

    def _activate_group(self, staged: tuple[StagingRevision, ...]) -> None:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            fence = self.run.fence()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanLeaseLost()
            updated = self._heartbeat_in_uow(uow, fence, now=now)
            if not uow.topology.activate_staging_group(fence, staged, activated_at=now):
                raise ScanStale()
            append_activation_outboxes(
                uow,
                run=self.run,
                staging=staged,
            )
            uow.commit()
            self.run = updated

    def _heartbeat_in_uow(
        self,
        uow: ScanUnitOfWork,
        fence: ScanFence,
        *,
        now: datetime,
        discovered_increment: int = 0,
        diagnostic_increment: int = 0,
    ) -> FullScanRun:
        lease_expires_at = scan_lease_deadline(now, self._lease_seconds)
        updated = uow.scans.heartbeat(
            fence,
            now=now,
            lease_expires_at=lease_expires_at,
            discovered_increment=discovered_increment,
            diagnostic_increment=diagnostic_increment,
        )
        if updated is None:
            raise ScanLeaseLost()
        if not uow.work_items.heartbeat_root(
            fence,
            now=now,
            lease_expires_at=lease_expires_at,
            discovered_increment=discovered_increment,
        ):
            raise ScanLeaseLost()
        return updated

    def _advance_stage(self, expected: ScanStage, following: ScanStage) -> None:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            fence = self.run.fence()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanLeaseLost()
            if not uow.scans.set_stage(
                fence,
                expected_stage=expected,
                next_stage=following,
                now=now,
            ):
                raise ScanStale()
            if not uow.work_items.set_stage(
                fence,
                expected_stage=expected,
                next_stage=following,
            ):
                raise ScanStale()
            uow.commit()
        self.run = replace(self.run, stage=following)

    def _begin_finalizing(self) -> None:
        now = self._clock.now()
        with self._unit_of_work_factory() as uow:
            fence = self.run.fence()
            if not uow.scans.guard_mutation(fence, now=now):
                raise ScanLeaseLost()
            finalizing = uow.scans.begin_finalizing(
                fence,
                expected_stage=ScanStage.RECONCILE,
                now=now,
            )
            if finalizing is None:
                raise ScanStale()
            if not uow.work_items.set_stage(
                fence,
                expected_stage=ScanStage.RECONCILE,
                next_stage=ScanStage.FINALIZE,
            ):
                raise ScanStale()
            uow.commit()
        self.run = finalizing


__all__ = ["RunFullLibraryScan"]
