"""Normalize stored settings to JSON and prevent literal-text writes."""

import sqlalchemy as sa
from alembic import op

revision = "0041_system_setting_json"
down_revision = "0040_periodic_scan_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table(
        "SystemSetting", sa.column("key", sa.String), sa.column("value", sa.Text)
    )
    # Preserve already encoded values and quote legacy strings exactly once.
    # Timestamp columns are deliberately untouched by this representation change.
    op.get_bind().execute(
        settings.update()
        .where(sa.func.json_valid(settings.c.value) == 0)
        .values(value=sa.func.json_quote(settings.c.value))
    )
    with op.batch_alter_table("SystemSetting") as batch:
        batch.create_check_constraint(
            "SystemSetting_value_json", sa.func.json_valid(sa.column("value"))
        )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade setting encoding")
