from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
import re
from time import time_ns
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.authorization import authorization_context, edition_visibility_sql, work_visibility_sql
from app.core.time import now_timestamp_ms, timestamp_ms_to_iso, to_timestamp_ms
from app.models.auth import User
from app.services.book_identity import UNKNOWN_AUTHOR, identity_merge_key, normalize_identity_part
from app.services.library_filters import compile_filter_rules


FACET_KINDS = {"AUTHOR", "TAG", "SERIES", "PUBLISHER"}
STATUS_RANK = {"UNREAD": 0, "READING": 1, "FINISHED": 2}
WORK_RESTORE_COLUMNS = {
    "monitorFolderId", "origin", "title", "normalizedTitle", "author", "normalizedAuthor",
    "description", "workType", "status", "publicationStatus", "trackingStatus", "localLatestVolume",
    "localLatestChapter", "localLatestTitle", "localLatestAt", "tags", "seriesName", "seriesIndex",
    "publishedYear", "metadataQuality", "organizeStatus", "coverPath", "coverStatus", "hidden",
    "organized", "primaryEditionId", "mergeKey", "updatedAt",
}
EDITION_RESTORE_COLUMNS = {
    "workId", "monitorFolderId", "origin", "mediaKind", "format", "versionName", "versionKey",
    "sourceGroupKey", "description", "language", "publisher", "publishedAt", "identifier", "isbn",
    "importStatus", "importError", "sizeBytes", "pageCount", "chapterCount", "durationMs", "trackCount",
    "narrator", "abridged", "coverPath", "coverStatus", "primary", "hidden", "updatedAt",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(text(sql), params or {}).mappings().all()]


def _row(db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    item = db.execute(text(sql), params or {}).mappings().first()
    return dict(item) if item else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _parse_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _table_exists(db: Session, table: str) -> bool:
    return db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table"),
        {"table": table},
    ).scalar() is not None


def _normalized_name(value: Any) -> str:
    return normalize_identity_part(str(value or "").strip())


def _unique_names(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = re.sub(r"\s+", " ", str(value or "")).strip()
        normalized = _normalized_name(name)
        if not name or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(name)
    return result


def split_authors(value: Any) -> list[str]:
    text_value = str(value or "").strip()
    if not text_value or text_value == UNKNOWN_AUTHOR:
        return []
    return _unique_names(re.split(r"\s*(?:,|，|;|；|、|/|&|\band\b)\s*", text_value, flags=re.I))


def _work_tags(value: Any) -> list[str]:
    parsed = _parse_json(value, [])
    if isinstance(parsed, list):
        return _unique_names(parsed)
    return _unique_names(re.split(r"[,，;；\n]", str(value or "")))


def _facet_id(kind: str, normalized_name: str) -> str:
    digest = sha1(f"{kind}\0{normalized_name}".encode("utf-8")).hexdigest()[:24]
    return f"facet_{digest}"


def _ensure_facet(db: Session, kind: str, name: str) -> str:
    normalized = _normalized_name(name)
    if kind not in FACET_KINDS or not normalized:
        raise ValueError("分类名称无效")
    existing = _row(
        db,
        "SELECT `id` FROM `LibraryFacet` WHERE `kind` = :kind AND `normalizedName` = :normalized",
        {"kind": kind, "normalized": normalized},
    )
    if existing:
        return str(existing["id"])
    facet_id = _facet_id(kind, normalized)
    now = _now()
    db.execute(
        text(
            "INSERT OR IGNORE INTO `LibraryFacet` "
            "(`id`, `kind`, `name`, `normalizedName`, `aliases`, `createdAt`, `updatedAt`) "
            "VALUES (:id, :kind, :name, :normalized, '[]', :now, :now)"
        ),
        {"id": facet_id, "kind": kind, "name": name, "normalized": normalized, "now": now},
    )
    return facet_id


def sync_work_facets(db: Session, work_id: str, *, commit: bool = True) -> None:
    if not {"LibraryWork", "LibraryEdition", "LibraryFacet", "LibraryWorkFacet", "LibraryEditionFacet"}.issubset(
        {table for table in ("LibraryWork", "LibraryEdition", "LibraryFacet", "LibraryWorkFacet", "LibraryEditionFacet") if _table_exists(db, table)}
    ):
        return
    work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": work_id})
    if not work:
        return
    now = _now()
    db.execute(text("DELETE FROM `LibraryWorkFacet` WHERE `workId` = :work_id"), {"work_id": work_id})
    work_values = {
        "AUTHOR": split_authors(work.get("author")),
        "TAG": _work_tags(work.get("tags")),
        "SERIES": _unique_names([work.get("seriesName")]),
    }
    for kind, names in work_values.items():
        for sort_order, name in enumerate(names):
            facet_id = _ensure_facet(db, kind, name)
            db.execute(
                text(
                    "INSERT OR IGNORE INTO `LibraryWorkFacet` (`facetId`, `workId`, `sortOrder`, `createdAt`) "
                    "VALUES (:facet_id, :work_id, :sort_order, :now)"
                ),
                {"facet_id": facet_id, "work_id": work_id, "sort_order": sort_order, "now": now},
            )

    editions = _rows(
        db,
        "SELECT `id`, `publisher` FROM `LibraryEdition` WHERE `workId` = :work_id",
        {"work_id": work_id},
    )
    for edition in editions:
        edition_id = str(edition["id"])
        db.execute(text("DELETE FROM `LibraryEditionFacet` WHERE `editionId` = :edition_id"), {"edition_id": edition_id})
        for publisher in _unique_names([edition.get("publisher")]):
            facet_id = _ensure_facet(db, "PUBLISHER", publisher)
            db.execute(
                text(
                    "INSERT OR IGNORE INTO `LibraryEditionFacet` (`facetId`, `editionId`, `createdAt`) "
                    "VALUES (:facet_id, :edition_id, :now)"
                ),
                {"facet_id": facet_id, "edition_id": edition_id, "now": now},
            )
    if commit:
        db.commit()


def backfill_library_facets(db: Session) -> int:
    if not {"LibraryWork", "LibraryEdition", "LibraryFacet", "LibraryWorkFacet", "LibraryEditionFacet"}.issubset(
        {table for table in ("LibraryWork", "LibraryEdition", "LibraryFacet", "LibraryWorkFacet", "LibraryEditionFacet") if _table_exists(db, table)}
    ):
        return 0
    work_ids = [str(row["id"]) for row in _rows(db, "SELECT `id` FROM `LibraryWork`")] 
    for work_id in work_ids:
        sync_work_facets(db, work_id, commit=False)
    db.execute(
        text(
            "DELETE FROM `LibraryFacet` WHERE `id` NOT IN "
            "(SELECT `facetId` FROM `LibraryWorkFacet` UNION SELECT `facetId` FROM `LibraryEditionFacet`)"
        )
    )
    db.commit()
    return len(work_ids)


def count_categories(db: Session, kind: str, search: str = "") -> int:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    params: dict[str, Any] = {"kind": normalized_kind}
    search_sql = ""
    if search.strip():
        search_sql = " AND (LOWER(`name`) LIKE :search OR LOWER(`aliases`) LIKE :search)"
        params["search"] = f"%{search.strip().lower()}%"
    return int(
        db.execute(
            text(f"SELECT COUNT(1) FROM `LibraryFacet` WHERE `kind` = :kind{search_sql}"),
            params,
        ).scalar()
        or 0
    )


def list_categories(
    db: Session,
    kind: str,
    search: str = "",
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    params: dict[str, Any] = {"kind": normalized_kind}
    search_sql = ""
    if search.strip():
        search_sql = " AND (LOWER(f.`name`) LIKE :search OR LOWER(f.`aliases`) LIKE :search)"
        params["search"] = f"%{search.strip().lower()}%"
    if normalized_kind == "PUBLISHER":
        count_sql = (
            "COUNT(DISTINCT CASE WHEN COALESCE(w.`hidden`, 0) = 0 THEN e.`workId` END) AS `bookCount` "
            "FROM `LibraryFacet` f "
            "LEFT JOIN `LibraryEditionFacet` ef ON ef.`facetId` = f.`id` "
            "LEFT JOIN `LibraryEdition` e ON e.`id` = ef.`editionId` "
            "LEFT JOIN `LibraryWork` w ON w.`id` = e.`workId`"
        )
    else:
        count_sql = (
            "COUNT(DISTINCT CASE WHEN COALESCE(w.`hidden`, 0) = 0 THEN wf.`workId` END) AS `bookCount` "
            "FROM `LibraryFacet` f "
            "LEFT JOIN `LibraryWorkFacet` wf ON wf.`facetId` = f.`id` "
            "LEFT JOIN `LibraryWork` w ON w.`id` = wf.`workId`"
        )
    pagination_sql = ""
    if limit is not None:
        if limit <= 0 or offset < 0:
            raise ValueError("分页参数无效")
        pagination_sql = " LIMIT :limit OFFSET :offset"
        params.update({"limit": limit, "offset": offset})
    rows = _rows(
        db,
        f"SELECT f.*, {count_sql} WHERE f.`kind` = :kind{search_sql} "
        f"GROUP BY f.`id` ORDER BY `bookCount` DESC, f.`name` COLLATE NOCASE ASC{pagination_sql}",
        params,
    )
    return [
        {**row, "aliases": _parse_json(row.get("aliases"), []), "bookCount": int(row.get("bookCount") or 0)}
        for row in rows
    ]


def _update_row(db: Session, table: str, row_id: str, values: dict[str, Any], columns: set[str]) -> None:
    filtered = {key: value for key, value in values.items() if key in columns}
    if not filtered:
        return
    assignments = ", ".join(f"`{key}` = :{key}" for key in filtered)
    db.execute(text(f"UPDATE `{table}` SET {assignments} WHERE `id` = :row_id"), {**filtered, "row_id": row_id})


def _insert_snapshot(db: Session, table: str, row: dict[str, Any]) -> None:
    if not row:
        return
    available = {str(item[1]) for item in db.execute(text(f"PRAGMA table_info(`{table}`)")).all()}
    filtered = {key: value for key, value in row.items() if key in available}
    columns = list(filtered.keys())
    if not columns:
        return
    db.execute(
        text(
            f"INSERT OR REPLACE INTO `{table}` ({', '.join(f'`{column}`' for column in columns)}) "
            f"VALUES ({', '.join(f':{column}' for column in columns)})"
        ),
        filtered,
    )


def _create_operation(
    db: Session,
    *,
    user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    summary: str,
    payload: dict[str, Any],
    inverse: dict[str, Any],
) -> dict[str, Any]:
    operation_id = f"op_{time_ns()}"
    now = _now()
    expires_at = now + timedelta(days=7)
    if not _table_exists(db, "LibraryOperation"):
        return {
            "id": operation_id,
            "action": action,
            "status": "COMPLETED",
            "summary": summary,
            "expiresAt": expires_at.isoformat(),
            "undoAvailable": False,
        }
    db.execute(
        text(
            "INSERT INTO `LibraryOperation` "
            "(`id`, `userId`, `action`, `status`, `targetType`, `targetId`, `summary`, `payloadJson`, "
            "`inverseJson`, `expiresAt`, `createdAt`, `updatedAt`) "
            "VALUES (:id, :user_id, :action, 'COMPLETED', :target_type, :target_id, :summary, :payload, "
            ":inverse, :expires_at, :now, :now)"
        ),
        {
            "id": operation_id,
            "user_id": user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "summary": summary,
            "payload": _json(payload),
            "inverse": _json(inverse),
            "expires_at": expires_at,
            "now": now,
        },
    )
    return {
        "id": operation_id,
        "action": action,
        "status": "COMPLETED",
        "summary": summary,
        "expiresAt": expires_at.isoformat(),
        "undoAvailable": True,
    }


def smart_shelf_work_ids(db: Session, rules: dict[str, Any], user_id: str | None = None) -> list[str]:
    where = ["COALESCE(w.`hidden`, 0) = 0"]
    params: dict[str, Any] = {}
    direct_edition_scope = "1 = 1"
    filter_edition_scope = "1 = 1"
    filter_edition_params: dict[str, Any] = {}
    if user_id:
        user = db.get(User, user_id)
        if user is not None:
            context = authorization_context(db, user)
            work_scope, work_scope_params = work_visibility_sql(
                context,
                alias="w",
                prefix="smart_shelf_work",
            )
            where.append(work_scope)
            params.update(work_scope_params)
            direct_edition_scope, direct_edition_params = edition_visibility_sql(
                context,
                alias="e",
                prefix="smart_shelf_direct_edition",
            )
            params.update(direct_edition_params)
            filter_edition_scope, filter_edition_params = edition_visibility_sql(
                context,
                alias="filter_edition",
                # compile_filter_rules substitutes the SQL alias
                # `filter_edition` for reading-state projections. Keep that
                # alias out of bind names so the substitution cannot rename a
                # placeholder without also renaming its parameter.
                prefix="smart_shelf_scope",
            )
    search = str(rules.get("search") or "").strip()
    if search:
        where.append("(LOWER(w.`title`) LIKE :search OR LOWER(COALESCE(w.`author`, '')) LIKE :search OR LOWER(w.`tags`) LIKE :search)")
        params["search"] = f"%{search.lower()}%"
    statuses = [str(item).upper() for item in rules.get("statuses") or [] if str(item).upper() in STATUS_RANK]
    if statuses:
        status_clause, status_params, status_error = compile_filter_rules(
            db,
            {
                "combinator": "ANY",
                "conditions": [
                    {"field": "readingStatus", "operator": "equals", "value": status}
                    for status in statuses
                ],
            },
            alias="w",
            user_id=user_id,
            param_prefix="shelf_status",
            edition_scope_sql=filter_edition_scope,
            edition_scope_params=filter_edition_params,
            shelf_owner_user_id=user_id,
        )
        if status_error:
            return []
        if status_clause:
            where.append(status_clause)
            params.update(status_params)
    media_kinds = [str(item).upper() for item in rules.get("mediaKinds") or [] if str(item).upper() in {"EBOOK", "COMIC", "AUDIOBOOK"}]
    if media_kinds:
        placeholders = []
        for index, kind in enumerate(media_kinds):
            key = f"media_{index}"
            placeholders.append(f":{key}")
            params[key] = kind
        where.append(
            "EXISTS (SELECT 1 FROM `LibraryEdition` e WHERE e.`workId` = w.`id` "
            f"AND COALESCE(e.`hidden`, 0) = 0 AND {direct_edition_scope} "
            f"AND e.`mediaKind` IN ({', '.join(placeholders)}))"
        )
    tags = _unique_names(rules.get("tags") or [])
    for index, tag in enumerate(tags):
        key = f"tag_{index}"
        where.append(f"w.`tags` LIKE :{key}")
        params[key] = f'%"{tag}"%'
    authors = _unique_names(rules.get("authors") or [])
    if authors:
        author_terms = []
        for index, author in enumerate(authors):
            key = f"author_{index}"
            author_terms.append(f"LOWER(COALESCE(w.`author`, '')) LIKE :{key}")
            params[key] = f"%{author.lower()}%"
        where.append(f"({' OR '.join(author_terms)})")
    publishers = _unique_names(rules.get("publishers") or [])
    if publishers:
        publisher_terms = []
        for index, publisher in enumerate(publishers):
            key = f"publisher_{index}"
            publisher_terms.append(f"LOWER(COALESCE(e.`publisher`, '')) = :{key}")
            params[key] = publisher.lower()
        where.append(
            "EXISTS (SELECT 1 FROM `LibraryEdition` e WHERE e.`workId` = w.`id` "
            f"AND COALESCE(e.`hidden`, 0) = 0 AND {direct_edition_scope} "
            f"AND ({' OR '.join(publisher_terms)}))"
        )
    dynamic_clause, dynamic_params, dynamic_error = compile_filter_rules(
        db,
        {"combinator": rules.get("combinator", "ALL"), "conditions": rules.get("conditions") or []},
        alias="w",
        user_id=user_id,
        param_prefix="shelf_filter",
        edition_scope_sql=filter_edition_scope,
        edition_scope_params=filter_edition_params,
        shelf_owner_user_id=user_id,
    )
    if dynamic_error:
        return []
    if dynamic_clause:
        where.append(dynamic_clause)
        params.update(dynamic_params)
    matched_ids = [
        str(row["id"])
        for row in _rows(
            db,
            f"SELECT w.`id` FROM `LibraryWork` w WHERE {' AND '.join(where)} ORDER BY w.`updatedAt` DESC",
            params,
        )
    ]
    included_ids = [
        str(item).strip()
        for item in rules.get("includedWorkIds") or []
        if str(item).strip()
    ]
    return list(dict.fromkeys([*matched_ids, *included_ids]))


def duplicate_groups(db: Session) -> list[dict[str, Any]]:
    groups = _rows(
        db,
        """
        SELECT `normalizedTitle`, COALESCE(`normalizedAuthor`, '') AS `normalizedAuthor`, COUNT(*) AS `count`
        FROM `LibraryWork`
        WHERE COALESCE(`hidden`, 0) = 0 AND TRIM(COALESCE(`normalizedTitle`, '')) != ''
        GROUP BY `normalizedTitle`, COALESCE(`normalizedAuthor`, '')
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, MAX(`updatedAt`) DESC
        """,
    )
    result: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        group_key = f"{group['normalizedTitle']}:{group['normalizedAuthor']}"
        works = _rows(
            db,
            "SELECT * FROM `LibraryWork` WHERE COALESCE(`hidden`, 0) = 0 "
            "AND `normalizedTitle` = :title AND COALESCE(`normalizedAuthor`, '') = :author "
            "ORDER BY `updatedAt` DESC, `createdAt` ASC",
            {"title": group["normalizedTitle"], "author": group["normalizedAuthor"]},
        )
        result.append(
            {
                "id": f"duplicate_{index}_{sha1(group_key.encode()).hexdigest()[:12]}",
                "confidence": 0.98,
                "reasons": ["标题与作者规范化后相同"],
                "works": works,
            }
        )
    return result


def _shelf_snapshot(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids or not _table_exists(db, "ShelfWork"):
        return []
    placeholders = ", ".join(f":work_{index}" for index in range(len(work_ids)))
    return _rows(
        db,
        f"SELECT * FROM `ShelfWork` WHERE `workId` IN ({placeholders})",
        {f"work_{index}": value for index, value in enumerate(work_ids)},
    )


def merge_works(db: Session, target_work_id: str, source_work_ids: list[str], user_id: str | None) -> dict[str, Any]:
    sources = [value for value in dict.fromkeys(source_work_ids) if value and value != target_work_id]
    target = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id AND COALESCE(`hidden`, 0) = 0", {"id": target_work_id})
    if not target:
        raise ValueError("主作品不存在")
    source_rows = [
        row for work_id in sources
        if (row := _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id AND COALESCE(`hidden`, 0) = 0", {"id": work_id}))
    ]
    if len(source_rows) != len(sources) or not source_rows:
        raise ValueError("请选择至少一条可合并的作品")

    all_work_ids = [target_work_id, *sources]
    editions = []
    progress = []
    consumption = []
    for work_id in all_work_ids:
        editions.extend(_rows(db, "SELECT * FROM `LibraryEdition` WHERE `workId` = :work_id", {"work_id": work_id}))
        progress.extend(_rows(db, "SELECT `id`, `workId` FROM `LibraryReadingProgress` WHERE `workId` = :work_id", {"work_id": work_id}))
        consumption.extend(_rows(db, "SELECT * FROM `LibraryConsumptionState` WHERE `workId` = :work_id", {"work_id": work_id}))
    inverse = {
        "targetWork": target,
        "sourceWorks": source_rows,
        "editions": editions,
        "progress": progress,
        "consumption": consumption,
        "shelfWorks": _shelf_snapshot(db, all_work_ids),
    }

    target_tags = _work_tags(target.get("tags"))
    for source in source_rows:
        target_tags = _unique_names([*target_tags, *_work_tags(source.get("tags"))])
    now = _now()
    db.execute(
        text(
            "UPDATE `LibraryWork` SET `tags` = :tags, `description` = COALESCE(NULLIF(`description`, ''), :description), "
            "`seriesName` = COALESCE(NULLIF(`seriesName`, ''), :series_name), `updatedAt` = :now WHERE `id` = :id"
        ),
        {
            "tags": _json(target_tags),
            "description": next((row.get("description") for row in source_rows if row.get("description")), None),
            "series_name": next((row.get("seriesName") for row in source_rows if row.get("seriesName")), None),
            "now": now,
            "id": target_work_id,
        },
    )

    target_primary_kinds = {
        str(row.get("mediaKind") or "EBOOK")
        for row in editions
        if row.get("workId") == target_work_id and bool(row.get("primary")) and not bool(row.get("hidden"))
    }
    target_version_keys = {
        str(row.get("versionKey") or "")
        for row in editions
        if row.get("workId") == target_work_id
    }
    for edition in editions:
        if edition.get("workId") not in sources:
            continue
        edition_id = str(edition["id"])
        media_kind = str(edition.get("mediaKind") or "EBOOK")
        version_key = str(edition.get("versionKey") or edition_id)
        if version_key in target_version_keys:
            version_key = f"{version_key}:merged:{edition_id[-10:]}"
        target_version_keys.add(version_key)
        primary = bool(edition.get("primary")) and media_kind not in target_primary_kinds
        if primary:
            target_primary_kinds.add(media_kind)
        db.execute(
            text(
                "UPDATE `LibraryEdition` SET `workId` = :target_id, `versionKey` = :version_key, "
                "`primary` = :primary, `updatedAt` = :now WHERE `id` = :edition_id"
            ),
            {"target_id": target_work_id, "version_key": version_key, "primary": int(primary), "now": now, "edition_id": edition_id},
        )

    for source_id in sources:
        db.execute(text("UPDATE `LibraryReadingProgress` SET `workId` = :target_id, `updatedAt` = :now WHERE `workId` = :source_id"), {"target_id": target_work_id, "source_id": source_id, "now": now})
        source_states = _rows(db, "SELECT * FROM `LibraryConsumptionState` WHERE `workId` = :source_id", {"source_id": source_id})
        for state in source_states:
            existing = _row(
                db,
                "SELECT * FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :target_id AND `mediaKind` = :media_kind",
                {"user_id": state["userId"], "target_id": target_work_id, "media_kind": state["mediaKind"]},
            )
            if existing:
                source_rank = STATUS_RANK.get(str(state.get("status") or "UNREAD"), 0)
                target_rank = STATUS_RANK.get(str(existing.get("status") or "UNREAD"), 0)
                newer_source = str(state.get("updatedAt") or "") > str(existing.get("updatedAt") or "")
                db.execute(
                    text(
                        "UPDATE `LibraryConsumptionState` SET `status` = :status, `lastEditionId` = :edition_id, "
                        "`lastVolumeId` = :volume_id, `lastUnitId` = :unit_id, `updatedAt` = :now WHERE `id` = :id"
                    ),
                    {
                        "status": state.get("status") if source_rank > target_rank else existing.get("status"),
                        "edition_id": state.get("lastEditionId") if newer_source else existing.get("lastEditionId"),
                        "volume_id": state.get("lastVolumeId") if newer_source else existing.get("lastVolumeId"),
                        "unit_id": state.get("lastUnitId") if newer_source else existing.get("lastUnitId"),
                        "now": now,
                        "id": existing["id"],
                    },
                )
                db.execute(text("DELETE FROM `LibraryConsumptionState` WHERE `id` = :id"), {"id": state["id"]})
            else:
                db.execute(text("UPDATE `LibraryConsumptionState` SET `workId` = :target_id, `updatedAt` = :now WHERE `id` = :id"), {"target_id": target_work_id, "now": now, "id": state["id"]})

        shelf_ids = [str(row["shelfId"]) for row in _rows(db, "SELECT `shelfId` FROM `ShelfWork` WHERE `workId` = :source_id", {"source_id": source_id})]
        for shelf_id in shelf_ids:
            db.execute(
                text("INSERT OR IGNORE INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES (:shelf_id, :target_id, :now)"),
                {"shelf_id": shelf_id, "target_id": target_work_id, "now": now},
            )
        db.execute(text("DELETE FROM `ShelfWork` WHERE `workId` = :source_id"), {"source_id": source_id})
        db.execute(
            text("UPDATE `LibraryWork` SET `hidden` = 1, `organizeStatus` = 'APPLIED', `updatedAt` = :now WHERE `id` = :source_id"),
            {"now": now, "source_id": source_id},
        )

    primary = _row(
        db,
        "SELECT `id`, `format` FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 "
        "ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC LIMIT 1",
        {"work_id": target_work_id},
    )
    if primary:
        db.execute(
            text("UPDATE `LibraryWork` SET `primaryEditionId` = :edition_id, `workType` = :format, `updatedAt` = :now WHERE `id` = :work_id"),
            {"edition_id": primary["id"], "format": primary.get("format") or target.get("workType"), "now": now, "work_id": target_work_id},
        )
    operation = _create_operation(
        db,
        user_id=user_id,
        action="MERGE_WORKS",
        target_type="work",
        target_id=target_work_id,
        summary=f"已将 {len(source_rows) + 1} 条作品记录合并为《{target.get('title') or '未命名作品'}》",
        payload={"targetWorkId": target_work_id, "sourceWorkIds": sources},
        inverse=inverse,
    )
    db.commit()
    sync_work_facets(db, target_work_id)
    return {"targetWorkId": target_work_id, "sourceWorkIds": sources, "operation": operation}


def split_edition(
    db: Session,
    source_work_id: str,
    edition_id: str,
    *,
    title: str,
    author: str | None,
    copy_shelves: bool,
    user_id: str | None,
) -> dict[str, Any]:
    source = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": source_work_id})
    edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id AND `workId` = :work_id AND COALESCE(`hidden`, 0) = 0", {"id": edition_id, "work_id": source_work_id})
    if not source or not edition:
        raise ValueError("版本不存在或不属于该作品")
    edition_count = int(db.execute(text("SELECT COUNT(*) FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0"), {"work_id": source_work_id}).scalar() or 0)
    if edition_count < 2:
        raise ValueError("作品只有一个版本，无法拆分")
    next_title = re.sub(r"\s+", " ", title).strip()
    if not next_title:
        raise ValueError("请填写新作品标题")
    next_author = re.sub(r"\s+", " ", str(author or source.get("author") or UNKNOWN_AUTHOR)).strip() or UNKNOWN_AUTHOR
    now = _now()
    new_work_id = f"work_{time_ns()}"
    inverse = {
        "sourceWork": source,
        "edition": edition,
        "progress": _rows(db, "SELECT `id`, `workId` FROM `LibraryReadingProgress` WHERE `editionId` = :edition_id", {"edition_id": edition_id}) if _table_exists(db, "LibraryReadingProgress") else [],
        "shelfWorks": _shelf_snapshot(db, [source_work_id]),
        "newWorkId": new_work_id,
    }
    _insert_snapshot(
        db,
        "LibraryWork",
        {
            **source,
            "id": new_work_id,
            "title": next_title,
            "normalizedTitle": _normalized_name(next_title),
            "author": next_author,
            "normalizedAuthor": _normalized_name(next_author),
            "workType": edition.get("format") or source.get("workType") or "EPUB",
            "status": source.get("status") or "UNREAD",
            "coverPath": edition.get("coverPath") or source.get("coverPath"),
            "coverStatus": edition.get("coverStatus") or source.get("coverStatus") or "PENDING",
            "hidden": 0,
            "primaryEditionId": edition_id,
            "mergeKey": identity_merge_key(next_title, next_author),
            "createdAt": now,
            "updatedAt": now,
        },
    )
    db.execute(text("UPDATE `LibraryEdition` SET `workId` = :new_work_id, `primary` = 1, `updatedAt` = :now WHERE `id` = :edition_id"), {"new_work_id": new_work_id, "now": now, "edition_id": edition_id})
    if _table_exists(db, "LibraryReadingProgress"):
        db.execute(text("UPDATE `LibraryReadingProgress` SET `workId` = :new_work_id, `updatedAt` = :now WHERE `editionId` = :edition_id"), {"new_work_id": new_work_id, "now": now, "edition_id": edition_id})
    replacement = _row(
        db,
        "SELECT `id`, `format` FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC LIMIT 1",
        {"work_id": source_work_id},
    )
    if replacement:
        db.execute(text("UPDATE `LibraryEdition` SET `primary` = 1, `updatedAt` = :now WHERE `id` = :id"), {"now": now, "id": replacement["id"]})
        db.execute(text("UPDATE `LibraryWork` SET `primaryEditionId` = :edition_id, `workType` = :format, `updatedAt` = :now WHERE `id` = :work_id"), {"edition_id": replacement["id"], "format": replacement.get("format") or source.get("workType"), "now": now, "work_id": source_work_id})
    if copy_shelves and _table_exists(db, "ShelfWork"):
        for shelf in inverse["shelfWorks"]:
            db.execute(
                text("INSERT OR IGNORE INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES (:shelf_id, :work_id, :now)"),
                {"shelf_id": shelf["shelfId"], "work_id": new_work_id, "now": now},
            )
    operation = _create_operation(
        db,
        user_id=user_id,
        action="SPLIT_EDITION",
        target_type="work",
        target_id=new_work_id,
        summary=f"已将版本拆分为《{next_title}》",
        payload={"sourceWorkId": source_work_id, "editionId": edition_id, "newWorkId": new_work_id},
        inverse=inverse,
    )
    db.commit()
    sync_work_facets(db, source_work_id)
    sync_work_facets(db, new_work_id)
    return {"sourceWorkId": source_work_id, "newWorkId": new_work_id, "editionId": edition_id, "operation": operation}


def merge_categories(
    db: Session,
    kind: str,
    source_ids: list[str],
    target_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    target = _row(db, "SELECT * FROM `LibraryFacet` WHERE `id` = :id AND `kind` = :kind", {"id": target_id, "kind": normalized_kind})
    sources = [value for value in dict.fromkeys(source_ids) if value != target_id]
    source_rows = [
        row for source_id in sources
        if (row := _row(db, "SELECT * FROM `LibraryFacet` WHERE `id` = :id AND `kind` = :kind", {"id": source_id, "kind": normalized_kind}))
    ]
    if not target or not source_rows or len(source_rows) != len(sources):
        raise ValueError("请选择同一分类中的有效合并项")
    all_facet_ids = [target_id, *sources]
    placeholders = ", ".join(f":facet_{index}" for index in range(len(all_facet_ids)))
    facet_params = {f"facet_{index}": value for index, value in enumerate(all_facet_ids)}
    work_links = _rows(db, f"SELECT * FROM `LibraryWorkFacet` WHERE `facetId` IN ({placeholders})", facet_params)
    edition_links = _rows(db, f"SELECT * FROM `LibraryEditionFacet` WHERE `facetId` IN ({placeholders})", facet_params)
    work_ids = list(dict.fromkeys(str(row["workId"]) for row in work_links))
    edition_ids = list(dict.fromkeys(str(row["editionId"]) for row in edition_links))
    affected_works = [
        row for work_id in work_ids
        if (row := _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": work_id}))
    ]
    affected_editions = [
        row for edition_id in edition_ids
        if (row := _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id}))
    ]
    inverse = {
        "facets": [target, *source_rows],
        "workLinks": work_links,
        "editionLinks": edition_links,
        "works": affected_works,
        "editions": affected_editions,
        "kind": normalized_kind,
    }
    source_names = {_normalized_name(row.get("name")) for row in source_rows}
    target_name = str(target["name"])
    now = _now()
    if normalized_kind == "TAG":
        for work in affected_works:
            tags = [target_name if _normalized_name(tag) in source_names else tag for tag in _work_tags(work.get("tags"))]
            db.execute(text("UPDATE `LibraryWork` SET `tags` = :tags, `updatedAt` = :now WHERE `id` = :id"), {"tags": _json(_unique_names(tags)), "now": now, "id": work["id"]})
    elif normalized_kind == "AUTHOR":
        for work in affected_works:
            authors = [target_name if _normalized_name(author) in source_names else author for author in split_authors(work.get("author"))]
            author_text = "、".join(_unique_names(authors)) or target_name
            db.execute(
                text("UPDATE `LibraryWork` SET `author` = :author, `normalizedAuthor` = :normalized, `mergeKey` = :merge_key, `updatedAt` = :now WHERE `id` = :id"),
                {"author": author_text, "normalized": _normalized_name(author_text), "merge_key": identity_merge_key(str(work.get("title") or ""), author_text), "now": now, "id": work["id"]},
            )
    elif normalized_kind == "SERIES":
        for work in affected_works:
            db.execute(text("UPDATE `LibraryWork` SET `seriesName` = :name, `updatedAt` = :now WHERE `id` = :id"), {"name": target_name, "now": now, "id": work["id"]})
    else:
        for edition in affected_editions:
            db.execute(text("UPDATE `LibraryEdition` SET `publisher` = :name, `updatedAt` = :now WHERE `id` = :id"), {"name": target_name, "now": now, "id": edition["id"]})

    aliases = _unique_names([
        *_parse_json(target.get("aliases"), []),
        *(row.get("name") for row in source_rows),
        *(alias for row in source_rows for alias in _parse_json(row.get("aliases"), [])),
    ])
    db.execute(text("UPDATE `LibraryFacet` SET `aliases` = :aliases, `updatedAt` = :now WHERE `id` = :id"), {"aliases": _json(aliases), "now": now, "id": target_id})
    for source_id in sources:
        db.execute(text("DELETE FROM `LibraryFacet` WHERE `id` = :id"), {"id": source_id})
    operation = _create_operation(
        db,
        user_id=user_id,
        action="MERGE_FACETS",
        target_type="facet",
        target_id=target_id,
        summary=f"已合并 {len(source_rows) + 1} 个{normalized_kind.lower()}分类",
        payload={"kind": normalized_kind, "targetId": target_id, "sourceIds": sources},
        inverse=inverse,
    )
    db.commit()
    for work_id in work_ids:
        sync_work_facets(db, work_id, commit=False)
    db.commit()
    return {"targetId": target_id, "mergedIds": sources, "operation": operation}


def rename_category(db: Session, facet_id: str, name: str, user_id: str | None) -> dict[str, Any]:
    facet = _row(db, "SELECT * FROM `LibraryFacet` WHERE `id` = :id", {"id": facet_id})
    next_name = re.sub(r"\s+", " ", name).strip()
    if not facet or not next_name:
        raise ValueError("分类不存在或名称无效")
    normalized = _normalized_name(next_name)
    conflict = _row(db, "SELECT `id` FROM `LibraryFacet` WHERE `kind` = :kind AND `normalizedName` = :normalized AND `id` != :id", {"kind": facet["kind"], "normalized": normalized, "id": facet_id})
    if conflict:
        raise ValueError("同名分类已存在，请使用合并")
    source_name = str(facet["name"])
    linked_works: list[dict[str, Any]] = []
    linked_editions: list[dict[str, Any]] = []
    if facet["kind"] == "PUBLISHER":
        linked = _rows(db, "SELECT `editionId` FROM `LibraryEditionFacet` WHERE `facetId` = :id", {"id": facet_id})
        linked_editions = [item for link in linked if (item := _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": link["editionId"]}))]
        for item in linked:
            db.execute(text("UPDATE `LibraryEdition` SET `publisher` = :name, `updatedAt` = :now WHERE `id` = :id"), {"name": next_name, "now": _now(), "id": item["editionId"]})
    else:
        linked = _rows(db, "SELECT `workId` FROM `LibraryWorkFacet` WHERE `facetId` = :id", {"id": facet_id})
        linked_works = [item for link in linked if (item := _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": link["workId"]}))]
        for item in linked:
            work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": item["workId"]}) or {}
            if facet["kind"] == "TAG":
                values = [next_name if _normalized_name(tag) == _normalized_name(source_name) else tag for tag in _work_tags(work.get("tags"))]
                db.execute(text("UPDATE `LibraryWork` SET `tags` = :value, `updatedAt` = :now WHERE `id` = :id"), {"value": _json(_unique_names(values)), "now": _now(), "id": item["workId"]})
            elif facet["kind"] == "AUTHOR":
                values = [next_name if _normalized_name(author) == _normalized_name(source_name) else author for author in split_authors(work.get("author"))]
                author_text = "、".join(_unique_names(values))
                db.execute(text("UPDATE `LibraryWork` SET `author` = :value, `normalizedAuthor` = :normalized, `mergeKey` = :merge_key, `updatedAt` = :now WHERE `id` = :id"), {"value": author_text, "normalized": _normalized_name(author_text), "merge_key": identity_merge_key(str(work.get("title") or ""), author_text), "now": _now(), "id": item["workId"]})
            elif facet["kind"] == "SERIES":
                db.execute(text("UPDATE `LibraryWork` SET `seriesName` = :value, `updatedAt` = :now WHERE `id` = :id"), {"value": next_name, "now": _now(), "id": item["workId"]})
    aliases = _unique_names([*_parse_json(facet.get("aliases"), []), source_name])
    db.execute(text("UPDATE `LibraryFacet` SET `name` = :name, `normalizedName` = :normalized, `aliases` = :aliases, `updatedAt` = :now WHERE `id` = :id"), {"name": next_name, "normalized": normalized, "aliases": _json(aliases), "now": _now(), "id": facet_id})
    operation = _create_operation(
        db,
        user_id=user_id,
        action="RENAME_FACET",
        target_type="facet",
        target_id=facet_id,
        summary=f"已将“{source_name}”重命名为“{next_name}”",
        payload={"facetId": facet_id, "name": next_name},
        inverse={"facet": facet, "works": linked_works, "editions": linked_editions},
    )
    db.commit()
    return {"facetId": facet_id, "name": next_name, "operation": operation}


def delete_category(db: Session, facet_id: str, user_id: str | None) -> dict[str, Any]:
    facet = _row(db, "SELECT * FROM `LibraryFacet` WHERE `id` = :id", {"id": facet_id})
    if not facet:
        raise ValueError("分类不存在")

    kind = str(facet["kind"])
    source_name = str(facet["name"])
    work_links = _rows(db, "SELECT * FROM `LibraryWorkFacet` WHERE `facetId` = :id", {"id": facet_id})
    edition_links = _rows(db, "SELECT * FROM `LibraryEditionFacet` WHERE `facetId` = :id", {"id": facet_id})
    affected_works = [
        row for link in work_links
        if (row := _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": link["workId"]}))
    ]
    affected_editions = [
        row for link in edition_links
        if (row := _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": link["editionId"]}))
    ]
    now = _now()

    if kind == "TAG":
        for work in affected_works:
            tags = [tag for tag in _work_tags(work.get("tags")) if _normalized_name(tag) != _normalized_name(source_name)]
            db.execute(
                text("UPDATE `LibraryWork` SET `tags` = :value, `updatedAt` = :now WHERE `id` = :id"),
                {"value": _json(tags), "now": now, "id": work["id"]},
            )
    elif kind == "AUTHOR":
        for work in affected_works:
            authors = [author for author in split_authors(work.get("author")) if _normalized_name(author) != _normalized_name(source_name)]
            author_text = "、".join(authors) or UNKNOWN_AUTHOR
            db.execute(
                text(
                    "UPDATE `LibraryWork` SET `author` = :value, `normalizedAuthor` = :normalized, "
                    "`mergeKey` = :merge_key, `updatedAt` = :now WHERE `id` = :id"
                ),
                {
                    "value": author_text,
                    "normalized": _normalized_name(author_text),
                    "merge_key": identity_merge_key(str(work.get("title") or ""), author_text),
                    "now": now,
                    "id": work["id"],
                },
            )
    elif kind == "SERIES":
        for work in affected_works:
            db.execute(
                text("UPDATE `LibraryWork` SET `seriesName` = NULL, `seriesIndex` = NULL, `updatedAt` = :now WHERE `id` = :id"),
                {"now": now, "id": work["id"]},
            )
    elif kind == "PUBLISHER":
        for edition in affected_editions:
            db.execute(
                text("UPDATE `LibraryEdition` SET `publisher` = NULL, `updatedAt` = :now WHERE `id` = :id"),
                {"now": now, "id": edition["id"]},
            )
    else:
        raise ValueError("分类类型无效")

    db.execute(text("DELETE FROM `LibraryFacet` WHERE `id` = :id"), {"id": facet_id})
    operation = _create_operation(
        db,
        user_id=user_id,
        action="DELETE_FACET",
        target_type="facet",
        target_id=facet_id,
        summary=f"已删除{kind.lower()}分类“{source_name}”",
        payload={"facetId": facet_id, "kind": kind, "name": source_name},
        inverse={
            "facet": facet,
            "workLinks": work_links,
            "editionLinks": edition_links,
            "works": affected_works,
            "editions": affected_editions,
        },
    )
    db.commit()
    return {
        "facetId": facet_id,
        "kind": kind,
        "name": source_name,
        "affectedBookCount": len({
            *(str(link["workId"]) for link in work_links),
            *(str(edition["workId"]) for edition in affected_editions),
        }),
        "operation": operation,
    }


def undo_operation(db: Session, operation_id: str, user_id: str | None) -> dict[str, Any]:
    operation = _row(db, "SELECT * FROM `LibraryOperation` WHERE `id` = :id", {"id": operation_id})
    if not operation:
        raise ValueError("操作记录不存在")
    if operation.get("status") == "UNDONE":
        raise ValueError("该操作已经撤销")
    expires_at = to_timestamp_ms(operation.get("expiresAt"))
    if expires_at is not None and expires_at < now_timestamp_ms():
        raise ValueError("撤销期限已过")
    inverse = _parse_json(operation.get("inverseJson"), {})
    action = str(operation.get("action") or "")
    if action == "MERGE_WORKS":
        target = inverse.get("targetWork") or {}
        sources = inverse.get("sourceWorks") or []
        work_ids = [str(target.get("id") or ""), *(str(item.get("id") or "") for item in sources)]
        shelf_ids = list(dict.fromkeys(str(item.get("shelfId")) for item in inverse.get("shelfWorks") or []))
        for shelf_id in shelf_ids:
            for work_id in work_ids:
                db.execute(text("DELETE FROM `ShelfWork` WHERE `shelfId` = :shelf_id AND `workId` = :work_id"), {"shelf_id": shelf_id, "work_id": work_id})
        for shelf in inverse.get("shelfWorks") or []:
            _insert_snapshot(db, "ShelfWork", shelf)
        for state in inverse.get("consumption") or []:
            db.execute(text("DELETE FROM `LibraryConsumptionState` WHERE `id` = :id"), {"id": state["id"]})
        for state in inverse.get("consumption") or []:
            _insert_snapshot(db, "LibraryConsumptionState", state)
        for progress in inverse.get("progress") or []:
            db.execute(text("UPDATE `LibraryReadingProgress` SET `workId` = :work_id WHERE `id` = :id"), {"work_id": progress["workId"], "id": progress["id"]})
        edition_ids = [str(item["id"]) for item in inverse.get("editions") or []]
        for edition_id in edition_ids:
            db.execute(text("UPDATE `LibraryEdition` SET `primary` = 0 WHERE `id` = :id"), {"id": edition_id})
        for edition in inverse.get("editions") or []:
            _update_row(db, "LibraryEdition", str(edition["id"]), edition, EDITION_RESTORE_COLUMNS)
        _update_row(db, "LibraryWork", str(target["id"]), target, WORK_RESTORE_COLUMNS)
        for source in sources:
            _update_row(db, "LibraryWork", str(source["id"]), source, WORK_RESTORE_COLUMNS)
        db.commit()
        for work_id in work_ids:
            if work_id:
                sync_work_facets(db, work_id, commit=False)
    elif action == "SPLIT_EDITION":
        source = inverse.get("sourceWork") or {}
        edition = inverse.get("edition") or {}
        new_work_id = str(inverse.get("newWorkId") or "")
        db.execute(text("UPDATE `LibraryEdition` SET `primary` = 0 WHERE `id` = :id"), {"id": edition.get("id")})
        _update_row(db, "LibraryEdition", str(edition["id"]), edition, EDITION_RESTORE_COLUMNS)
        for progress in inverse.get("progress") or []:
            db.execute(text("UPDATE `LibraryReadingProgress` SET `workId` = :work_id WHERE `id` = :id"), {"work_id": progress["workId"], "id": progress["id"]})
        if new_work_id:
            db.execute(text("DELETE FROM `LibraryWork` WHERE `id` = :id"), {"id": new_work_id})
        _update_row(db, "LibraryWork", str(source["id"]), source, WORK_RESTORE_COLUMNS)
        db.commit()
        sync_work_facets(db, str(source["id"]), commit=False)
    elif action == "MERGE_FACETS":
        for work in inverse.get("works") or []:
            _update_row(db, "LibraryWork", str(work["id"]), work, WORK_RESTORE_COLUMNS)
        for edition in inverse.get("editions") or []:
            _update_row(db, "LibraryEdition", str(edition["id"]), edition, EDITION_RESTORE_COLUMNS)
        for facet in inverse.get("facets") or []:
            _insert_snapshot(db, "LibraryFacet", facet)
        work_ids = list(dict.fromkeys(str(item["workId"]) for item in inverse.get("workLinks") or []))
        edition_ids = list(dict.fromkeys(str(item["editionId"]) for item in inverse.get("editionLinks") or []))
        for work_id in work_ids:
            db.execute(text("DELETE FROM `LibraryWorkFacet` WHERE `workId` = :id"), {"id": work_id})
        for edition_id in edition_ids:
            db.execute(text("DELETE FROM `LibraryEditionFacet` WHERE `editionId` = :id"), {"id": edition_id})
        for link in inverse.get("workLinks") or []:
            _insert_snapshot(db, "LibraryWorkFacet", link)
        for link in inverse.get("editionLinks") or []:
            _insert_snapshot(db, "LibraryEditionFacet", link)
    elif action == "RENAME_FACET":
        facet = inverse.get("facet") or {}
        if not facet:
            raise ValueError("撤销数据不完整")
        for work in inverse.get("works") or []:
            _update_row(db, "LibraryWork", str(work["id"]), work, WORK_RESTORE_COLUMNS)
        for edition in inverse.get("editions") or []:
            _update_row(db, "LibraryEdition", str(edition["id"]), edition, EDITION_RESTORE_COLUMNS)
        _update_row(db, "LibraryFacet", str(facet["id"]), facet, {"name", "normalizedName", "aliases", "updatedAt"})
    elif action == "DELETE_FACET":
        facet = inverse.get("facet") or {}
        if not facet:
            raise ValueError("撤销数据不完整")
        for work in inverse.get("works") or []:
            _update_row(db, "LibraryWork", str(work["id"]), work, WORK_RESTORE_COLUMNS)
        for edition in inverse.get("editions") or []:
            _update_row(db, "LibraryEdition", str(edition["id"]), edition, EDITION_RESTORE_COLUMNS)
        _insert_snapshot(db, "LibraryFacet", facet)
        for link in inverse.get("workLinks") or []:
            _insert_snapshot(db, "LibraryWorkFacet", link)
        for link in inverse.get("editionLinks") or []:
            _insert_snapshot(db, "LibraryEditionFacet", link)
    else:
        raise ValueError("该操作不支持撤销")
    now = _now()
    db.execute(text("UPDATE `LibraryOperation` SET `status` = 'UNDONE', `undoneAt` = :now, `updatedAt` = :now WHERE `id` = :id"), {"now": now, "id": operation_id})
    db.commit()
    return {"id": operation_id, "status": "UNDONE", "undoneAt": timestamp_ms_to_iso(now), "userId": user_id}


def operation_view(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        **operation,
        "payload": _parse_json(operation.get("payloadJson"), {}),
        "undoAvailable": operation.get("status") == "COMPLETED" and (
            not operation.get("expiresAt") or (to_timestamp_ms(operation.get("expiresAt")) or 0) >= now_timestamp_ms()
        ),
    }
