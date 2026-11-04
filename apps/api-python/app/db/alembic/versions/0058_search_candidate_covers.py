"""Cover candidate authorization and title ordering without heap lookups."""

import sqlalchemy as sa
from alembic import op

revision = "0058_search_candidate_covers"
down_revision = "0057_book_substring_search"
branch_labels = None
depends_on = None

INDEXES = (
    ("LibraryBook_identity_scope_cover_idx", "LibraryBook", ["id", "visibilityState", "libraryId"]),
    ("LibraryBookMetadata_identity_title_cover_idx", "LibraryBookMetadata", ["bookId", "title"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        if name not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
