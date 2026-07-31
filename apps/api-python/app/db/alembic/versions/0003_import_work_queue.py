"""Add the bounded persistent import work queue.

Revision ID: 0003_import_work_queue
Revises: 0002_shelf_collections
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0003_import_work_queue"
down_revision: str | Sequence[str] | None = "0002_shelf_collections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        str(index["name"])
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    if "sourceKey" not in _column_names("ImportTask"):
        with op.batch_alter_table("ImportTask") as batch_op:
            batch_op.add_column(
                sa.Column("sourceKey", sa.String(length=64), nullable=True)
            )
    if "ImportTask_sourceKey_status_createdAt_idx" not in _index_names("ImportTask"):
        op.create_index(
            "ImportTask_sourceKey_status_createdAt_idx",
            "ImportTask",
            ["sourceKey", "status", "createdAt"],
            unique=False,
        )

    if "pathKey" not in _column_names("LibraryFile"):
        with op.batch_alter_table("LibraryFile") as batch_op:
            batch_op.add_column(
                sa.Column("pathKey", sa.String(length=64), nullable=True)
            )
    if "LibraryFile_pathKey_idx" not in _index_names("LibraryFile"):
        op.create_index(
            "LibraryFile_pathKey_idx",
            "LibraryFile",
            ["pathKey"],
            unique=False,
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ImportScanJob" not in tables:
        op.create_table(
            "ImportScanJob",
            sa.Column("id", sa.String(length=191), nullable=False),
            sa.Column("monitorFolderId", sa.String(length=191), nullable=True),
            sa.Column("actorUserId", sa.String(length=191), nullable=True),
            sa.Column("rootPath", sa.Text(), nullable=False),
            sa.Column("trigger", sa.String(length=32), nullable=False),
            sa.Column(
                "status", sa.String(length=32), server_default="PENDING", nullable=False
            ),
            sa.Column(
                "directoriesScanned", sa.Integer(), server_default="0", nullable=False
            ),
            sa.Column("filesScanned", sa.Integer(), server_default="0", nullable=False),
            sa.Column(
                "candidatesFound", sa.Integer(), server_default="0", nullable=False
            ),
            sa.Column("queuedCount", sa.Integer(), server_default="0", nullable=False),
            sa.Column("skippedCount", sa.Integer(), server_default="0", nullable=False),
            sa.Column("errorCount", sa.Integer(), server_default="0", nullable=False),
            sa.Column(
                "ignoredReasonCounts", sa.JSON(), server_default="{}", nullable=False
            ),
            sa.Column("errorSamples", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("restartCount", sa.Integer(), server_default="0", nullable=False),
            sa.Column("startedAt", TimestampMilliseconds(), nullable=True),
            sa.Column("heartbeatAt", TimestampMilliseconds(), nullable=True),
            sa.Column("finishedAt", TimestampMilliseconds(), nullable=True),
            sa.Column(
                "createdAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
            sa.ForeignKeyConstraint(
                ["monitorFolderId"],
                ["MonitorFolder.id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["actorUserId"],
                ["User.id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    scan_indexes = _index_names("ImportScanJob")
    if "ImportScanJob_monitorFolderId_status_createdAt_idx" not in scan_indexes:
        op.create_index(
            "ImportScanJob_monitorFolderId_status_createdAt_idx",
            "ImportScanJob",
            ["monitorFolderId", "status", "createdAt"],
            unique=False,
        )
    if "ImportScanJob_status_updatedAt_idx" not in scan_indexes:
        op.create_index(
            "ImportScanJob_status_updatedAt_idx",
            "ImportScanJob",
            ["status", "updatedAt"],
            unique=False,
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ImportWorkItem" not in tables:
        op.create_table(
            "ImportWorkItem",
            sa.Column("id", sa.String(length=191), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("scanJobId", sa.String(length=191), nullable=True),
            sa.Column("importTaskId", sa.String(length=191), nullable=True),
            sa.Column("dedupeKey", sa.String(length=191), nullable=False),
            sa.Column(
                "status", sa.String(length=32), server_default="PENDING", nullable=False
            ),
            sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
            sa.Column(
                "availableAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.Column("leaseOwner", sa.String(length=191), nullable=True),
            sa.Column("leaseExpiresAt", TimestampMilliseconds(), nullable=True),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column(
                "createdAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
            sa.CheckConstraint(
                "(kind = 'SCAN_DIRECTORY' AND scanJobId IS NOT NULL "
                "AND importTaskId IS NULL) OR "
                "(kind = 'IMPORT_SOURCE' AND importTaskId IS NOT NULL "
                "AND scanJobId IS NULL)",
                name="ImportWorkItem_target_check",
            ),
            sa.ForeignKeyConstraint(
                ["scanJobId"],
                ["ImportScanJob.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["importTaskId"],
                ["ImportTask.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dedupeKey", name="ImportWorkItem_dedupeKey_key"),
            sa.UniqueConstraint("scanJobId", name="ImportWorkItem_scanJobId_key"),
            sa.UniqueConstraint("importTaskId", name="ImportWorkItem_importTaskId_key"),
        )
    work_indexes = _index_names("ImportWorkItem")
    if "ImportWorkItem_status_availableAt_priority_createdAt_idx" not in work_indexes:
        op.create_index(
            "ImportWorkItem_status_availableAt_priority_createdAt_idx",
            "ImportWorkItem",
            ["status", "availableAt", "priority", "createdAt"],
            unique=False,
        )
    if "ImportWorkItem_kind_status_idx" not in work_indexes:
        op.create_index(
            "ImportWorkItem_kind_status_idx",
            "ImportWorkItem",
            ["kind", "status"],
            unique=False,
        )
    if "ImportWorkItem_leaseExpiresAt_idx" not in work_indexes:
        op.create_index(
            "ImportWorkItem_leaseExpiresAt_idx",
            "ImportWorkItem",
            ["leaseExpiresAt"],
            unique=False,
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ImportWorkItem" in tables:
        op.drop_table("ImportWorkItem")
    if "ImportScanJob" in tables:
        op.drop_table("ImportScanJob")
    if "pathKey" in _column_names("LibraryFile"):
        with op.batch_alter_table("LibraryFile") as batch_op:
            if "LibraryFile_pathKey_idx" in _index_names("LibraryFile"):
                batch_op.drop_index("LibraryFile_pathKey_idx")
            batch_op.drop_column("pathKey")
    if "sourceKey" in _column_names("ImportTask"):
        with op.batch_alter_table("ImportTask") as batch_op:
            if "ImportTask_sourceKey_status_createdAt_idx" in _index_names(
                "ImportTask"
            ):
                batch_op.drop_index("ImportTask_sourceKey_status_createdAt_idx")
            batch_op.drop_column("sourceKey")
