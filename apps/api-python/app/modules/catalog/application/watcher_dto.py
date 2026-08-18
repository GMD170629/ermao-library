"""Explicit DTOs for watcher journaling and targeted subtree reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.modules.catalog.application.scan_dto import (
    SourceObservation,
    SourcePathBinding,
    TargetedPathAbsent,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.scan import (
    AssetMembershipPlan,
    TopologyProjectionPlan,
    TopologyUnitKind,
    TopologyUnitPlan,
    VersionProjectionPlan,
    VolumeProjectionPlan,
    WorkProjectionPlan,
)
from app.modules.catalog.domain.watcher import (
    FullRescanReason,
    ReconcileMoveEvidence,
    ReconcileScope,
    WatcherEvent,
    WatcherMovedEntryType,
    WatcherMoveEvent,
    WatcherPathEvent,
    WatcherTrustLost,
)


def _identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _integer(value: int, field_name: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")


def _lease_seconds(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("lease_seconds must be an integer")
    if not 1 <= value <= 3_600:
        raise ValueError("lease_seconds must be between 1 and 3600")


def _relative_path(value: tuple[str, ...], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    for component in value:
        if not isinstance(component, str):
            raise TypeError(f"{field_name} components must be strings")
        if (
            not component
            or component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError(f"{field_name} contains an invalid component")
        try:
            component.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError(f"{field_name} components must be strict UTF-8") from error


class ReconcileIntentState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"


class ReconcileIntentPhase(StrEnum):
    EXECUTE = "EXECUTE"
    FOLD = "FOLD"


class WatcherIngestDisposition(StrEnum):
    QUEUED = "QUEUED"
    COALESCED = "COALESCED"
    FULL_SCAN_REQUIRED = "FULL_SCAN_REQUIRED"


class ReconcileRunDisposition(StrEnum):
    NO_WORK = "NO_WORK"
    COMPLETED = "COMPLETED"
    FULL_SCAN_REQUIRED = "FULL_SCAN_REQUIRED"


class SourceRebindDisposition(StrEnum):
    PRESERVED_MOVED_ID = "PRESERVED_MOVED_ID"
    REACTIVATED_TARGET_ID = "REACTIVATED_TARGET_ID"
    RETIRED_TARGET_AND_PRESERVED_MOVED_ID = "RETIRED_TARGET_AND_PRESERVED_MOVED_ID"
    NOT_PROVEN = "NOT_PROVEN"


class SourceRebindRejectionReason(StrEnum):
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_STILL_PRESENT = "SOURCE_STILL_PRESENT"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    TARGET_COLLISION = "TARGET_COLLISION"


class BoundProjectionKind(StrEnum):
    WORK = "WORK"
    VERSION = "VERSION"
    VOLUME = "VOLUME"
    ASSET = "ASSET"


@dataclass(frozen=True, slots=True)
class WatcherState:
    library_id: str
    latest_sequence: int
    overflow_through_sequence: int | None
    full_rescan_reason: FullRescanReason | None

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _integer(self.latest_sequence, "latest_sequence")
        if self.overflow_through_sequence is not None:
            _integer(
                self.overflow_through_sequence,
                "overflow_through_sequence",
                minimum=1,
            )
            if self.overflow_through_sequence > self.latest_sequence:
                raise ValueError("overflow cannot pass the latest sequence")
        if (self.overflow_through_sequence is None) != (
            self.full_rescan_reason is None
        ):
            raise ValueError("overflow sequence and reason must be paired")
        if self.full_rescan_reason is not None and not isinstance(
            self.full_rescan_reason, FullRescanReason
        ):
            raise TypeError("full_rescan_reason must be a FullRescanReason")


@dataclass(frozen=True, slots=True)
class ReconcileIntent:
    intent_id: str
    library_id: str
    first_sequence: int
    through_sequence: int
    scopes: tuple[ReconcileScope, ...]
    move_evidence: ReconcileMoveEvidence | None
    state: ReconcileIntentState
    phase: ReconcileIntentPhase
    lease_owner: str | None
    lease_expires_at: datetime | None
    topology_writer_fence: int | None
    attempt: int
    available_at: datetime
    fold_after_source_entry_id: str | None
    config_revision: int
    organization_mode: OrganizationMode
    topology_version: int
    path_comparison: PathComparison
    root_path_snapshot: str
    root_identity_snapshot: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id",
            "library_id",
            "root_path_snapshot",
            "root_identity_snapshot",
        ):
            _identifier(getattr(self, field_name), field_name)
        _integer(self.first_sequence, "first_sequence", minimum=1)
        _integer(self.through_sequence, "through_sequence", minimum=1)
        if self.first_sequence > self.through_sequence:
            raise ValueError("first_sequence cannot exceed through_sequence")
        if not isinstance(self.scopes, tuple) or not 1 <= len(self.scopes) <= 2:
            raise ValueError("an intent requires one or two scopes")
        if any(not isinstance(scope, ReconcileScope) for scope in self.scopes):
            raise TypeError("scopes must contain ReconcileScope values")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("an intent cannot repeat an exact raw scope")
        if self.move_evidence is not None and not isinstance(
            self.move_evidence, ReconcileMoveEvidence
        ):
            raise TypeError("move_evidence must be ReconcileMoveEvidence")
        if not isinstance(self.state, ReconcileIntentState):
            raise TypeError("state must be a ReconcileIntentState")
        if not isinstance(self.phase, ReconcileIntentPhase):
            raise TypeError("phase must be a ReconcileIntentPhase")
        if not isinstance(self.organization_mode, OrganizationMode):
            raise TypeError("organization_mode must be an OrganizationMode")
        if not isinstance(self.path_comparison, PathComparison):
            raise TypeError("path_comparison must be a PathComparison")
        for value, field_name, minimum in (
            (self.attempt, "attempt", 0),
            (self.config_revision, "config_revision", 1),
            (self.topology_version, "topology_version", 1),
        ):
            _integer(value, field_name, minimum=minimum)
        if self.state is ReconcileIntentState.PENDING:
            if (
                self.lease_owner is not None
                or self.lease_expires_at is not None
                or self.topology_writer_fence is not None
            ):
                raise ValueError("pending intents cannot retain a writer lease")
        elif (
            self.lease_owner is None
            or self.lease_expires_at is None
            or self.topology_writer_fence is None
        ):
            raise ValueError("running intents require a writer lease and fence")
        if self.lease_owner is not None:
            _identifier(self.lease_owner, "lease_owner")
        if self.topology_writer_fence is not None:
            _integer(
                self.topology_writer_fence,
                "topology_writer_fence",
                minimum=1,
            )
        if self.fold_after_source_entry_id is not None:
            _identifier(
                self.fold_after_source_entry_id,
                "fold_after_source_entry_id",
            )
        if (
            self.phase is ReconcileIntentPhase.EXECUTE
            and self.fold_after_source_entry_id is not None
        ):
            raise ValueError("EXECUTE intents cannot retain a fold cursor")

    def fence(self, *, presence_generation: int) -> ReconcileFence:
        if (
            self.state is not ReconcileIntentState.RUNNING
            or self.lease_owner is None
            or self.topology_writer_fence is None
        ):
            raise ValueError("only a RUNNING reconcile intent has a fence")
        return ReconcileFence(
            library_id=self.library_id,
            intent_id=self.intent_id,
            through_sequence=self.through_sequence,
            config_revision=self.config_revision,
            organization_mode=self.organization_mode,
            topology_version=self.topology_version,
            path_comparison=self.path_comparison,
            root_path_snapshot=self.root_path_snapshot,
            root_identity=self.root_identity_snapshot,
            topology_writer_fence=self.topology_writer_fence,
            lease_owner=self.lease_owner,
            presence_generation=presence_generation,
        )


@dataclass(frozen=True, slots=True)
class ReconcileFence:
    library_id: str
    intent_id: str
    through_sequence: int
    config_revision: int
    organization_mode: OrganizationMode
    topology_version: int
    path_comparison: PathComparison
    root_path_snapshot: str
    root_identity: str
    topology_writer_fence: int
    lease_owner: str
    presence_generation: int

    def __post_init__(self) -> None:
        for field_name in (
            "library_id",
            "intent_id",
            "root_path_snapshot",
            "root_identity",
            "lease_owner",
        ):
            _identifier(getattr(self, field_name), field_name)
        if not isinstance(self.organization_mode, OrganizationMode):
            raise TypeError("organization_mode must be an OrganizationMode")
        if not isinstance(self.path_comparison, PathComparison):
            raise TypeError("path_comparison must be a PathComparison")
        for value, field_name in (
            (self.through_sequence, "through_sequence"),
            (self.config_revision, "config_revision"),
            (self.topology_version, "topology_version"),
            (self.topology_writer_fence, "topology_writer_fence"),
            (self.presence_generation, "presence_generation"),
        ):
            _integer(value, field_name, minimum=1)


@dataclass(frozen=True, slots=True)
class RecordWatcherEventCommand:
    library_id: str
    root_identity: str
    event: WatcherEvent

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.root_identity, "root_identity")
        if not isinstance(
            self.event, (WatcherPathEvent, WatcherMoveEvent, WatcherTrustLost)
        ):
            raise TypeError("event must be a typed WatcherEvent")


@dataclass(frozen=True, slots=True)
class RunNextReconcileSubtreeCommand:
    library_id: str
    owner_token: str
    lease_seconds: int = 60

    def __post_init__(self) -> None:
        _identifier(self.library_id, "library_id")
        _identifier(self.owner_token, "owner_token")
        _lease_seconds(self.lease_seconds)


@dataclass(frozen=True, slots=True)
class WatcherIngestResult:
    sequence: int
    disposition: WatcherIngestDisposition
    intent_id: str | None
    full_rescan_reason: FullRescanReason | None

    def __post_init__(self) -> None:
        _integer(self.sequence, "sequence", minimum=1)
        if not isinstance(self.disposition, WatcherIngestDisposition):
            raise TypeError("disposition must be a WatcherIngestDisposition")
        if self.intent_id is not None:
            _identifier(self.intent_id, "intent_id")
        if self.full_rescan_reason is not None and not isinstance(
            self.full_rescan_reason, FullRescanReason
        ):
            raise TypeError("full_rescan_reason must be a FullRescanReason")
        requires_scan = self.disposition is WatcherIngestDisposition.FULL_SCAN_REQUIRED
        if requires_scan != (self.full_rescan_reason is not None):
            raise ValueError("full-scan disposition and reason must be paired")
        if requires_scan and self.intent_id is not None:
            raise ValueError("a full-scan fence cannot return an intent")
        if not requires_scan and self.intent_id is None:
            raise ValueError("queued/coalesced results require an intent")


@dataclass(frozen=True, slots=True)
class ReconcileRunResult:
    disposition: ReconcileRunDisposition
    intent_id: str | None
    units_activated: int

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ReconcileRunDisposition):
            raise TypeError("disposition must be a ReconcileRunDisposition")
        if self.intent_id is not None:
            _identifier(self.intent_id, "intent_id")
        _integer(self.units_activated, "units_activated")
        if self.disposition is ReconcileRunDisposition.NO_WORK:
            if self.intent_id is not None or self.units_activated:
                raise ValueError("NO_WORK cannot report an intent or activation")
        elif self.intent_id is None:
            raise ValueError("completed/full-scan results require an intent")


@dataclass(frozen=True, slots=True)
class FullRescanTransition:
    state: WatcherState
    newly_required: bool
    invalidated_running_intent_id: str | None
    topology_writer_fence: int

    def __post_init__(self) -> None:
        if self.state.overflow_through_sequence is None:
            raise ValueError("a rescan transition requires an overflow fence")
        if not isinstance(self.newly_required, bool):
            raise TypeError("newly_required must be a bool")
        if self.invalidated_running_intent_id is not None:
            _identifier(
                self.invalidated_running_intent_id,
                "invalidated_running_intent_id",
            )
        _integer(
            self.topology_writer_fence,
            "topology_writer_fence",
            minimum=1,
        )


@dataclass(frozen=True, slots=True)
class FullScanWatcherStart:
    watcher_sequence_watermark: int
    topology_writer_fence: int

    def __post_init__(self) -> None:
        _integer(
            self.watcher_sequence_watermark,
            "watcher_sequence_watermark",
        )
        _integer(
            self.topology_writer_fence,
            "topology_writer_fence",
        )


@dataclass(frozen=True, slots=True)
class WatcherFinalizeOutcome:
    state: WatcherState
    discarded_intent_count: int
    replay_available: bool

    def __post_init__(self) -> None:
        _integer(self.discarded_intent_count, "discarded_intent_count")
        if not isinstance(self.replay_available, bool):
            raise TypeError("replay_available must be a bool")


@dataclass(frozen=True, slots=True)
class WatcherResumeOutcome:
    """Read-only follow-up decision after an unsuccessful terminal full scan."""

    state: WatcherState
    replay_available: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, WatcherState):
            raise TypeError("state must be a WatcherState")
        if not isinstance(self.replay_available, bool):
            raise TypeError("replay_available must be a bool")
        if self.state.full_rescan_reason is not None and self.replay_available:
            raise ValueError("an overflow fence supersedes targeted replay")


@dataclass(frozen=True, slots=True)
class DirectoryPresenceEpoch:
    directory: SourcePathBinding
    base_epoch: int
    proposed_epoch: int

    def __post_init__(self) -> None:
        if not isinstance(self.directory, SourcePathBinding):
            raise TypeError("directory must be a SourcePathBinding")
        _integer(self.base_epoch, "base_epoch")
        _integer(self.proposed_epoch, "proposed_epoch", minimum=1)
        if self.proposed_epoch <= self.base_epoch:
            raise ValueError("proposed_epoch must advance beyond base_epoch")


@dataclass(frozen=True, slots=True)
class PendingSourceObservation:
    observation: SourceObservation
    pending_parent_epoch: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.observation, SourceObservation):
            raise TypeError("observation must be a SourceObservation")
        if self.pending_parent_epoch is not None:
            _integer(
                self.pending_parent_epoch,
                "pending_parent_epoch",
                minimum=1,
            )
        top_level = len(self.observation.source.relative_path) == 1
        if top_level != (self.pending_parent_epoch is None):
            raise ValueError(
                "top-level observations use no pending epoch; nested observations require one"
            )


@dataclass(frozen=True, slots=True)
class PresenceFoldPage:
    folded_count: int
    next_source_entry_id: str | None
    complete: bool

    def __post_init__(self) -> None:
        _integer(self.folded_count, "folded_count")
        if self.next_source_entry_id is not None:
            _identifier(self.next_source_entry_id, "next_source_entry_id")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be a bool")
        if self.complete and self.next_source_entry_id is not None:
            raise ValueError("a complete fold page has no continuation cursor")
        if not self.complete and (
            self.next_source_entry_id is None or self.folded_count == 0
        ):
            raise ValueError("an incomplete fold page requires progress and a cursor")


@dataclass(frozen=True, slots=True)
class ProvenMoveEvidence:
    source_path: tuple[str, ...]
    destination_path: tuple[str, ...]
    filesystem_identity: str
    entry_type: WatcherMovedEntryType
    source_absence: TargetedPathAbsent

    def __post_init__(self) -> None:
        _relative_path(self.source_path, "source_path")
        _relative_path(self.destination_path, "destination_path")
        if self.source_path == self.destination_path:
            raise ValueError("a proven move must change the preserved path")
        _identifier(self.filesystem_identity, "filesystem_identity")
        if not isinstance(self.entry_type, WatcherMovedEntryType):
            raise TypeError("entry_type must be a WatcherMovedEntryType")
        if not isinstance(self.source_absence, TargetedPathAbsent):
            raise TypeError("source_absence must be a TargetedPathAbsent")
        if self.source_absence.relative_path != self.source_path:
            raise ValueError("source_absence must prove the exact source path")


@dataclass(frozen=True, slots=True)
class SourceRebindResult:
    disposition: SourceRebindDisposition
    binding: SourcePathBinding | None
    rejection_reason: SourceRebindRejectionReason | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, SourceRebindDisposition):
            raise TypeError("disposition must be a SourceRebindDisposition")
        if self.binding is not None and not isinstance(self.binding, SourcePathBinding):
            raise TypeError("binding must be a SourcePathBinding")
        if self.rejection_reason is not None and not isinstance(
            self.rejection_reason, SourceRebindRejectionReason
        ):
            raise TypeError("rejection_reason must be a SourceRebindRejectionReason")
        rejected = self.disposition is SourceRebindDisposition.NOT_PROVEN
        if rejected != (self.rejection_reason is not None):
            raise ValueError("NOT_PROVEN and rejection_reason must be paired")
        if rejected == (self.binding is not None):
            raise ValueError("only a proven rebind returns a binding")


@dataclass(frozen=True, slots=True)
class BoundTopologyProjection:
    row_index: int
    kind: BoundProjectionKind
    stable_id: str
    parent_stable_id: str | None
    parent_kind: BoundProjectionKind | None
    root_source_entry_id: str | None
    source_entry_id: str | None
    structure_key: str | None

    def __post_init__(self) -> None:
        _integer(self.row_index, "row_index")
        if not isinstance(self.kind, BoundProjectionKind):
            raise TypeError("kind must be a BoundProjectionKind")
        _identifier(self.stable_id, "stable_id")
        if self.parent_kind is not None and not isinstance(
            self.parent_kind, BoundProjectionKind
        ):
            raise TypeError("parent_kind must be a BoundProjectionKind")
        for value, field_name in (
            (self.parent_stable_id, "parent_stable_id"),
            (self.root_source_entry_id, "root_source_entry_id"),
            (self.source_entry_id, "source_entry_id"),
            (self.structure_key, "structure_key"),
        ):
            if value is not None:
                _identifier(value, field_name)
        if self.kind is BoundProjectionKind.WORK:
            if (
                self.parent_stable_id is not None
                or self.parent_kind is not None
                or self.root_source_entry_id is None
                or self.source_entry_id is not None
                or self.structure_key is None
            ):
                raise ValueError("Work binding shape is invalid")
        elif self.kind is BoundProjectionKind.ASSET:
            if (
                self.parent_stable_id is None
                or self.parent_kind is not BoundProjectionKind.VOLUME
                or self.source_entry_id is None
                or self.root_source_entry_id is not None
                or self.structure_key is not None
            ):
                raise ValueError("Asset binding shape is invalid")
        elif (
            self.parent_stable_id is None
            or self.parent_kind
            is not (
                BoundProjectionKind.WORK
                if self.kind is BoundProjectionKind.VERSION
                else BoundProjectionKind.VERSION
            )
            or self.source_entry_id is not None
            or self.structure_key is None
        ):
            raise ValueError("Version and Volume bindings require parent structure")
        elif (
            self.kind is BoundProjectionKind.VOLUME
            and self.root_source_entry_id is None
        ):
            raise ValueError("Volume bindings require a root SourceEntry")


def required_topology_source_paths(
    plan: TopologyUnitPlan,
) -> tuple[tuple[str, ...], ...]:
    """Return every referenced SourceEntry slot and non-root physical ancestor.

    Targeted materialization must carry an explicit current-attempt presence
    proof for every future-pending ancestor; a leaf binding cannot implicitly
    authorize an arbitrary orphan ancestor merely because its parent has a
    later ``next`` epoch.
    """

    paths: list[tuple[str, ...]] = []

    def require(path: tuple[str, ...] | None) -> None:
        if path is None:
            return
        for depth in range(1, len(path) + 1):
            ancestor = path[:depth]
            if ancestor not in paths:
                paths.append(ancestor)

    for row in plan.rows:
        if isinstance(row, WorkProjectionPlan):
            require(row.root_path)
        elif isinstance(row, VersionProjectionPlan):
            require(row.work_path)
            require(row.root_path)
        elif isinstance(row, VolumeProjectionPlan):
            require(row.work_path)
            require(row.version_path)
            require(row.root_path)
        elif isinstance(row, AssetMembershipPlan):
            require(row.volume_path)
            require(row.source_path)
        else:
            raise TypeError("unsupported topology projection plan")
    return tuple(paths)


@dataclass(frozen=True, slots=True)
class BoundTopologyUnitPlan:
    plan: TopologyUnitPlan
    unit_id: str
    owner_stable_id: str
    source_bindings: tuple[SourcePathBinding, ...]
    projections: tuple[BoundTopologyProjection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, TopologyUnitPlan):
            raise TypeError("plan must be a TopologyUnitPlan")
        _identifier(self.unit_id, "unit_id")
        _identifier(self.owner_stable_id, "owner_stable_id")
        if any(
            not isinstance(binding, SourcePathBinding)
            for binding in self.source_bindings
        ):
            raise TypeError("source_bindings must contain SourcePathBinding values")
        if len({value.relative_path for value in self.source_bindings}) != len(
            self.source_bindings
        ):
            raise ValueError("source_bindings cannot repeat a path")
        if len({value.source_entry_id for value in self.source_bindings}) != len(
            self.source_bindings
        ):
            raise ValueError("source_bindings cannot repeat a SourceEntry ID")
        if tuple(value.relative_path for value in self.source_bindings) != (
            required_topology_source_paths(self.plan)
        ):
            raise ValueError("source_bindings must exactly cover all plan source paths")
        if any(
            not isinstance(projection, BoundTopologyProjection)
            for projection in self.projections
        ):
            raise TypeError("projections must contain BoundTopologyProjection values")
        if tuple(value.row_index for value in self.projections) != tuple(
            range(len(self.plan.rows))
        ):
            raise ValueError("bound projections must cover plan rows in order")
        if len({value.stable_id for value in self.projections}) != len(
            self.projections
        ):
            raise ValueError("bound projections cannot repeat a stable ID")
        expected_kinds = tuple(_projection_kind(row) for row in self.plan.rows)
        if tuple(value.kind for value in self.projections) != expected_kinds:
            raise ValueError("bound projection kinds must match plan rows")
        binding_by_path = {
            value.relative_path: value.source_entry_id for value in self.source_bindings
        }
        for row, projection in zip(self.plan.rows, self.projections, strict=True):
            if isinstance(row, WorkProjectionPlan):
                expected_source_id = binding_by_path.get(row.root_path)
                if projection.root_source_entry_id != expected_source_id:
                    raise ValueError("Work root binding must match its source path")
            elif isinstance(row, VersionProjectionPlan):
                expected_source_id = (
                    None
                    if row.root_path is None
                    else binding_by_path.get(row.root_path)
                )
                if projection.root_source_entry_id != expected_source_id:
                    raise ValueError("Version root binding must match its source path")
            elif isinstance(row, VolumeProjectionPlan):
                if projection.root_source_entry_id != binding_by_path.get(
                    row.root_path
                ):
                    raise ValueError("Volume root binding must match its source path")
            elif projection.source_entry_id != binding_by_path.get(row.source_path):
                raise ValueError("Asset binding must match its source path")
        self._validate_typed_relations()

    def _validate_typed_relations(self) -> None:
        projection_by_id = {
            projection.stable_id: projection for projection in self.projections
        }
        for projection in self.projections:
            if projection.parent_stable_id is None:
                continue
            parent = projection_by_id.get(projection.parent_stable_id)
            if parent is not None and parent.kind is not projection.parent_kind:
                raise ValueError("bound projection has the wrong typed parent")

        rows_and_projections = tuple(zip(self.plan.rows, self.projections, strict=True))
        works = {
            row.root_path: projection.stable_id
            for row, projection in rows_and_projections
            if isinstance(row, WorkProjectionPlan)
        }
        versions = {
            (row.work_path, row.root_path): projection.stable_id
            for row, projection in rows_and_projections
            if isinstance(row, VersionProjectionPlan)
        }
        volumes = {
            row.root_path: projection.stable_id
            for row, projection in rows_and_projections
            if isinstance(row, VolumeProjectionPlan)
        }
        for row, projection in rows_and_projections:
            expected_parent: str | None = None
            if isinstance(row, VersionProjectionPlan):
                expected_parent = works.get(row.work_path)
            elif isinstance(row, VolumeProjectionPlan):
                expected_parent = versions.get((row.work_path, row.version_path))
            elif isinstance(row, AssetMembershipPlan):
                expected_parent = volumes.get(row.volume_path)
            if (
                expected_parent is not None
                and projection.parent_stable_id != expected_parent
            ):
                raise ValueError("bound projection has the wrong typed parent")

        expected_owner_kind = (
            BoundProjectionKind.WORK
            if self.plan.unit_kind
            in {TopologyUnitKind.WORK_CONTAINER, TopologyUnitKind.AUDIOBOOK_WORK}
            else BoundProjectionKind.VERSION
            if self.plan.unit_kind is TopologyUnitKind.VERSION_CONTAINER
            else BoundProjectionKind.VOLUME
        )
        owner = projection_by_id.get(self.owner_stable_id)
        if owner is None or owner.kind is not expected_owner_kind:
            raise ValueError(
                f"{self.plan.unit_kind.value} owner must be a "
                f"{expected_owner_kind.value} projection"
            )


def _projection_kind(row: TopologyProjectionPlan) -> BoundProjectionKind:
    if isinstance(row, WorkProjectionPlan):
        return BoundProjectionKind.WORK
    if isinstance(row, VersionProjectionPlan):
        return BoundProjectionKind.VERSION
    if isinstance(row, VolumeProjectionPlan):
        return BoundProjectionKind.VOLUME
    if isinstance(row, AssetMembershipPlan):
        return BoundProjectionKind.ASSET
    raise TypeError("unsupported topology projection plan")


@dataclass(frozen=True, slots=True)
class BoundTopologyStageBatch:
    first_row: int
    rows: tuple[TopologyProjectionPlan, ...]
    bindings: tuple[BoundTopologyProjection, ...]
    complete: bool

    def __post_init__(self) -> None:
        _integer(self.first_row, "first_row")
        if not isinstance(self.rows, tuple) or not self.rows:
            raise ValueError("a bound staging batch requires rows")
        if len(self.rows) > 500:
            raise ValueError("a bound staging batch cannot exceed 500 rows")
        if any(
            not isinstance(
                row,
                (
                    WorkProjectionPlan,
                    VersionProjectionPlan,
                    VolumeProjectionPlan,
                    AssetMembershipPlan,
                ),
            )
            for row in self.rows
        ):
            raise TypeError("rows must contain typed topology projection plans")
        if not isinstance(self.bindings, tuple) or len(self.bindings) != len(self.rows):
            raise ValueError("bindings must cover every staging row")
        if any(
            not isinstance(binding, BoundTopologyProjection)
            for binding in self.bindings
        ):
            raise TypeError("bindings must contain BoundTopologyProjection values")
        expected_indexes = tuple(range(self.first_row, self.first_row + len(self.rows)))
        if tuple(value.row_index for value in self.bindings) != expected_indexes:
            raise ValueError("staging bindings must use contiguous plan row indexes")
        if tuple(value.kind for value in self.bindings) != tuple(
            _projection_kind(row) for row in self.rows
        ):
            raise ValueError("staging binding kinds must match their rows")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be a bool")


__all__ = [
    "BoundProjectionKind",
    "BoundTopologyProjection",
    "BoundTopologyStageBatch",
    "BoundTopologyUnitPlan",
    "DirectoryPresenceEpoch",
    "FullRescanTransition",
    "FullScanWatcherStart",
    "PendingSourceObservation",
    "PresenceFoldPage",
    "ProvenMoveEvidence",
    "ReconcileFence",
    "ReconcileIntent",
    "ReconcileIntentPhase",
    "ReconcileIntentState",
    "ReconcileRunDisposition",
    "ReconcileRunResult",
    "RecordWatcherEventCommand",
    "RunNextReconcileSubtreeCommand",
    "SourceRebindDisposition",
    "SourceRebindRejectionReason",
    "SourceRebindResult",
    "WatcherFinalizeOutcome",
    "WatcherIngestDisposition",
    "WatcherIngestResult",
    "WatcherResumeOutcome",
    "WatcherState",
    "required_topology_source_paths",
]
