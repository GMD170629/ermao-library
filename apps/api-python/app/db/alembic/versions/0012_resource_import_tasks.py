"""Resource tasks for single-file adapters; never infer historical processed versions."""

import sqlalchemy as sa
from alembic import op

revision = "0012_resource_import_tasks"
down_revision = "0011_incremental_library_scan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "processedSourceVersion" not in {
        c["name"] for c in inspector.get_columns("LibraryResourceAsset")
    }:
        op.add_column(
            "LibraryResourceAsset",
            sa.Column("processedSourceVersion", sa.Text(), nullable=True),
        )
    if "LibraryReadableResource_id_sourceNodeId_key" not in {
        i["name"] for i in inspector.get_indexes("LibraryReadableResource")
    }:
        op.create_index(
            "LibraryReadableResource_id_sourceNodeId_key",
            "LibraryReadableResource",
            ["id", "sourceNodeId"],
            unique=True,
        )
    if "rerunRequested" not in {
        c["name"] for c in inspector.get_columns("LibraryImportTask")
    }:
        kind = sa.column("kind")
        node = sa.column("sourceNodeId")
        resource = sa.column("resourceId")
        role = sa.column("role")
        anchor = sa.column("resourceAnchorNodeId")
        with op.batch_alter_table("LibraryImportTask") as batch:
            batch.add_column(
                sa.Column(
                    "rerunRequested", sa.Boolean(), nullable=False, server_default="0"
                )
            )
            batch.add_column(
                sa.Column("resourceAnchorNodeId", sa.String(191), nullable=True)
            )
            batch.drop_constraint("LibraryImportTask_kind_check", type_="check")
            batch.drop_constraint("LibraryImportTask_kind_shape_check", type_="check")
            batch.create_check_constraint(
                "LibraryImportTask_kind_check",
                kind.in_(
                    (
                        "SCAN_LIBRARY",
                        "CONTINUE_SOURCE",
                        "IMPORT_ASSET",
                        "IMPORT_RESOURCE",
                        "IDENTIFY_BOOK",
                    )
                ),
            )
            batch.create_check_constraint(
                "LibraryImportTask_kind_shape_check",
                sa.or_(
                    sa.and_(
                        kind == "SCAN_LIBRARY",
                        node.is_(None),
                        resource.is_(None),
                        role.is_(None),
                    ),
                    sa.and_(
                        kind.in_(("CONTINUE_SOURCE", "IDENTIFY_BOOK")),
                        node.is_not(None),
                        resource.is_(None),
                        role.is_(None),
                    ),
                    sa.and_(
                        kind == "IMPORT_ASSET",
                        node.is_not(None),
                        resource.is_not(None),
                        role.is_not(None),
                    ),
                    sa.and_(
                        kind == "IMPORT_RESOURCE",
                        node.is_not(None),
                        resource.is_not(None),
                        role.is_(None),
                    ),
                ),
            )
            batch.create_check_constraint(
                "LibraryImportTask_resource_anchor_check",
                sa.or_(
                    sa.and_(
                        kind == "IMPORT_RESOURCE", anchor.is_not(None), anchor == node
                    ),
                    sa.and_(kind != "IMPORT_RESOURCE", anchor.is_(None)),
                ),
            )
            batch.create_foreign_key(
                "fk_LibraryImportTask_resource_anchor",
                "LibraryReadableResource",
                ["resourceId", "resourceAnchorNodeId"],
                ["id", "sourceNodeId"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            )
            batch.create_index(
                "LibraryImportTask_resource_anchor_idx",
                ["resourceId", "resourceAnchorNodeId"],
            )
            batch.create_index(
                "LibraryImportTask_import_resource_key",
                ["resourceId"],
                unique=True,
                sqlite_where=kind == "IMPORT_RESOURCE",
            )

    # Bounded conversion of unfinished single-file work only. Keep the survivor
    # ID and failure state so existing ContinueImport links still work. Assets,
    # navigation and metadata are untouched; their unknown versions remain NULL.
    metadata = sa.MetaData()
    tasks = sa.Table("LibraryImportTask", metadata, autoload_with=bind)
    resources = sa.Table("LibraryReadableResource", metadata, autoload_with=bind)
    while True:
        rows = bind.execute(
            sa.select(tasks.c.id, tasks.c.resourceId, resources.c.sourceNodeId)
            .join(resources, tasks.c.resourceId == resources.c.id)
            .where(
                tasks.c.kind == "IMPORT_ASSET",
                tasks.c.state != "SUCCEEDED",
                resources.c.adapterId.in_(
                    ("epub", "pdf", "txt", "mobi-family", "comic-archive", "audio-file")
                ),
            )
            .order_by(tasks.c.id)
            .limit(100)
        ).all()
        if not rows:
            break
        for task_id, resource_id, anchor_id in rows:
            existing = bind.scalar(
                sa.select(tasks.c.id).where(
                    tasks.c.kind == "IMPORT_RESOURCE", tasks.c.resourceId == resource_id
                )
            )
            if existing is None:
                bind.execute(
                    sa.update(tasks)
                    .where(tasks.c.id == task_id)
                    .values(
                        kind="IMPORT_RESOURCE",
                        sourceNodeId=anchor_id,
                        resourceAnchorNodeId=anchor_id,
                        role=None,
                    )
                )
            else:
                bind.execute(
                    sa.update(tasks)
                    .where(tasks.c.id == existing)
                    .values(state="QUEUED", rerunRequested=False)
                )
                bind.execute(sa.delete(tasks).where(tasks.c.id == task_id))


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade resource imports")
