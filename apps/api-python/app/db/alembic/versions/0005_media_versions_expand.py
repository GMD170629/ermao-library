"""Expand the library schema for singleton media versions and volume resources.

Revision ID: 0005_media_versions_expand
Revises: 0004_schema_normalization
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0005_media_versions_expand"
down_revision: str | Sequence[str] | None = "0004_schema_normalization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _add_columns(table_name: str, columns: list[sa.Column[object]]) -> None:
    existing = _columns(table_name)
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table_name) as batch_op:
        for column in missing:
            batch_op.add_column(column)


def upgrade() -> None:
    tables = _tables()
    if "LibraryMediaVersion" not in tables:
        op.create_table(
            "LibraryMediaVersion",
            sa.Column("id", sa.String(length=191), nullable=False),
            sa.Column("workId", sa.String(length=191), nullable=False),
            sa.Column(
                "mediaKind",
                sa.String(length=191),
                server_default="EBOOK",
                nullable=False,
            ),
            sa.Column(
                "createdAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
            sa.ForeignKeyConstraint(
                ["workId"],
                ["LibraryWork.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "LibraryMediaVersion_workId_idx",
            "LibraryMediaVersion",
            ["workId"],
            unique=False,
        )
        op.create_index(
            "LibraryMediaVersion_mediaKind_idx",
            "LibraryMediaVersion",
            ["mediaKind"],
            unique=False,
        )

    _add_columns(
        "LibraryVolume",
        [
            sa.Column("mediaVersionId", sa.String(length=191), nullable=True),
            sa.Column("monitorFolderId", sa.String(length=191), nullable=True),
            sa.Column("origin", sa.String(length=191), nullable=True),
            sa.Column("format", sa.String(length=191), nullable=True),
            sa.Column("resourceKey", sa.String(length=191), nullable=True),
            sa.Column("sourceGroupKey", sa.Text(), nullable=True),
            sa.Column("derivedFromVolumeId", sa.String(length=191), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("language", sa.String(length=191), nullable=True),
            sa.Column("publisher", sa.Text(), nullable=True),
            sa.Column("publishedAt", TimestampMilliseconds(), nullable=True),
            sa.Column("identifier", sa.Text(), nullable=True),
            sa.Column("isbn", sa.String(length=191), nullable=True),
            sa.Column("importStatus", sa.String(length=191), nullable=True),
            sa.Column("importError", sa.Text(), nullable=True),
            sa.Column("sizeBytes", sa.Integer(), nullable=True),
            sa.Column("trackCount", sa.Integer(), nullable=True),
            sa.Column("narrator", sa.Text(), nullable=True),
            sa.Column("abridged", sa.Boolean(), nullable=True),
            sa.Column("coverStatus", sa.String(length=191), nullable=True),
            sa.Column("hidden", sa.Boolean(), nullable=True),
        ],
    )

    _add_columns(
        "LibraryMetadata",
        [sa.Column("volumeId", sa.String(length=191), nullable=True)],
    )
    _add_columns(
        "ReaderBookmark",
        [sa.Column("volumeId", sa.String(length=191), nullable=True)],
    )
    _add_columns(
        "OrganizeJob",
        [sa.Column("volumeId", sa.String(length=191), nullable=True)],
    )
    _add_columns(
        "MetadataLookupTask",
        [sa.Column("volumeId", sa.String(length=191), nullable=True)],
    )
    _add_columns(
        "BookConversionTask",
        [
            sa.Column("sourceVolumeId", sa.String(length=191), nullable=True),
            sa.Column("derivedVolumeId", sa.String(length=191), nullable=True),
            sa.Column("idempotencyKey", sa.String(length=191), nullable=True),
        ],
    )

    tables = _tables()
    if "LibraryVolumeFacet" not in tables:
        op.create_table(
            "LibraryVolumeFacet",
            sa.Column("facetId", sa.String(length=191), nullable=False),
            sa.Column("volumeId", sa.String(length=191), nullable=False),
            sa.Column(
                "createdAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["facetId"],
                ["LibraryFacet.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["volumeId"],
                ["LibraryVolume.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("facetId", "volumeId"),
        )
        op.create_index(
            "LibraryVolumeFacet_volumeId_idx",
            "LibraryVolumeFacet",
            ["volumeId"],
            unique=False,
        )

    if "UserMediaHistory" not in tables:
        op.create_table(
            "UserMediaHistory",
            sa.Column("id", sa.String(length=191), nullable=False),
            sa.Column("userId", sa.String(length=191), nullable=False),
            sa.Column("mediaVersionId", sa.String(length=191), nullable=False),
            sa.Column("lastVolumeId", sa.String(length=191), nullable=True),
            sa.Column(
                "createdAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
            sa.ForeignKeyConstraint(
                ["userId"], ["User.id"], ondelete="CASCADE", onupdate="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["mediaVersionId"],
                ["LibraryMediaVersion.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["lastVolumeId"],
                ["LibraryVolume.id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "UserMediaHistory_updatedAt_idx",
            "UserMediaHistory",
            ["updatedAt"],
            unique=False,
        )

    if "MediaVersionMigrationCheckpoint" not in tables:
        op.create_table(
            "MediaVersionMigrationCheckpoint",
            sa.Column("workId", sa.String(length=191), nullable=False),
            sa.Column(
                "completedAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("workId"),
        )

    if "MediaVersionMigrationEvent" not in tables:
        op.create_table(
            "MediaVersionMigrationEvent",
            sa.Column("id", sa.String(length=191), nullable=False),
            sa.Column("workId", sa.String(length=191), nullable=False),
            sa.Column("recordType", sa.String(length=64), nullable=False),
            sa.Column("recordId", sa.String(length=191), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("detailsJson", sa.Text(), nullable=False),
            sa.Column(
                "createdAt",
                TimestampMilliseconds(),
                server_default=sa.func.unixepoch() * 1000,
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "recordType",
                "recordId",
                "code",
                name="MediaVersionMigrationEvent_record_code_key",
            ),
        )


def downgrade() -> None:
    for table_name in (
        "MediaVersionMigrationEvent",
        "MediaVersionMigrationCheckpoint",
        "UserMediaHistory",
        "LibraryVolumeFacet",
    ):
        if table_name in _tables():
            op.drop_table(table_name)

    removable: dict[str, tuple[str, ...]] = {
        "BookConversionTask": (
            "idempotencyKey",
            "derivedVolumeId",
            "sourceVolumeId",
        ),
        "MetadataLookupTask": ("volumeId",),
        "OrganizeJob": ("volumeId",),
        "ReaderBookmark": ("volumeId",),
        "LibraryMetadata": ("volumeId",),
        "LibraryVolume": (
            "hidden",
            "coverStatus",
            "abridged",
            "narrator",
            "trackCount",
            "sizeBytes",
            "importError",
            "importStatus",
            "isbn",
            "identifier",
            "publishedAt",
            "publisher",
            "language",
            "description",
            "derivedFromVolumeId",
            "sourceGroupKey",
            "resourceKey",
            "format",
            "origin",
            "monitorFolderId",
            "mediaVersionId",
        ),
    }
    for table_name, names in removable.items():
        existing = _columns(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            for name in names:
                if name in existing:
                    batch_op.drop_column(name)
    if "LibraryMediaVersion" in _tables():
        op.drop_table("LibraryMediaVersion")
