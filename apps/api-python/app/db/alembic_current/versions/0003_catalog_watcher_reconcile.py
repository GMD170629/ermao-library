"""Add bounded watcher reconciliation and stable source-presence state.

The current lineage is fresh-install only. This revision transforms an empty
0002 schema and deliberately contains no compatibility backfill or runtime
model imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from types import ModuleType
from typing import cast

from alembic import context, op
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    column,
    func,
    or_,
)

revision: str = "0003_catalog_watcher_reconcile"
down_revision: str | None = "0002_catalog_scan_topology"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ID = String(191)
_DT = DateTime(timezone=True)
_ACTIVE_SCAN_STATES = ("PENDING", "RUNNING", "FINALIZING")
_SCAN_STATES = (*_ACTIVE_SCAN_STATES, "COMPLETED", "FAILED", "CANCELLED")
_SCAN_FAILURE_CODES = (
    "ROOT_UNAVAILABLE",
    "PERMISSION_DENIED",
    "IO_ERROR",
    "DIRECTORY_CHANGED",
    "INVALID_RELATIVE_PATH",
    "ROOT_IDENTITY_CHANGED",
)
_SOURCE_ENTRY_TYPES = (
    "SYNTHETIC_ROOT",
    "DIRECTORY",
    "FILE",
    "SYMLINK",
    "JUNCTION",
    "SPECIAL",
)
_SLOT_STATES = ("ACTIVE", "COLLIDING", "RETIRED")
_FULL_RESCAN_REASONS = (
    "JOURNAL_CAPACITY",
    "DISCONNECTED",
    "BACKEND_OVERFLOW",
    "UNTRUSTED",
    "ROOT_CHANGED",
    "COLLISION_RECHECK",
)

_baseline_revision = cast(
    ModuleType,
    import_module("app.db.alembic_current.versions.0001_system_and_catalog_core"),
)
_baseline_metadata = cast(MetaData, _baseline_revision.metadata)


def _enum(name: str, *values: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True)


def _remove_constraints(table: Table, *names: str) -> None:
    for constraint in tuple(table.constraints):
        if constraint.name in names:
            table.constraints.remove(constraint)


def _post_0002_copy_metadata() -> MetaData:
    metadata = MetaData()
    for baseline_table in _baseline_metadata.tables.values():
        baseline_table.to_metadata(metadata)

    source = metadata.tables["LibrarySourceEntry"]
    _remove_constraints(source, "sourceentrytype", "slotstate")
    source.c.entryType.type = String(14)
    source.c.slotState.type = String(9)
    source.append_constraint(
        CheckConstraint(
            source.c.entryType.in_(_SOURCE_ENTRY_TYPES), name="sourceentrytype"
        )
    )
    source.append_constraint(
        CheckConstraint(source.c.slotState.in_(_SLOT_STATES), name="slotstate")
    )
    Index(
        "LibrarySourceEntry_generation_idx",
        source.c.libraryId,
        source.c.lastSeenGeneration,
    )

    scan = metadata.tables["LibraryScanRun"]
    _remove_constraints(scan, "scanstate")
    scan.c.state.type = String(10)
    scan.append_column(Column("rootPathSnapshot", Text, nullable=False))
    scan.append_column(Column("pathComparisonSnapshot", String(11), nullable=False))
    scan.append_column(Column("failureCode", String(32)))
    scan.append_constraint(
        CheckConstraint(scan.c.state.in_(_SCAN_STATES), name="scanstate")
    )
    scan.append_constraint(
        CheckConstraint(
            scan.c.pathComparisonSnapshot.in_(("SENSITIVE", "INSENSITIVE")),
            name="pathcomparison",
        )
    )
    scan.append_constraint(
        CheckConstraint(
            scan.c.failureCode.in_(_SCAN_FAILURE_CODES), name="scanfailurecode"
        )
    )
    scan.append_constraint(
        CheckConstraint(
            or_(
                and_(scan.c.state == "FAILED", scan.c.failureCode.is_not(None)),
                and_(scan.c.state != "FAILED", scan.c.failureCode.is_(None)),
            ),
            name="LibraryScanRun_failure_shape_ck",
        )
    )
    scan.append_constraint(
        CheckConstraint(
            and_(
                scan.c.generation > 0,
                scan.c.configRevision > 0,
                scan.c.topologyVersionSnapshot > 0,
                scan.c.topologyWriterFence > 0,
                scan.c.discoveredCount >= 0,
                scan.c.diagnosticCount >= 0,
            ),
            name="LibraryScanRun_positive_ck",
        )
    )
    scan.append_constraint(
        CheckConstraint(
            or_(
                and_(
                    scan.c.state == "PENDING",
                    scan.c.stage == "DISCOVER",
                    scan.c.leaseOwner.is_not(None),
                    scan.c.leaseExpiresAt.is_not(None),
                    scan.c.rootIdentitySnapshot.is_(None),
                    scan.c.startedAt.is_(None),
                    scan.c.finishedAt.is_(None),
                ),
                and_(
                    scan.c.state == "RUNNING",
                    scan.c.stage.in_(("DISCOVER", "RECONCILE")),
                    scan.c.leaseOwner.is_not(None),
                    scan.c.leaseExpiresAt.is_not(None),
                    scan.c.rootIdentitySnapshot.is_not(None),
                    scan.c.startedAt.is_not(None),
                    scan.c.finishedAt.is_(None),
                ),
                and_(
                    scan.c.state == "FINALIZING",
                    scan.c.stage == "FINALIZE",
                    scan.c.leaseOwner.is_not(None),
                    scan.c.leaseExpiresAt.is_not(None),
                    scan.c.rootIdentitySnapshot.is_not(None),
                    scan.c.startedAt.is_not(None),
                    scan.c.finishedAt.is_(None),
                ),
                and_(
                    scan.c.state == "COMPLETED",
                    scan.c.stage == "FINALIZE",
                    scan.c.leaseOwner.is_(None),
                    scan.c.leaseExpiresAt.is_(None),
                    scan.c.rootIdentitySnapshot.is_not(None),
                    scan.c.startedAt.is_not(None),
                    scan.c.finishedAt.is_not(None),
                ),
                and_(
                    scan.c.state.in_(("FAILED", "CANCELLED")),
                    scan.c.leaseOwner.is_(None),
                    scan.c.leaseExpiresAt.is_(None),
                    scan.c.finishedAt.is_not(None),
                    or_(
                        and_(
                            scan.c.rootIdentitySnapshot.is_(None),
                            scan.c.startedAt.is_(None),
                        ),
                        and_(
                            scan.c.rootIdentitySnapshot.is_not(None),
                            scan.c.startedAt.is_not(None),
                        ),
                    ),
                ),
            ),
            name="LibraryScanRun_state_shape_ck",
        )
    )
    Index(
        "LibraryScanRun_one_active_idx",
        scan.c.libraryId,
        unique=True,
        sqlite_where=scan.c.state.in_(_ACTIVE_SCAN_STATES),
    )
    return metadata


_copy_metadata = _post_0002_copy_metadata()


def _offline_copy(table_name: str) -> Table | None:
    if not context.is_offline_mode():
        return None
    return _copy_metadata.tables[table_name]


def _create_watcher_tables() -> None:
    latest_sequence = column("latestSequence", BigInteger)
    overflow_through_sequence = column("overflowThroughSequence", BigInteger)
    full_rescan_reason = column("fullRescanReason", String(19))
    op.create_table(
        "LibraryWatcherState",
        Column("libraryId", _ID, primary_key=True),
        Column("latestSequence", BigInteger, nullable=False),
        Column("overflowThroughSequence", BigInteger),
        Column(
            "fullRescanReason",
            _enum("fullrescanreason", *_FULL_RESCAN_REASONS),
        ),
        Column(
            "updatedAt",
            _DT,
            nullable=False,
            server_default=func.current_timestamp(),
        ),
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        CheckConstraint(
            latest_sequence >= 0,
            name="LibraryWatcherState_latest_sequence_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    overflow_through_sequence.is_(None),
                    full_rescan_reason.is_(None),
                ),
                and_(
                    overflow_through_sequence.is_not(None),
                    overflow_through_sequence > 0,
                    overflow_through_sequence <= latest_sequence,
                    full_rescan_reason.is_not(None),
                ),
            ),
            name="LibraryWatcherState_overflow_shape_ck",
        ),
    )

    first_sequence = column("firstSequence", BigInteger)
    through_sequence = column("throughSequence", BigInteger)
    scope2_path = column("scope2Path", Text)
    scope2_key = column("scope2Key", Text)
    move_old_path = column("moveOldPath", JSON)
    move_new_path = column("moveNewPath", JSON)
    moved_entry_type = column("movedEntryType", String(9))
    intent_state = column("state", String(7))
    intent_phase = column("phase", String(7))
    lease_owner = column("leaseOwner", _ID)
    lease_expires_at = column("leaseExpiresAt", _DT)
    topology_writer_fence = column("topologyWriterFence", BigInteger)
    attempt = column("attempt", Integer)
    fold_cursor = column("foldAfterSourceEntryId", _ID)
    config_revision = column("configRevision", BigInteger)
    topology_version = column("topologyVersion", Integer)
    reconcile_intent = op.create_table(
        "LibraryReconcileIntent",
        Column("id", _ID, primary_key=True),
        Column("libraryId", _ID, nullable=False),
        Column("firstSequence", BigInteger, nullable=False),
        Column("throughSequence", BigInteger, nullable=False),
        Column("scope1Path", Text, nullable=False),
        Column("scope1Key", Text, nullable=False),
        Column("scope2Path", Text),
        Column("scope2Key", Text),
        Column("coalesceKey", String(191), nullable=False),
        Column("moveOldPath", JSON),
        Column("moveNewPath", JSON),
        Column(
            "movedEntryType",
            _enum("reconcilemovedentrytype", "FILE", "DIRECTORY"),
        ),
        Column(
            "state",
            _enum("reconcileintentstate", "PENDING", "RUNNING"),
            nullable=False,
        ),
        Column(
            "phase",
            _enum("reconcileintentphase", "EXECUTE", "FOLD"),
            nullable=False,
        ),
        Column("leaseOwner", _ID),
        Column("leaseExpiresAt", _DT),
        Column("topologyWriterFence", BigInteger),
        Column("attempt", Integer, nullable=False),
        Column("availableAt", _DT, nullable=False),
        Column("foldAfterSourceEntryId", _ID),
        Column("configRevision", BigInteger, nullable=False),
        Column(
            "organizationMode",
            _enum("organizationmode", "FLAT", "VOLUMES", "AUDIOBOOK"),
            nullable=False,
        ),
        Column("topologyVersion", Integer, nullable=False),
        Column(
            "pathComparison",
            _enum("pathcomparison", "SENSITIVE", "INSENSITIVE"),
            nullable=False,
        ),
        Column("rootPathSnapshot", Text, nullable=False),
        Column("rootIdentitySnapshot", String(191), nullable=False),
        Column("createdAt", _DT, nullable=False),
        Column("updatedAt", _DT, nullable=False),
        ForeignKeyConstraint(["libraryId"], ["CatalogLibrary.id"], ondelete="CASCADE"),
        UniqueConstraint(
            "libraryId",
            "throughSequence",
            name="LibraryReconcileIntent_library_through_key",
        ),
        CheckConstraint(
            and_(
                first_sequence > 0,
                through_sequence >= first_sequence,
                attempt >= 0,
                config_revision > 0,
                topology_version > 0,
            ),
            name="LibraryReconcileIntent_positive_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    scope2_path.is_(None),
                    scope2_key.is_(None),
                ),
                and_(
                    scope2_path.is_not(None),
                    scope2_key.is_not(None),
                ),
            ),
            name="LibraryReconcileIntent_scope_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    move_old_path.is_(None),
                    move_new_path.is_(None),
                    moved_entry_type.is_(None),
                ),
                and_(
                    move_old_path.is_not(None),
                    move_new_path.is_not(None),
                    moved_entry_type.is_not(None),
                ),
            ),
            name="LibraryReconcileIntent_move_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    intent_state == "PENDING",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    topology_writer_fence.is_(None),
                ),
                and_(
                    intent_state == "RUNNING",
                    lease_owner.is_not(None),
                    lease_expires_at.is_not(None),
                    topology_writer_fence > 0,
                ),
            ),
            name="LibraryReconcileIntent_lease_shape_ck",
        ),
        CheckConstraint(
            or_(
                and_(
                    intent_phase == "EXECUTE",
                    fold_cursor.is_(None),
                ),
                intent_phase == "FOLD",
            ),
            name="LibraryReconcileIntent_phase_shape_ck",
        ),
    )

    indexes = (
        Index(
            "LibraryReconcileIntent_claim_idx",
            reconcile_intent.c.libraryId,
            reconcile_intent.c.state,
            reconcile_intent.c.availableAt,
            reconcile_intent.c.firstSequence,
            reconcile_intent.c.id,
        ),
        Index(
            "LibraryReconcileIntent_lease_idx",
            reconcile_intent.c.libraryId,
            reconcile_intent.c.state,
            reconcile_intent.c.leaseExpiresAt,
        ),
        Index(
            "LibraryReconcileIntent_one_pending_key_idx",
            reconcile_intent.c.libraryId,
            reconcile_intent.c.coalesceKey,
            unique=True,
            sqlite_where=reconcile_intent.c.state == "PENDING",
        ),
        Index(
            "LibraryReconcileIntent_one_running_idx",
            reconcile_intent.c.libraryId,
            unique=True,
            sqlite_where=reconcile_intent.c.state == "RUNNING",
        ),
    )
    for index in indexes:
        index.create(bind=op.get_bind())


def _extend_source_entry() -> None:
    children_epoch = column("childrenPresenceEpoch", BigInteger)
    next_epoch = column("nextChildrenPresenceEpoch", BigInteger)
    observed_epoch = column("observedParentPresenceEpoch", BigInteger)
    pending_epoch = column("pendingObservedParentPresenceEpoch", BigInteger)
    with op.batch_alter_table(
        "LibrarySourceEntry",
        recreate="always",
        partial_reordering=[
            (
                "id",
                "libraryId",
                "parentEntryId",
                "localName",
                "localNameKey",
                "entryType",
                "filesystemIdentity",
                "sizeBytes",
                "modifiedNs",
                "lastSeenGeneration",
                "absenceConfirmedAt",
                "childrenPresenceEpoch",
                "nextChildrenPresenceEpoch",
                "observedParentPresenceEpoch",
                "pendingObservedParentPresenceEpoch",
                "layoutState",
                "slotState",
                "createdAt",
                "updatedAt",
            )
        ],
        copy_from=_offline_copy("LibrarySourceEntry"),
    ) as batch_op:
        batch_op.add_column(
            Column("nextChildrenPresenceEpoch", BigInteger, nullable=False)
        )
        batch_op.add_column(Column("pendingObservedParentPresenceEpoch", BigInteger))
        batch_op.create_check_constraint(
            "LibrarySourceEntry_presence_epoch_ck",
            and_(
                children_epoch >= 0,
                next_epoch >= children_epoch,
                or_(observed_epoch.is_(None), observed_epoch >= 0),
                or_(pending_epoch.is_(None), pending_epoch > 0),
            ),
        )

    index_table = Table(
        "LibrarySourceEntry",
        MetaData(),
        Column("id", _ID, nullable=False),
        Column("libraryId", _ID, nullable=False),
        Column("parentEntryId", _ID),
        Column("localName", Text, nullable=False),
        Column("slotState", String(9), nullable=False),
        Column("filesystemIdentity", String(191)),
        Column("pendingObservedParentPresenceEpoch", BigInteger),
    )
    for index in (
        Index(
            "LibrarySourceEntry_pending_presence_idx",
            index_table.c.libraryId,
            index_table.c.parentEntryId,
            index_table.c.pendingObservedParentPresenceEpoch,
            index_table.c.id,
        ),
        Index(
            "LibrarySourceEntry_identity_idx",
            index_table.c.libraryId,
            index_table.c.filesystemIdentity,
        ),
        Index(
            "LibrarySourceEntry_raw_slot_idx",
            index_table.c.libraryId,
            index_table.c.parentEntryId,
            index_table.c.localName,
        ),
        Index(
            "LibrarySourceEntry_live_raw_slot_idx",
            index_table.c.libraryId,
            index_table.c.parentEntryId,
            index_table.c.localName,
            unique=True,
            sqlite_where=index_table.c.slotState != "RETIRED",
        ),
    ):
        index.create(bind=op.get_bind())


def _extend_scan_run() -> None:
    watermark = column("watcherSequenceWatermark", BigInteger)
    with op.batch_alter_table(
        "LibraryScanRun",
        recreate="always",
        partial_reordering=[
            (
                "id",
                "libraryId",
                "generation",
                "configRevision",
                "modeSnapshot",
                "rootPathSnapshot",
                "pathComparisonSnapshot",
                "topologyVersionSnapshot",
                "rootIdentitySnapshot",
                "topologyWriterFence",
                "watcherSequenceWatermark",
                "state",
                "failureCode",
                "leaseOwner",
                "leaseExpiresAt",
                "heartbeatAt",
                "stage",
                "discoveredCount",
                "diagnosticCount",
                "startedAt",
                "finishedAt",
                "createdByUserId",
                "createdAt",
            )
        ],
        copy_from=_offline_copy("LibraryScanRun"),
    ) as batch_op:
        batch_op.add_column(
            Column("watcherSequenceWatermark", BigInteger, nullable=False)
        )
        batch_op.create_check_constraint(
            "LibraryScanRun_watcher_watermark_ck", watermark >= 0
        )


def _add_reconcile_origins() -> None:
    scan_run_id = column("scanRunId", _ID)
    reconcile_origin_id = column("reconcileOriginId", _ID)
    for table_name, constraint_name in (
        ("TopologyUnitRevision", "TopologyUnitRevision_origin_ck"),
        ("LayoutDiagnostic", "LayoutDiagnostic_origin_ck"),
    ):
        column_order = (
            (
                "id",
                "libraryId",
                "unitId",
                "scanRunId",
                "reconcileOriginId",
                "unitRootEntryId",
                "revision",
                "state",
                "createdAt",
            )
            if table_name == "TopologyUnitRevision"
            else (
                "id",
                "libraryId",
                "scanRunId",
                "reconcileOriginId",
                "generation",
                "configRevision",
                "scopeRelativePath",
                "code",
                "severity",
                "parameters",
                "firstObservedAt",
                "lastObservedAt",
                "resolvedAt",
            )
        )
        with op.batch_alter_table(
            table_name,
            recreate="always",
            partial_reordering=[column_order],
            copy_from=_offline_copy(table_name),
        ) as batch_op:
            if table_name == "TopologyUnitRevision":
                batch_op.alter_column("scanRunId", existing_type=_ID, nullable=True)
            batch_op.add_column(Column("reconcileOriginId", _ID))
            batch_op.create_check_constraint(
                constraint_name,
                (
                    scan_run_id.is_not(None).cast(Integer)
                    + reconcile_origin_id.is_not(None).cast(Integer)
                    == 1
                ),
            )

    revision = Table(
        "TopologyUnitRevision",
        MetaData(),
        Column("libraryId", _ID, nullable=False),
        Column("reconcileOriginId", _ID),
        Column("state", String(10), nullable=False),
    )
    diagnostic = Table(
        "LayoutDiagnostic",
        MetaData(),
        Column("libraryId", _ID, nullable=False),
        Column("reconcileOriginId", _ID),
    )
    for index in (
        Index(
            "TopologyUnitRevision_reconcile_origin_idx",
            revision.c.libraryId,
            revision.c.reconcileOriginId,
            revision.c.state,
        ),
        Index(
            "LayoutDiagnostic_reconcile_origin_idx",
            diagnostic.c.libraryId,
            diagnostic.c.reconcileOriginId,
        ),
    ):
        index.create(bind=op.get_bind())


def upgrade() -> None:
    """Apply watcher journal, origin, watermark, and presence schema."""

    _create_watcher_tables()
    _extend_source_entry()
    _extend_scan_run()
    _add_reconcile_origins()


def downgrade() -> None:
    """Reject downgrade before touching the append-only current schema."""

    raise NotImplementedError(
        "current schema lineage is append-only; downgrade is unsupported"
    )
