"""Cover directory member candidate filtering without loading source-node rows."""

import sqlalchemy as sa
from alembic import op

revision = "0052_directory_member_cover_index"
down_revision = "0051_book_search_cover_index"
branch_labels = None
depends_on = None
INDEX = "LibrarySourceNode_directory_member_cover_idx"
OLD_INDEX = "LibrarySourceNode_libraryId_relativePath_idx"


def upgrade() -> None:
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("LibrarySourceNode")}
    if INDEX not in existing:
        op.create_index(INDEX, "LibrarySourceNode", ["libraryId", "relativePath", "id", "physicalKind"])
    if OLD_INDEX in existing:
        op.drop_index(OLD_INDEX, table_name="LibrarySourceNode")


def downgrade() -> None:
    op.create_index(OLD_INDEX, "LibrarySourceNode", ["libraryId", "relativePath"])
    op.drop_index(INDEX, table_name="LibrarySourceNode")
