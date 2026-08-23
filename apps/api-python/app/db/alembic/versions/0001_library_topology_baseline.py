"""Fresh-install library topology and ADR 0018 readable-resource overlay baseline.

Revision ID: 0001_library_topology_baseline
Revises: None

Single fresh-install baseline only. Prior development revisions are not supported
for upgrade. Downgrade is not supported.
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
        Column("visibilityState", String(32), nullable=False, server_default="VISIBLE"),
        Column("curationState", String(32), nullable=False, server_default="PENDING"),
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
        Column("enablementState", String(32), nullable=False, server_default="ENABLED"),
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
        Column("resourceIndex", Float(), nullable=True),
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
            column("role").in_(("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")),
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
            ForeignKey(
                "LibraryResourceAsset.id", ondelete="CASCADE", onupdate="CASCADE"
            ),
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
            sa.column("organizationMode").in_(("FLAT", "VOLUMES")),
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

    overlay_meta = _build_overlay_metadata()
    for overlay_name in _OVERLAY_TABLES:
        overlay_meta.tables[overlay_name].create(op.get_bind())

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
        sa.ForeignKeyConstraint(
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
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
        "LibraryBookFacet",
        sa.Column("facetId", sa.String(length=191), nullable=False),
        sa.Column("bookId", sa.String(length=191), nullable=False),
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
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("facetId", "bookId"),
    )
    with op.batch_alter_table("LibraryBookFacet", schema=None) as batch_op:
        batch_op.create_index("LibraryBookFacet_bookId_idx", ["bookId"], unique=False)

    op.create_table(
        "LibraryReadableResourceFacet",
        sa.Column("facetId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("facetId", "resourceId"),
    )
    with op.batch_alter_table("LibraryReadableResourceFacet", schema=None) as batch_op:
        batch_op.create_index(
            "LibraryReadableResourceFacet_resourceId_idx", ["resourceId"], unique=False
        )

    op.create_table(
        "ReadableResourceNavigationUnit",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("assetId", sa.String(length=191), nullable=True),
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
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table(
        "ReadableResourceNavigationUnit", schema=None
    ) as batch_op:
        batch_op.create_index(
            "ReadableResourceNavigationUnit_assetId_sortOrder_idx",
            ["assetId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "ReadableResourceNavigationUnit_resourceId_sortOrder_idx",
            ["resourceId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "ReadableResourceNavigationUnit_resourceId_unitType_sortOrder_key",
            ["resourceId", "unitType", "sortOrder"],
            unique=True,
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
            sa.column("pendingPreparations") >= 0,
            name="MetadataOpfQueueState_pendingPreparations_nonnegative",
        ),
        sa.CheckConstraint(
            sa.column("pendingTargets") >= 0,
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
        "ReaderResourceProgress",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ReaderResourceProgress", schema=None) as batch_op:
        batch_op.create_index(
            "ReaderResourceProgress_clientId_clientSequence_idx",
            ["clientId", "clientSequence"],
            unique=False,
        )
        batch_op.create_index(
            "ReaderResourceProgress_userId_updatedAt_resourceId_idx",
            ["userId", "updatedAt", "resourceId"],
            unique=False,
        )
        batch_op.create_index(
            "ReaderResourceProgress_userId_resourceId_key",
            ["userId", "resourceId"],
            unique=True,
        )
        batch_op.create_index(
            "ReaderResourceProgress_resourceId_idx", ["resourceId"], unique=False
        )

    op.create_table(
        "BookDetailPreference",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("bookId", sa.String(length=191), nullable=False),
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
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("BookDetailPreference", schema=None) as batch_op:
        batch_op.create_index(
            "BookDetailPreference_user_book_key", ["userId", "bookId"], unique=True
        )

    op.create_table(
        "ShelfBook",
        sa.Column("shelfId", sa.String(length=191), nullable=False),
        sa.Column("bookId", sa.String(length=191), nullable=False),
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
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("shelfId", "bookId"),
    )
    with op.batch_alter_table("ShelfBook", schema=None) as batch_op:
        batch_op.create_index(
            "ShelfBook_shelfId_createdAt_idx", ["shelfId", "createdAt"], unique=False
        )
        batch_op.create_index("ShelfBook_bookId_idx", ["bookId"], unique=False)

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
        "ReaderBookPreference",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("bookId", sa.String(length=191), nullable=False),
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
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId", "bookId", name="ReaderBookPreference_userId_bookId_key"
        ),
    )
    with op.batch_alter_table("ReaderBookPreference", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ReaderBookPreference_userId"), ["userId"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ReaderBookPreference_bookId"), ["bookId"], unique=False
        )

    op.create_table(
        "ReaderProgressCursor",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "resourceId",
            "clientId",
            name="ReaderProgressCursor_userId_resourceId_clientId_key",
        ),
    )
    with op.batch_alter_table("ReaderProgressCursor", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ReaderProgressCursor_userId"), ["userId"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ReaderProgressCursor_resourceId"),
            ["resourceId"],
            unique=False,
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
            sa.column("collectionId") != sa.column("shelfId"),
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
        "ReaderBookmark",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "resourceId",
            "bookmarkId",
            name="ReaderBookmark_user_resource_bookmark_key",
        ),
    )
    with op.batch_alter_table("ReaderBookmark", schema=None) as batch_op:
        batch_op.create_index(
            "ReaderBookmark_user_resource_idx", ["userId", "resourceId"], unique=False
        )

    op.create_table(
        "ReaderProgressMutation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "resourceId",
            "mutationId",
            name="ReaderProgressMutation_userId_resourceId_mutationId_key",
        ),
    )
    with op.batch_alter_table("ReaderProgressMutation", schema=None) as batch_op:
        batch_op.create_index(
            "ReaderProgressMutation_userId_resourceId_revision_idx",
            ["userId", "resourceId", "revision"],
            unique=False,
        )

    op.create_table(
        "KindleSendTask",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=True),
        sa.Column("bookId", sa.String(length=191), nullable=True),
        sa.Column("resourceId", sa.String(length=191), nullable=True),
        sa.Column("assetId", sa.String(length=191), nullable=True),
        sa.Column("bookTitle", sa.Text(), nullable=False),
        sa.Column("resourceTitle", sa.Text(), nullable=True),
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
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("KindleSendTask", schema=None) as batch_op:
        batch_op.create_index(
            "KindleSendTask_active_asset_recipient_key",
            ["assetId", "recipientEmail"],
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
            "KindleSendTask_bookId_createdAt_idx", ["bookId", "createdAt"], unique=False
        )

    op.create_table(
        "OrganizeJob",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("runId", sa.String(length=191), nullable=True),
        sa.Column("bookId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=True),
        sa.Column("assetId", sa.String(length=191), nullable=True),
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
            ["importTaskId"],
            ["LibraryImportTask.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["runId"], ["OrganizeRun.id"], onupdate="CASCADE", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
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
            "OrganizeJob_unresolved_bookId_key",
            ["bookId"],
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
        batch_op.create_index("OrganizeJob_assetId_idx", ["assetId"], unique=False)
        batch_op.create_index(
            "OrganizeJob_resourceId_idx", ["resourceId"], unique=False
        )
        batch_op.create_index(
            "OrganizeJob_bookId_status_idx", ["bookId", "status"], unique=False
        )

    op.create_table(
        "PublicationNavigationCache",
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("assetId", sa.String(length=191), nullable=False),
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
            sa.column("chapterCount") >= 0,
            name="PublicationNavigationCache_chapterCount_check",
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("resourceId"),
    )
    op.create_table(
        "MetadataLookupTask",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("bookId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=True),
        sa.Column("assetId", sa.String(length=191), nullable=True),
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
            ["importTaskId"],
            ["LibraryImportTask.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organizeJobId"],
            ["OrganizeJob.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
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
            "MetadataLookupTask_assetId_idx", ["assetId"], unique=False
        )
        batch_op.create_index(
            "MetadataLookupTask_resourceId_idx", ["resourceId"], unique=False
        )
        batch_op.create_index(
            "MetadataLookupTask_bookId_createdAt_idx",
            ["bookId", "createdAt"],
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
        sa.Column("bookId", sa.String(length=191), nullable=False),
        sa.Column("sourceNodeId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=True),
        sa.Column("assetId", sa.String(length=191), nullable=True),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sourceNodeId"],
            ["LibrarySourceNode.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
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
            "MetadataWritebackOperation_bookId_createdAt_idx",
            ["bookId", "createdAt"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackOperation_sourceNodeId_idx",
            ["sourceNodeId"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackOperation_resourceId_idx", ["resourceId"], unique=False
        )
        batch_op.create_index(
            "MetadataWritebackOperation_assetId_idx", ["assetId"], unique=False
        )

    op.create_table(
        "MetadataWritebackPreparation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("operationId", sa.String(length=191), nullable=True),
        sa.Column("bookId", sa.String(length=191), nullable=False),
        sa.Column("sourceNodeId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=True),
        sa.Column("assetId", sa.String(length=191), nullable=True),
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
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bookId"], ["LibraryBook.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sourceNodeId"],
            ["LibrarySourceNode.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
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
            "MetadataWritebackPreparation_bookId_idx", ["bookId"], unique=False
        )
        batch_op.create_index(
            "MetadataWritebackPreparation_resourceId_idx", ["resourceId"], unique=False
        )
        batch_op.create_index(
            "MetadataWritebackPreparation_sourceNodeId_idx",
            ["sourceNodeId"],
            unique=False,
        )
        batch_op.create_index(
            "MetadataWritebackPreparation_assetId_idx", ["assetId"], unique=False
        )

    op.create_table(
        "MetadataWritebackTarget",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("operationId", sa.String(length=191), nullable=False),
        sa.Column("assetId", sa.String(length=191), nullable=True),
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
            ["assetId"],
            ["LibraryResourceAsset.id"],
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

    # ### end Alembic commands ###


def downgrade() -> None:
    raise NotImplementedError("The fresh-install baseline does not support downgrade")
