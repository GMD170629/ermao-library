from __future__ import annotations

from sqlalchemy import Engine, text

from appv2.modules.reporting.contracts import (
    DashboardProjection,
    ManagementProjection,
    ReportingReadPort,
)


class SqlReportingQueries(ReportingReadPort):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def dashboard(self) -> DashboardProjection:
        with self._engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        """
                    SELECT
                      (SELECT count(*) FROM catalog.works WHERE status = 'active') AS works,
                      (SELECT count(*) FROM catalog.editions) AS editions,
                      (SELECT count(DISTINCT user_id) FROM reading.progress
                         WHERE updated_at >= now() - interval '30 days') AS readers,
                      (SELECT count(*) FROM ingestion.jobs
                         WHERE status IN ('queued', 'retry', 'running'))
                      + (SELECT count(*) FROM discovery.download_jobs
                         WHERE status IN ('queued', 'retry', 'running'))
                      + (SELECT count(*) FROM delivery.jobs
                         WHERE status IN ('queued', 'retry', 'running')) AS queued
                    """
                    )
                )
                .mappings()
                .one()
            )
            recent = connection.execute(
                text(
                    """
                    SELECT id, title, author, media_type, updated_at
                    FROM catalog.works
                    WHERE status = 'active'
                    ORDER BY updated_at DESC
                    LIMIT 12
                    """
                )
            ).mappings()
            recent_items = tuple(
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "author": row["author"],
                    "mediaType": row["media_type"],
                    "updatedAt": row["updated_at"].isoformat(),
                }
                for row in recent
            )
        return DashboardProjection(
            work_count=int(counts["works"]),
            edition_count=int(counts["editions"]),
            active_readers=int(counts["readers"]),
            queued_jobs=int(counts["queued"]),
            recent_items=recent_items,
        )

    def management(self) -> ManagementProjection:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT
                      (SELECT count(*) FROM accounts.users
                         WHERE disabled_at IS NULL) AS users,
                      (SELECT count(*) FROM catalog.works) AS works,
                      (SELECT count(*) FROM catalog.files) AS files,
                      (SELECT count(*) FROM ingestion.jobs
                         WHERE status IN ('queued', 'retry', 'running')) AS imports,
                      (SELECT count(*) FROM discovery.download_jobs
                         WHERE status IN ('queued', 'retry', 'running')) AS downloads,
                      (SELECT count(*) FROM delivery.jobs
                         WHERE status IN ('queued', 'retry', 'running')) AS deliveries,
                      (SELECT count(*) FROM ingestion.jobs WHERE status = 'failed')
                      + (SELECT count(*) FROM metadata.jobs WHERE status = 'failed')
                      + (SELECT count(*) FROM discovery.download_jobs WHERE status = 'failed')
                      + (SELECT count(*) FROM delivery.jobs WHERE status = 'failed') AS failed
                    """
                    )
                )
                .mappings()
                .one()
            )
        return ManagementProjection(
            users=int(row["users"]),
            works=int(row["works"]),
            files=int(row["files"]),
            queued_imports=int(row["imports"]),
            queued_downloads=int(row["downloads"]),
            queued_deliveries=int(row["deliveries"]),
            failed_jobs=int(row["failed"]),
        )
