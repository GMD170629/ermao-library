"""Persist AI-generated description/tag ownership without user locks."""

import sqlalchemy as sa
from alembic import op

revision = "0039_generated_metadata_fields"
down_revision = "0038_import_scan_round_fact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("LibraryBookMetadata", "LibraryReadableResourceMetadata"):
        op.add_column(
            table,
            sa.Column(
                "generatedFields", sa.Text(), nullable=False, server_default="[]"
            ),
        )


def downgrade() -> None:
    raise RuntimeError(
        "Restore the pre-upgrade backup to downgrade generated field markers"
    )
