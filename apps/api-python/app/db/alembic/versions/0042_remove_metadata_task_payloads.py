"""Remove unused metadata candidate and provider response archives.

For large histories, run app.db.metadata_task_payload_cleanup with API/workers
stopped before upgrading. It backs up and clears payloads in bounded commits,
so native DROP COLUMN need not rewrite hundreds of MiB in one statement.
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_remove_metadata_task_payloads"
down_revision = "0041_system_setting_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in (
        ("MetadataLookupTask", "candidateRawJson"),
        ("MetadataProviderExecution", "rawResultJson"),
    ):
        # Native DROP COLUMN preserves the parent table and its cascade graph.
        # SQLite DDL can survive an interrupted migration without its revision.
        columns = sa.inspect(op.get_bind()).get_columns(table)
        if any(item["name"] == column for item in columns):
            op.drop_column(table, column)


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to recover metadata payloads")
