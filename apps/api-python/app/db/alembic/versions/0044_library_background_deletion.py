"""Persist library removal; remaining books provide cleanup progress."""

import sqlalchemy as sa
from alembic import op

revision = "0044_library_background_deletion"
down_revision = "0043_remove_legacy_system_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("Library")}
    if "deletionRequestedAt" not in columns:
        op.add_column("Library", sa.Column("deletionRequestedAt", sa.BigInteger(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("Library")}
    if "ix_Library_deletionRequestedAt" not in indexes:
        op.create_index("ix_Library_deletionRequestedAt", "Library", ["deletionRequestedAt"])


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to undo library deletion state")
