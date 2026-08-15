"""Remove file-content hashes and fingerprint-scoped Reader state.

Revision ID: 0027_remove_file_content_hashes
Revises: 0026_publication_render_cache
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0027_remove_file_content_hashes"
down_revision: str | Sequence[str] | None = "0026_publication_render_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _deduplicate_bookmarks() -> None:
    bookmark = sa.table(
        "ReaderBookmark",
        sa.column("id", sa.String()),
        sa.column("userId", sa.String()),
        sa.column("volumeId", sa.String()),
        sa.column("bookmarkId", sa.String()),
        sa.column("updatedAt", TimestampMilliseconds()),
    )
    rows = op.get_bind().execute(
        sa.select(
            bookmark.c.id,
            bookmark.c.userId,
            bookmark.c.volumeId,
            bookmark.c.bookmarkId,
        ).order_by(
            bookmark.c.userId,
            bookmark.c.volumeId,
            bookmark.c.bookmarkId,
            bookmark.c.updatedAt.desc(),
            bookmark.c.id.desc(),
        )
    )
    seen: set[tuple[str, str, str]] = set()
    duplicate_ids: list[str] = []
    for row in rows:
        key = (row.userId, row.volumeId, row.bookmarkId)
        if key in seen:
            duplicate_ids.append(row.id)
        else:
            seen.add(key)
    for offset in range(0, len(duplicate_ids), 500):
        op.get_bind().execute(
            sa.delete(bookmark).where(
                bookmark.c.id.in_(duplicate_ids[offset : offset + 500])
            )
        )


def _create_navigation_cache() -> None:
    op.create_table(
        "PublicationNavigationCache",
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("fileId", sa.String(length=191), nullable=False),
        sa.Column("sourceSizeBytes", sa.Integer(), nullable=False),
        sa.Column("sourceMtimeMs", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=191), nullable=False),
        sa.Column("normalization", sa.String(length=191), nullable=False),
        sa.Column("projectionVersion", sa.Integer(), nullable=False),
        sa.Column("chapterCount", sa.Integer(), nullable=False),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.CheckConstraint(
            '"chapterCount" >= 0',
            name="PublicationNavigationCache_chapterCount_check",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["fileId"], ["LibraryFile.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.PrimaryKeyConstraint("volumeId"),
    )


def _create_render_cache() -> None:
    op.create_table(
        "PublicationRenderCache",
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("fileId", sa.String(length=191), nullable=False),
        sa.Column("sourceSizeBytes", sa.Integer(), nullable=False),
        sa.Column("sourceMtimeMs", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=191), nullable=False),
        sa.Column("normalization", sa.String(length=191), nullable=False),
        sa.Column("relativePath", sa.String(length=1024), nullable=False),
        sa.Column("sizeBytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("unreadableResourceCount", sa.Integer(), nullable=False),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.CheckConstraint('"sizeBytes" > 0', name="PublicationRenderCache_sizeBytes_check"),
        sa.CheckConstraint(
            '"unreadableResourceCount" >= 0',
            name="PublicationRenderCache_unreadableResourceCount_check",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["fileId"], ["LibraryFile.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.PrimaryKeyConstraint("volumeId"),
    )


def upgrade() -> None:
    _deduplicate_bookmarks()
    with op.batch_alter_table("ReaderBookmark") as batch_op:
        batch_op.drop_constraint(
            "ReaderBookmark_user_volume_fingerprint_bookmark_key", type_="unique"
        )
        batch_op.drop_column("contentFingerprint")
        batch_op.create_unique_constraint(
            "ReaderBookmark_user_volume_bookmark_key",
            ["userId", "volumeId", "bookmarkId"],
        )
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.drop_column("contentFingerprint")
    with op.batch_alter_table("ReaderProgressMutation") as batch_op:
        batch_op.drop_column("contentFingerprint")
    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.drop_index("ImportTask_contentHash_idx")
        batch_op.drop_column("contentHash")
    with op.batch_alter_table("LibraryFile") as batch_op:
        batch_op.drop_index("LibraryFile_fingerprint_idx")
        batch_op.drop_index("LibraryFile_fullHash_idx")
        batch_op.drop_column("fingerprint")
        batch_op.drop_column("fullHash")
        batch_op.drop_column("hashStatus")
    with op.batch_alter_table("MetadataWritebackTarget") as batch_op:
        batch_op.drop_column("outputHash")
    with op.batch_alter_table("BookConversionTask") as batch_op:
        batch_op.drop_index("BookConversionTask_sourceHash_idx")
        batch_op.drop_column("sourceHash")
        batch_op.add_column(sa.Column("sourceKey", sa.String(191), nullable=True))
        batch_op.create_index("BookConversionTask_sourceKey_idx", ["sourceKey"], unique=False)
    op.drop_table("PublicationNavigationCache")
    op.drop_table("PublicationRenderCache")
    _create_navigation_cache()
    _create_render_cache()


def downgrade() -> None:
    op.drop_table("PublicationNavigationCache")
    op.drop_table("PublicationRenderCache")
    with op.batch_alter_table("MetadataWritebackTarget") as batch_op:
        batch_op.add_column(sa.Column("outputHash", sa.String(64), nullable=True))
    with op.batch_alter_table("BookConversionTask") as batch_op:
        batch_op.drop_index("BookConversionTask_sourceKey_idx")
        batch_op.drop_column("sourceKey")
        batch_op.add_column(sa.Column("sourceHash", sa.String(191), nullable=True))
        batch_op.create_index("BookConversionTask_sourceHash_idx", ["sourceHash"], unique=False)
    with op.batch_alter_table("LibraryFile") as batch_op:
        batch_op.add_column(sa.Column("hashStatus", sa.String(191), nullable=False, server_default="FAILED"))
        batch_op.add_column(sa.Column("fullHash", sa.String(191), nullable=True))
        batch_op.add_column(sa.Column("fingerprint", sa.Text(), nullable=True))
        batch_op.create_index("LibraryFile_fullHash_idx", ["fullHash"], unique=False)
        batch_op.create_index("LibraryFile_fingerprint_idx", ["fingerprint"], unique=False)
    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.add_column(sa.Column("contentHash", sa.String(191), nullable=True))
        batch_op.create_index("ImportTask_contentHash_idx", ["contentHash"], unique=False)
    with op.batch_alter_table("ReaderProgressMutation") as batch_op:
        batch_op.add_column(sa.Column("contentFingerprint", sa.String(191), nullable=False, server_default="legacy"))
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.add_column(sa.Column("contentFingerprint", sa.String(191), nullable=True))
    with op.batch_alter_table("ReaderBookmark") as batch_op:
        batch_op.drop_constraint("ReaderBookmark_user_volume_bookmark_key", type_="unique")
        batch_op.add_column(sa.Column("contentFingerprint", sa.String(191), nullable=False, server_default="legacy"))
        batch_op.create_unique_constraint(
            "ReaderBookmark_user_volume_fingerprint_bookmark_key",
            ["userId", "volumeId", "contentFingerprint", "bookmarkId"],
        )
