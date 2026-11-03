"""Cover bounded source-node cleanup pages before joining library roots."""

import sqlalchemy as sa
from alembic import op

revision = "0047_source_cleanup_page_index"
down_revision = "0046_import_task_page_indexes"
branch_labels = None
depends_on = None
INDEX = "LibrarySourceNode_cleanup_page_idx"


def upgrade() -> None:
    existing = {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibrarySourceNode")
    }
    if INDEX not in existing:
        op.create_index(INDEX, "LibrarySourceNode", ["id", "libraryId", "relativePath"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibrarySourceNode")
