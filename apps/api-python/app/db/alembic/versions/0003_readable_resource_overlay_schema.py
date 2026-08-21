"""Add ADR 0018 readable-resource overlay target schema.

Revision ID: 0003_readable_resource_overlay_schema
Revises: 0002_version_covers

Temporary incremental revision. Flatten into a fresh baseline only after the
target import flow is stable and ready for first production release.

This revision is migration-local and immutable: it must not import runtime
model packages, the declarative registry module, or application services.
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

revision: str = "0003_readable_resource_overlay_schema"
down_revision: str | Sequence[str] | None = "0002_version_covers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PATH_KEY_LENGTH = 67
_NONTERMINAL_RUN_STATES = ("PENDING", "RUNNING")

_OVERLAY_TABLES: tuple[str, ...] = (
    "LibrarySourceNode",
    "LibrarySourceNodeMetadata",
    "LibrarySourceNodeInterpretation",
    "LibraryBook",
    "LibraryBookMetadata",
    "LibraryImportRun",
    "LibraryReadableResource",
    "LibraryReadableResourceMetadata",
    "LibraryResourceAsset",
    "LibraryResourceAssetMetadata",
    "ResourceCandidate",
    "AssetCandidate",
    "LibraryImportTask",
)


def _timestamp_default() -> sa.ColumnElement[int]:
    return sa.func.unixepoch() * 1000


def _build_overlay_metadata() -> MetaData:
    """Frozen schema objects for this revision only."""

    meta = MetaData()
    # Resolve FK targets to existing Library without creating/dropping it.
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
        Column("updatedAt", BigInteger(), nullable=False),
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
            or_(
                column("parentId").is_(None),
                column("parentId") != column("id"),
            ),
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
            "libraryId",
            "pathKey",
            name="LibrarySourceNode_libraryId_pathKey_key",
        ),
        UniqueConstraint(
            "id",
            "libraryId",
            name="LibrarySourceNode_id_libraryId_key",
        ),
        UniqueConstraint(
            "id",
            "physicalKind",
            name="LibrarySourceNode_id_physicalKind_key",
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
        Column(
            "coverStatus",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
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
        Column("updatedAt", BigInteger(), nullable=False),
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
        Column("updatedAt", BigInteger(), nullable=False),
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
        Column(
            "coverStatus",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column(
            "metadataQuality",
            Integer(),
            nullable=False,
            server_default="0",
        ),
        Column(
            "publicationStatus",
            String(32),
            nullable=False,
            server_default="UNKNOWN",
        ),
        Column(
            "trackingStatus",
            String(32),
            nullable=False,
            server_default="NOT_TRACKING",
        ),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
    )

    Table(
        "LibraryImportRun",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("kind", String(32), nullable=False),
        Column(
            "state",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column("sourceNodeId", String(191), nullable=False),
        Column("resourceId", String(191), nullable=True),
        Column("adapterId", String(191), nullable=True),
        Column("adapterVersion", String(64), nullable=True),
        Column(
            "discoveryComplete",
            Boolean(),
            nullable=False,
            server_default="0",
        ),
        Column("errorSummary", Text(), nullable=True),
        Column("publishedAt", BigInteger(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
        CheckConstraint(
            column("kind").in_(("INITIAL", "RETRY", "REIMPORT", "RECOVERY")),
            name="LibraryImportRun_kind_check",
        ),
        CheckConstraint(
            column("state").in_(
                (
                    "PENDING",
                    "RUNNING",
                    "COMPLETED",
                    "COMPLETED_WITH_ERRORS",
                    "FAILED",
                    "CANCELLED",
                )
            ),
            name="LibraryImportRun_state_check",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportRun_sourceNode_library",
        ),
        ForeignKeyConstraint(
            ["resourceId", "libraryId"],
            ["LibraryReadableResource.id", "LibraryReadableResource.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            use_alter=True,
            name="fk_LibraryImportRun_resource_library",
        ),
        Index("LibraryImportRun_libraryId_state_idx", "libraryId", "state"),
        Index("LibraryImportRun_sourceNodeId_idx", "sourceNodeId"),
        Index(
            "LibraryImportRun_nonterminal_resource_key",
            "resourceId",
            unique=True,
            sqlite_where=and_(
                column("resourceId").is_not(None),
                column("state", String).in_(_NONTERMINAL_RUN_STATES),
            ),
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
            "enablementState",
            String(32),
            nullable=False,
            server_default="ENABLED",
        ),
        Column(
            "importState",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column(
            "publishedRunId",
            String(191),
            ForeignKey(
                "LibraryImportRun.id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                use_alter=True,
                name="fk_LibraryReadableResource_publishedRunId",
            ),
            nullable=True,
        ),
        Column(
            "activeImportRunId",
            String(191),
            ForeignKey(
                "LibraryImportRun.id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                use_alter=True,
                name="fk_LibraryReadableResource_activeImportRunId",
            ),
            nullable=True,
        ),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
        CheckConstraint(
            column("enablementState").in_(("ENABLED", "DISABLED")),
            name="LibraryReadableResource_enablementState_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="LibraryReadableResource_importState_check",
        ),
        UniqueConstraint(
            "sourceNodeId",
            name="LibraryReadableResource_sourceNodeId_key",
        ),
        UniqueConstraint(
            "id",
            "libraryId",
            name="LibraryReadableResource_id_libraryId_key",
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
        Index(
            "LibraryReadableResource_activeImportRunId_key",
            "activeImportRunId",
            unique=True,
            sqlite_where=column("activeImportRunId").is_not(None),
        ),
    )

    Table(
        "LibraryReadableResourceMetadata",
        meta,
        Column(
            "resourceId",
            String(191),
            ForeignKey(
                "LibraryReadableResource.id",
                ondelete="CASCADE",
                onupdate="CASCADE",
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
        Column(
            "coverStatus",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
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
        Column(
            "publishedRunId",
            String(191),
            ForeignKey(
                "LibraryImportRun.id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                use_alter=True,
                name="fk_LibraryResourceAsset_publishedRunId",
            ),
            nullable=True,
        ),
        Column("role", String(32), nullable=False),
        Column(
            "importState",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column("sequenceIndex", Integer(), nullable=True),
        Column("sortKey", Text(), nullable=True),
        Column("failureReason", Text(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
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
            "LibraryResourceAsset_current_published_idx",
            "resourceId",
            "publishedRunId",
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
                "LibraryResourceAsset.id",
                ondelete="CASCADE",
                onupdate="CASCADE",
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
        Column("updatedAt", BigInteger(), nullable=False),
    )

    Table(
        "ResourceCandidate",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "importRunId",
            String(191),
            ForeignKey("LibraryImportRun.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("bookId", String(191), nullable=True),
        Column("sourceNodeId", String(191), nullable=False),
        Column("adapterId", String(191), nullable=False),
        Column("adapterVersion", String(64), nullable=False),
        Column("mediaKind", String(32), nullable=False),
        Column("format", String(32), nullable=False),
        Column(
            "enablementState",
            String(32),
            nullable=False,
            server_default="ENABLED",
        ),
        Column(
            "importState",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column("title", Text(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
        CheckConstraint(
            column("enablementState").in_(("ENABLED", "DISABLED")),
            name="ResourceCandidate_enablementState_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="ResourceCandidate_importState_check",
        ),
        UniqueConstraint("importRunId", name="ResourceCandidate_importRunId_key"),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_ResourceCandidate_sourceNode_library",
        ),
    )

    Table(
        "AssetCandidate",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "importRunId",
            String(191),
            ForeignKey("LibraryImportRun.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column("sourceNodeId", String(191), nullable=False),
        Column("role", String(32), nullable=False),
        Column(
            "importState",
            String(32),
            nullable=False,
            server_default="PENDING",
        ),
        Column("sequenceIndex", Integer(), nullable=True),
        Column("sortKey", Text(), nullable=True),
        Column("failureReason", Text(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
        CheckConstraint(
            column("role").in_(
                ("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")
            ),
            name="AssetCandidate_role_check",
        ),
        CheckConstraint(
            column("importState").in_(("PENDING", "READY", "FAILED")),
            name="AssetCandidate_importState_check",
        ),
        UniqueConstraint(
            "importRunId",
            "sourceNodeId",
            name="AssetCandidate_importRunId_sourceNodeId_key",
        ),
        ForeignKeyConstraint(
            ["sourceNodeId", "libraryId"],
            ["LibrarySourceNode.id", "LibrarySourceNode.libraryId"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_AssetCandidate_sourceNode_library",
        ),
    )

    Table(
        "LibraryImportTask",
        meta,
        Column("id", String(191), primary_key=True, nullable=False),
        Column(
            "libraryId",
            String(191),
            ForeignKey("Library.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        Column(
            "state",
            String(32),
            nullable=False,
            server_default="QUEUED",
        ),
        Column("resourceId", String(191), nullable=False),
        Column("sourceNodeId", String(191), nullable=False),
        Column(
            "ownerImportRunId",
            String(191),
            ForeignKey("LibraryImportRun.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=True,
        ),
        Column("role", String(32), nullable=False),
        Column(
            "attemptCount",
            Integer(),
            nullable=False,
            server_default="0",
        ),
        Column("errorSummary", Text(), nullable=True),
        Column(
            "createdAt",
            BigInteger(),
            nullable=False,
            server_default=_timestamp_default(),
        ),
        Column("updatedAt", BigInteger(), nullable=False),
        CheckConstraint(
            column("state").in_(
                ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
            ),
            name="LibraryImportTask_state_check",
        ),
        CheckConstraint(
            column("role").in_(
                ("PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT")
            ),
            name="LibraryImportTask_role_check",
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
            "LibraryImportTask_run_owned_key",
            "ownerImportRunId",
            "sourceNodeId",
            "role",
            unique=True,
            sqlite_where=column("ownerImportRunId").is_not(None),
        ),
        Index(
            "LibraryImportTask_incremental_key",
            "resourceId",
            "sourceNodeId",
            unique=True,
            sqlite_where=column("ownerImportRunId").is_(None),
        ),
        Index("LibraryImportTask_state_idx", "state"),
    )

    return meta


def upgrade() -> None:
    bind = op.get_bind()
    meta = _build_overlay_metadata()
    for name in _OVERLAY_TABLES:
        meta.tables[name].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    meta = _build_overlay_metadata()
    for name in reversed(_OVERLAY_TABLES):
        meta.tables[name].drop(bind=bind, checkfirst=True)
