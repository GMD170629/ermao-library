"""Contract the library schema to media-version and volume-only identities.

Revision ID: 0006_media_versions_contract
Revises: 0005_media_versions_backfill
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_media_versions_contract"
down_revision: str | Sequence[str] | None = "0005_media_versions_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def _columns(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _indexes(table_name: str) -> set[str]:
    return {
        str(index["name"])
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def _assert_no_null(table_name: str, column_name: str) -> None:
    metadata = sa.MetaData()
    table = sa.Table(table_name, metadata, autoload_with=op.get_bind())
    count = op.get_bind().scalar(
        sa.select(sa.func.count())
        .select_from(table)
        .where(table.c[column_name].is_(None))
    )
    if count:
        raise RuntimeError(
            f"media-version backfill incomplete: {table_name}.{column_name} has {count} null rows"
        )


def _drop_index_if_present(batch_op, table_name: str, index_name: str) -> None:
    if index_name in _indexes(table_name):
        batch_op.drop_index(index_name)


def _stage_binding(
    staging: sa.Table,
    table_name: str,
    source: sa.Table,
    record_column: sa.Column[object],
    target_column: sa.Column[object],
) -> None:
    op.get_bind().execute(
        sa.insert(staging).from_select(
            ["tableName", "recordId", "targetId"],
            sa.select(sa.literal(table_name), record_column, target_column).where(
                target_column.is_not(None)
            ),
        )
    )


def _restore_binding(
    staging: sa.Table,
    table_name: str,
    target: sa.Table,
    target_column: sa.Column[object],
) -> None:
    bindings = op.get_bind().execute(
        sa.select(staging.c.recordId, staging.c.targetId).where(
            staging.c.tableName == table_name
        )
    )
    for record_id, target_id in bindings:
        op.get_bind().execute(
            sa.update(target)
            .where(target.c.id == record_id)
            .values({target_column.name: target_id})
        )


def _create_import_task_contract(legacy: sa.Table) -> sa.Table:
    retained_names = [
        column.name for column in legacy.columns if column.name != "editionId"
    ]
    columns: list[sa.SchemaItem] = []
    for name in retained_names:
        source = legacy.c[name]
        columns.append(
            sa.Column(
                name,
                source.type,
                nullable=source.nullable,
                server_default=source.server_default,
            )
        )
    columns.extend(
        [
            sa.ForeignKeyConstraint(
                ["monitorFolderId"],
                ["MonitorFolder.id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["workId"],
                ["LibraryWork.id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["volumeId"],
                ["LibraryVolume.id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        ]
    )
    op.create_table("ImportTask", *columns)
    target = sa.Table("ImportTask", sa.MetaData(), autoload_with=op.get_bind())
    op.get_bind().execute(
        sa.insert(target).from_select(
            retained_names, sa.select(*(legacy.c[name] for name in retained_names))
        )
    )
    for name, column_names in (
        ("ImportTask_monitorFolderId_status_idx", ["monitorFolderId", "status"]),
        ("ImportTask_status_createdAt_idx", ["status", "createdAt"]),
        ("ImportTask_contentHash_idx", ["contentHash"]),
        ("ImportTask_workId_idx", ["workId"]),
        ("ImportTask_volumeId_idx", ["volumeId"]),
        ("ImportTask_status_leaseExpiresAt_idx", ["status", "leaseExpiresAt"]),
        ("ImportTask_createdAt_id_idx", ["createdAt", "id"]),
        (
            "ImportTask_sourceKey_status_createdAt_idx",
            ["sourceKey", "status", "createdAt"],
        ),
    ):
        op.create_index(name, "ImportTask", column_names, unique=False)
    return target


def _repoint_import_task_foreign_key(table_name: str) -> None:
    with op.batch_alter_table(
        table_name, recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            f"fk_{table_name}_importTaskId_LegacyImportTask", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            f"fk_{table_name}_importTaskId_ImportTask",
            "ImportTask",
            ["importTaskId"],
            ["id"],
            ondelete=(
                "SET NULL"
                if table_name in {"OrganizeJob", "MetadataLookupTask"}
                else "CASCADE"
            ),
            onupdate="CASCADE",
        )


def upgrade() -> None:
    for table_name, column_name in (
        ("LibraryVolume", "mediaVersionId"),
        ("LibraryVolume", "format"),
        ("LibraryVolume", "resourceKey"),
        ("LibraryFile", "volumeId"),
        ("LibraryReadingUnit", "volumeId"),
        ("LibraryMetadata", "volumeId"),
        ("LibraryReadingProgress", "volumeId"),
        ("ReaderBookmark", "volumeId"),
        ("BookConversionTask", "sourceVolumeId"),
        ("BookConversionTask", "idempotencyKey"),
    ):
        _assert_no_null(table_name, column_name)

    with op.batch_alter_table(
        "LibraryMediaVersion",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        batch_op.create_unique_constraint(
            "LibraryMediaVersion_workId_mediaKind_key", ["workId", "mediaKind"]
        )

    op.create_table(
        "MediaVersionBindingStaging",
        sa.Column("tableName", sa.String(length=128), nullable=False),
        sa.Column("recordId", sa.String(length=191), nullable=False),
        sa.Column("targetId", sa.String(length=191), nullable=False),
        sa.Column("createdAt", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("tableName", "recordId", "targetId"),
    )
    staging = sa.Table(
        "MediaVersionBindingStaging", sa.MetaData(), autoload_with=op.get_bind()
    )
    binding_specs = (
        ("LibraryFile.volumeId", "LibraryFile", "volumeId"),
        ("LibraryReadingUnit.volumeId", "LibraryReadingUnit", "volumeId"),
        ("LibraryReadingProgress.volumeId", "LibraryReadingProgress", "volumeId"),
        (
            "LibraryConsumptionState.lastVolumeId",
            "LibraryConsumptionState",
            "lastVolumeId",
        ),
        ("LibraryConsumptionState.lastUnitId", "LibraryConsumptionState", "lastUnitId"),
        ("UserMediaHistory.lastVolumeId", "UserMediaHistory", "lastVolumeId"),
        ("ImportTask.volumeId", "ImportTask", "volumeId"),
        ("KindleSendTask.volumeId", "KindleSendTask", "volumeId"),
        ("LibraryReadingUnit.fileId", "LibraryReadingUnit", "fileId"),
        ("KindleSendTask.fileId", "KindleSendTask", "fileId"),
        ("ImportAsset.fileId", "ImportAsset", "fileId"),
    )
    reflected: dict[str, sa.Table] = {}
    for binding_name, table_name, column_name in binding_specs:
        table = reflected.setdefault(
            table_name,
            sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind()),
        )
        _stage_binding(staging, binding_name, table, table.c.id, table.c[column_name])

    volume_facets = sa.Table(
        "LibraryVolumeFacet", sa.MetaData(), autoload_with=op.get_bind()
    )
    op.get_bind().execute(
        sa.insert(staging).from_select(
            ["tableName", "recordId", "targetId", "createdAt"],
            sa.select(
                sa.literal("LibraryVolumeFacet"),
                volume_facets.c.facetId,
                volume_facets.c.volumeId,
                volume_facets.c.createdAt,
            ),
        )
    )

    with op.batch_alter_table(
        "LibraryReadingUnit", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_LibraryReadingUnit_volumeId_LibraryVolume", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_LibraryReadingUnit_volumeId_LibraryVolume",
            "LibraryVolume",
            ["volumeId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
    consumption = sa.Table(
        "LibraryConsumptionState", sa.MetaData(), autoload_with=op.get_bind()
    )
    _restore_binding(
        staging,
        "LibraryConsumptionState.lastUnitId",
        consumption,
        consumption.c.lastUnitId,
    )
    op.drop_table("LibraryVolumeFacet")

    with op.batch_alter_table(
        "LibraryVolume", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        _drop_index_if_present(
            batch_op, "LibraryVolume", "LibraryVolume_editionId_sortOrder_idx"
        )
        _drop_index_if_present(
            batch_op, "LibraryVolume", "LibraryVolume_editionId_volumeIndex_idx"
        )
        batch_op.drop_constraint(
            "fk_LibraryVolume_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_column("editionId")
        batch_op.alter_column(
            "mediaVersionId", existing_type=sa.String(191), nullable=False
        )
        batch_op.alter_column(
            "origin",
            existing_type=sa.String(191),
            nullable=False,
            server_default="MANUAL",
        )
        batch_op.alter_column("format", existing_type=sa.String(191), nullable=False)
        batch_op.alter_column(
            "resourceKey", existing_type=sa.String(191), nullable=False
        )
        batch_op.alter_column(
            "importStatus",
            existing_type=sa.String(191),
            nullable=False,
            server_default="PENDING",
        )
        batch_op.alter_column(
            "sizeBytes", existing_type=sa.Integer(), nullable=False, server_default="0"
        )
        batch_op.alter_column(
            "coverStatus",
            existing_type=sa.String(191),
            nullable=False,
            server_default="PENDING",
        )
        batch_op.alter_column(
            "hidden", existing_type=sa.Boolean(), nullable=False, server_default="0"
        )
        batch_op.create_foreign_key(
            "fk_LibraryVolume_mediaVersionId_LibraryMediaVersion",
            "LibraryMediaVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_LibraryVolume_monitorFolderId_MonitorFolder",
            "MonitorFolder",
            ["monitorFolderId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_LibraryVolume_derivedFromVolumeId_LibraryVolume",
            "LibraryVolume",
            ["derivedFromVolumeId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "LibraryVolume_mediaVersionId_sortOrder_idx",
            ["mediaVersionId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryVolume_mediaVersionId_volumeIndex_idx",
            ["mediaVersionId", "volumeIndex"],
            unique=False,
        )
        batch_op.create_index("LibraryVolume_format_idx", ["format"], unique=False)
        batch_op.create_index(
            "LibraryVolume_identifier_idx", ["identifier"], unique=False
        )
        batch_op.create_index("LibraryVolume_isbn_idx", ["isbn"], unique=False)
        batch_op.create_index(
            "LibraryVolume_resourceKey_idx", ["resourceKey"], unique=False
        )
        batch_op.create_index(
            "LibraryVolume_monitorFolderId_idx", ["monitorFolderId"], unique=False
        )

    for binding_name, table_name, column_name in binding_specs:
        if binding_name == "LibraryConsumptionState.lastUnitId":
            continue
        table = sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind())
        _restore_binding(staging, binding_name, table, table.c[column_name])

    op.create_table(
        "LibraryVolumeFacet",
        sa.Column("facetId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
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
    recreated_volume_facets = sa.Table(
        "LibraryVolumeFacet", sa.MetaData(), autoload_with=op.get_bind()
    )
    op.get_bind().execute(
        sa.insert(recreated_volume_facets).from_select(
            ["facetId", "volumeId", "createdAt"],
            sa.select(
                staging.c.recordId, staging.c.targetId, staging.c.createdAt
            ).where(staging.c.tableName == "LibraryVolumeFacet"),
        )
    )
    op.create_index(
        "LibraryVolumeFacet_volumeId_idx",
        "LibraryVolumeFacet",
        ["volumeId"],
        unique=False,
    )

    with op.batch_alter_table(
        "LibraryFile", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        _drop_index_if_present(
            batch_op, "LibraryFile", "LibraryFile_editionId_sortOrder_idx"
        )
        batch_op.drop_constraint(
            "fk_LibraryFile_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_LibraryFile_volumeId_LibraryVolume", type_="foreignkey"
        )
        batch_op.drop_column("editionId")
        batch_op.alter_column("volumeId", existing_type=sa.String(191), nullable=False)
        batch_op.create_foreign_key(
            "fk_LibraryFile_volumeId_LibraryVolume",
            "LibraryVolume",
            ["volumeId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )

    for binding_name, table_name, column_name in binding_specs:
        if not binding_name.endswith(".fileId"):
            continue
        table = sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind())
        _restore_binding(staging, binding_name, table, table.c[column_name])

    with op.batch_alter_table(
        "LibraryReadingUnit", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        _drop_index_if_present(
            batch_op,
            "LibraryReadingUnit",
            "LibraryReadingUnit_editionId_sortOrder_idx",
        )
        _drop_index_if_present(
            batch_op,
            "LibraryReadingUnit",
            "LibraryReadingUnit_editionId_unitType_idx",
        )
        batch_op.drop_constraint(
            "fk_LibraryReadingUnit_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_LibraryReadingUnit_volumeId_LibraryVolume", type_="foreignkey"
        )
        batch_op.drop_column("editionId")
        batch_op.alter_column("volumeId", existing_type=sa.String(191), nullable=False)
        batch_op.create_foreign_key(
            "fk_LibraryReadingUnit_volumeId_LibraryVolume",
            "LibraryVolume",
            ["volumeId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )

    with op.batch_alter_table(
        "LibraryMetadata", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        _drop_index_if_present(
            batch_op, "LibraryMetadata", "LibraryMetadata_editionId_idx"
        )
        batch_op.drop_constraint(
            "fk_LibraryMetadata_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_column("editionId")
        batch_op.alter_column("volumeId", existing_type=sa.String(191), nullable=False)
        batch_op.create_foreign_key(
            "fk_LibraryMetadata_volumeId_LibraryVolume",
            "LibraryVolume",
            ["volumeId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "LibraryMetadata_volumeId_idx", ["volumeId"], unique=False
        )

    with op.batch_alter_table(
        "LibraryReadingProgress",
        recreate="always",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        for index_name in (
            "LibraryReadingProgress_workId_idx",
            "LibraryReadingProgress_editionId_idx",
            "LibraryReadingProgress_userId_editionId_volumeId_key",
        ):
            _drop_index_if_present(batch_op, "LibraryReadingProgress", index_name)
        batch_op.drop_constraint(
            "fk_LibraryReadingProgress_workId_LibraryWork", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_LibraryReadingProgress_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_LibraryReadingProgress_volumeId_LibraryVolume", type_="foreignkey"
        )
        batch_op.drop_column("workId")
        batch_op.drop_column("editionId")
        batch_op.alter_column("volumeId", existing_type=sa.String(191), nullable=False)
        batch_op.create_foreign_key(
            "fk_LibraryReadingProgress_volumeId_LibraryVolume",
            "LibraryVolume",
            ["volumeId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "LibraryReadingProgress_userId_volumeId_key",
            ["userId", "volumeId"],
            unique=True,
        )

    with op.batch_alter_table(
        "ReaderBookmark", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        _drop_index_if_present(
            batch_op, "ReaderBookmark", "ReaderBookmark_user_edition_idx"
        )
        batch_op.drop_constraint(
            "ReaderBookmark_user_edition_fingerprint_bookmark_key", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_ReaderBookmark_workId_LibraryWork", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_ReaderBookmark_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_column("workId")
        batch_op.drop_column("editionId")
        batch_op.alter_column("volumeId", existing_type=sa.String(191), nullable=False)
        batch_op.create_foreign_key(
            "fk_ReaderBookmark_volumeId_LibraryVolume",
            "LibraryVolume",
            ["volumeId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_unique_constraint(
            "ReaderBookmark_user_volume_fingerprint_bookmark_key",
            ["userId", "volumeId", "contentFingerprint", "bookmarkId"],
        )
        batch_op.create_index(
            "ReaderBookmark_user_volume_idx", ["userId", "volumeId"], unique=False
        )

    op.rename_table("ImportTask", "LegacyImportTask")
    legacy_import_task = sa.Table(
        "LegacyImportTask", sa.MetaData(), autoload_with=op.get_bind()
    )
    for legacy_index_name in _indexes("LegacyImportTask"):
        op.drop_index(legacy_index_name, table_name="LegacyImportTask")
    _create_import_task_contract(legacy_import_task)
    for dependent_table in ("ImportAsset", "ImportLog", "ImportWorkItem"):
        _repoint_import_task_foreign_key(dependent_table)

    with op.batch_alter_table(
        "KindleSendTask", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_KindleSendTask_editionId_LibraryEdition", type_="foreignkey"
        )
        batch_op.drop_column("editionId")
        batch_op.drop_column("editionName")

    for table_name in ("OrganizeJob", "MetadataLookupTask"):
        with op.batch_alter_table(
            table_name, recreate="always", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            _drop_index_if_present(batch_op, table_name, f"{table_name}_editionId_idx")
            batch_op.drop_constraint(
                f"fk_{table_name}_editionId_LibraryEdition", type_="foreignkey"
            )
            batch_op.drop_column("editionId")
            batch_op.drop_constraint(
                f"fk_{table_name}_importTaskId_LegacyImportTask", type_="foreignkey"
            )
            batch_op.create_foreign_key(
                f"fk_{table_name}_importTaskId_ImportTask",
                "ImportTask",
                ["importTaskId"],
                ["id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            )
            batch_op.create_foreign_key(
                f"fk_{table_name}_volumeId_LibraryVolume",
                "LibraryVolume",
                ["volumeId"],
                ["id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            )
            batch_op.create_index(
                f"{table_name}_volumeId_idx", ["volumeId"], unique=False
            )

    with op.batch_alter_table(
        "BookConversionTask", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_BookConversionTask_importTaskId_LegacyImportTask", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_BookConversionTask_importTaskId_ImportTask",
            "ImportTask",
            ["importTaskId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.alter_column(
            "sourceVolumeId", existing_type=sa.String(191), nullable=False
        )
        batch_op.alter_column(
            "idempotencyKey", existing_type=sa.String(191), nullable=False
        )
        batch_op.create_foreign_key(
            "fk_BookConversionTask_sourceVolumeId_LibraryVolume",
            "LibraryVolume",
            ["sourceVolumeId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_BookConversionTask_derivedVolumeId_LibraryVolume",
            "LibraryVolume",
            ["derivedVolumeId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )
        batch_op.create_unique_constraint(
            "BookConversionTask_idempotencyKey_key", ["idempotencyKey"]
        )

    op.drop_table("LegacyImportTask")

    with op.batch_alter_table(
        "UserMediaHistory", recreate="always", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.create_unique_constraint(
            "UserMediaHistory_user_mediaVersion_key", ["userId", "mediaVersionId"]
        )

    op.drop_table("LibraryConsumptionState")
    op.drop_table("LibraryEditionFacet")
    op.drop_table("MediaVersionMigrationCheckpoint")
    op.drop_table("MediaVersionBindingStaging")
    op.drop_table("LibraryEdition")
    op.drop_column("LibraryWork", "primaryEditionId")
    op.drop_column("LibraryWork", "status")


def downgrade() -> None:
    raise RuntimeError(
        "0006_media_versions_contract is intentionally irreversible; restore the pre-migration SQLite snapshot"
    )
