from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self, cast

import pytest

from app.modules.catalog.application.full_scan_execution import RunFullLibraryScan
from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryIssue,
    DiscoveryIssueCode,
    DiscoveryObservation,
    FullScanRun,
    FullScanWorkItem,
    PathCollision,
    RunFullLibraryScanCommand,
    ScanLibrarySnapshot,
    SourceObservation,
    SourceObservationOutcome,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryDiscoveryPort,
    ScanUowFactory,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceAdmissionPort,
    SourceChangedDuringProbe,
    SourceStatExpectation,
)
from app.modules.catalog.application.watcher_dto import (
    WatcherFinalizeOutcome,
    WatcherState,
)
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    AudioCodec,
    AudioEvidence,
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule, IgnoreRuleKind
from app.modules.catalog.domain.library import LibraryControlState, LibraryHealth
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    ViolationCode,
)
from app.modules.catalog.domain.scan import (
    ScanDiagnostic,
    ScanObservationCode,
    ScanStage,
    ScanState,
)

_NOW = datetime(2026, 8, 18, tzinfo=UTC)
_ROOT_IDENTITY = "17:23"
_EXPECTATION = SourceStatExpectation(17, 29, 4, 31)


class _MutableMonotonicClock:
    def __init__(self) -> None:
        self.value = 0.0

    def seconds(self) -> float:
        return self.value


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


class _TrackingIterator(Iterator[DiscoveryObservation]):
    def __init__(
        self,
        values: Iterator[DiscoveryObservation],
        *,
        before_yield: Callable[[], None],
    ) -> None:
        self._values = values
        self._before_yield = before_yield
        self.consumed = 0
        self.exhausted = False

    def __next__(self) -> DiscoveryObservation:
        try:
            value = next(self._values)
        except StopIteration:
            self.exhausted = True
            raise
        self._before_yield()
        self.consumed += 1
        return value


class _DiscoverySession:
    def __init__(
        self,
        factories: dict[tuple[str, ...], Callable[[], Iterator[DiscoveryObservation]]],
        *,
        before_yield: Callable[[], None],
    ) -> None:
        self._factories = factories
        self._before_yield = before_yield
        self.streams: dict[tuple[str, ...], _TrackingIterator] = {}
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.closed = True

    @property
    def root_identity(self) -> str:
        return _ROOT_IDENTITY

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]:
        stream = _TrackingIterator(
            self._factories[relative_directory](),
            before_yield=self._before_yield,
        )
        self.streams[relative_directory] = stream
        return stream

    def revalidate_root_identity(self) -> str:
        return _ROOT_IDENTITY


class _DiscoveryPort:
    def __init__(
        self,
        factories: dict[tuple[str, ...], Callable[[], Iterator[DiscoveryObservation]]],
        *,
        before_yield: Callable[[], None],
    ) -> None:
        self._factories = factories
        self._before_yield = before_yield
        self.sessions: list[_DiscoverySession] = []

    @property
    def scan_session(self) -> _DiscoverySession:
        return self.sessions[0]

    def open(self, *, canonical_root: str) -> _DiscoverySession:
        assert canonical_root == "/library"
        session = _DiscoverySession(
            self._factories,
            before_yield=self._before_yield,
        )
        self.sessions.append(session)
        return session


class _RejectingAdmission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionRejection:
        assert canonical_root == "/library"
        assert expected_stat is not None
        self.calls.append(relative_path)
        return SourceAdmissionRejection(
            relative_path,
            EntryType.FILE,
            AdmissionRejectionReason.UNSUPPORTED_EXTENSION,
        )


class _AudioAdmission:
    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionEvidence:
        assert canonical_root == "/library"
        assert expected_stat is not None
        return SourceAdmissionEvidence(
            relative_path=relative_path,
            entry_type=EntryType.FILE,
            admission=AdmissionKind.AUDIO_TRACK,
            source_format=SourceFormat.MP3,
            evidence=AudioEvidence(
                source_format=SourceFormat.MP3,
                codec=AudioCodec.MPEG_LAYER_III,
                probe_bytes_examined=4,
                probe_byte_budget=16,
            ),
        )


class _DriftingThenRejectingAdmission(_RejectingAdmission):
    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionRejection:
        if not self.calls:
            self.calls.append(relative_path)
            raise SourceChangedDuringProbe()
        return super().probe(
            canonical_root=canonical_root,
            relative_path=relative_path,
            expected_stat=expected_stat,
        )


class _EventSink:
    def __init__(self) -> None:
        self.values: list[object] = []

    def append(self, value: object) -> None:
        self.values.append(value)


class _DiagnosticSink:
    def __init__(self, batches: list[tuple[ScanDiagnostic, ...]]) -> None:
        self._batches = batches

    def record(
        self,
        _fence: object,
        diagnostics: tuple[ScanDiagnostic, ...],
        *,
        observed_at: datetime,
    ) -> None:
        assert observed_at == _NOW
        self._batches.append(diagnostics)


class _CollisionSink:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def record(
        self,
        _fence: object,
        collisions: tuple[PathCollision, ...],
        *,
        observed_at: datetime,
    ) -> None:
        assert observed_at == _NOW
        self.batch_sizes.append(len(collisions))


class _ForbiddenTopology:
    def abandon_scan_staging(self, _fence: object, *, abandoned_at: datetime) -> None:
        assert abandoned_at == _NOW

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"topology must be blocked in this contract: {name}")


class _ScanStore:
    def __init__(
        self,
        *,
        mode: OrganizationMode,
        ignore_rules: tuple[IgnoreRule, ...],
        progress: Callable[[], bool],
        block_topology_with_collision: bool,
    ) -> None:
        self.library = ScanLibrarySnapshot(
            library_id="library-1",
            canonical_root="/library",
            organization_mode=mode,
            topology_version=1,
            path_comparison=PathComparison.SENSITIVE,
            control_state=LibraryControlState.ACTIVE,
            observed_health=LibraryHealth.HEALTHY,
            config_revision=1,
            topology_writer_fence=1,
            next_scan_generation=2,
            last_successful_generation=None,
            ignore_rules=ignore_rules,
        )
        self.run = FullScanRun(
            scan_id="scan-1",
            library_id="library-1",
            canonical_root="/library",
            generation=1,
            config_revision=1,
            organization_mode=mode,
            topology_version=1,
            path_comparison=PathComparison.SENSITIVE,
            root_identity=_ROOT_IDENTITY,
            topology_writer_fence=1,
            watcher_sequence_watermark=0,
            state=ScanState.RUNNING,
            failure_code=None,
            stage=ScanStage.DISCOVER,
            lease_owner="worker-1",
            lease_expires_at=_NOW + timedelta(minutes=1),
            heartbeat_at=_NOW,
            discovered_count=0,
            diagnostic_count=0,
            created_by_actor_id="actor-1",
            started_at=_NOW,
            finished_at=None,
        )
        self.work_item: FullScanWorkItem | None = FullScanWorkItem(
            work_item_id="work-1",
            library_id="library-1",
            scan_id="scan-1",
            root_path_snapshot="/library",
            scope_relative_path=(),
            state=ScanState.RUNNING,
            stage=ScanStage.DISCOVER,
            lease_owner="worker-1",
            lease_expires_at=_NOW + timedelta(minutes=1),
            attempt=1,
            available_at=_NOW,
            idempotency_key="full-scan:library-1:1",
            discovered_count=0,
        )
        self._progress = progress
        self._block_topology = block_topology_with_collision
        self._collision_returned = False
        self.heartbeat_events: list[tuple[int, bool]] = []
        self.source_batch_sizes: list[int] = []
        self.diagnostic_batches: list[tuple[ScanDiagnostic, ...]] = []
        self.commits = 0

    def get_for_scan_for_update(self, library_id: str) -> ScanLibrarySnapshot | None:
        return self.library if library_id == "library-1" else None

    def get_for_update(self, library_id: str, scan_id: str) -> FullScanRun | None:
        if (library_id, scan_id) != ("library-1", "scan-1"):
            return None
        return self.run

    def get_root_for_update(
        self, library_id: str, scan_id: str
    ) -> FullScanWorkItem | None:
        if (library_id, scan_id) != ("library-1", "scan-1"):
            return None
        return self.work_item

    def guard_mutation(self, _fence: object, *, now: datetime) -> bool:
        return now == _NOW

    def bind_synthetic_root(
        self,
        _fence: object,
        *,
        observed_identity: str,
        observed_at: datetime,
    ) -> bool:
        assert observed_identity == _ROOT_IDENTITY
        assert observed_at == _NOW
        return True

    def upsert_observations(
        self,
        _fence: object,
        observations: tuple[SourceObservation, ...],
        *,
        observed_at: datetime,
    ) -> SourceObservationOutcome:
        assert observed_at == _NOW
        self.source_batch_sizes.append(len(observations))
        if self._block_topology and not self._collision_returned:
            self._collision_returned = True
            return SourceObservationOutcome(
                (
                    PathCollision(
                        parent_path=("Work",),
                        comparison_key="track-collision",
                        related_paths=(
                            ("Work", "track-0001.mp3"),
                            ("Work", "track-0002.mp3"),
                        ),
                    ),
                )
            )
        return SourceObservationOutcome()

    def heartbeat(
        self,
        _fence: object,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int = 0,
        diagnostic_increment: int = 0,
    ) -> FullScanRun:
        if discovered_increment > 0:
            self.heartbeat_events.append((discovered_increment, self._progress()))
        self.run = replace(
            self.run,
            lease_expires_at=lease_expires_at,
            heartbeat_at=now,
            discovered_count=self.run.discovered_count + discovered_increment,
            diagnostic_count=self.run.diagnostic_count + diagnostic_increment,
        )
        return self.run

    def heartbeat_root(
        self,
        _fence: object,
        *,
        now: datetime,
        lease_expires_at: datetime,
        discovered_increment: int,
    ) -> bool:
        assert now == _NOW
        assert lease_expires_at > now
        assert discovered_increment >= 0
        return True

    def set_stage(
        self,
        _fence: object,
        *,
        expected_stage: ScanStage,
        next_stage: ScanStage,
        now: datetime | None = None,
    ) -> bool:
        assert expected_stage is not next_stage
        assert now is None or now == _NOW
        return True

    def begin_finalizing(
        self,
        _fence: object,
        *,
        expected_stage: ScanStage,
        now: datetime,
    ) -> FullScanRun:
        assert expected_stage is ScanStage.RECONCILE
        self.run = replace(
            self.run,
            state=ScanState.FINALIZING,
            stage=ScanStage.FINALIZE,
            heartbeat_at=now,
        )
        return self.run

    def finalize_generation(self, _fence: object, *, completed_at: datetime) -> bool:
        return completed_at == _NOW

    def finalize_full_scan(
        self,
        library_id: str,
        *,
        watcher_sequence_watermark: int,
        completed_at: datetime,
    ) -> WatcherFinalizeOutcome:
        assert library_id == "library-1"
        assert watcher_sequence_watermark == 0
        assert completed_at == _NOW
        return WatcherFinalizeOutcome(
            WatcherState("library-1", 0, None, None),
            discarded_intent_count=0,
            replay_available=False,
        )

    def complete(self, _fence: object, *, completed_at: datetime) -> FullScanRun:
        self.run = replace(
            self.run,
            state=ScanState.COMPLETED,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=completed_at,
        )
        return self.run

    def delete_for_terminal(self, library_id: str, scan_id: str) -> bool:
        assert (library_id, scan_id) == ("library-1", "scan-1")
        self.work_item = None
        return True

    def get(self, _actor_id: str, _library_id: str) -> None:
        return None


class _FakeUnitOfWork:
    def __init__(self, store: _ScanStore) -> None:
        self._store = store
        self.libraries = store
        self.scans = store
        self.work_items = store
        self.sources = store
        self.topology = _ForbiddenTopology()
        self.watcher = store
        self.diagnostics = _DiagnosticSink(store.diagnostic_batches)
        self.collisions = _CollisionSink()
        self.grants = store
        self.audit = _EventSink()
        self.outbox = _EventSink()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> Literal[False]:
        return False

    def commit(self) -> None:
        self._store.commits += 1

    def rollback(self) -> None:
        raise AssertionError("the success-path contract must not roll back")


class _UnitOfWorkFactory:
    def __init__(self, store: _ScanStore) -> None:
        self._store = store

    def __call__(self) -> _FakeUnitOfWork:
        return _FakeUnitOfWork(self._store)


def _file(path: tuple[str, ...]) -> DiscoveredSource:
    return DiscoveredSource(
        relative_path=path,
        entry_type=DiscoveryEntryType.FILE,
        filesystem_identity=f"file:{path[-1]}",
        expected_stat=_EXPECTATION,
    )


def _entry(path: tuple[str, ...], entry_type: DiscoveryEntryType) -> DiscoveredSource:
    return DiscoveredSource(
        relative_path=path,
        entry_type=entry_type,
        filesystem_identity=f"entry:{path[-1]}",
        expected_stat=None,
    )


def _run_scan(
    *,
    factories: dict[tuple[str, ...], Callable[[], Iterator[DiscoveryObservation]]],
    mode: OrganizationMode,
    monotonic: _MutableMonotonicClock,
    before_yield: Callable[[], None],
    admission: SourceAdmissionPort,
    ignore_rules: tuple[IgnoreRule, ...] = (),
    progress_path: tuple[str, ...] = (),
    block_topology_with_collision: bool = False,
) -> tuple[_ScanStore, _DiscoveryPort]:
    discovery = _DiscoveryPort(factories, before_yield=before_yield)
    store = _ScanStore(
        mode=mode,
        ignore_rules=ignore_rules,
        progress=lambda: (
            bool(discovery.sessions)
            and progress_path in discovery.scan_session.streams
            and discovery.scan_session.streams[progress_path].exhausted
        ),
        block_topology_with_collision=block_topology_with_collision,
    )
    result = RunFullLibraryScan(
        unit_of_work_factory=cast(ScanUowFactory, _UnitOfWorkFactory(store)),
        discovery=cast(DirectoryDiscoveryPort, discovery),
        admission=admission,
        clock=_FixedClock(),
        monotonic_clock=monotonic,
    ).execute(RunFullLibraryScanCommand("library-1", "scan-1", "worker-1"))

    assert result.run.state is ScanState.COMPLETED
    assert discovery.scan_session.closed
    return store, discovery


def _timed_case(
    case: str,
) -> tuple[
    DiscoveryObservation,
    tuple[IgnoreRule, ...],
    int,
]:
    if case == "ignored_nfd":
        decomposed = unicodedata.normalize("NFD", "café.epub")
        return (
            _file((decomposed,)),
            (IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="café.epub"),),
            0,
        )
    if case == "noise":
        return _file((".DS_Store",)), (), 0
    if case == "issue":
        return (
            DiscoveryIssue((), DiscoveryIssueCode.PATH_NAME_UNSUPPORTED),
            (),
            0,
        )
    if case == "unsupported":
        return _file(("unsupported.bin",)), (), 1
    entry_type = {
        "directory": DiscoveryEntryType.DIRECTORY,
        "symlink": DiscoveryEntryType.SYMLINK,
        "junction": DiscoveryEntryType.JUNCTION,
        "special": DiscoveryEntryType.SPECIAL,
    }[case]
    return _entry((case,), entry_type), (), 0


@pytest.mark.parametrize(
    "case",
    [
        "ignored_nfd",
        "noise",
        "issue",
        "unsupported",
        "directory",
        "symlink",
        "junction",
        "special",
    ],
)
def test_every_observation_class_honors_the_250ms_heartbeat_boundary(
    case: str,
) -> None:
    observation, ignore_rules, expected_admission_calls = _timed_case(case)
    monotonic = _MutableMonotonicClock()
    admission = _RejectingAdmission()

    store, discovery = _run_scan(
        factories={(): lambda: iter((observation,))},
        mode=OrganizationMode.FLAT,
        monotonic=monotonic,
        before_yield=lambda: setattr(monotonic, "value", 0.250),
        admission=admission,
        ignore_rules=ignore_rules,
    )

    assert store.heartbeat_events[0] == (1, False)
    assert discovery.scan_session.streams[()].consumed == 1
    assert len(admission.calls) == expected_admission_calls


@pytest.mark.parametrize(
    ("observation_count", "exhausted_at_first_heartbeat"),
    [(4_999, True), (5_000, False)],
)
def test_observation_slice_heartbeats_exactly_at_5000_before_exhaustion(
    observation_count: int,
    exhausted_at_first_heartbeat: bool,
) -> None:
    monotonic = _MutableMonotonicClock()

    def observations() -> Iterator[DiscoveryObservation]:
        for _index in range(observation_count):
            yield DiscoveryIssue((), DiscoveryIssueCode.PATH_NAME_UNSUPPORTED)

    store, discovery = _run_scan(
        factories={(): observations},
        mode=OrganizationMode.FLAT,
        monotonic=monotonic,
        before_yield=lambda: None,
        admission=_RejectingAdmission(),
    )

    assert store.heartbeat_events[0] == (
        observation_count,
        exhausted_at_first_heartbeat,
    )
    assert discovery.scan_session.streams[()].consumed == observation_count


@pytest.mark.parametrize(
    ("track_count", "exhausted_at_first_heartbeat"),
    [(499, True), (500, False)],
)
def test_admitted_candidate_slice_heartbeats_exactly_at_500_before_exhaustion(
    track_count: int,
    exhausted_at_first_heartbeat: bool,
) -> None:
    monotonic = _MutableMonotonicClock()
    work = _entry(("Work",), DiscoveryEntryType.DIRECTORY)

    def tracks() -> Iterator[DiscoveryObservation]:
        for index in range(track_count):
            yield _file(("Work", f"track-{index + 1:04}.mp3"))

    store, discovery = _run_scan(
        factories={
            (): lambda: iter((work,)),
            ("Work",): tracks,
        },
        mode=OrganizationMode.AUDIOBOOK,
        monotonic=monotonic,
        before_yield=lambda: None,
        admission=_AudioAdmission(),
        progress_path=("Work",),
        block_topology_with_collision=True,
    )

    assert store.heartbeat_events[0] == (
        track_count + 1,
        exhausted_at_first_heartbeat,
    )
    assert discovery.scan_session.streams[("Work",)].consumed == track_count


@pytest.mark.parametrize(
    ("track_count", "limit_diagnostic_count"),
    [(10_000, 0), (10_001, 1)],
)
def test_audiobook_track_limit_is_global_and_exact(
    track_count: int,
    limit_diagnostic_count: int,
) -> None:
    monotonic = _MutableMonotonicClock()
    work = _entry(("Work",), DiscoveryEntryType.DIRECTORY)

    def tracks() -> Iterator[DiscoveryObservation]:
        for index in range(track_count):
            yield _file(("Work", f"track-{index + 1:05}.mp3"))

    store, discovery = _run_scan(
        factories={
            (): lambda: iter((work,)),
            ("Work",): tracks,
        },
        mode=OrganizationMode.AUDIOBOOK,
        monotonic=monotonic,
        before_yield=lambda: None,
        admission=_AudioAdmission(),
        progress_path=("Work",),
        block_topology_with_collision=True,
    )

    diagnostic_codes = tuple(
        diagnostic.code for batch in store.diagnostic_batches for diagnostic in batch
    )
    assert diagnostic_codes.count(ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED) == (
        limit_diagnostic_count
    )
    assert discovery.scan_session.streams[("Work",)].consumed == track_count
    assert max(store.source_batch_sizes) <= 501
    assert max(increment for increment, _exhausted in store.heartbeat_events) <= 501


@pytest.mark.parametrize("mode", tuple(OrganizationMode))
def test_source_drift_is_isolated_and_later_siblings_continue_in_every_mode(
    mode: OrganizationMode,
) -> None:
    monotonic = _MutableMonotonicClock()
    admission = _DriftingThenRejectingAdmission()
    observations = (
        _file(("changed.epub",)),
        _file(("later-sibling.bin",)),
    )

    store, discovery = _run_scan(
        factories={(): lambda: iter(observations)},
        mode=mode,
        monotonic=monotonic,
        before_yield=lambda: None,
        admission=admission,
    )

    diagnostic_codes = tuple(
        diagnostic.code for batch in store.diagnostic_batches for diagnostic in batch
    )
    assert admission.calls == [("changed.epub",), ("later-sibling.bin",)]
    assert ScanObservationCode.SOURCE_CHANGED_DURING_SCAN in diagnostic_codes
    assert AdmissionRejectionReason.UNSUPPORTED_EXTENSION in diagnostic_codes
    assert discovery.scan_session.streams[()].consumed == 2
