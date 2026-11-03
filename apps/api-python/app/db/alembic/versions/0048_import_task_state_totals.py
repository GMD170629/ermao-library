"""Use a compact covering state index for exact library task totals."""

import sqlalchemy as sa
from alembic import op

revision = "0048_import_task_state_totals"
down_revision = "0047_source_cleanup_page_index"
branch_labels = None
depends_on = None
INDEX = "LibraryImportTask_library_state_totals_idx"


def upgrade() -> None:
    indexes = {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryImportTask")
    }
    if INDEX not in indexes:
        op.create_index(INDEX, "LibraryImportTask", ["libraryId", "state"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryImportTask")
