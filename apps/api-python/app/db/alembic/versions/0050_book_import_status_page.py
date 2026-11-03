"""Page minimal import status by immutable import time and book identity."""

import sqlalchemy as sa
from alembic import op

revision = "0050_book_import_status_page"
down_revision = "0049_book_list_identity_indexes"
branch_labels = None
depends_on = None
INDEX = "LibraryBook_library_imported_page_idx"


def upgrade() -> None:
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryBook")}
    if INDEX not in existing:
        op.create_index(
            INDEX, "LibraryBook", ["libraryId", "visibilityState", "createdAt", "id"]
        )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryBook")
