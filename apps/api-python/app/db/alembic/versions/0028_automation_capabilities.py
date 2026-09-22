"""Reset unpublished automation capabilities without rotating credentials."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0028_automation_capabilities"
down_revision = "0027_automation_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    grants = sa.table("AutomationGrant", sa.column("scopes", sa.JSON))
    op.get_bind().execute(grants.update().values(scopes=["system:read"]))
    settings = sa.table(
        "SystemSetting", sa.column("key", sa.String), sa.column("value", sa.Text)
    )
    for key, raw in op.get_bind().execute(sa.select(settings.c.key, settings.c.value)):
        if key != "automation.mcp":
            continue
        value = json.loads(raw)
        value["enabled_scopes"] = ["system:read"]
        op.get_bind().execute(
            settings.update()
            .where(settings.c.key == key)
            .values(value=json.dumps(value))
        )
    # Rebuilding this parent table would cascade-delete historical receipts.
    # Supported SQLite runtimes provide native DROP COLUMN (3.35+).
    op.drop_column("AutomationGrant", "writebackTargets")
    op.drop_column("AutomationGrant", "allowCrossLibrary")


def downgrade() -> None:
    raise RuntimeError("Capability reset requires restoring the pre-migration backup")
