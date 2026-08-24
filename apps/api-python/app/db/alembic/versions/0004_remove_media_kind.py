"""Remove resource classification and per-class metadata provider pipelines.

Revision ID: 0004_remove_media_kind
Revises: 0003_audio_asset_title
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_remove_media_kind"
down_revision: str | Sequence[str] | None = "0003_audio_asset_title"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("MetadataProviderPipeline")
    with op.batch_alter_table("LibraryReadableResource") as batch:
        batch.drop_column("mediaKind")


def downgrade() -> None:
    raise NotImplementedError("mediaKind removal is irreversible")

