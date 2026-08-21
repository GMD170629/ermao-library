"""Add ADR 0018 readable-resource overlay target schema.

Revision ID: 0003_readable_resource_overlay_schema
Revises: 0002_version_covers

Temporary incremental revision. Flatten into a fresh baseline only after the
target import flow is stable and ready for first production release.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401 — register mapped tables on Base.metadata
from app.db.base import Base

revision: str = "0003_readable_resource_overlay_schema"
down_revision: str | Sequence[str] | None = "0002_version_covers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Create order respects FK dependencies; circular FKs use use_alter.
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


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in _OVERLAY_TABLES]
    Base.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_OVERLAY_TABLES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
