"""Fresh-install library topology and ADR 0018 readable-resource overlay baseline.

Revision ID: 0001_library_topology_baseline
Revises: None

Single fresh-install baseline only. Prior development revisions
0002_version_covers and 0003_readable_resource_overlay_schema are not
supported for upgrade. Downgrade is not supported.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
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

# revision identifiers, used by Alembic.
revision: str = "0001_library_topology_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PATH_KEY_LENGTH = 67

_OVERLAY_TABLES: tuple[str, ...] = (
    "LibrarySourceNode",
    "LibrarySourceNodeMetadata",
    "LibrarySourceNodeInterpretation",
    "LibraryBook",
    "LibraryBookMetadata",
    "LibraryReadableResource",
    "LibraryReadableResourceMetadata",
    "LibraryResourceAsset",
    "LibraryResourceAssetMetadata",
    "LibraryImportTask",
)


def _timestamp_default() -> sa.ColumnElement[int]:
    return sa.func.unixepoch() * 1000


def _build_overlay_metadata() -> MetaData:
    """Frozen schema objects for this revision only."""

    meta = MetaData()
    Table("Library", meta, Column("id", String(191), primary_key=True))

    Table(
        "LibrarySourceNode",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("parentId", String(191), nullable=True),
        Column("parentPhysicalKind", String(32), nullable=True),
        Column("relativePath", Text(), nullable=False),
        Column("pathKey", String(_PATH_KEY_LENGTH), nullable=False),
        Column("name", Text(), nullable=False),
        Column("physicalKind", String(32), nullable=False),
        Column("observedSizeBytes", BigInteger(), nullable=True),
        Column("observedMtimeNs", BigInteger(), nullable=False),
        Column("observedAt", BigInteger(), nullable=False),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
        CheckConstraint(
            column("physicalKind").in_(
                ("REGULAR_FILE", "DIRECTORY", "SYMLINK", "OTHER")
            ),
            name="LibrarySourceNode_physicalKind_check",
        ),
        CheckConstraint(
            and_(
                func.length(column("pathKey")) == _PATH_KEY_LENGTH,
                func.substr(column("pathKey"), 1, 3) == "v1:",
            ),
            name="LibrarySourceNode_pathKey_format_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("parentId").is_(None),
                    column("parentPhysicalKind").is_(None),
                ),
                and_(
                    column("parentId").is_not(None),
                    column("parentPhysicalKind") == "DIRECTORY",
                ),
            ),
            name="LibrarySourceNode_parent_pair_check",
        ),
        CheckConstraint(
            or_(column("parentId").is_(None), column("parentId") != column("id")),
            name="LibrarySourceNode_no_self_parent_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("physicalKind") == "DIRECTORY",
                    column("observedSizeBytes").is_(None),
                ),
                and_(
                    column("physicalKind") != "DIRECTORY",
                    column("observedSizeBytes").is_not(None),
                    column("observedSizeBytes") >= 0,
                ),
            ),
            name="LibrarySourceNode_observedSizeBytes_check",
        ),
        UniqueConstraint(
            "libraryId", "pathKey", name="LibrarySourceNode_libraryId_pathKey_key"
        ),
        UniqueConstraint("id", "libraryId", name="LibrarySourceNode_id_libraryId_key"),
        UniqueConstraint(
            "id", "physicalKind", name="LibrarySourceNode_id_physicalKind_key"
        ),
        ForeignKeyConstraint(
            ["parentId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibrarySourceNode_parent_library",
        ),
        ForeignKeyConstraint(
            ["parentId", "parentPhysicalKind"],
            ["LibrarySourceNode.id", "LibrarySourceNode.physicalKind"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibrarySourceNode_parent_directory",
        ),
        Index("LibrarySourceNode_libraryId_parentId_idx", "libraryId", "parentId"),
        Index("LibrarySourceNode_libraryId_name_idx", "libraryId", "name"),
    )

    Table(
        "LibrarySourceNodeMetadata",
        meta,
        Column(
            "sourceNodeId",
            String(191),
            ForeignKey("LibrarySourceNode.id", ondelete="CASCADE", onupdate="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("title", Text(), nullable=True),
        Column("description", Text(), nullable=True),
        Column("coverPath", Text(), nullable=True),
        Column("coverStatus", String(32), nullable=False, server_default="PENDING"),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
    )

    Table(
        "LibrarySourceNodeInterpretation",
        meta,
        Column(
            "sourceNodeId",
            String(191),
            ForeignKey("LibrarySourceNode.id", ondelete="CASCADE", onupdate="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("result", String(32), nullable=False),
        Column("source", String(32), nullable=False),
        Column("adapterId", String(191), nullable=True),
        Column("adapterVersion", String(64), nullable=True),
        Column("reasonCode", String(64), nullable=True),
        Column("sampleRelativePaths", Text(), nullable=True),
        Column("sampleCount", Integer(), nullable=True),
        Column("maxEntriesVisited", Integer(), nullable=True),
        Column("maxDepth", Integer(), nullable=True),
        Column("timeBudgetMs", Integer(), nullable=True),
        Column("terminationReason", String(64), nullable=True),
        Column("recognizedAt", BigInteger(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
        CheckConstraint(
            column("result").in_(("NODE_ONLY", "RESOURCE")),
            name="LibrarySourceNodeInterpretation_result_check",
        ),
        CheckConstraint(
            column("source").in_(("AUTO", "USER")),
            name="LibrarySourceNodeInterpretation_source_check",
        ),
    )

    Table(
        "LibraryBook",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("sourceNodeId", String(191), nullable=False),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
        UniqueConstraint("sourceNodeId", name="LibraryBook_sourceNodeId_key"),
        UniqueConstraint("id", "libraryId", name="LibraryBook_id_libraryId_key"),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryBook_sourceNode_library",
        ),
        Index("LibraryBook_libraryId_idx", "libraryId"),
    )

    Table(
        "LibraryBookMetadata",
        meta,
        Column(
            "bookId",
            String(191),
            ForeignKey("LibraryBook.id", ondelete="CASCADE", onupdate="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("title", Text(), nullable=False),
        Column("normalizedTitle", Text(), nullable=False),
        Column("author", Text(), nullable=True),
        Column("normalizedAuthor", Text(), nullable=True),
        Column("description", Text(), nullable=True),
        Column("seriesName", Text(), nullable=True),
        Column("seriesIndex", Float(), nullable=True),
        Column("coverPath", Text(), nullable=True),
        Column("coverStatus", String(32), nullable=False, server_default="PENDING"),
        Column("metadataQuality", Integer(), nullable=False, server_default="0"),
        Column(
            "publicationStatus", String(32), nullable=False, server_default="UNKNOWN"
        ),
        Column(
            "trackingStatus", String(32), nullable=False, server_default="NOT_TRACKING"
        ),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
    )

    Table(
        "LibraryReadableResource",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("bookId", String(191), nullable=False),
        Column("sourceNodeId", String(191), nullable=False),
        Column("adapterId", String(191), nullable=False),
        Column("adapterVersion", String(64), nullable=False),
        Column("mediaKind", String(32), nullable=False),
        Column("format", String(32), nullable=False),
        Column(
            "enablementState", String(32), nullable=False, server_default="ENABLED"
        ),
        Column("importState", String(32), nullable=False, server_default="PENDING"),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
        CheckConstraint(
            column("enablementState").in_(("ENABLED", "DISABLED")),
            name="LibraryReadableResource_enablementState_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="LibraryReadableResource_importState_check",
        ),
        UniqueConstraint(
            "sourceNodeId", name="LibraryReadableResource_sourceNodeId_key"
        ),
        UniqueConstraint(
            "id", "libraryId", name="LibraryReadableResource_id_libraryId_key"
        ),
        ForeignKeyConstraint(
            ["bookId", "libraryId"],
            ["LibraryBook.id", "LibraryBook.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryReadableResource_book_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryReadableResource_sourceNode_library",
        ),
        Index("LibraryReadableResource_bookId_idx", "bookId"),
        Index("LibraryReadableResource_libraryId_idx", "libraryId"),
    )

    Table(
        "LibraryReadableResourceMetadata",
        meta,
        Column(
            "resourceId",
            String(191),
            ForeignKey(
                "LibraryReadableResource.id", ondelete="CASCADE", onupdate="CASCADE"
            ),
            primary_key=True,
            nullable=False,
        ),
        Column("title", Text(), nullable=False),
        Column("description", Text(), nullable=True),
        Column("language", String(64), nullable=True),
        Column("publisher", Text(), nullable=True),
        Column("publishedAt", BigInteger(), nullable=True),
        Column("identifier", Text(), nullable=True),
        Column("isbn", String(64), nullable=True),
        Column("pageCount", Integer(), nullable=True),
        Column("chapterCount", Integer(), nullable=True),
        Column("durationMs", Integer(), nullable=True),
        Column("trackCount", Integer(), nullable=True),
        Column("narrator", Text(), nullable=True),
        Column("abridged", Boolean(), nullable=True),
        Column("volumeIndex", Float(), nullable=True),
        Column("coverPath", Text(), nullable=True),
        Column("coverStatus", String(32), nullable=False, server_default="PENDING"),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
    )

    Table(
        "LibraryResourceAsset",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("resourceId", String(191), nullable=False),
        Column("sourceNodeId", String(191), nullable=False),
        Column(
            "sourceNodePhysicalKind",
            String(32),
            nullable=False,
            server_default="REGULAR_FILE",
        ),
        Column("role", String(32), nullable=False),
        Column("importState", String(32), nullable=False, server_default="PENDING"),
        Column("sequenceIndex", Integer(), nullable=True),
        Column("sortKey", Text(), nullable=True),
        Column("failureReason", Text(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
        CheckConstraint(
            column("role").in_(
                ("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")
            ),
            name="LibraryResourceAsset_role_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="LibraryResourceAsset_importState_check",
        ),
        CheckConstraint(
            column("sourceNodePhysicalKind") == "REGULAR_FILE",
            name="LibraryResourceAsset_sourceNodePhysicalKind_check",
        ),
        UniqueConstraint(
            "resourceId",
            "sourceNodeId",
            name="LibraryResourceAsset_resourceId_sourceNodeId_key",
        ),
        ForeignKeyConstraint(
            ["resourceId", "libraryId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryResourceAsset_resource_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryResourceAsset_sourceNode_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "sourceNodePhysicalKind"],
            ["LibrarySourceNode.id", "LibrarySourceNode.physicalKind"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryResourceAsset_sourceNode_file",
        ),
        Index(
            "LibraryResourceAsset_resourceId_importState_idx",
            "resourceId",
            "importState",
        ),
        Index("LibraryResourceAsset_sourceNodeId_idx", "sourceNodeId"),
    )

    Table(
        "LibraryResourceAssetMetadata",
        meta,
        Column(
            "assetId",
            String(191),
            ForeignKey("LibraryResourceAsset.id", ondelete="CASCADE", onupdate="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("mimeType", String(191), nullable=True),
        Column("durationMs", Integer(), nullable=True),
        Column("codec", String(64), nullable=True),
        Column("bitrate", Integer(), nullable=True),
        Column("sampleRate", Integer(), nullable=True),
        Column("channels", Integer(), nullable=True),
        Column("discNumber", Integer(), nullable=True),
        Column("trackNumber", Integer(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column(
            "updatedAt",
            BigInteger(),
            nullable=False,
        ),
    )

    Table(
        "LibraryImportTask",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column("kind", String(32), nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("resourceId", String(191), nullable=True),
        Column("sourceNodeId", String(191), nullable=True),
        Column("role", String(32), nullable=True),
        Column("state", String(32), nullable=False, server_default="QUEUED"),
        Column("errorSummary", Text(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("startedAt", BigInteger(), nullable=True),
        Column("finishedAt", BigInteger(), nullable=True),
        CheckConstraint(
            column("kind").in_(("SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_ASSET")),
            name="LibraryImportTask_kind_check",
        ),
        CheckConstraint(
            column("state").in_(("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")),
            name="LibraryImportTask_state_check",
        ),
        CheckConstraint(
            or_(
                column("role").is_(None),
                column("role").in_(
                    ("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")
                ),
            ),
            name="LibraryImportTask_role_check",
        ),
        CheckConstraint(
            or_(
                and_(
                    column("kind") == "SCAN_LIBRARY",
                    column("sourceNodeId").is_(None),
                    column("resourceId").is_(None),
                    column("role").is_(None),
                ),
                and_(
                    column("kind") == "CONTINUE_SOURCE",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_(None),
                    column("role").is_(None),
                ),
                and_(
                    column("kind") == "IMPORT_ASSET",
                    column("sourceNodeId").is_not(None),
                    column("resourceId").is_not(None),
                    column("role").is_not(None),
                ),
            ),
            name="LibraryImportTask_kind_shape_check",
        ),
        ForeignKeyConstraint(
            ["resourceId", "libraryId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportTask_resource_library",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportTask_sourceNode_library",
        ),
        Index(
            "LibraryImportTask_import_asset_key",
            "resourceId",
            "sourceNodeId",
            unique=True,
            sqlite_where=column("kind") == "IMPORT_ASSET",
        ),
        Index("LibraryImportTask_queued_createdAt_idx", "state", "createdAt"),
        Index("LibraryImportTask_libraryId_kind_idx", "libraryId", "kind", "state"),
    )

    return meta

def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "BookIdentityCache",
        sa.Column("logicalPath", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("volumeIndex", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("parserVersion", sa.Integer(), nullable=False),
        sa.Column("rawJson", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("logicalPath"),
    )
    with op.batch_alter_table("BookIdentityCache", schema=None) as batch_op:
        batch_op.create_index(
            "BookIdentityCache_parserVersion_idx", ["parserVersion"], unique=False
        )

    op.create_table(
        "DownloadTask",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("sourceId", sa.String(length=191), nullable=True),
        sa.Column("searchRecordId", sa.String(length=191), nullable=True),
        sa.Column("bookId", sa.String(length=191), nullable=True),
        sa.Column("type", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("displayName", sa.Text(), nullable=False),
        sa.Column("remoteRef", sa.Text(), nullable=True),
        sa.Column("savePath", sa.Text(), nullable=True),
        sa.Column("filePath", sa.Text(), nullable=True),
        sa.Column("errorMessage", sa.Text(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("DownloadTask", schema=None) as batch_op:
        batch_op.create_index("DownloadTask_bookId_idx", ["bookId"], unique=False)
        batch_op.create_index(
            "DownloadTask_searchRecordId_idx", ["searchRecordId"], unique=False
        )
        batch_op.create_index("DownloadTask_sourceId_idx", ["sourceId"], unique=False)
        batch_op.create_index(
            "DownloadTask_status_createdAt_idx", ["status", "createdAt"], unique=False
        )
        batch_op.create_index("DownloadTask_type_idx", ["type"], unique=False)

    op.create_table(
        "ExternalMetadataCache",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("provider", sa.String(length=191), nullable=False),
        sa.Column("queryKey", sa.Text(), nullable=False),
        sa.Column("rawJson", sa.Text(), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ExternalMetadataCache", schema=None) as batch_op:
        batch_op.create_index(
            "ExternalMetadataCache_provider_expiresAt_idx",
            ["provider", "expiresAt"],
            unique=False,
        )
        batch_op.create_index(
            "ExternalMetadataCache_provider_queryKey_key",
            ["provider", "queryKey"],
            unique=True,
        )

    op.create_table(
        "Library",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("rootPath", sa.String(length=191), nullable=False),
        sa.Column("organizationMode", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("ignorePatterns", sa.Text(), nullable=True),
        sa.Column("ignoreHidden", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "minFileSizeBytes", sa.Integer(), server_default="10240", nullable=False
        ),
        sa.Column("description", sa.String(length=191), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "organizationMode IN ('FLAT', 'VOLUMES', 'AUDIOBOOK')",
            name="Library_organizationMode_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rootPath"),
    )
    op.create_table(
        "LibraryFacet",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("kind", sa.String(length=191), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalizedName", sa.Text(), nullable=False),
        sa.Column("aliases", sa.Text(), server_default="[]", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "normalizedName"),
    )
    with op.batch_alter_table("LibraryFacet", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryFacet_kind_name_idx", ["kind", "name"], unique=False
        )

    op.create_table(
        "MetadataOpfQueueState",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("pendingTargets", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "pendingPreparations", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            '"pendingPreparations" >= 0',
            name="MetadataOpfQueueState_pendingPreparations_nonnegative",
        ),
        sa.CheckConstraint(
            '"pendingTargets" >= 0',
            name="MetadataOpfQueueState_pendingTargets_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "MetadataProviderPipeline",
        sa.Column("mediaKind", sa.String(length=191), nullable=False),
        sa.Column("providerId", sa.String(length=191), nullable=False),
        sa.Column("included", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("position", sa.Integer(), server_default="100", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("mediaKind", "providerId"),
    )
    with op.batch_alter_table("MetadataProviderPipeline", schema=None) as batch_op:
        batch_op.create_index(
            "MetadataProviderPipeline_mediaKind_position_idx",
            ["mediaKind", "included", "position"],
            unique=False,
        )

    op.create_table(
        "OrganizePolicy",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "scheduleMode",
            sa.String(length=191),
            server_default="MANUAL",
            nullable=False,
        ),
        sa.Column("intervalMinutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("autoRunOnNew", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("autoRunOnNewSince", sa.BigInteger(), nullable=True),
        sa.Column("rulesJson", sa.Text(), server_default="{}", nullable=False),
        sa.Column(
            "writeMetadataToFiles", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.Column(
            "preferLocalMetadata", sa.Boolean(), server_default="1", nullable=False
        ),
        sa.Column(
            "localMetadataPriorityJson",
            sa.Text(),
            server_default='["SIDECAR_OPF","EMBEDDED","PATH"]',
            nullable=False,
        ),
        sa.Column("lastScheduledAt", sa.BigInteger(), nullable=True),
        sa.Column("nextRunAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "OrganizeRun",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("trigger", sa.String(length=191), nullable=False),
        sa.Column("scopeJson", sa.Text(), server_default="{}", nullable=False),
        sa.Column("dedupeKey", sa.String(length=191), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="QUEUED", nullable=False
        ),
        sa.Column("queuedCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completedCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reviewCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failedCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupeKey"),
    )
    with op.batch_alter_table("OrganizeRun", schema=None) as batch_op:
        batch_op.create_index(
            "OrganizeRun_status_createdAt_idx", ["status", "createdAt"], unique=False
        )

    op.create_table(
        "QueueControlOperation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("queueName", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actorUserId", sa.String(length=191), nullable=False),
        sa.Column("messageCode", sa.String(length=191), nullable=True),
        sa.Column("requestedAt", sa.BigInteger(), nullable=False),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("QueueControlOperation", schema=None) as batch_op:
        batch_op.create_index(
            "QueueControlOperation_queue_status_idx",
            ["queueName", "status", "requestedAt"],
            unique=False,
        )

    op.create_table(
        "QueueRuntimeState",
        sa.Column("queueName", sa.String(length=64), nullable=False),
        sa.Column("instanceId", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pollIntervalSeconds", sa.Float(), nullable=False),
        sa.Column("startedAt", sa.BigInteger(), nullable=False),
        sa.Column("heartbeatAt", sa.BigInteger(), nullable=False),
        sa.Column("lastProcessedAt", sa.BigInteger(), nullable=True),
        sa.Column("lastError", sa.Text(), nullable=True),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("queueName"),
    )
    op.create_table(
        "Source",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("kind", sa.String(length=191), nullable=False),
        sa.Column("providerType", sa.String(length=191), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("config", sa.Text(), nullable=True),
        sa.Column("credentialsKey", sa.String(length=191), nullable=True),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("rateLimit", sa.Text(), nullable=True),
        sa.Column("lastTestAt", sa.BigInteger(), nullable=True),
        sa.Column("lastTestStatus", sa.String(length=191), nullable=True),
        sa.Column("lastError", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("Source", schema=None) as batch_op:
        batch_op.create_index("Source_enabled_idx", ["enabled"], unique=False)
        batch_op.create_index("Source_kind_idx", ["kind"], unique=False)
        batch_op.create_index("Source_priority_idx", ["priority"], unique=False)
        batch_op.create_index("Source_providerType_idx", ["providerType"], unique=False)

    op.create_table(
        "SystemEvent",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column(
            "level", sa.String(length=191), server_default="info", nullable=False
        ),
        sa.Column("source", sa.String(length=191), nullable=False),
        sa.Column(
            "actorType", sa.String(length=191), server_default="system", nullable=False
        ),
        sa.Column("actorId", sa.String(length=191), nullable=True),
        sa.Column("action", sa.String(length=191), nullable=False),
        sa.Column("targetType", sa.String(length=191), nullable=True),
        sa.Column("targetId", sa.String(length=191), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("SystemEvent", schema=None) as batch_op:
        batch_op.create_index(
            "SystemEvent_action_createdAt_idx", ["action", "createdAt"], unique=False
        )
        batch_op.create_index(
            "SystemEvent_actorType_createdAt_idx",
            ["actorType", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "SystemEvent_createdAt_id_idx", ["createdAt", "id"], unique=False
        )
        batch_op.create_index("SystemEvent_createdAt_idx", ["createdAt"], unique=False)
        batch_op.create_index(
            "SystemEvent_level_createdAt_idx", ["level", "createdAt"], unique=False
        )
        batch_op.create_index(
            "SystemEvent_source_createdAt_idx", ["source", "createdAt"], unique=False
        )
        batch_op.create_index(
            "SystemEvent_targetType_createdAt_id_idx",
            ["targetType", "createdAt", "id"],
            unique=False,
        )
        batch_op.create_index(
            "SystemEvent_targetType_targetId_idx",
            ["targetType", "targetId"],
            unique=False,
        )

    op.create_table(
        "SystemHealthRun",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("actorUserId", sa.String(length=191), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="running", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("startedAt", sa.BigInteger(), nullable=False),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "SystemSetting",
        sa.Column("key", sa.String(length=191), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "User",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("email", sa.String(length=191), nullable=False),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("passwordHash", sa.String(length=191), nullable=False),
        sa.Column("avatarPath", sa.String(length=500), nullable=True),
        sa.Column(
            "role", sa.String(length=191), server_default="member", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=32), server_default="active", nullable=False
        ),
        sa.Column("canManageSystem", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "canViewManualImports", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.Column("authzVersion", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "ImportScanJob",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("libraryId", sa.String(length=191), nullable=True),
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
        sa.Column("candidatesFound", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queuedCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skippedCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errorCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "ignoredReasonCounts", sa.JSON(), server_default="{}", nullable=False
        ),
        sa.Column("errorSamples", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("restartCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("heartbeatAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actorUserId"], ["User.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["libraryId"], ["Library.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ImportScanJob", schema=None) as batch_op:
        batch_op.create_index(
            "ImportScanJob_libraryId_status_createdAt_idx",
            ["libraryId", "status", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "ImportScanJob_status_updatedAt_idx", ["status", "updatedAt"], unique=False
        )

    op.create_table(
        "LibraryOperation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=True),
        sa.Column("action", sa.String(length=191), nullable=False),
        sa.Column(
            "status", sa.String(length=191), server_default="COMPLETED", nullable=False
        ),
        sa.Column("targetType", sa.String(length=191), nullable=True),
        sa.Column("targetId", sa.String(length=191), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payloadJson", sa.Text(), server_default="{}", nullable=False),
        sa.Column("inverseJson", sa.Text(), server_default="{}", nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=True),
        sa.Column("undoneAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("LibraryOperation", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryOperation_action_createdAt_idx",
            ["action", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryOperation_status_expiresAt_idx",
            ["status", "expiresAt"],
            unique=False,
        )

    op.create_table(
        "LibraryWork",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("libraryId", sa.String(length=191), nullable=False),
        sa.Column(
            "origin", sa.String(length=191), server_default="SCAN", nullable=False
        ),
        sa.Column("sourceKey", sa.String(length=191), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalizedTitle", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("normalizedAuthor", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "publicationStatus",
            sa.String(length=191),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column(
            "trackingStatus",
            sa.String(length=191),
            server_default="NOT_TRACKING",
            nullable=False,
        ),
        sa.Column("localLatestVolume", sa.Float(), nullable=True),
        sa.Column("localLatestChapter", sa.Float(), nullable=True),
        sa.Column("localLatestTitle", sa.Text(), nullable=True),
        sa.Column("localLatestAt", sa.BigInteger(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("seriesName", sa.Text(), nullable=True),
        sa.Column("seriesIndex", sa.Float(), nullable=True),
        sa.Column("metadataQuality", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "organizeStatus",
            sa.String(length=191),
            server_default="REVIEWING",
            nullable=False,
        ),
        sa.Column("coverPath", sa.Text(), nullable=True),
        sa.Column(
            "coverStatus",
            sa.String(length=191),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("hidden", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("organized", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["libraryId"], ["Library.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "libraryId", "sourceKey", name="LibraryWork_libraryId_sourceKey_key"
        ),
    )
    with op.batch_alter_table("LibraryWork", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryWork_createdAt_id_idx", ["createdAt", "id"], unique=False
        )
        batch_op.create_index(
            "LibraryWork_hidden_createdAt_id_idx",
            ["hidden", "createdAt", "id"],
            unique=False,
        )
        batch_op.create_index("LibraryWork_hidden_idx", ["hidden"], unique=False)
        batch_op.create_index(
            "LibraryWork_hidden_normalizedTitle_normalizedAuthor_id_idx",
            ["hidden", "normalizedTitle", "normalizedAuthor", "id"],
            unique=False,
        )
        batch_op.create_index("LibraryWork_libraryId_idx", ["libraryId"], unique=False)
        batch_op.create_index(
            "LibraryWork_normalizedAuthor_idx", ["normalizedAuthor"], unique=False
        )
        batch_op.create_index(
            "LibraryWork_normalizedTitle_idx", ["normalizedTitle"], unique=False
        )
        batch_op.create_index(
            "LibraryWork_organizeStatus_idx", ["organizeStatus"], unique=False
        )
        batch_op.create_index("LibraryWork_organized_idx", ["organized"], unique=False)
        batch_op.create_index(
            "LibraryWork_publicationStatus_idx", ["publicationStatus"], unique=False
        )
        batch_op.create_index(
            "LibraryWork_seriesName_idx", ["seriesName"], unique=False
        )
        batch_op.create_index("LibraryWork_sourceKey_idx", ["sourceKey"], unique=False)
        batch_op.create_index("LibraryWork_title_idx", ["title"], unique=False)
        batch_op.create_index(
            "LibraryWork_trackingStatus_idx", ["trackingStatus"], unique=False
        )

    op.create_table(
        "PasswordResetToken",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("tokenHash", sa.String(length=64), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=False),
        sa.Column("usedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tokenHash"),
    )
    with op.batch_alter_table("PasswordResetToken", schema=None) as batch_op:
        batch_op.create_index(
            "PasswordResetToken_expiresAt_idx", ["expiresAt"], unique=False
        )
        batch_op.create_index(
            "PasswordResetToken_userId_createdAt_idx",
            ["userId", "createdAt"],
            unique=False,
        )

    op.create_table(
        "ReaderPreference",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("readerType", sa.String(length=191), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId", "readerType", name="ReaderPreference_userId_readerType_key"
        ),
    )
    with op.batch_alter_table("ReaderPreference", schema=None) as batch_op:
        batch_op.create_index("ReaderPreference_userId_idx", ["userId"], unique=False)

    op.create_table(
        "Session",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("tokenHash", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tokenHash"),
    )
    op.create_table(
        "Shelf",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("ownerUserId", sa.String(length=191), nullable=True),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "kind", sa.String(length=191), server_default="STATIC", nullable=False
        ),
        sa.Column("rulesJson", sa.Text(), server_default="{}", nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ownerUserId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("Shelf", schema=None) as batch_op:
        batch_op.create_index(
            "Shelf_kind_updatedAt_idx", ["kind", "updatedAt"], unique=False
        )
        batch_op.create_index(
            "Shelf_ownerUserId_updatedAt_idx",
            ["ownerUserId", "updatedAt"],
            unique=False,
        )
        batch_op.create_index("Shelf_updatedAt_idx", ["updatedAt"], unique=False)

    op.create_table(
        "SourceSearchRecord",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("sourceId", sa.String(length=191), nullable=False),
        sa.Column("providerType", sa.String(length=191), nullable=False),
        sa.Column("externalId", sa.String(length=191), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("coverUrl", sa.Text(), nullable=True),
        sa.Column("externalUrl", sa.Text(), nullable=True),
        sa.Column("format", sa.String(length=191), nullable=True),
        sa.Column("size", sa.String(length=191), nullable=True),
        sa.Column("language", sa.String(length=191), nullable=True),
        sa.Column("publishedAt", sa.String(length=191), nullable=True),
        sa.Column(
            "downloadAvailable", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.Column("downloadMeta", sa.Text(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="new", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sourceId"], ["Source.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sourceId", "externalId", name="SourceSearchRecord_sourceId_externalId_key"
        ),
    )
    with op.batch_alter_table("SourceSearchRecord", schema=None) as batch_op:
        batch_op.create_index(
            "SourceSearchRecord_createdAt_idx", ["createdAt"], unique=False
        )
        batch_op.create_index(
            "SourceSearchRecord_providerType_idx", ["providerType"], unique=False
        )
        batch_op.create_index(
            "SourceSearchRecord_sourceId_idx", ["sourceId"], unique=False
        )
        batch_op.create_index("SourceSearchRecord_status_idx", ["status"], unique=False)
        batch_op.create_index("SourceSearchRecord_title_idx", ["title"], unique=False)

    op.create_table(
        "UserLibraryAccess",
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("libraryId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["libraryId"], ["Library.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("userId", "libraryId"),
    )
    with op.batch_alter_table("UserLibraryAccess", schema=None) as batch_op:
        batch_op.create_index(
            "UserLibraryAccess_library_idx", ["libraryId"], unique=False
        )

    op.create_table(
        "UserPreference",
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("key", sa.String(length=191), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("userId", "key"),
    )
    with op.batch_alter_table("UserPreference", schema=None) as batch_op:
        batch_op.create_index("UserPreference_userId_idx", ["userId"], unique=False)

    op.create_table(
        "LibraryVersion",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("sourceKey", sa.String(length=191), nullable=False),
        sa.Column("sourceName", sa.Text(), nullable=True),
        sa.Column("coverPath", sa.Text(), nullable=True),
        sa.Column(
            "coverStatus",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workId", "sourceKey", name="LibraryVersion_workId_sourceKey_key"
        ),
    )
    with op.batch_alter_table("LibraryVersion", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryVersion_sourceKey_idx", ["sourceKey"], unique=False
        )
        batch_op.create_index("LibraryVersion_workId_idx", ["workId"], unique=False)

    op.create_table(
        "LibraryWorkFacet",
        sa.Column("facetId", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("sortOrder", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["facetId"], ["LibraryFacet.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("facetId", "workId"),
    )
    with op.batch_alter_table("LibraryWorkFacet", schema=None) as batch_op:
        batch_op.create_index("LibraryWorkFacet_workId_idx", ["workId"], unique=False)

    op.create_table(
        "ReaderBookPreference",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("schemaVersion", sa.Integer(), server_default="3", nullable=False),
        sa.Column("preferences", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId", "workId", name="ReaderBookPreference_userId_workId_key"
        ),
    )
    with op.batch_alter_table("ReaderBookPreference", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ReaderBookPreference_userId"), ["userId"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ReaderBookPreference_workId"), ["workId"], unique=False
        )

    op.create_table(
        "ReaderProgressCursor",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("clientId", sa.String(length=191), nullable=False),
        sa.Column("highWater", sa.BigInteger(), server_default="-1", nullable=False),
        sa.Column("lastMutationId", sa.String(length=191), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "workId",
            "clientId",
            name="ReaderProgressCursor_userId_workId_clientId_key",
        ),
    )
    with op.batch_alter_table("ReaderProgressCursor", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ReaderProgressCursor_userId"), ["userId"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ReaderProgressCursor_workId"), ["workId"], unique=False
        )

    op.create_table(
        "ShelfCollectionMembership",
        sa.Column("collectionId", sa.String(length=191), nullable=False),
        sa.Column("shelfId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.CheckConstraint(
            '"collectionId" != "shelfId"',
            name="ShelfCollectionMembership_distinct_shelves_check",
        ),
        sa.ForeignKeyConstraint(
            ["collectionId"], ["Shelf.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["shelfId"], ["Shelf.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("collectionId", "shelfId"),
    )
    with op.batch_alter_table("ShelfCollectionMembership", schema=None) as batch_op:
        batch_op.create_index(
            "ShelfCollectionMembership_shelfId_createdAt_idx",
            ["shelfId", "createdAt"],
            unique=False,
        )

    op.create_table(
        "ShelfWork",
        sa.Column("shelfId", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shelfId"], ["Shelf.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("shelfId", "workId"),
    )
    with op.batch_alter_table("ShelfWork", schema=None) as batch_op:
        batch_op.create_index(
            "ShelfWork_shelfId_createdAt_idx", ["shelfId", "createdAt"], unique=False
        )
        batch_op.create_index("ShelfWork_workId_idx", ["workId"], unique=False)

    op.create_table(
        "WorkDetailPreference",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("selectedTab", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("WorkDetailPreference", schema=None) as batch_op:
        batch_op.create_index(
            "WorkDetailPreference_user_work_key", ["userId", "workId"], unique=True
        )

    op.create_table(
        "LibraryVolume",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("versionId", sa.String(length=191), nullable=False),
        sa.Column(
            "origin", sa.String(length=191), server_default="SCAN", nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("volumeIndex", sa.Float(), nullable=True),
        sa.Column("sortOrder", sa.Integer(), server_default="0", nullable=False),
        sa.Column("format", sa.String(length=191), nullable=False),
        sa.Column(
            "classificationSource",
            sa.String(length=32),
            server_default="AUTO",
            nullable=False,
        ),
        sa.Column(
            "classificationReason",
            sa.String(length=64),
            server_default="FORMAT_DEFAULT",
            nullable=False,
        ),
        sa.Column("suggestedMediaKind", sa.String(length=32), nullable=True),
        sa.Column("resourceKey", sa.String(length=191), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=191), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("publishedAt", sa.BigInteger(), nullable=True),
        sa.Column("identifier", sa.Text(), nullable=True),
        sa.Column("isbn", sa.String(length=191), nullable=True),
        sa.Column(
            "importStatus",
            sa.String(length=191),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("importError", sa.Text(), nullable=True),
        sa.Column("sizeBytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pageCount", sa.Integer(), nullable=True),
        sa.Column("chapterCount", sa.Integer(), nullable=True),
        sa.Column("durationMs", sa.Integer(), nullable=True),
        sa.Column("trackCount", sa.Integer(), nullable=True),
        sa.Column("narrator", sa.Text(), nullable=True),
        sa.Column("abridged", sa.Boolean(), nullable=True),
        sa.Column("coverPath", sa.Text(), nullable=True),
        sa.Column(
            "coverStatus",
            sa.String(length=191),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("hidden", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["versionId"], ["LibraryVersion.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "versionId", "resourceKey", name="LibraryVolume_versionId_resourceKey_key"
        ),
    )
    with op.batch_alter_table("LibraryVolume", schema=None) as batch_op:
        batch_op.create_index("LibraryVolume_format_idx", ["format"], unique=False)
        batch_op.create_index(
            "LibraryVolume_identifier_idx", ["identifier"], unique=False
        )
        batch_op.create_index("LibraryVolume_isbn_idx", ["isbn"], unique=False)
        batch_op.create_index(
            "LibraryVolume_resourceKey_idx", ["resourceKey"], unique=False
        )
        batch_op.create_index(
            "LibraryVolume_versionId_hidden_idx", ["versionId", "hidden"], unique=False
        )
        batch_op.create_index(
            "LibraryVolume_versionId_sortOrder_idx",
            ["versionId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryVolume_versionId_volumeIndex_idx",
            ["versionId", "volumeIndex"],
            unique=False,
        )

    op.create_table(
        "ImportTask",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("libraryId", sa.String(length=191), nullable=True),
        sa.Column(
            "mediaKindPolicy",
            sa.String(length=32),
            server_default="MIXED",
            nullable=False,
        ),
        sa.Column("workId", sa.String(length=191), nullable=True),
        sa.Column("volumeId", sa.String(length=191), nullable=True),
        sa.Column("origin", sa.String(length=191), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("originalName", sa.Text(), nullable=True),
        sa.Column("requestedTitle", sa.Text(), nullable=True),
        sa.Column("requestedAuthor", sa.Text(), nullable=True),
        sa.Column("recognizedMetadata", sa.JSON(), nullable=True),
        sa.Column("sourcePath", sa.Text(), nullable=False),
        sa.Column("sourceKey", sa.String(length=64), nullable=True),
        sa.Column(
            "taskKind", sa.String(length=191), server_default="FILE", nullable=False
        ),
        sa.Column("bundleKey", sa.String(length=191), nullable=True),
        sa.Column("assetCount", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "processedAssetCount", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("duration", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column("errorCode", sa.String(length=191), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("leaseOwner", sa.String(length=191), nullable=True),
        sa.Column("leaseExpiresAt", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["libraryId"], ["Library.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ImportTask", schema=None) as batch_op:
        batch_op.create_index(
            "ImportTask_createdAt_id_idx", ["createdAt", "id"], unique=False
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
        batch_op.create_index(
            "ImportTask_libraryId_status_idx", ["libraryId", "status"], unique=False
        )
        batch_op.create_index(
            "ImportTask_sourceKey_status_createdAt_idx",
            ["sourceKey", "status", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "ImportTask_status_createdAt_idx", ["status", "createdAt"], unique=False
        )
        batch_op.create_index(
            "ImportTask_status_leaseExpiresAt_idx",
            ["status", "leaseExpiresAt"],
            unique=False,
        )
        batch_op.create_index("ImportTask_volumeId_idx", ["volumeId"], unique=False)
        batch_op.create_index("ImportTask_workId_idx", ["workId"], unique=False)

    op.create_table(
        "LibraryFile",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("pathKey", sa.String(length=64), nullable=True),
        sa.Column("filePathHash", sa.String(length=191), nullable=True),
        sa.Column("mtimeMs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kind", sa.String(length=191), nullable=False),
        sa.Column("mimeType", sa.String(length=191), nullable=False),
        sa.Column("sizeBytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("durationMs", sa.Integer(), nullable=True),
        sa.Column("codec", sa.String(length=191), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("sampleRate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("discNumber", sa.Integer(), nullable=True),
        sa.Column("trackNumber", sa.Integer(), nullable=True),
        sa.Column("sortOrder", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("LibraryFile", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryFile_filePathHash_key", ["filePathHash"], unique=True
        )
        batch_op.create_index("LibraryFile_pathKey_idx", ["pathKey"], unique=False)
        batch_op.create_index("LibraryFile_path_key", ["path"], unique=True)
        batch_op.create_index(
            "LibraryFile_sizeBytes_mtimeMs_idx", ["sizeBytes", "mtimeMs"], unique=False
        )
        batch_op.create_index(
            "LibraryFile_volumeId_sortOrder_idx",
            ["volumeId", "sortOrder"],
            unique=False,
        )

    op.create_table(
        "LibraryMetadata",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("source", sa.String(length=191), nullable=False),
        sa.Column("rawJson", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("LibraryMetadata", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryMetadata_volumeId_idx", ["volumeId"], unique=False
        )

    op.create_table(
        "LibraryReadingProgress",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("readerType", sa.String(length=191), nullable=False),
        sa.Column("position", sa.Text(), server_default="0", nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("extra", sa.Text(), nullable=False),
        sa.Column("schemaVersion", sa.Integer(), server_default="3", nullable=False),
        sa.Column("locationType", sa.String(length=191), nullable=True),
        sa.Column("locationJson", sa.Text(), nullable=True),
        sa.Column("mutationId", sa.String(length=191), nullable=True),
        sa.Column("clientId", sa.String(length=191), nullable=True),
        sa.Column("clientSequence", sa.Integer(), nullable=True),
        sa.Column(
            "progressedAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column(
            "sourceProtocol",
            sa.String(length=32),
            server_default="SHUKU_WEB",
            nullable=False,
        ),
        sa.Column("sourceDeviceName", sa.String(length=191), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("LibraryReadingProgress", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryReadingProgress_clientId_clientSequence_idx",
            ["clientId", "clientSequence"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryReadingProgress_userId_updatedAt_volumeId_idx",
            ["userId", "updatedAt", "volumeId"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryReadingProgress_userId_volumeId_key",
            ["userId", "volumeId"],
            unique=True,
        )
        batch_op.create_index(
            "LibraryReadingProgress_volumeId_idx", ["volumeId"], unique=False
        )

    op.create_table(
        "LibraryVolumeFacet",
        sa.Column("facetId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["facetId"], ["LibraryFacet.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("facetId", "volumeId"),
    )
    with op.batch_alter_table("LibraryVolumeFacet", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryVolumeFacet_volumeId_idx", ["volumeId"], unique=False
        )

    op.create_table(
        "ReaderBookmark",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("bookmarkId", sa.Text(), nullable=False),
        sa.Column("locationJson", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("bookmarkCreatedAt", sa.String(length=64), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "volumeId",
            "bookmarkId",
            name="ReaderBookmark_user_volume_bookmark_key",
        ),
    )
    with op.batch_alter_table("ReaderBookmark", schema=None) as batch_op:
        batch_op.create_index(
            "ReaderBookmark_user_volume_idx", ["userId", "volumeId"], unique=False
        )

    op.create_table(
        "ReaderProgressMutation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("mutationId", sa.String(length=36), nullable=False),
        sa.Column("clientId", sa.String(length=256), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("locatorJson", sa.Text(), nullable=False),
        sa.Column("displayPercent", sa.Float(), nullable=False),
        sa.Column("capturedAt", sa.BigInteger(), nullable=False),
        sa.Column("receivedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "volumeId",
            "mutationId",
            name="ReaderProgressMutation_userId_volumeId_mutationId_key",
        ),
    )
    with op.batch_alter_table("ReaderProgressMutation", schema=None) as batch_op:
        batch_op.create_index(
            "ReaderProgressMutation_userId_volumeId_revision_idx",
            ["userId", "volumeId", "revision"],
            unique=False,
        )

    op.create_table(
        "ImportAsset",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("importTaskId", sa.String(length=191), nullable=False),
        sa.Column("sourcePath", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("sortOrder", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fileId", sa.String(length=191), nullable=True),
        sa.Column("errorCode", sa.String(length=191), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fileId"], ["LibraryFile.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["importTaskId"], ["ImportTask.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "importTaskId", "sourcePath", name="ImportAsset_importTaskId_sourcePath_key"
        ),
    )
    with op.batch_alter_table("ImportAsset", schema=None) as batch_op:
        batch_op.create_index(
            "ImportAsset_importTaskId_sortOrder_idx",
            ["importTaskId", "sortOrder"],
            unique=False,
        )

    op.create_table(
        "ImportLog",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("importTaskId", sa.String(length=191), nullable=False),
        sa.Column(
            "level", sa.String(length=191), server_default="info", nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["importTaskId"], ["ImportTask.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ImportLog", schema=None) as batch_op:
        batch_op.create_index(
            "ImportLog_importTaskId_createdAt_idx",
            ["importTaskId", "createdAt"],
            unique=False,
        )

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
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("leaseOwner", sa.String(length=191), nullable=True),
        sa.Column("leaseExpiresAt", sa.BigInteger(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "(kind = 'SCAN_DIRECTORY' AND scanJobId IS NOT NULL AND importTaskId IS NULL) OR (kind = 'IMPORT_SOURCE' AND importTaskId IS NOT NULL AND scanJobId IS NULL)",
            name="ImportWorkItem_target_check",
        ),
        sa.ForeignKeyConstraint(
            ["importTaskId"], ["ImportTask.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scanJobId"], ["ImportScanJob.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupeKey", name="ImportWorkItem_dedupeKey_key"),
        sa.UniqueConstraint("importTaskId", name="ImportWorkItem_importTaskId_key"),
        sa.UniqueConstraint("scanJobId", name="ImportWorkItem_scanJobId_key"),
    )
    with op.batch_alter_table("ImportWorkItem", schema=None) as batch_op:
        batch_op.create_index(
            "ImportWorkItem_kind_status_idx", ["kind", "status"], unique=False
        )
        batch_op.create_index(
            "ImportWorkItem_leaseExpiresAt_idx", ["leaseExpiresAt"], unique=False
        )
        batch_op.create_index(
            "ImportWorkItem_status_availableAt_priority_createdAt_idx",
            ["status", "availableAt", "priority", "createdAt"],
            unique=False,
        )

    op.create_table(
        "KindleSendTask",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=True),
        sa.Column("workId", sa.String(length=191), nullable=True),
        sa.Column("volumeId", sa.String(length=191), nullable=True),
        sa.Column("fileId", sa.String(length=191), nullable=True),
        sa.Column("bookTitle", sa.Text(), nullable=False),
        sa.Column("volumeTitle", sa.Text(), nullable=True),
        sa.Column("fileName", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=191), nullable=False),
        sa.Column("mimeType", sa.String(length=191), nullable=False),
        sa.Column("sizeBytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("senderEmail", sa.String(length=191), nullable=True),
        sa.Column("recipientEmail", sa.String(length=191), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("smtpHost", sa.String(length=191), nullable=True),
        sa.Column("smtpPort", sa.Integer(), nullable=True),
        sa.Column("smtpSecurity", sa.String(length=191), nullable=True),
        sa.Column("smtpUsername", sa.String(length=191), nullable=True),
        sa.Column("messageId", sa.String(length=191), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="queued", nullable=False
        ),
        sa.Column("attemptCount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("nextAttemptAt", sa.BigInteger(), nullable=True),
        sa.Column("errorMessage", sa.Text(), nullable=True),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("sentAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fileId"], ["LibraryFile.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("KindleSendTask", schema=None) as batch_op:
        batch_op.create_index(
            "KindleSendTask_active_file_recipient_key",
            ["fileId", "recipientEmail"],
            unique=True,
            sqlite_where=sa.column("status", sa.String()).in_(("queued", "sending")),
        )
        batch_op.create_index(
            "KindleSendTask_status_nextAttemptAt_createdAt_idx",
            ["status", "nextAttemptAt", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "KindleSendTask_userId_createdAt_idx", ["userId", "createdAt"], unique=False
        )
        batch_op.create_index(
            "KindleSendTask_workId_createdAt_idx", ["workId", "createdAt"], unique=False
        )

    op.create_table(
        "LibraryReadingUnit",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("fileId", sa.String(length=191), nullable=True),
        sa.Column("unitType", sa.String(length=191), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("href", sa.Text(), nullable=False),
        sa.Column("mediaType", sa.String(length=191), nullable=True),
        sa.Column("sortOrder", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("startMs", sa.Integer(), nullable=True),
        sa.Column("endMs", sa.Integer(), nullable=True),
        sa.Column("durationMs", sa.Integer(), nullable=True),
        sa.Column("metadataJson", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fileId"], ["LibraryFile.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("LibraryReadingUnit", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryReadingUnit_fileId_sortOrder_idx",
            ["fileId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryReadingUnit_volumeId_sortOrder_idx",
            ["volumeId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryReadingUnit_volumeId_unitType_sortOrder_key",
            ["volumeId", "unitType", "sortOrder"],
            unique=True,
        )

    op.create_table(
        "OrganizeJob",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("runId", sa.String(length=191), nullable=True),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=True),
        sa.Column("versionId", sa.String(length=191), nullable=True),
        sa.Column("importTaskId", sa.String(length=191), nullable=True),
        sa.Column("trigger", sa.String(length=191), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="REVIEWING", nullable=False
        ),
        sa.Column("issueCodes", sa.Text(), nullable=False),
        sa.Column("reasonCodes", sa.Text(), server_default="[]", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["importTaskId"], ["ImportTask.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["runId"], ["OrganizeRun.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["versionId"],
            ["LibraryVersion.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("OrganizeJob", schema=None) as batch_op:
        batch_op.create_index(
            "OrganizeJob_importTaskId_idx", ["importTaskId"], unique=False
        )
        batch_op.create_index(
            "OrganizeJob_runId_status_idx", ["runId", "status"], unique=False
        )
        batch_op.create_index(
            "OrganizeJob_status_updatedAt_idx", ["status", "updatedAt"], unique=False
        )
        batch_op.create_index(
            "OrganizeJob_unresolved_workId_key",
            ["workId"],
            unique=True,
            sqlite_where=sa.column("status", sa.String()).in_(
                (
                    "LOOKUP_PENDING",
                    "PENDING",
                    "QUEUED",
                    "RUNNING",
                    "RETRY_WAIT",
                    "REVIEWING",
                    "FAILED",
                )
            ),
        )
        batch_op.create_index("OrganizeJob_versionId_idx", ["versionId"], unique=False)
        batch_op.create_index("OrganizeJob_volumeId_idx", ["volumeId"], unique=False)
        batch_op.create_index(
            "OrganizeJob_workId_status_idx", ["workId", "status"], unique=False
        )

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
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            '"chapterCount" >= 0', name="PublicationNavigationCache_chapterCount_check"
        ),
        sa.ForeignKeyConstraint(
            ["fileId"], ["LibraryFile.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("volumeId"),
    )
    op.create_table(
        "MetadataLookupTask",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=True),
        sa.Column("versionId", sa.String(length=191), nullable=True),
        sa.Column("importTaskId", sa.String(length=191), nullable=True),
        sa.Column("organizeJobId", sa.String(length=191), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("providerOrder", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("nextAttemptAt", sa.BigInteger(), nullable=True),
        sa.Column("leaseOwnerId", sa.String(length=191), nullable=True),
        sa.Column("leaseExpiresAt", sa.BigInteger(), nullable=True),
        sa.Column("resultSource", sa.Text(), nullable=True),
        sa.Column("candidateRawJson", sa.Text(), nullable=True),
        sa.Column("appliedFields", sa.Text(), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["importTaskId"], ["ImportTask.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organizeJobId"],
            ["OrganizeJob.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["versionId"],
            ["LibraryVersion.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("importTaskId", name="MetadataLookupTask_importTaskId_key"),
    )
    with op.batch_alter_table("MetadataLookupTask", schema=None) as batch_op:
        batch_op.create_index(
            "MetadataLookupTask_claim_idx",
            ["status", "nextAttemptAt", "leaseExpiresAt", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataLookupTask_versionId_idx", ["versionId"], unique=False
        )
        batch_op.create_index(
            "MetadataLookupTask_volumeId_idx", ["volumeId"], unique=False
        )
        batch_op.create_index(
            "MetadataLookupTask_workId_createdAt_idx",
            ["workId", "createdAt"],
            unique=False,
        )

    op.create_table(
        "MetadataSuggestion",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("jobId", sa.String(length=191), nullable=False),
        sa.Column("field", sa.String(length=191), nullable=False),
        sa.Column("currentValue", sa.Text(), nullable=True),
        sa.Column("suggestedValue", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=191), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["jobId"], ["OrganizeJob.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("MetadataSuggestion", schema=None) as batch_op:
        batch_op.create_index("MetadataSuggestion_field_idx", ["field"], unique=False)
        batch_op.create_index(
            "MetadataSuggestion_jobId_status_idx", ["jobId", "status"], unique=False
        )
        batch_op.create_index("MetadataSuggestion_source_idx", ["source"], unique=False)

    op.create_table(
        "MetadataProviderExecution",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("jobId", sa.String(length=191), nullable=True),
        sa.Column("lookupTaskId", sa.String(length=191), nullable=True),
        sa.Column("providerId", sa.String(length=191), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rawResultJson", sa.Text(), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column("startedAt", sa.BigInteger(), nullable=True),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["jobId"], ["OrganizeJob.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lookupTaskId"],
            ["MetadataLookupTask.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("MetadataProviderExecution", schema=None) as batch_op:
        batch_op.create_index(
            "MetadataProviderExecution_jobId_status_idx",
            ["jobId", "status"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataProviderExecution_lookupTaskId_idx", ["lookupTaskId"], unique=False
        )

    op.create_table(
        "MetadataWritebackOperation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("versionId", sa.String(length=191), nullable=False),
        sa.Column("lookupTaskId", sa.String(length=191), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("totalTargets", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completedTargets", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warningTargets", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["lookupTaskId"],
            ["MetadataLookupTask.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["versionId"], ["LibraryVersion.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("MetadataWritebackOperation", schema=None) as batch_op:
        batch_op.create_index(
            "MetadataWritebackOperation_status_createdAt_idx",
            ["status", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackOperation_workId_createdAt_idx",
            ["workId", "createdAt"],
            unique=False,
        )

    op.create_table(
        "MetadataWritebackPreparation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("operationId", sa.String(length=191), nullable=True),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("versionId", sa.String(length=191), nullable=True),
        sa.Column("volumeId", sa.String(length=191), nullable=True),
        sa.Column("lookupTaskId", sa.String(length=191), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("idempotencyKey", sa.String(length=64), nullable=False),
        sa.Column("sourceRevision", sa.String(length=191), nullable=False),
        sa.Column("snapshotJson", sa.Text(), server_default="{}", nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("leaseOwnerId", sa.String(length=191), nullable=True),
        sa.Column("leaseExpiresAt", sa.BigInteger(), nullable=True),
        sa.Column("nextAttemptAt", sa.BigInteger(), nullable=True),
        sa.Column("errorCode", sa.String(length=64), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lookupTaskId"],
            ["MetadataLookupTask.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operationId"],
            ["MetadataWritebackOperation.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["versionId"], ["LibraryVersion.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"], ["LibraryVolume.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workId"], ["LibraryWork.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotencyKey", name="MetadataWritebackPreparation_idempotency_key"
        ),
    )
    with op.batch_alter_table("MetadataWritebackPreparation", schema=None) as batch_op:
        batch_op.create_index(
            "MetadataWritebackPreparation_claim_idx",
            ["status", "nextAttemptAt", "leaseExpiresAt", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackPreparation_operationId_idx",
            ["operationId"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackPreparation_workId_idx", ["workId"], unique=False
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
            "status", sa.String(length=32), server_default="PENDING", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("nextAttemptAt", sa.BigInteger(), nullable=True),
        sa.Column("leaseOwnerId", sa.String(length=191), nullable=True),
        sa.Column("leaseExpiresAt", sa.BigInteger(), nullable=True),
        sa.Column("preparedPath", sa.Text(), nullable=True),
        sa.Column("writtenFieldsJson", sa.Text(), server_default="[]", nullable=False),
        sa.Column("warningCode", sa.String(length=64), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.Column("finishedAt", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["libraryFileId"],
            ["LibraryFile.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operationId"],
            ["MetadataWritebackOperation.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operationId",
            "targetKey",
            name="MetadataWritebackTarget_operation_target_key",
        ),
    )
    with op.batch_alter_table("MetadataWritebackTarget", schema=None) as batch_op:
        batch_op.create_index(
            "MetadataWritebackTarget_claim_idx",
            ["status", "nextAttemptAt", "leaseExpiresAt", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackTarget_operationId_idx", ["operationId"], unique=False
        )


    meta = _build_overlay_metadata()
    for name in _OVERLAY_TABLES:
        meta.tables[name].create(op.get_bind())

    # ### end Alembic commands ###


def downgrade() -> None:
    raise NotImplementedError("The fresh-install baseline does not support downgrade")
