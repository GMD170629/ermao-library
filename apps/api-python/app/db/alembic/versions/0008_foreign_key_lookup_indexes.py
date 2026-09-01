"""Add non-partial indexes for every uncovered foreign-key lookup.

Revision ID: 0008_foreign_key_lookup_indexes
Revises: 0007_source_node_lookup_indexes
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_foreign_key_lookup_indexes"
down_revision: str | Sequence[str] | None = "0007_source_node_lookup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("BookDetailPreference_bookId_idx", "BookDetailPreference", ("bookId",)),
    ("KindleSendTask_resourceId_idx", "KindleSendTask", ("resourceId",)),
    ("KindleSendTask_assetId_idx", "KindleSendTask", ("assetId",)),
    (
        "LibraryImportTask_sourceNodeId_libraryId_idx",
        "LibraryImportTask",
        ("sourceNodeId", "libraryId"),
    ),
    (
        "LibraryImportTask_resourceId_libraryId_idx",
        "LibraryImportTask",
        ("resourceId", "libraryId"),
    ),
    ("LibraryOperation_userId_idx", "LibraryOperation", ("userId",)),
    ("LibraryResourceAsset_libraryId_idx", "LibraryResourceAsset", ("libraryId",)),
    (
        "LibrarySourceNode_parentId_libraryId_idx",
        "LibrarySourceNode",
        ("parentId", "libraryId"),
    ),
    (
        "LibrarySourceNode_parentId_parentPhysicalKind_idx",
        "LibrarySourceNode",
        ("parentId", "parentPhysicalKind"),
    ),
    (
        "LibraryReadableResource_bookId_libraryId_idx",
        "LibraryReadableResource",
        ("bookId", "libraryId"),
    ),
    (
        "LibraryResourceAsset_sourceNodeId_libraryId_idx",
        "LibraryResourceAsset",
        ("sourceNodeId", "libraryId"),
    ),
    (
        "LibraryResourceAsset_sourceNodeId_sourceNodePhysicalKind_idx",
        "LibraryResourceAsset",
        ("sourceNodeId", "sourceNodePhysicalKind"),
    ),
    (
        "LibraryResourceAsset_resourceId_libraryId_idx",
        "LibraryResourceAsset",
        ("resourceId", "libraryId"),
    ),
    ("MetadataLookupTask_organizeJobId_idx", "MetadataLookupTask", ("organizeJobId",)),
    (
        "MetadataWritebackOperation_lookupTaskId_idx",
        "MetadataWritebackOperation",
        ("lookupTaskId",),
    ),
    (
        "MetadataWritebackPreparation_lookupTaskId_idx",
        "MetadataWritebackPreparation",
        ("lookupTaskId",),
    ),
    ("MetadataWritebackTarget_assetId_idx", "MetadataWritebackTarget", ("assetId",)),
    ("ReaderBookmark_resourceId_idx", "ReaderBookmark", ("resourceId",)),
    (
        "ReaderProgressMutation_resourceId_idx",
        "ReaderProgressMutation",
        ("resourceId",),
    ),
    ("Session_userId_idx", "Session", ("userId",)),
)


def upgrade() -> None:
    for index_name, table_name, columns in _INDEXES:
        op.create_index(index_name, table_name, list(columns))


def downgrade() -> None:
    for index_name, table_name, _columns in reversed(_INDEXES):
        op.drop_index(index_name, table_name=table_name)
