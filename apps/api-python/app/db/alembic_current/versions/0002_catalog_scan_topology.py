"""Tighten fresh catalog scan and topology schema shapes.

The current lineage is fresh-install only. This revision therefore transforms
an empty 0001 schema and contains no compatibility backfill or runtime imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from types import ModuleType
from typing import cast

from alembic import context, op
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    Index,
    MetaData,
    String,
    Table,
    Text,
    and_,
    column,
    or_,
)

revision: str = "0002_catalog_scan_topology"
down_revision: str | None = "0001_system_and_catalog_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ID = String(191)
_ACTIVE_SCAN_STATES = ("PENDING", "RUNNING", "FINALIZING")
_SCAN_STATES = (*_ACTIVE_SCAN_STATES, "COMPLETED", "FAILED", "CANCELLED")
_SOURCE_ENTRY_TYPES = (
    "SYNTHETIC_ROOT",
    "DIRECTORY",
    "FILE",
    "SYMLINK",
    "JUNCTION",
    "SPECIAL",
)
_SLOT_STATES = ("ACTIVE", "COLLIDING", "RETIRED")
_SCAN_FAILURE_CODES = (
    "ROOT_UNAVAILABLE",
    "PERMISSION_DENIED",
    "IO_ERROR",
    "DIRECTORY_CHANGED",
    "INVALID_RELATIVE_PATH",
    "ROOT_IDENTITY_CHANGED",
)

_baseline_revision = cast(
    ModuleType,
    import_module("app.db.alembic_current.versions.0001_system_and_catalog_core"),
)
_baseline_metadata = cast(MetaData, _baseline_revision.metadata)


def _cloned_baseline_metadata() -> MetaData:
    cloned = MetaData()
    for baseline_table in _baseline_metadata.tables.values():
        baseline_table.to_metadata(cloned)
    return cloned


_scan_copy_metadata = _cloned_baseline_metadata()
_scan_run_copy = _scan_copy_metadata.tables["LibraryScanRun"]
_scan_work_item_copy = _scan_copy_metadata.tables["LibraryScanWorkItem"]
_source_entry_copy = _scan_copy_metadata.tables["LibrarySourceEntry"]
for _scan_table in (_scan_run_copy, _scan_work_item_copy):
    for _constraint in tuple(_scan_table.constraints):
        if _constraint.name == "scanstate":
            _scan_table.constraints.remove(_constraint)
    _scan_table.c.state.type = String(10)
for _constraint in tuple(_source_entry_copy.constraints):
    if _constraint.name in {"sourceentrytype", "slotstate"}:
        _source_entry_copy.constraints.remove(_constraint)
_source_entry_copy.c.entryType.type = String(14)
_source_entry_copy.c.slotState.type = String(9)

_index_metadata = MetaData()
_source_entry = Table(
    "LibrarySourceEntry",
    _index_metadata,
    Column("libraryId", _ID, nullable=False),
    Column("lastSeenGeneration", BigInteger),
)
_scan_run = Table(
    "LibraryScanRun",
    _index_metadata,
    Column("libraryId", _ID, nullable=False),
    Column("state", String(10), nullable=False),
)
_scan_work_item = Table(
    "LibraryScanWorkItem",
    _index_metadata,
    Column("libraryId", _ID, nullable=False),
    Column("state", String(10), nullable=False),
    Column("leaseExpiresAt", DateTime(timezone=True)),
)


def _offline_copy(table_name: str) -> Table | None:
    if not context.is_offline_mode():
        return None
    if table_name == "LibraryScanRun":
        return _scan_run_copy
    if table_name == "LibraryScanWorkItem":
        return _scan_work_item_copy
    if table_name == "LibrarySourceEntry":
        return _source_entry_copy
    return _baseline_metadata.tables[table_name]


def _tighten_volume_projection() -> None:
    with op.batch_alter_table(
        "TopologyVolumeProjection",
        recreate="always",
        partial_reordering=[
            (
                "id",
                "libraryId",
                "unitRevisionId",
                "volumeId",
                "versionId",
                "rootEntryId",
                "sourceKind",
                "readingMorphology",
                "structureKey",
                "sourceName",
                "sortKey",
            )
        ],
        copy_from=_offline_copy("TopologyVolumeProjection"),
    ) as batch_op:
        batch_op.drop_constraint(
            "TopologyVolumeProjection_revision_key", type_="unique"
        )
        batch_op.alter_column("versionId", existing_type=_ID, nullable=False)
        batch_op.add_column(Column("readingMorphology", String(32), nullable=False))


def _tighten_version_projection() -> None:
    kind = column("kind", String(9))
    root_entry_id = column("rootEntryId", _ID)
    source_name = column("sourceName", Text())
    with op.batch_alter_table(
        "TopologyVersionProjection",
        recreate="always",
        copy_from=_offline_copy("TopologyVersionProjection"),
    ) as batch_op:
        batch_op.alter_column("sourceName", existing_type=Text(), nullable=True)
        batch_op.create_check_constraint(
            "TopologyVersionProjection_shape_ck",
            or_(
                and_(
                    kind == "IMPLICIT",
                    root_entry_id.is_(None),
                    source_name.is_(None),
                ),
                and_(
                    kind == "DIRECTORY",
                    root_entry_id.is_not(None),
                    source_name.is_not(None),
                ),
            ),
        )


def _tighten_scan_run() -> None:
    state = column("state", String(10))
    failure_code = column("failureCode", String(32))
    path_comparison = column("pathComparisonSnapshot", String(11))
    generation = column("generation", BigInteger())
    config_revision = column("configRevision", BigInteger())
    topology_version = column("topologyVersionSnapshot", BigInteger())
    writer_fence = column("topologyWriterFence", BigInteger())
    discovered_count = column("discoveredCount", BigInteger())
    diagnostic_count = column("diagnosticCount", BigInteger())
    root_identity = column("rootIdentitySnapshot", String(191))
    lease_owner = column("leaseOwner", _ID)
    lease_expires_at = column("leaseExpiresAt", DateTime(timezone=True))
    stage = column("stage", String(9))
    started_at = column("startedAt", DateTime(timezone=True))
    finished_at = column("finishedAt", DateTime(timezone=True))
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
        if not context.is_offline_mode():
            batch_op.drop_constraint("scanstate", type_="check")
        batch_op.add_column(Column("rootPathSnapshot", Text(), nullable=False))
        batch_op.add_column(
            Column("pathComparisonSnapshot", String(11), nullable=False)
        )
        batch_op.add_column(
            Column(
                "failureCode",
                Enum(
                    *_SCAN_FAILURE_CODES,
                    name="scanfailurecode",
                    native_enum=False,
                    create_constraint=False,
                ),
            )
        )
        batch_op.alter_column("state", existing_type=String(9), type_=String(10))
        batch_op.create_check_constraint("scanstate", state.in_(_SCAN_STATES))
        batch_op.create_check_constraint(
            "LibraryScanRun_failure_shape_ck",
            or_(
                and_(state == "FAILED", failure_code.is_not(None)),
                and_(state != "FAILED", failure_code.is_(None)),
            ),
        )
        batch_op.create_check_constraint(
            "scanfailurecode", failure_code.in_(_SCAN_FAILURE_CODES)
        )
        batch_op.create_check_constraint(
            "pathcomparison",
            path_comparison.in_(("SENSITIVE", "INSENSITIVE")),
        )
        batch_op.create_check_constraint(
            "LibraryScanRun_positive_ck",
            and_(
                generation > 0,
                config_revision > 0,
                topology_version > 0,
                writer_fence > 0,
                discovered_count >= 0,
                diagnostic_count >= 0,
            ),
        )
        batch_op.create_check_constraint(
            "LibraryScanRun_state_shape_ck",
            or_(
                and_(
                    state == "PENDING",
                    stage == "DISCOVER",
                    lease_owner.is_not(None),
                    lease_expires_at.is_not(None),
                    root_identity.is_(None),
                    started_at.is_(None),
                    finished_at.is_(None),
                ),
                and_(
                    state == "RUNNING",
                    stage.in_(("DISCOVER", "RECONCILE")),
                    lease_owner.is_not(None),
                    lease_expires_at.is_not(None),
                    root_identity.is_not(None),
                    started_at.is_not(None),
                    finished_at.is_(None),
                ),
                and_(
                    state == "FINALIZING",
                    stage == "FINALIZE",
                    lease_owner.is_not(None),
                    lease_expires_at.is_not(None),
                    root_identity.is_not(None),
                    started_at.is_not(None),
                    finished_at.is_(None),
                ),
                and_(
                    state == "COMPLETED",
                    stage == "FINALIZE",
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    root_identity.is_not(None),
                    started_at.is_not(None),
                    finished_at.is_not(None),
                ),
                and_(
                    state.in_(("FAILED", "CANCELLED")),
                    lease_owner.is_(None),
                    lease_expires_at.is_(None),
                    finished_at.is_not(None),
                    or_(
                        and_(root_identity.is_(None), started_at.is_(None)),
                        and_(root_identity.is_not(None), started_at.is_not(None)),
                    ),
                ),
            ),
        )


def _tighten_scan_work_item() -> None:
    state = column("state", String(10))
    lease_owner = column("leaseOwner", _ID)
    lease_expires_at = column("leaseExpiresAt", DateTime(timezone=True))
    subtree_root_entry_id = column("subtreeRootEntryId", _ID)
    scope_relative_path = column("scopeRelativePath", Text())
    attempt = column("attempt", BigInteger())
    discovered_count = column("discoveredCount", BigInteger())
    with op.batch_alter_table(
        "LibraryScanWorkItem",
        recreate="always",
        partial_reordering=[
            (
                "id",
                "libraryId",
                "scanRunId",
                "rootPathSnapshot",
                "subtreeRootEntryId",
                "scopeRelativePath",
                "state",
                "stage",
                "leaseOwner",
                "leaseExpiresAt",
                "attempt",
                "availableAt",
                "idempotencyKey",
                "discoveredCount",
                "createdAt",
            )
        ],
        copy_from=_offline_copy("LibraryScanWorkItem"),
    ) as batch_op:
        if not context.is_offline_mode():
            batch_op.drop_constraint("scanstate", type_="check")
        batch_op.add_column(Column("rootPathSnapshot", Text(), nullable=False))
        batch_op.alter_column("state", existing_type=String(9), type_=String(10))
        batch_op.create_check_constraint("scanstate", state.in_(_SCAN_STATES))
        batch_op.create_check_constraint(
            "LibraryScanWorkItem_root_shape_ck",
            and_(
                subtree_root_entry_id.is_(None),
                scope_relative_path == "",
                attempt >= 0,
                discovered_count >= 0,
                or_(
                    and_(
                        state == "PENDING",
                        lease_owner.is_(None),
                        lease_expires_at.is_(None),
                    ),
                    and_(
                        state == "RUNNING",
                        lease_owner.is_not(None),
                        lease_expires_at.is_not(None),
                    ),
                ),
            ),
        )


def _expand_source_observation_states() -> None:
    entry_type = column("entryType", String(14))
    slot_state = column("slotState", String(9))
    with op.batch_alter_table(
        "LibrarySourceEntry",
        recreate="always",
        copy_from=_offline_copy("LibrarySourceEntry"),
    ) as batch_op:
        if not context.is_offline_mode():
            batch_op.drop_constraint("sourceentrytype", type_="check")
            batch_op.drop_constraint("slotstate", type_="check")
        batch_op.alter_column("entryType", existing_type=String(14), type_=String(14))
        batch_op.alter_column("slotState", existing_type=String(9), type_=String(9))
        batch_op.create_check_constraint(
            "sourceentrytype", entry_type.in_(_SOURCE_ENTRY_TYPES)
        )
        batch_op.create_check_constraint("slotstate", slot_state.in_(_SLOT_STATES))


def _create_indexes() -> None:
    indexes = (
        Index(
            "LibrarySourceEntry_generation_idx",
            _source_entry.c.libraryId,
            _source_entry.c.lastSeenGeneration,
        ),
        Index(
            "LibraryScanWorkItem_lease_recovery_idx",
            _scan_work_item.c.libraryId,
            _scan_work_item.c.state,
            _scan_work_item.c.leaseExpiresAt,
        ),
        Index(
            "LibraryScanRun_one_active_idx",
            _scan_run.c.libraryId,
            unique=True,
            sqlite_where=_scan_run.c.state.in_(_ACTIVE_SCAN_STATES),
        ),
    )
    for index in indexes:
        index.create(bind=op.get_bind())


def upgrade() -> None:
    """Apply the fresh-only scan and topology schema constraints."""

    _tighten_volume_projection()
    _tighten_version_projection()
    _tighten_scan_run()
    _tighten_scan_work_item()
    _expand_source_observation_states()
    _create_indexes()


def downgrade() -> None:
    """Reject downgrade before touching the append-only current schema."""

    raise NotImplementedError(
        "current schema lineage is append-only; downgrade is unsupported"
    )
