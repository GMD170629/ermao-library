"""Make media versions the only work media-type source of truth.

Revision ID: 0009_media_version_metadata_contract
Revises: 0008_audiobook_audio_formats
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_media_version_metadata_contract"
down_revision: str | Sequence[str] | None = "0008_audiobook_audio_formats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_publisher_facets() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    facets = sa.Table("LibraryFacet", metadata, autoload_with=connection)
    work_facets = sa.Table("LibraryWorkFacet", metadata, autoload_with=connection)
    volume_facets = sa.Table("LibraryVolumeFacet", metadata, autoload_with=connection)
    publisher_ids = sa.select(facets.c.id).where(facets.c.kind == "PUBLISHER")
    connection.execute(
        sa.delete(work_facets).where(work_facets.c.facetId.in_(publisher_ids))
    )
    connection.execute(
        sa.delete(volume_facets).where(volume_facets.c.facetId.in_(publisher_ids))
    )
    connection.execute(sa.delete(facets).where(facets.c.kind == "PUBLISHER"))


def _replace_provider_pipeline() -> None:
    connection = op.get_bind()
    source = sa.Table(
        "MetadataProviderPipeline", sa.MetaData(), autoload_with=connection
    )
    op.create_table(
        "_MetadataProviderPipeline_0009",
        sa.Column("mediaKind", sa.String(length=191), nullable=False),
        sa.Column("providerId", sa.String(length=191), nullable=False),
        sa.Column("included", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("position", sa.Integer(), server_default="100", nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("mediaKind", "providerId"),
    )
    target = sa.Table(
        "_MetadataProviderPipeline_0009",
        sa.MetaData(),
        autoload_with=connection,
    )
    normalized_kind = sa.case(
        (sa.func.lower(source.c.workType) == "comic", "COMIC"),
        (sa.func.lower(source.c.workType) == "audiobook", "AUDIOBOOK"),
        else_="EBOOK",
    )
    connection.execute(
        sa.insert(target).from_select(
            [
                "mediaKind",
                "providerId",
                "included",
                "enabled",
                "position",
                "createdAt",
                "updatedAt",
            ],
            sa.select(
                normalized_kind,
                source.c.providerId,
                source.c.included,
                source.c.enabled,
                source.c.position,
                source.c.createdAt,
                source.c.updatedAt,
            ),
        )
    )
    op.drop_table("MetadataProviderPipeline")
    op.rename_table("_MetadataProviderPipeline_0009", "MetadataProviderPipeline")
    op.create_index(
        "MetadataProviderPipeline_mediaKind_position_idx",
        "MetadataProviderPipeline",
        ["mediaKind", "included", "position"],
        unique=False,
    )


def upgrade() -> None:
    _drop_publisher_facets()

    with op.batch_alter_table("LibraryWork", recreate="always") as batch_op:
        batch_op.drop_index("LibraryWork_workType_idx")
        batch_op.drop_index("LibraryWork_publishedYear_idx")
        batch_op.drop_column("workType")
        batch_op.drop_column("publishedYear")

    _replace_provider_pipeline()

    with op.batch_alter_table("OrganizeJob") as batch_op:
        batch_op.add_column(sa.Column("mediaVersionId", sa.String(191), nullable=True))
        batch_op.create_foreign_key(
            "fk_OrganizeJob_mediaVersionId_LibraryMediaVersion",
            "LibraryMediaVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "OrganizeJob_mediaVersionId_idx", ["mediaVersionId"], unique=False
        )

    with op.batch_alter_table("MetadataLookupTask") as batch_op:
        batch_op.add_column(sa.Column("mediaVersionId", sa.String(191), nullable=True))
        batch_op.create_foreign_key(
            "fk_MetadataLookupTask_mediaVersionId_LibraryMediaVersion",
            "LibraryMediaVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "MetadataLookupTask_mediaVersionId_idx",
            ["mediaVersionId"],
            unique=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "0009_media_version_metadata_contract is irreversible because work-level "
        "media type and publication year data were intentionally removed"
    )
