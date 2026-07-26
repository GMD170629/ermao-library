"""Add the reliable appv2 ingestion pipeline.

Revision ID: 0002_ingestion_pipeline
Revises: 0001_appv2_initial
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ingestion_pipeline"
down_revision: str | None = "0001_appv2_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now = datetime.now(UTC)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    folder_columns = {
        str(column["name"])
        for column in inspector.get_columns("monitor_folders", schema="ingestion")
    }
    if "move_source" in folder_columns:
        op.drop_column("monitor_folders", "move_source", schema="ingestion")

    job_columns = {
        str(column["name"]) for column in inspector.get_columns("jobs", schema="ingestion")
    }
    if "result_id" in job_columns and "result_edition_id" not in job_columns:
        op.alter_column(
            "jobs",
            "result_id",
            new_column_name="result_edition_id",
            schema="ingestion",
        )
    requested_by = next(
        column
        for column in inspector.get_columns("jobs", schema="ingestion")
        if column["name"] == "requested_by"
    )
    if not requested_by["nullable"]:
        op.alter_column("jobs", "requested_by", nullable=True, schema="ingestion")
    job_additions = {
        "origin": sa.Column("origin", sa.String(20), nullable=False, server_default="manual"),
        "stage": sa.Column("stage", sa.String(50), nullable=False, server_default="queued"),
        "progress": sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        "monitor_folder_id": sa.Column("monitor_folder_id", sa.Uuid(), nullable=True),
        "triggered_by": sa.Column(
            "triggered_by", sa.String(20), nullable=False, server_default="user"
        ),
        "cancel_requested": sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        "result_work_id": sa.Column("result_work_id", sa.Uuid()),
        "result_volume_ids": sa.Column(
            "result_volume_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        "retryable": sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
        "started_at": sa.Column("started_at", sa.DateTime(timezone=True)),
        "finished_at": sa.Column("finished_at", sa.DateTime(timezone=True)),
    }
    for name, column in job_additions.items():
        if name not in job_columns:
            op.add_column("jobs", column, schema="ingestion")
    check_names = {
        str(item["name"]) for item in inspector.get_check_constraints("jobs", schema="ingestion")
    }
    if "ck_jobs_progress_valid" not in check_names and "progress_valid" not in check_names:
        op.create_check_constraint(
            "ck_jobs_progress_valid",
            "jobs",
            "progress >= 0 AND progress <= 100",
            schema="ingestion",
        )
    foreign_keys = {
        str(item["name"]) for item in inspector.get_foreign_keys("jobs", schema="ingestion")
    }
    if "fk_jobs_monitor_folder_id_monitor_folders" not in foreign_keys:
        op.create_foreign_key(
            "fk_jobs_monitor_folder_id_monitor_folders",
            "jobs",
            "monitor_folders",
            ["monitor_folder_id"],
            ["id"],
            source_schema="ingestion",
            referent_schema="ingestion",
            ondelete="SET NULL",
        )

    if not inspector.has_table("monitor_observations", schema="ingestion"):
        op.create_table(
            "monitor_observations",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("monitor_folder_id", sa.Uuid(), nullable=False),
            sa.Column("normalized_path", sa.Text(), nullable=False),
            sa.Column("source_kind", sa.String(20), nullable=False, server_default="file"),
            sa.Column("import_job_id", sa.Uuid()),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["monitor_folder_id"],
                ["ingestion.monitor_folders.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["import_job_id"],
                ["ingestion.jobs.id"],
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint(
                "monitor_folder_id",
                "normalized_path",
                name="uq_monitor_observations_folder_path",
            ),
            schema="ingestion",
        )
        op.create_index(
            "ix_ingestion_observations_seen",
            "monitor_observations",
            ["monitor_folder_id", "last_seen_at"],
            schema="ingestion",
        )
    if not inspector.has_table("scan_runs", schema="ingestion"):
        op.create_table(
            "scan_runs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("trigger", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("monitor_folder_id", sa.Uuid()),
            sa.Column("requested_by", sa.Uuid()),
            sa.Column("directories_scanned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("files_scanned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("candidates_found", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("queued", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ignored", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "errors",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'completed', 'failed')",
                name="ck_scan_runs_status_valid",
            ),
            sa.ForeignKeyConstraint(
                ["monitor_folder_id"],
                ["ingestion.monitor_folders.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["requested_by"], ["accounts.users.id"]),
            schema="ingestion",
        )
        op.create_index(
            "ix_ingestion_scan_runs_claim",
            "scan_runs",
            ["status", "created_at"],
            schema="ingestion",
        )
    if not inspector.has_table("outbox", schema="ingestion"):
        op.create_table(
            "outbox",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("aggregate_id", sa.Uuid(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("idempotency_key", sa.String(200), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("error_detail", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
            schema="ingestion",
        )
        op.create_index(
            "ix_ingestion_outbox_pending",
            "outbox",
            ["published_at", "created_at"],
            schema="ingestion",
        )
    if not inspector.has_table("policies", schema="ingestion"):
        op.create_table(
            "policies",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("allowed_extensions", postgresql.JSONB(), nullable=False),
            sa.Column("ignore_patterns", postgresql.JSONB(), nullable=False),
            sa.Column("stability_check_enabled", sa.Boolean(), nullable=False),
            sa.Column("stability_check_seconds", sa.Integer(), nullable=False),
            sa.Column("auto_convert_to_epub", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("name", name="uq_policies_name"),
            schema="ingestion",
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO ingestion.policies (
                id, name, allowed_extensions, ignore_patterns,
                stability_check_enabled, stability_check_seconds,
                auto_convert_to_epub, created_at, updated_at
            ) VALUES (
                :id, 'default', CAST(:extensions AS jsonb), '[]'::jsonb,
                true, 2, true, :now, :now
            )
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {
            "id": uuid.uuid4(),
            "extensions": (
                '[".epub",".mobi",".azw",".azw3",".prc",".fb2",".txt",'
                '".pdf",".cbz",".zip",".m4b",".m4a",".mp3"]'
            ),
            "now": now,
        },
    )

    metadata_job_columns = {
        str(column["name"]) for column in inspector.get_columns("jobs", schema="metadata")
    }
    if "requested_by" in metadata_job_columns:
        metadata_requested_by = next(
            column
            for column in inspector.get_columns("jobs", schema="metadata")
            if column["name"] == "requested_by"
        )
        if not metadata_requested_by["nullable"]:
            op.alter_column(
                "jobs",
                "requested_by",
                nullable=True,
                schema="metadata",
            )
    if not inspector.has_table("organize_policy", schema="metadata"):
        op.create_table(
            "organize_policy",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column(
                "schedule_mode",
                sa.String(20),
                nullable=False,
                server_default="MANUAL",
            ),
            sa.Column("interval_minutes", sa.Integer()),
            sa.Column(
                "auto_run_on_new",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "provider_scope",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "overwrite_fields",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "rules",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "schedule_mode IN ('MANUAL', 'INTERVAL')",
                name="ck_organize_policy_schedule_mode_valid",
            ),
            sa.UniqueConstraint(
                "name",
                name="uq_metadata_organize_policy_name",
            ),
            schema="metadata",
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO metadata.organize_policy (
                id, name, schedule_mode, interval_minutes, auto_run_on_new,
                provider_scope, overwrite_fields, rules, created_at, updated_at
            ) VALUES (
                :id, 'default', 'MANUAL', NULL, false,
                '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, :now, :now
            )
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {"id": uuid.uuid4(), "now": now},
    )


def downgrade() -> None:
    op.drop_table("organize_policy", schema="metadata")
    op.alter_column("jobs", "requested_by", nullable=False, schema="metadata")
    op.drop_table("policies", schema="ingestion")
    op.drop_index("ix_ingestion_outbox_pending", table_name="outbox", schema="ingestion")
    op.drop_table("outbox", schema="ingestion")
    op.drop_index("ix_ingestion_scan_runs_claim", table_name="scan_runs", schema="ingestion")
    op.drop_table("scan_runs", schema="ingestion")
    op.drop_index(
        "ix_ingestion_observations_seen",
        table_name="monitor_observations",
        schema="ingestion",
    )
    op.drop_table("monitor_observations", schema="ingestion")
    op.drop_constraint(
        "fk_jobs_monitor_folder_id_monitor_folders",
        "jobs",
        schema="ingestion",
        type_="foreignkey",
    )
    op.drop_constraint("ck_jobs_progress_valid", "jobs", schema="ingestion", type_="check")
    for column in (
        "finished_at",
        "started_at",
        "retryable",
        "result_volume_ids",
        "result_work_id",
        "cancel_requested",
        "triggered_by",
        "monitor_folder_id",
        "progress",
        "stage",
        "origin",
    ):
        op.drop_column("jobs", column, schema="ingestion")
    op.alter_column(
        "jobs",
        "result_edition_id",
        new_column_name="result_id",
        schema="ingestion",
    )
    op.alter_column("jobs", "requested_by", nullable=False, schema="ingestion")
    op.add_column(
        "monitor_folders",
        sa.Column("move_source", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="ingestion",
    )
