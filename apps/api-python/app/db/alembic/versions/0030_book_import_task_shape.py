"""Add Book-scoped work to the existing single-consumer import task table."""

import sqlalchemy as sa
from alembic import op

revision = "0030_book_import_task_shape"
down_revision = "0029_file_deletions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    kind = sa.column("kind")
    node = sa.column("sourceNodeId")
    resource = sa.column("resourceId")
    role = sa.column("role")
    book = sa.column("bookId")
    phase = sa.column("phase")
    with op.batch_alter_table("LibraryImportTask") as batch:
        batch.add_column(sa.Column("bookId", sa.String(191), nullable=True))
        batch.add_column(sa.Column("phase", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column(
                "requestVersion", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(sa.Column("executionVersion", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("bookWork", sa.Text(), nullable=True))
        batch.add_column(sa.Column("resourceCursor", sa.String(191), nullable=True))
        batch.add_column(
            sa.Column("retryCount", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("nextAttemptAt", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("supersededByTaskId", sa.String(191), nullable=True))
        batch.drop_constraint("LibraryImportTask_kind_check", type_="check")
        batch.drop_constraint("LibraryImportTask_kind_shape_check", type_="check")
        batch.create_check_constraint(
            "LibraryImportTask_kind_check",
            kind.in_(
                (
                    "SCAN_LIBRARY",
                    "CONTINUE_SOURCE",
                    "IMPORT_ASSET",
                    "IMPORT_RESOURCE",
                    "IDENTIFY_BOOK",
                    "IMPORT_BOOK",
                )
            ),
        )
        batch.create_check_constraint(
            "LibraryImportTask_kind_shape_check",
            sa.or_(
                sa.and_(
                    kind == "SCAN_LIBRARY",
                    node.is_(None),
                    resource.is_(None),
                    role.is_(None),
                ),
                sa.and_(
                    kind.in_(("CONTINUE_SOURCE", "IDENTIFY_BOOK")),
                    node.is_not(None),
                    resource.is_(None),
                    role.is_(None),
                ),
                sa.and_(
                    kind == "IMPORT_RESOURCE",
                    node.is_not(None),
                    resource.is_not(None),
                    role.is_(None),
                ),
                sa.and_(
                    kind == "IMPORT_ASSET",
                    node.is_not(None),
                    resource.is_not(None),
                    role.is_not(None),
                ),
                sa.and_(
                    kind == "IMPORT_BOOK",
                    node.is_not(None),
                    resource.is_(None),
                    role.is_(None),
                    book.is_not(None),
                    sa.column("bookWork").is_not(None),
                ),
            ),
        )
        batch.create_check_constraint(
            "LibraryImportTask_book_scope_check",
            sa.or_(
                sa.and_(
                    kind == "IMPORT_BOOK",
                    phase.is_not(None),
                    phase.in_(("SCAN", "RESOURCES", "IDENTIFY", "FINALIZE")),
                ),
                sa.and_(kind != "IMPORT_BOOK", book.is_(None), phase.is_(None)),
            ),
        )
        batch.create_check_constraint(
            "LibraryImportTask_book_counters_check",
            sa.and_(
                sa.column("requestVersion") >= 0,
                sa.column("retryCount") >= 0,
            ),
        )
        batch.create_foreign_key(
            "fk_LibraryImportTask_book_library",
            "LibraryBook",
            ["bookId", "libraryId"],
            ["id", "libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch.create_index(
            "LibraryImportTask_book_key",
            ["bookId"],
            unique=True,
            sqlite_where=kind == "IMPORT_BOOK",
        )
        batch.create_index(
            "LibraryImportTask_bookId_libraryId_idx",
            ["bookId", "libraryId"],
        )
        batch.create_index(
            "LibraryImportTask_book_runnable_idx",
            ["state", "nextAttemptAt", "createdAt", "id"],
            sqlite_where=kind == "IMPORT_BOOK",
        )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade Book imports")
