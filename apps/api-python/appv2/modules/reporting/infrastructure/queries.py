from __future__ import annotations

import uuid

from sqlalchemy import Engine, text

from appv2.modules.reporting.contracts import (
    DashboardProjection,
    LibraryFilterSchema,
    LibraryQuery,
    LibraryWorkProjection,
    ManagementProjection,
    ReportingReadPort,
)
from appv2.modules.reporting.infrastructure.library_filters import (
    DATE_OPERATORS,
    NUMBER_OPERATORS,
    SELECT_OPERATORS,
    TEXT_OPERATORS,
    SqlParams,
    condition_clause,
    option,
    reading_status_clause,
)


class SqlReportingQueries(ReportingReadPort):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def library(
        self,
        account_id: uuid.UUID,
        query: LibraryQuery,
    ) -> tuple[list[LibraryWorkProjection], int]:
        params: SqlParams = {"account_id": account_id}
        clauses = ["w.status = 'active'"]
        if query.query:
            params["query"] = f"%{query.query}%"
            clauses.append(
                "(w.title ILIKE :query OR coalesce(w.author, '') ILIKE :query "
                "OR coalesce(w.summary, '') ILIKE :query)"
            )
        if query.media_type:
            params["media_type"] = query.media_type
            clauses.append("w.media_type = :media_type")
        if query.series_name:
            params["series_name"] = query.series_name
            clauses.append("w.metadata ->> 'seriesName' = :series_name")
        if query.reading_status:
            clauses.append(reading_status_clause(query.reading_status))
        smart_clauses = [
            condition_clause(condition, index, params)
            for index, condition in enumerate(query.filters.conditions)
        ]
        if smart_clauses:
            joiner = " AND " if query.filters.combinator == "ALL" else " OR "
            clauses.append(f"({joiner.join(smart_clauses)})")
        where = " AND ".join(clauses)
        direction = "ASC" if query.sort_direction == "asc" else "DESC"
        order_expressions = {
            "recent_read": (
                "(SELECT max(sort_progress.updated_at) "
                "FROM reading.progress AS sort_progress "
                "JOIN catalog.editions AS sort_edition "
                "ON sort_edition.id = sort_progress.edition_id "
                "WHERE sort_progress.user_id = :account_id "
                "AND sort_edition.work_id = w.id)"
            ),
            "recent_import": "w.created_at",
            "title": "lower(w.sort_title)",
            "author": "lower(coalesce(w.author, ''))",
            "publisher": "lower(coalesce(w.metadata ->> 'publisher', ''))",
            "series": "lower(coalesce(w.metadata ->> 'seriesName', ''))",
        }
        order = order_expressions[query.sort]
        params["limit"] = query.page_size
        params["offset"] = (query.page - 1) * query.page_size
        with self._engine.connect() as connection:
            total = int(
                connection.execute(
                    # Clauses are assembled only from the fixed expressions above.
                    text(f"SELECT count(*) FROM catalog.works AS w WHERE {where}"),  # noqa: S608
                    params,
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    text(
                        # WHERE, ORDER BY, and direction are fixed whitelist fragments.
                        f"""
                    SELECT
                      w.id, w.title, w.author, w.media_type, w.status, w.cover_key,
                      w.summary, w.metadata, w.created_at, w.updated_at
                    FROM catalog.works AS w
                    WHERE {where}
                    ORDER BY {order} {direction} NULLS LAST, w.id ASC
                    LIMIT :limit OFFSET :offset
                    """  # noqa: S608
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return (
            [
                LibraryWorkProjection(
                    id=row["id"],
                    title=str(row["title"]),
                    author=str(row["author"]) if row["author"] is not None else None,
                    media_type=str(row["media_type"]),
                    status=str(row["status"]),
                    cover_key=(str(row["cover_key"]) if row["cover_key"] is not None else None),
                    summary=str(row["summary"]) if row["summary"] is not None else None,
                    metadata=dict(row["metadata"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ],
            total,
        )

    def library_filter_schema(self, account_id: uuid.UUID) -> LibraryFilterSchema:
        with self._engine.connect() as connection:
            option_rows = connection.execute(
                text(
                    """
                    SELECT 'language' AS source, language AS value, count(*) AS count
                    FROM catalog.editions
                    WHERE coalesce(language, '') <> ''
                    GROUP BY language
                    UNION ALL
                    SELECT 'format', format, count(*) FROM catalog.editions GROUP BY format
                    ORDER BY source, count DESC, value
                    """
                )
            ).mappings()
            options: dict[str, list[dict[str, object]]] = {
                "language": [],
                "format": [],
            }
            for row in option_rows:
                options[str(row["source"])].append(option(row["value"], row["value"], row["count"]))
            shelf_rows = connection.execute(
                text(
                    """
                    SELECT s.id, s.name, count(i.id) AS count
                    FROM catalog.shelves AS s
                    LEFT JOIN catalog.shelf_items AS i ON i.shelf_id = s.id
                    WHERE s.owner_id = :account_id AND s.kind = 'manual'
                    GROUP BY s.id, s.name
                    ORDER BY lower(s.name), s.id
                    """
                ),
                {"account_id": account_id},
            ).mappings()
            options["shelf"] = [option(row["id"], row["name"], row["count"]) for row in shelf_rows]
        fields: tuple[dict[str, object], ...] = (
            {
                "key": "title",
                "label": "书名",
                "group": "作品元数据",
                "type": "text",
                "operators": list(TEXT_OPERATORS),
            },
            {
                "key": "author",
                "label": "作者",
                "group": "作品元数据",
                "type": "text",
                "operators": list(TEXT_OPERATORS),
            },
            {
                "key": "description",
                "label": "简介",
                "group": "作品元数据",
                "type": "text",
                "operators": list(TEXT_OPERATORS),
            },
            {
                "key": "series",
                "label": "丛书",
                "group": "作品元数据",
                "type": "text",
                "operators": list(TEXT_OPERATORS),
            },
            {
                "key": "language",
                "label": "语言",
                "group": "版本元数据",
                "type": "select",
                "operators": list(SELECT_OPERATORS),
                "options": options["language"],
                "allowCustom": True,
            },
            {
                "key": "format",
                "label": "文件格式",
                "group": "格式与文件",
                "type": "select",
                "operators": list(SELECT_OPERATORS),
                "options": options["format"],
                "allowCustom": True,
            },
            {
                "key": "fileSize",
                "label": "文件总大小",
                "group": "格式与文件",
                "type": "number",
                "operators": list(NUMBER_OPERATORS),
                "unit": "MB",
            },
            {
                "key": "pageCount",
                "label": "页数",
                "group": "格式与文件",
                "type": "number",
                "operators": list(NUMBER_OPERATORS),
            },
            {
                "key": "duration",
                "label": "时长",
                "group": "格式与文件",
                "type": "number",
                "operators": list(NUMBER_OPERATORS),
                "unit": "分钟",
            },
            {
                "key": "versionCount",
                "label": "版本数量",
                "group": "格式与文件",
                "type": "number",
                "operators": list(NUMBER_OPERATORS),
            },
            {
                "key": "readingStatus",
                "label": "阅读状态",
                "group": "阅读与整理",
                "type": "select",
                "operators": list(SELECT_OPERATORS),
                "options": [
                    option("UNREAD", "未开始"),
                    option("READING", "进行中"),
                    option("FINISHED", "已完成"),
                ],
            },
            {
                "key": "progress",
                "label": "阅读进度",
                "group": "阅读与整理",
                "type": "number",
                "operators": list(NUMBER_OPERATORS),
                "unit": "%",
            },
            {
                "key": "lastReadAt",
                "label": "最近阅读时间",
                "group": "阅读与整理",
                "type": "date",
                "operators": list(DATE_OPERATORS),
            },
            {
                "key": "hasCover",
                "label": "有封面",
                "group": "阅读与整理",
                "type": "boolean",
                "operators": ["is_true", "is_false"],
            },
            {
                "key": "shelf",
                "label": "所在普通书架",
                "group": "来源与归档",
                "type": "select",
                "operators": list(SELECT_OPERATORS),
                "options": options["shelf"],
            },
            {
                "key": "createdAt",
                "label": "加入时间",
                "group": "来源与归档",
                "type": "date",
                "operators": list(DATE_OPERATORS),
            },
            {
                "key": "updatedAt",
                "label": "最后更新时间",
                "group": "来源与归档",
                "type": "date",
                "operators": list(DATE_OPERATORS),
            },
        )
        return LibraryFilterSchema(fields=fields, max_conditions=30)

    def dashboard(self, account_id: uuid.UUID) -> DashboardProjection:
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
            reading = connection.execute(
                text(
                    """
                    SELECT
                      w.id,
                      w.title,
                      w.author,
                      w.media_type,
                      e.id AS edition_id,
                      p.percentage,
                      p.position,
                      p.updated_at AS last_read_at
                    FROM reading.progress AS p
                    JOIN catalog.editions AS e ON e.id = p.edition_id
                    JOIN catalog.works AS w ON w.id = e.work_id
                    WHERE p.user_id = :account_id
                      AND w.status = 'active'
                    ORDER BY p.updated_at DESC
                    LIMIT 10
                    """
                ),
                {"account_id": account_id},
            ).mappings()
            recent_reading = tuple(
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "author": row["author"],
                    "mediaType": row["media_type"],
                    "editionId": str(row["edition_id"]),
                    "progress": float(row["percentage"]) * 100,
                    "position": dict(row["position"]),
                    "lastReadAt": row["last_read_at"].isoformat(),
                }
                for row in reading
            )
        return DashboardProjection(
            work_count=int(counts["works"]),
            edition_count=int(counts["editions"]),
            active_readers=int(counts["readers"]),
            queued_jobs=int(counts["queued"]),
            continue_item=recent_reading[0] if recent_reading else None,
            recent_reading=recent_reading,
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
