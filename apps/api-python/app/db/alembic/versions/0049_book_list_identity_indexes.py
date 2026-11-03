"""Cover book identity counts and ordered pages before metadata hydration."""

import sqlalchemy as sa
from alembic import op

revision = "0049_book_list_identity_indexes"
down_revision = "0048_import_task_state_totals"
branch_labels = None
depends_on = None
INDEXES = {
    "LibraryBook_library_visibility_idx": ["libraryId", "visibilityState"],
    "LibraryBook_library_updated_page_idx": [
        "libraryId",
        "visibilityState",
        "updatedAt",
        "id",
    ],
    "LibraryBook_visible_updated_page_idx": [
        "visibilityState",
        "updatedAt",
        "id",
        "libraryId",
    ],
}


def upgrade() -> None:
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryBook")}
    for name, columns in INDEXES.items():
        if name not in existing:
            op.create_index(name, "LibraryBook", columns)


def downgrade() -> None:
    for name in reversed(INDEXES):
        op.drop_index(name, table_name="LibraryBook")
