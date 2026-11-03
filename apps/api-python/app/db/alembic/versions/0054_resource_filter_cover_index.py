"""Cover readable-resource filter counts without resource heap scans."""

import sqlalchemy as sa
from alembic import op

revision = "0054_resource_filter_cover_index"
down_revision = "0053_book_recent_import_page"
branch_labels = None
depends_on = None
INDEX = "LibraryReadableResource_filter_cover_idx"


def upgrade() -> None:
    if INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryReadableResource")}:
        op.create_index(INDEX, "LibraryReadableResource", ["enablementState", "importState", "bookId", "libraryId", "format"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryReadableResource")
