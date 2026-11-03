"""Page global recent imports before hydrating the selected Books."""

import sqlalchemy as sa
from alembic import op

revision = "0053_book_recent_import_page"
down_revision = "0052_directory_member_cover_index"
branch_labels = None
depends_on = None
INDEX = "LibraryBook_visible_imported_page_idx"


def upgrade() -> None:
    if INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryBook")}:
        op.create_index(INDEX, "LibraryBook", ["visibilityState", "createdAt", "id", "libraryId"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryBook")
