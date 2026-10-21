"""Drop obsolete database logs and index global metadata cache expiry."""

import sqlalchemy as sa
from alembic import op

revision = "0043_remove_legacy_system_events"
down_revision = "0042_remove_metadata_task_payloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "SystemEvent" in inspector.get_table_names():
        op.drop_table("SystemEvent")
    index_name = "ExternalMetadataCache_expiresAt_id_idx"
    if not any(
        index["name"] == index_name
        for index in inspector.get_indexes("ExternalMetadataCache")
    ):
        op.create_index(index_name, "ExternalMetadataCache", ["expiresAt", "id"])


def downgrade() -> None:
    raise RuntimeError("Removed historical logs cannot be recovered by downgrade")
