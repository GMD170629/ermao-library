"""Merge unfinished audio-track work into the existing resource queue."""

import sqlalchemy as sa
from alembic import op

revision = "0014_audio_resource_tasks"
down_revision = "0013_image_resource_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tasks = sa.Table("LibraryImportTask", metadata, autoload_with=bind)
    resources = sa.Table("LibraryReadableResource", metadata, autoload_with=bind)
    while True:
        rows = bind.execute(
            sa.select(resources.c.id, resources.c.sourceNodeId)
            .join(tasks, tasks.c.resourceId == resources.c.id)
            .where(
                resources.c.format == "AUDIOBOOK_DIR",
                tasks.c.kind == "IMPORT_ASSET",
                tasks.c.state != "SUCCEEDED",
            )
            .distinct()
            .limit(100)
        ).all()
        if not rows:
            break
        for resource_id, anchor_id in rows:
            survivor = bind.scalar(
                sa.select(tasks.c.id).where(
                    tasks.c.resourceId == resource_id, tasks.c.kind == "IMPORT_RESOURCE"
                )
            )
            pending = bind.scalar(
                sa.select(tasks.c.id)
                .where(
                    tasks.c.resourceId == resource_id,
                    tasks.c.kind == "IMPORT_ASSET",
                    tasks.c.state == "QUEUED",
                )
                .limit(1)
            )
            if survivor is None:
                survivor = bind.scalar(
                    sa.select(tasks.c.id)
                    .where(
                        tasks.c.resourceId == resource_id,
                        tasks.c.kind == "IMPORT_ASSET",
                        tasks.c.state != "SUCCEEDED",
                    )
                    .order_by(tasks.c.id)
                    .limit(1)
                )
                bind.execute(
                    sa.update(tasks)
                    .where(tasks.c.id == survivor)
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
                    .where(tasks.c.id == survivor)
                    .values(
                        state="QUEUED",
                        rerunRequested=False,
                        finishedAt=None,
                        errorSummary=None,
                    )
                )
            if pending is not None:
                bind.execute(
                    sa.update(tasks)
                    .where(tasks.c.id == survivor)
                    .values(
                        state="QUEUED",
                        finishedAt=None,
                        startedAt=None,
                        errorSummary=None,
                    )
                )
            bind.execute(
                sa.delete(tasks).where(
                    tasks.c.resourceId == resource_id,
                    tasks.c.kind == "IMPORT_ASSET",
                    tasks.c.state != "SUCCEEDED",
                )
            )
    # Asset IDs, progress and metadata are preserved. Unknown processed versions
    # remain NULL; the first resource execution conservatively checks those files.


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade audio imports")
