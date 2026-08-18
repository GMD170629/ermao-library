"""Remove UserMediaHistory; reading activity uses LibraryReadingProgress.

Revision ID: 0033_remove_user_media_history
Revises: 0032_library_version_identity
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_remove_user_media_history"
down_revision: str | Sequence[str] | None = "0032_library_version_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("UserMediaHistory")


def downgrade() -> None:
    raise NotImplementedError(
        "0033_remove_user_media_history does not support downgrade"
    )
