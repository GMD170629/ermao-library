"""Scan only searchable metadata before matching authorized book identities."""

import sqlalchemy as sa
from alembic import op

revision = "0051_book_search_cover_index"
down_revision = "0050_book_import_status_page"
branch_labels = None
depends_on = None
INDEX = "LibraryBookMetadata_search_cover_idx"


def upgrade() -> None:
    indexes = {
        i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibraryBookMetadata")
    }
    if INDEX not in indexes:
        op.create_index(
            INDEX,
            "LibraryBookMetadata",
            ["bookId", "title", "author", "seriesName", "description"],
        )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibraryBookMetadata")
