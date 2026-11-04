"""Cover resource identity and visibility for actor activity queries."""

import sqlalchemy as sa
from alembic import op

revision = "0056_resource_identity_cover"
down_revision = "0055_resource_book_summary_cover"
branch_labels = None
depends_on = None
INDEX = "LibraryReadableResource_identity_cover_idx"


def upgrade() -> None:
    if INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryReadableResource")}:
        op.create_index(INDEX, "LibraryReadableResource", ["id", "bookId", "libraryId", "enablementState", "importState"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryReadableResource")
