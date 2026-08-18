"""Replace MonitorFolder with Library as the catalog root.

Revision ID: 0029_library_root
Revises: 0028_remove_publication_render_cache
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0029_library_root"
down_revision: str | Sequence[str] | None = "0028_remove_publication_render_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "Library",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("rootPath", sa.String(length=191), nullable=False),
        sa.Column("organizationMode", sa.String(length=32), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("ignorePatterns", sa.Text(), nullable=True),
        sa.Column(
            "ignoreHidden", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "minFileSizeBytes",
            sa.Integer(),
            server_default=sa.text("10240"),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=191), nullable=True),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.CheckConstraint(
            "organizationMode IN ('FLAT', 'VOLUMES', 'AUDIOBOOK')",
            name="Library_organizationMode_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rootPath"),
    )
    op.create_table(
        "UserLibraryAccess",
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("libraryId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["User.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["libraryId"],
            ["Library.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("userId", "libraryId"),
    )
    op.create_index(
        "UserLibraryAccess_library_idx",
        "UserLibraryAccess",
        ["libraryId"],
        unique=False,
    )

    with op.batch_alter_table("LibraryWork") as batch_op:
        batch_op.drop_index("LibraryWork_monitorFolderId_idx")
        batch_op.drop_column("monitorFolderId")
        batch_op.add_column(sa.Column("libraryId", sa.String(length=191), nullable=False))
        batch_op.create_foreign_key(
            "LibraryWork_libraryId_fkey",
            "Library",
            ["libraryId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_index("LibraryWork_libraryId_idx", ["libraryId"], unique=False)

    with op.batch_alter_table("LibraryVolume") as batch_op:
        batch_op.drop_index("LibraryVolume_monitorFolderId_idx")
        batch_op.drop_index("LibraryVolume_mediaVersionId_hidden_monitorFolderId_idx")
        batch_op.drop_column("monitorFolderId")
        batch_op.create_index(
            "LibraryVolume_mediaVersionId_hidden_idx",
            ["mediaVersionId", "hidden"],
            unique=False,
        )

    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.drop_index("ImportTask_monitorFolderId_status_idx")
        batch_op.drop_index("ImportTask_monitorFolderId_createdAt_id_idx")
        batch_op.drop_index("ImportTask_monitorFolderId_status_createdAt_id_idx")
        batch_op.drop_column("monitorFolderId")
        batch_op.add_column(sa.Column("libraryId", sa.String(length=191), nullable=True))
        batch_op.create_foreign_key(
            "ImportTask_libraryId_fkey",
            "Library",
            ["libraryId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "ImportTask_libraryId_status_idx", ["libraryId", "status"], unique=False
        )
        batch_op.create_index(
            "ImportTask_libraryId_createdAt_id_idx",
            ["libraryId", "createdAt", "id"],
            unique=False,
        )
        batch_op.create_index(
            "ImportTask_libraryId_status_createdAt_id_idx",
            ["libraryId", "status", "createdAt", "id"],
            unique=False,
        )

    with op.batch_alter_table("ImportScanJob") as batch_op:
        batch_op.drop_index("ImportScanJob_monitorFolderId_status_createdAt_idx")
        batch_op.drop_column("monitorFolderId")
        batch_op.add_column(sa.Column("libraryId", sa.String(length=191), nullable=True))
        batch_op.create_foreign_key(
            "ImportScanJob_libraryId_fkey",
            "Library",
            ["libraryId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "ImportScanJob_libraryId_status_createdAt_idx",
            ["libraryId", "status", "createdAt"],
            unique=False,
        )

    op.drop_index("UserMonitorFolderAccess_folder_idx", table_name="UserMonitorFolderAccess")
    op.drop_table("UserMonitorFolderAccess")
    op.drop_table("MonitorFolder")


def downgrade() -> None:
    raise NotImplementedError("0029_library_root does not support downgrade")
