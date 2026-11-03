"""Bound ordered child reconciliation to a single parent directory."""

import sqlalchemy as sa
from alembic import op

revision = "0045_source_children_scan_index"
down_revision = "0044_library_background_deletion"
branch_labels = None
depends_on = None

INDEX = "LibrarySourceNode_parent_path_scan_idx"


def upgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("LibrarySourceNode")
    if not any(index["name"] == INDEX for index in indexes):
        op.create_index(
            INDEX,
            "LibrarySourceNode",
            ["libraryId", "parentId", "pathKey", "id", "scanSeenGeneration"],
        )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="LibrarySourceNode")
