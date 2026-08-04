"""Add metadata file writeback policy and recoverable queue.

Revision ID: 0012_metadata_file_writeback
Revises: 0011_reader_progress_sources
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0012_metadata_file_writeback"
down_revision: str | Sequence[str] | None = "0011_reader_progress_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("OrganizePolicy") as batch_op:
        batch_op.add_column(
            sa.Column(
                "writeMetadataToFiles",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.drop_column("overwriteTitleAuthor")

    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.add_column(sa.Column("recognizedMetadata", sa.JSON(), nullable=True))

    op.create_table(
        "MetadataWritebackOperation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("mediaVersionId", sa.String(length=191), nullable=False),
        sa.Column("lookupTaskId", sa.String(length=191), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="PENDING"
        ),
        sa.Column("totalTargets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completedTargets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warningTargets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            nullable=False,
            server_default=sa.func.unixepoch() * 1000,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.Column("finishedAt", TimestampMilliseconds(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mediaVersionId"],
            ["LibraryMediaVersion.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lookupTaskId"],
            ["MetadataLookupTask.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "MetadataWritebackOperation_status_createdAt_idx",
        "MetadataWritebackOperation",
        ["status", "createdAt"],
    )
    op.create_index(
        "MetadataWritebackOperation_workId_createdAt_idx",
        "MetadataWritebackOperation",
        ["workId", "createdAt"],
    )

    op.create_table(
        "MetadataWritebackTarget",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("operationId", sa.String(length=191), nullable=False),
        sa.Column("libraryFileId", sa.String(length=191), nullable=True),
        sa.Column("targetKey", sa.String(length=64), nullable=False),
        sa.Column("sourcePath", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("payloadJson", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="PENDING"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nextAttemptAt", TimestampMilliseconds(), nullable=True),
        sa.Column("preparedPath", sa.Text(), nullable=True),
        sa.Column("outputHash", sa.String(length=64), nullable=True),
        sa.Column("writtenFieldsJson", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("warningCode", sa.String(length=64), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            nullable=False,
            server_default=sa.func.unixepoch() * 1000,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.Column("finishedAt", TimestampMilliseconds(), nullable=True),
        sa.ForeignKeyConstraint(
            ["operationId"],
            ["MetadataWritebackOperation.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["libraryFileId"],
            ["LibraryFile.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operationId",
            "targetKey",
            name="MetadataWritebackTarget_operation_target_key",
        ),
    )
    op.create_index(
        "MetadataWritebackTarget_status_createdAt_idx",
        "MetadataWritebackTarget",
        ["status", "createdAt"],
    )
    op.create_index(
        "MetadataWritebackTarget_operationId_idx",
        "MetadataWritebackTarget",
        ["operationId"],
    )


def downgrade() -> None:
    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.drop_column("recognizedMetadata")

    op.drop_index(
        "MetadataWritebackTarget_operationId_idx", table_name="MetadataWritebackTarget"
    )
    op.drop_index(
        "MetadataWritebackTarget_status_createdAt_idx",
        table_name="MetadataWritebackTarget",
    )
    op.drop_table("MetadataWritebackTarget")
    op.drop_index(
        "MetadataWritebackOperation_workId_createdAt_idx",
        table_name="MetadataWritebackOperation",
    )
    op.drop_index(
        "MetadataWritebackOperation_status_createdAt_idx",
        table_name="MetadataWritebackOperation",
    )
    op.drop_table("MetadataWritebackOperation")
    with op.batch_alter_table("OrganizePolicy") as batch_op:
        batch_op.add_column(
            sa.Column(
                "overwriteTitleAuthor", sa.Boolean(), nullable=False, server_default="1"
            )
        )
        batch_op.drop_column("writeMetadataToFiles")
