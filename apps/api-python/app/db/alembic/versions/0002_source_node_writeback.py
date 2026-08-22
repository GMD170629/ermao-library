"""Associate OPF writeback work with its source node.

Revision ID: 0002_source_node_writeback
Revises: 0001_library_topology_baseline

``sourceNodeId`` is the durable writeback subject. ``resourceId`` remains
nullable and identifies the resource-specific OPF representation when one is
available. Downgrade is not supported.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_source_node_writeback"
down_revision: str | Sequence[str] | None = "0001_library_topology_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "MetadataWritebackOperation",
        sa.Column("sourceNodeId", sa.String(length=191), nullable=True),
    )
    op.add_column(
        "MetadataWritebackPreparation",
        sa.Column("sourceNodeId", sa.String(length=191), nullable=True),
    )

    readable_resource = sa.table(
        "LibraryReadableResource",
        sa.column("id", sa.String(length=191)),
        sa.column("sourceNodeId", sa.String(length=191)),
    )
    operation = sa.table(
        "MetadataWritebackOperation",
        sa.column("id", sa.String(length=191)),
        sa.column("resourceId", sa.String(length=191)),
        sa.column("sourceNodeId", sa.String(length=191)),
    )
    preparation = sa.table(
        "MetadataWritebackPreparation",
        sa.column("operationId", sa.String(length=191)),
        sa.column("sourceNodeId", sa.String(length=191)),
    )
    connection = op.get_bind()
    connection.execute(
        sa.update(operation).values(
            sourceNodeId=(
                sa.select(readable_resource.c.sourceNodeId)
                .where(readable_resource.c.id == operation.c.resourceId)
                .scalar_subquery()
            )
        )
    )
    connection.execute(
        sa.update(preparation).values(
            sourceNodeId=(
                sa.select(operation.c.sourceNodeId)
                .where(operation.c.id == preparation.c.operationId)
                .scalar_subquery()
            )
        )
    )

    missing_operations = connection.scalar(
        sa.select(sa.func.count())
        .select_from(operation)
        .where(operation.c.sourceNodeId.is_(None))
    )
    missing_preparations = connection.scalar(
        sa.select(sa.func.count())
        .select_from(preparation)
        .where(preparation.c.sourceNodeId.is_(None))
    )
    if missing_operations or missing_preparations:
        raise RuntimeError("cannot associate existing OPF work with a source node")

    with op.batch_alter_table("MetadataWritebackOperation") as batch_op:
        batch_op.alter_column(
            "sourceNodeId",
            existing_type=sa.String(length=191),
            nullable=False,
        )
        batch_op.alter_column(
            "resourceId",
            existing_type=sa.String(length=191),
            nullable=True,
        )
        batch_op.create_foreign_key(
            "MetadataWritebackOperation_sourceNodeId_fkey",
            "LibrarySourceNode",
            ["sourceNodeId"],
            ["id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "MetadataWritebackOperation_sourceNodeId_idx",
            ["sourceNodeId"],
            unique=False,
        )

    with op.batch_alter_table("MetadataWritebackPreparation") as batch_op:
        batch_op.alter_column(
            "sourceNodeId",
            existing_type=sa.String(length=191),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "MetadataWritebackPreparation_sourceNodeId_fkey",
            "LibrarySourceNode",
            ["sourceNodeId"],
            ["id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "MetadataWritebackPreparation_sourceNodeId_idx",
            ["sourceNodeId"],
            unique=False,
        )


def downgrade() -> None:
    raise RuntimeError("downgrade is not supported")
