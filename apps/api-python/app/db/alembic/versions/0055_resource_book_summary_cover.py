"""Keep all-state resource summaries scoped to selected books."""

import sqlalchemy as sa
from alembic import op

revision = "0055_resource_book_summary_cover"
down_revision = "0054_resource_filter_cover_index"
branch_labels = None
depends_on = None
INDEX = "LibraryReadableResource_book_summary_cover_idx"


def upgrade() -> None:
    if INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryReadableResource")}:
        op.create_index(INDEX, "LibraryReadableResource", ["enablementState", "bookId", "importState", "format", "id"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryReadableResource")
