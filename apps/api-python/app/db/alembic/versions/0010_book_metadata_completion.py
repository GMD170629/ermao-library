"""Persist two-stage import metadata and manual field ownership."""

import sqlalchemy as sa
from alembic import op

revision = "0010_book_metadata_completion"
down_revision = "0009_reader_v5_opaque_progress"
branch_labels = None
depends_on = None


def _shape() -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.and_(
            sa.column("kind") == "SCAN_LIBRARY",
            sa.column("sourceNodeId").is_(None),
            sa.column("resourceId").is_(None),
            sa.column("role").is_(None),
        ),
        sa.and_(
            sa.column("kind").in_(("CONTINUE_SOURCE", "IDENTIFY_BOOK")),
            sa.column("sourceNodeId").is_not(None),
            sa.column("resourceId").is_(None),
            sa.column("role").is_(None),
        ),
        sa.and_(
            sa.column("kind") == "IMPORT_ASSET",
            sa.column("sourceNodeId").is_not(None),
            sa.column("resourceId").is_not(None),
            sa.column("role").is_not(None),
        ),
    )


def upgrade() -> None:
    for table in (
        "LibraryBookMetadata",
        "LibraryReadableResourceMetadata",
        "LibrarySourceNodeMetadata",
    ):
        op.add_column(
            table,
            sa.Column(
                "protectedFields", sa.Text(), nullable=False, server_default="[]"
            ),
        )
    for name, default in (("importRevision", "0"), ("processedRevision", "-1")):
        op.add_column(
            "LibraryBookMetadata",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )
    op.add_column(
        "LibraryBookMetadata",
        sa.Column("metadataPending", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.add_column(
        "LibraryBookMetadata",
        sa.Column(
            "metadataState",
            sa.String(32),
            nullable=False,
            server_default="WAITING_IMPORT",
        ),
    )
    op.add_column(
        "LibraryResourceAsset",
        sa.Column(
            "localMetadataCandidates", sa.Text(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "LibraryResourceAsset", sa.Column("localCoverPath", sa.Text(), nullable=True)
    )
    with op.batch_alter_table("LibraryImportTask") as batch:
        batch.add_column(sa.Column("bookMetadataRevision", sa.Integer(), nullable=True))
        batch.drop_constraint("LibraryImportTask_kind_check", type_="check")
        batch.drop_constraint("LibraryImportTask_kind_shape_check", type_="check")
        batch.create_check_constraint(
            "LibraryImportTask_kind_check",
            sa.column("kind").in_(
                ("SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_ASSET", "IDENTIFY_BOOK")
            ),
        )
        batch.create_check_constraint("LibraryImportTask_kind_shape_check", _shape())
        batch.create_index(
            "LibraryImportTask_book_active_key",
            ["sourceNodeId"],
            unique=True,
            sqlite_where=sa.and_(
                sa.column("kind") == "IDENTIFY_BOOK",
                sa.column("state").in_(("QUEUED", "RUNNING")),
            ),
        )


def downgrade() -> None:
    raise RuntimeError("Two-stage metadata requires restoring the pre-upgrade backup")
