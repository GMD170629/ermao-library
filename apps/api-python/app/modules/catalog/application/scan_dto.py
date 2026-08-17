"""Explicit application DTOs for dormant full-library scans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias, TypeVar

from app.modules.catalog.application.source_admission_ports import SourceStatExpectation
from app.modules.catalog.domain.admission import (
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
    SourceAdmissionResult,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule
from app.modules.catalog.domain.library import (
    LibraryControlState,
    LibraryHealth,
)
from app.modules.catalog.domain.model import EntryType, OrganizationMode, PathComparison
from app.modules.catalog.domain.scan import (
    ScanDiagnostic,
    ScanStage,
    ScanState,
    TopologyUnitPlan,
)


def _identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


_EnumValue = TypeVar("_EnumValue", bound=StrEnum)


def _typed_enum(value: object, enum_type: type[_EnumValue], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _integer(value: int, field_name: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")


def _relative_path(
    value: tuple[str, ...], field_name: str, *, root: bool = False
) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not value and not root:
        raise ValueError(f"{field_name} must not be empty")
    for component in value:
        if (
            not isinstance(component, str)
            or not component
            or component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError(f"{field_name} contains an invalid component")


def _lease_seconds(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("lease_seconds must be an integer")
    if not 1 <= value <= 3_600:
        raise ValueError("lease_seconds must be between 1 and 3600")


class DiscoveryEntryType(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    SYMLINK = "SYMLINK"
    JUNCTION = "JUNCTION"
    SPECIAL = "SPECIAL"


class DiscoveryIssueCode(StrEnum):
    PATH_NAME_UNSUPPORTED = "PATH_NAME_UNSUPPORTED"


class ScanFailureCode(StrEnum):
    ROOT_UNAVAILABLE = "ROOT_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    IO_ERROR = "IO_ERROR"
    DIRECTORY_CHANGED = "DIRECTORY_CHANGED"
    INVALID_RELATIVE_PATH = "INVALID_RELATIVE_PATH"
    ROOT_IDENTITY_CHANGED = "ROOT_IDENTITY_CHANGED"


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    relative_path: tuple[str, ...]
    entry_type: DiscoveryEntryType
    filesystem_identity: str | None
    expected_stat: SourceStatExpectation | None

    def __post_init__(self) -> None:
        _relative_path(self.relative_path, "relative_path")
        if not isinstance(self.entry_type, DiscoveryEntryType):
            raise TypeError("entry_type must be a DiscoveryEntryType")
        if self.filesystem_identity is not None:
            _identifier(self.filesystem_identity, "filesystem_identity")
        if self.expected_stat is not None and not isinstance(
            self.expected_stat, SourceStatExpectation
        ):
            raise TypeError("expected_stat must be a SourceStatExpectation")
        if self.entry_type is DiscoveryEntryType.FILE:
            if self.expected_stat is None:
                raise ValueError("regular files require an expected stat")
        elif (
            self.entry_type
            in {
                DiscoveryEntryType.SYMLINK,
                DiscoveryEntryType.JUNCTION,
                DiscoveryEntryType.SPECIAL,
            }
            and self.expected_stat is not None
        ):
            raise ValueError(
                "links and special entries cannot carry followed stat facts"
            )


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    parent_path: tuple[str, ...]
    code: DiscoveryIssueCode

    def __post_init__(self) -> None:
        _relative_path(self.parent_path, "parent_path", root=True)
        if not isinstance(self.code, DiscoveryIssueCode):
            raise TypeError("code must be a DiscoveryIssueCode")


DiscoveryObservation: TypeAlias = DiscoveredSource | DiscoveryIssue


@dataclass(frozen=True, slots=True)
class ScanLibrarySnapshot:
    library_id: str
    canonical_root: str
    organization_mode: OrganizationMode
    topology_version: int
    path_comparison: PathComparison
    control_state: LibraryControlState
    observed_health: LibraryHealth
    config_revision: int
    topology_writer_fence: int
    next_scan_generation: int
    last_successful_generation: int | None
    ignore_rules: tuple[IgnoreRule, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.canonical_root, "canonical_root")
        _typed_enum(self.organization_mode, OrganizationMode, "organization_mode")
        _typed_enum(self.path_comparison, PathComparison, "path_comparison")
        _typed_enum(self.control_state, LibraryControlState, "control_state")
        _typed_enum(self.observed_health, LibraryHealth, "observed_health")
        _integer(self.topology_version, "topology_version", minimum=1)
        _integer(self.config_revision, "config_revision", minimum=1)
        _integer(self.topology_writer_fence, "topology_writer_fence")
        _integer(self.next_scan_generation, "next_scan_generation", minimum=1)
        if self.last_successful_generation is not None and (
            isinstance(self.last_successful_generation, bool)
            or not isinstance(self.last_successful_generation, int)
            or self.last_successful_generation <= 0
        ):
            raise ValueError("last successful generation must be positive")
        if not isinstance(self.ignore_rules, tuple) or any(
            not isinstance(rule, IgnoreRule) for rule in self.ignore_rules
        ):
            raise TypeError("ignore_rules must contain IgnoreRule values")


@dataclass(frozen=True, slots=True)
class WriterReservation:
    generation: int
    topology_writer_fence: int

    def __post_init__(self) -> None:
        _integer(self.generation, "generation", minimum=1)
        _integer(self.topology_writer_fence, "topology_writer_fence", minimum=1)


@dataclass(frozen=True, slots=True)
class ScanFence:
    library_id: str
    scan_id: str
    generation: int
    config_revision: int
    organization_mode: OrganizationMode
    topology_version: int
    path_comparison: PathComparison
    root_path_snapshot: str
    root_identity: str | None
    topology_writer_fence: int
    lease_owner: str

    def __post_init__(self) -> None:
        for field_name in ("library_id", "scan_id", "lease_owner"):
            _identifier(getattr(self, field_name), field_name)
        _identifier(self.root_path_snapshot, "root_path_snapshot")
        if self.root_identity is not None:
            _identifier(self.root_identity, "root_identity")
        _typed_enum(self.organization_mode, OrganizationMode, "organization_mode")
        _typed_enum(self.path_comparison, PathComparison, "path_comparison")
        for value, field_name in (
            (self.generation, "generation"),
            (self.config_revision, "config_revision"),
            (self.topology_version, "topology_version"),
            (self.topology_writer_fence, "topology_writer_fence"),
        ):
            _integer(value, field_name, minimum=1)


@dataclass(frozen=True, slots=True)
class FullScanRun:
    scan_id: str
    library_id: str
    canonical_root: str
    generation: int
    config_revision: int
    organization_mode: OrganizationMode
    topology_version: int
    path_comparison: PathComparison
    root_identity: str | None
    topology_writer_fence: int
    state: ScanState
    failure_code: ScanFailureCode | None
    stage: ScanStage
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    discovered_count: int
    diagnostic_count: int
    created_by_actor_id: str | None
    started_at: datetime | None
    finished_at: datetime | None

    @property
    def root_path_snapshot(self) -> str:
        """Frozen raw physical spelling persisted as LibraryScanRun.rootPathSnapshot."""

        return self.canonical_root

    def __post_init__(self) -> None:
        for field_name in (
            "scan_id",
            "library_id",
            "canonical_root",
        ):
            _identifier(getattr(self, field_name), field_name)
        if self.created_by_actor_id is not None:
            _identifier(self.created_by_actor_id, "created_by_actor_id")
        _typed_enum(self.organization_mode, OrganizationMode, "organization_mode")
        _typed_enum(self.path_comparison, PathComparison, "path_comparison")
        _typed_enum(self.state, ScanState, "state")
        _typed_enum(self.stage, ScanStage, "stage")
        if self.failure_code is not None:
            _typed_enum(self.failure_code, ScanFailureCode, "failure_code")
        for value, field_name in (
            (self.generation, "generation"),
            (self.config_revision, "config_revision"),
            (self.topology_version, "topology_version"),
            (self.topology_writer_fence, "topology_writer_fence"),
        ):
            _integer(value, field_name, minimum=1)
        _integer(self.discovered_count, "discovered_count")
        _integer(self.diagnostic_count, "diagnostic_count")
        live_states = {
            ScanState.PENDING,
            ScanState.RUNNING,
            ScanState.FINALIZING,
        }
        if self.state in live_states and (
            self.lease_owner is None or self.lease_expires_at is None
        ):
            raise ValueError("non-terminal scans require a lease")
        if self.state not in live_states and (
            self.lease_owner is not None or self.lease_expires_at is not None
        ):
            raise ValueError("terminal scans cannot retain a lease")
        if self.state is ScanState.PENDING and (
            self.stage is not ScanStage.DISCOVER
            or self.started_at is not None
            or self.root_identity is not None
        ):
            raise ValueError(
                "pending scans must remain unbound and unstarted in DISCOVER"
            )
        if self.state is ScanState.RUNNING and (
            self.stage not in {ScanStage.DISCOVER, ScanStage.RECONCILE}
            or self.root_identity is None
            or self.started_at is None
        ):
            raise ValueError("running scans require a bound root and live stage")
        if self.state is ScanState.FINALIZING and (
            self.stage is not ScanStage.FINALIZE
            or self.root_identity is None
            or self.started_at is None
        ):
            raise ValueError("finalizing scans require a bound root and FINALIZE stage")
        if self.state in live_states and self.finished_at is not None:
            raise ValueError("live scans cannot have finished_at")
        if self.state not in live_states and self.finished_at is None:
            raise ValueError("terminal scans require finished_at")
        if self.state is ScanState.COMPLETED and self.stage is not ScanStage.FINALIZE:
            raise ValueError("completed scans must finish in FINALIZE")
        if self.state is ScanState.FAILED and self.failure_code is None:
            raise ValueError("failed scans require failure_code")
        if self.state is not ScanState.FAILED and self.failure_code is not None:
            raise ValueError("only failed scans may carry failure_code")

    def fence(self) -> ScanFence:
        if self.lease_owner is None:
            raise ValueError("a terminal run has no mutation fence")
        return ScanFence(
            library_id=self.library_id,
            scan_id=self.scan_id,
            generation=self.generation,
            config_revision=self.config_revision,
            organization_mode=self.organization_mode,
            topology_version=self.topology_version,
            path_comparison=self.path_comparison,
            root_path_snapshot=self.root_path_snapshot,
            root_identity=self.root_identity,
            topology_writer_fence=self.topology_writer_fence,
            lease_owner=self.lease_owner,
        )


@dataclass(frozen=True, slots=True)
class FullScanWorkItem:
    work_item_id: str
    library_id: str
    scan_id: str
    root_path_snapshot: str
    scope_relative_path: tuple[str, ...]
    state: ScanState
    stage: ScanStage
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempt: int
    available_at: datetime
    idempotency_key: str
    discovered_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "work_item_id",
            "library_id",
            "scan_id",
            "root_path_snapshot",
            "idempotency_key",
        ):
            _identifier(getattr(self, field_name), field_name)
        _typed_enum(self.state, ScanState, "state")
        _typed_enum(self.stage, ScanStage, "stage")
        if self.scope_relative_path:
            raise ValueError("a full scan has exactly one root-scoped work item")
        if self.state not in {ScanState.PENDING, ScanState.RUNNING}:
            raise ValueError(
                "root work items are deleted instead of retained terminally"
            )
        _integer(self.attempt, "attempt")
        _integer(self.discovered_count, "discovered_count")
        if self.state is ScanState.PENDING and (
            self.stage is not ScanStage.DISCOVER
            or self.lease_owner is not None
            or self.lease_expires_at is not None
        ):
            raise ValueError("pending root work must be unleased in DISCOVER")
        if self.state is ScanState.RUNNING and (
            self.lease_owner is None or self.lease_expires_at is None
        ):
            raise ValueError("running root work requires a lease")


@dataclass(frozen=True, slots=True)
class SourceObservation:
    source: DiscoveredSource
    generation: int
    admission: SourceAdmissionResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.source, DiscoveredSource):
            raise TypeError("source must be a DiscoveredSource")
        _integer(self.generation, "generation", minimum=1)
        if self.admission is None:
            return
        if not isinstance(
            self.admission, (SourceAdmissionEvidence, SourceAdmissionRejection)
        ):
            raise TypeError("admission must be a typed source admission result")
        if self.admission.relative_path != self.source.relative_path:
            raise ValueError("admission path must match the discovered source")
        expected_entry_type = {
            DiscoveryEntryType.FILE: EntryType.FILE,
            DiscoveryEntryType.DIRECTORY: EntryType.DIRECTORY,
            DiscoveryEntryType.SYMLINK: EntryType.SYMLINK,
            DiscoveryEntryType.JUNCTION: EntryType.JUNCTION,
        }.get(self.source.entry_type)
        if self.admission.entry_type is not expected_entry_type:
            raise ValueError("admission entry type must match the discovered source")


@dataclass(frozen=True, slots=True)
class PathCollision:
    parent_path: tuple[str, ...]
    comparison_key: str
    related_paths: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        _relative_path(self.parent_path, "parent_path", root=True)
        _identifier(self.comparison_key, "comparison_key")
        if not isinstance(self.related_paths, tuple):
            raise TypeError("related_paths must be a tuple")
        if len(self.related_paths) < 2:
            raise ValueError("a path collision requires at least two paths")
        for path in self.related_paths:
            _relative_path(path, "related_path")
            if path[:-1] != self.parent_path:
                raise ValueError("collision paths must share their exact parent")


@dataclass(frozen=True, slots=True)
class SourceObservationOutcome:
    collisions: tuple[PathCollision, ...] = ()

    def __post_init__(self) -> None:
        if any(not isinstance(value, PathCollision) for value in self.collisions):
            raise TypeError("collisions must contain PathCollision values")


@dataclass(frozen=True, slots=True)
class StagingRevision:
    revision_id: str
    unit_id: str
    expected_active_revision_id: str | None
    expected_row_count: int
    staged_row_count: int

    def __post_init__(self) -> None:
        _identifier(self.revision_id, "revision_id")
        _identifier(self.unit_id, "unit_id")
        if self.expected_active_revision_id is not None:
            _identifier(self.expected_active_revision_id, "expected_active_revision_id")
        _integer(self.expected_row_count, "expected_row_count", minimum=1)
        _integer(self.staged_row_count, "staged_row_count")
        if self.staged_row_count > self.expected_row_count:
            raise ValueError("invalid staging row counts")


@dataclass(frozen=True, slots=True)
class StartFullLibraryScanCommand:
    actor_id: str
    library_id: str
    owner_token: str
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.actor_id, "actor_id"),
            (self.library_id, "library_id"),
            (self.owner_token, "owner_token"),
        ):
            _identifier(value, field_name)
        _lease_seconds(self.lease_seconds)


@dataclass(frozen=True, slots=True)
class RunFullLibraryScanCommand:
    library_id: str
    scan_id: str
    owner_token: str
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.library_id, "library_id"),
            (self.scan_id, "scan_id"),
            (self.owner_token, "owner_token"),
        ):
            _identifier(value, field_name)
        _lease_seconds(self.lease_seconds)


@dataclass(frozen=True, slots=True)
class TakeOverFullLibraryScanCommand:
    library_id: str
    scan_id: str
    new_owner_token: str
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.library_id, "library_id"),
            (self.scan_id, "scan_id"),
            (self.new_owner_token, "new_owner_token"),
        ):
            _identifier(value, field_name)
        _lease_seconds(self.lease_seconds)


@dataclass(frozen=True, slots=True)
class HeartbeatFullLibraryScanCommand:
    library_id: str
    scan_id: str
    owner_token: str
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.library_id, "library_id"),
            (self.scan_id, "scan_id"),
            (self.owner_token, "owner_token"),
        ):
            _identifier(value, field_name)
        _lease_seconds(self.lease_seconds)


@dataclass(frozen=True, slots=True)
class FinalizeFullLibraryScanCommand:
    library_id: str
    scan_id: str
    owner_token: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.library_id, "library_id"),
            (self.scan_id, "scan_id"),
            (self.owner_token, "owner_token"),
        ):
            _identifier(value, field_name)


@dataclass(frozen=True, slots=True)
class FailFullLibraryScanCommand:
    library_id: str
    scan_id: str
    owner_token: str
    failure_code: ScanFailureCode

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.library_id, "library_id"),
            (self.scan_id, "scan_id"),
            (self.owner_token, "owner_token"),
        ):
            _identifier(value, field_name)
        if not isinstance(self.failure_code, ScanFailureCode):
            raise TypeError("failure_code must be a ScanFailureCode")


@dataclass(frozen=True, slots=True)
class CancelFullLibraryScanCommand:
    actor_id: str
    library_id: str
    scan_id: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.actor_id, "actor_id"),
            (self.library_id, "library_id"),
            (self.scan_id, "scan_id"),
        ):
            _identifier(value, field_name)


@dataclass(frozen=True, slots=True)
class RunFullLibraryScanResult:
    run: FullScanRun
    units_activated: int

    def __post_init__(self) -> None:
        if not isinstance(self.run, FullScanRun):
            raise TypeError("run must be a FullScanRun")
        _integer(self.units_activated, "units_activated")


@dataclass(frozen=True, slots=True)
class TopologyMaterialization:
    plan: TopologyUnitPlan
    diagnostics: tuple[ScanDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan, TopologyUnitPlan):
            raise TypeError("plan must be a TopologyUnitPlan")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(value, ScanDiagnostic) for value in self.diagnostics
        ):
            raise TypeError("diagnostics must contain ScanDiagnostic values")


__all__ = [
    "CancelFullLibraryScanCommand",
    "DiscoveredSource",
    "DiscoveryEntryType",
    "DiscoveryIssue",
    "DiscoveryIssueCode",
    "DiscoveryObservation",
    "FailFullLibraryScanCommand",
    "FinalizeFullLibraryScanCommand",
    "FullScanRun",
    "FullScanWorkItem",
    "HeartbeatFullLibraryScanCommand",
    "PathCollision",
    "RunFullLibraryScanCommand",
    "RunFullLibraryScanResult",
    "ScanFailureCode",
    "ScanFence",
    "ScanLibrarySnapshot",
    "SourceObservation",
    "SourceObservationOutcome",
    "StagingRevision",
    "StartFullLibraryScanCommand",
    "TakeOverFullLibraryScanCommand",
    "TopologyMaterialization",
    "WriterReservation",
]
