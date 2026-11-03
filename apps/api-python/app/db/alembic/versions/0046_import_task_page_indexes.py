"""Index library task pages with and without a state filter."""

import sqlalchemy as sa
from alembic import op

revision = "0046_import_task_page_indexes"
down_revision = "0045_source_children_scan_index"
branch_labels = None
depends_on = None

INDEXES = {
    "LibraryImportTask_library_state_page_idx": [
        "libraryId",
        "state",
        "createdAt",
        "id",
    ],
    "LibraryImportTask_library_page_idx": ["libraryId", "createdAt", "id"],
}


def upgrade() -> None:
    existing = {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryImportTask")
    }
    for name, columns in INDEXES.items():
        if name not in existing:
            op.create_index(name, "LibraryImportTask", columns)


def downgrade() -> None:
    for name in reversed(INDEXES):
        op.drop_index(name, table_name="LibraryImportTask")
