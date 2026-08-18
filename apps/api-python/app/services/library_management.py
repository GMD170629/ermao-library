"""Library management use cases: merge/split works, category edits, undo, smart shelves."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha1
from typing import Any

from sqlalchemy.orm import Session

from app.bootstrap.library import (
    PreparedWorkFacetWrite,
    execute_work_facet_write,
    load_work_facet_projections,
    prepare_work_facet_write,
)
from app.bootstrap.library import smart_shelf_work_ids as _query_smart_shelf_work_ids
from app.core.time import now_timestamp_ms, timestamp_ms_to_iso, to_timestamp_ms
from app.modules.library.application.management_commands import (
    DeleteLibraryCategory,
    MergeLibraryCategories,
    MergeLibraryWorks,
    RenameLibraryCategory,
    SyncWorkFacets,
    SyncWorksFacets,
    UndoLibraryOperation,
)
from app.modules.library.infrastructure import categories as library_categories
from app.modules.library.infrastructure import operations as library_operations
from app.modules.library.infrastructure import works as library_works
from app.modules.library.infrastructure.facets import (
    FACET_KINDS,
    count_categories,
    list_categories,
    list_categories_page,
    split_authors,
)
from app.modules.library.infrastructure.facets import (
    normalized_name as _normalized_name,
)
from app.modules.library.infrastructure.facets import (
    parse_json as _parse_json,
)
from app.modules.library.infrastructure.facets import (
    unique_names as _unique_names,
)
from app.modules.library.infrastructure.facets import (
    work_tags as _work_tags,
)
from app.modules.library.public import WorkFacetProjection, prepare_work_facet
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
)

STATUS_RANK = library_works.STATUS_RANK
__all__ = ["count_categories", "list_categories", "list_categories_page"]


class _LibraryManagementGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def merge_works(
        self, target_work_id: str, source_work_ids: list[str], user_id: str | None
    ) -> dict[str, object]:
        return _merge_works(self._db, target_work_id, source_work_ids, user_id)

    def merge_categories(
        self,
        kind: str,
        source_ids: list[str],
        target_id: str,
        user_id: str | None,
    ) -> dict[str, object]:
        return _merge_categories(self._db, kind, source_ids, target_id, user_id)

    def rename_category(
        self, facet_id: str, name: str, user_id: str | None
    ) -> dict[str, object]:
        return _rename_category(self._db, facet_id, name, user_id)

    def delete_category(self, facet_id: str, user_id: str | None) -> dict[str, object]:
        return _delete_category(self._db, facet_id, user_id)

    def undo_operation(
        self, operation_id: str, user_id: str | None
    ) -> dict[str, object]:
        return _undo_operation(self._db, operation_id, user_id)


class _FacetSyncGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def sync_work(self, work_id: str) -> None:
        self.sync_works((work_id,))

    def sync_works(self, work_ids: Iterable[str]) -> None:
        normalized_ids = tuple(dict.fromkeys(str(value) for value in work_ids if value))
        projections = load_work_facet_projections(self._db, normalized_ids)
        prepared = tuple(prepare_work_facet(projection) for projection in projections)
        write = prepare_work_facet_write(prepared, now=_now())
        execute_work_facet_write(self._db, write)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def smart_shelf_work_ids(
    db: Session, rules: dict[str, Any], user_id: str | None = None
) -> list[str]:
    """Compatibility entry point; remove after callers inject GetSmartShelfWorkIds."""

    return _query_smart_shelf_work_ids(db, rules, user_id=user_id)


def sync_work_facets(
    db: Session,
    work_id: str,
) -> None:
    """Compatibility entry point backed by a named application command."""

    SyncWorkFacets(_FacetSyncGateway(db), db).execute(work_id)


def sync_works_facets(
    db: Session,
    work_ids: Iterable[str],
) -> None:
    """Synchronize one prepared work set through a named application command."""

    SyncWorksFacets(_FacetSyncGateway(db), db).execute(work_ids)


def _prepare_record_facet_write(
    records: Iterable[dict[str, Any]],
    *,
    now: datetime,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> PreparedWorkFacetWrite:
    changes = overrides or {}
    prepared = []
    for record in records:
        work_id = str(record.get("id") or "")
        if not work_id:
            continue
        values = changes.get(work_id, {})
        prepared.append(
            prepare_work_facet(
                WorkFacetProjection(
                    work_id=work_id,
                    author=(
                        str(values["author"])
                        if values.get("author") is not None
                        else None
                    )
                    if "author" in values
                    else (
                        str(record["author"])
                        if record.get("author") is not None
                        else None
                    ),
                    tags_source=(
                        str(values.get("tags") or "[]")
                        if "tags" in values
                        else str(record.get("tags") or "[]")
                    ),
                    series_name=(
                        str(values["seriesName"])
                        if values.get("seriesName") is not None
                        else None
                    )
                    if "seriesName" in values
                    else (
                        str(record["seriesName"])
                        if record.get("seriesName") is not None
                        else None
                    ),
                )
            )
        )
    return prepare_work_facet_write(tuple(prepared), now=now)


def duplicate_groups(db: Session) -> list[dict[str, Any]]:
    groups = library_works.list_duplicate_identity_groups(db)
    result: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        group_key = f"{group['normalizedTitle']}:{group['normalizedAuthor']}"
        works = library_works.list_works_for_normalized_identity(
            db,
            normalized_title=str(group["normalizedTitle"]),
            normalized_author=str(group["normalizedAuthor"]),
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


def duplicate_groups_page(
    db: Session,
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, int]:
    identity_groups, total, clamped_page = library_works.list_duplicate_identity_page(
        db,
        page=page,
        page_size=page_size,
    )
    groups: list[dict[str, Any]] = []
    start = (clamped_page - 1) * page_size
    for index, group in enumerate(identity_groups, start=start):
        group_key = f"{group['normalizedTitle']}:{group['normalizedAuthor']}"
        groups.append(
            {
                "id": (
                    f"duplicate_{index}_{sha1(group_key.encode()).hexdigest()[:12]}"
                ),
                "confidence": 0.98,
                "reasons": ["标题与作者规范化后相同"],
                "works": group["works"],
            }
        )
    return groups, total, clamped_page


def _shelf_snapshot(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids or not library_operations.has_table(db, "ShelfWork"):
        return []
    return library_works.list_shelf_links_for_works(db, work_ids)


def _merge_works(
    db: Session, target_work_id: str, source_work_ids: list[str], user_id: str | None
) -> dict[str, Any]:
    sources = [
        value
        for value in dict.fromkeys(source_work_ids)
        if value and value != target_work_id
    ]
    work_rows_by_id = {
        str(row["id"]): row
        for row in library_works.list_works_by_ids(db, (target_work_id, *sources))
        if not bool(row.get("hidden"))
    }
    target = work_rows_by_id.get(target_work_id)
    if not target:
        raise ValueError("主作品不存在")
    source_rows = [
        work_rows_by_id[work_id] for work_id in sources if work_id in work_rows_by_id
    ]
    if len(source_rows) != len(sources) or not source_rows:
        raise ValueError("请选择至少一条可合并的作品")
    library_ids = {str(row.get("libraryId") or "") for row in (target, *source_rows)}
    if len(library_ids) != 1 or "" in library_ids:
        raise ValueError("不能跨书库合并作品")

    all_work_ids = [target_work_id, *sources]
    media_versions = library_works.list_media_versions_for_works(db, all_work_ids)
    inverse = {
        "targetWork": target,
        "sourceWorks": source_rows,
        "mediaVersions": media_versions,
        "volumes": library_operations.snapshot_volumes_for_media_versions(
            db,
            [str(item["id"]) for item in media_versions],
        ),
        "shelfWorks": _shelf_snapshot(db, all_work_ids),
    }

    target_tags = _work_tags(target.get("tags"))
    for source in source_rows:
        target_tags = _unique_names([*target_tags, *_work_tags(source.get("tags"))])
    now = _now()
    merged_description = next(
        (row.get("description") for row in source_rows if row.get("description")),
        None,
    )
    merged_series_name = next(
        (row.get("seriesName") for row in source_rows if row.get("seriesName")),
        None,
    )
    facet_write = _prepare_record_facet_write(
        (target,),
        now=now,
        overrides={
            target_work_id: {
                "tags": _json(target_tags),
                "seriesName": target.get("seriesName") or merged_series_name,
            }
        },
    )
    library_works.update_merged_target_work(
        db,
        work_id=target_work_id,
        tags_json=_json(target_tags),
        description=merged_description,
        series_name=merged_series_name,
        now=now,
    )

    source_id_set = set(sources)
    for media_version in media_versions:
        if media_version.get("workId") not in source_id_set:
            continue
        library_works.move_media_version_to_work(
            db,
            media_version_id=str(media_version["id"]),
            target_work_id=target_work_id,
            now=now,
        )

    for source_id in sources:
        library_works.transfer_source_work_side_effects(
            db,
            source_work_id=source_id,
            target_work_id=target_work_id,
            now=now,
        )

    operation = library_operations.create_operation(
        db,
        user_id=user_id,
        action="MERGE_WORKS",
        target_type="work",
        target_id=target_work_id,
        summary=f"已将 {len(source_rows) + 1} 条作品记录合并为《{target.get('title') or '未命名作品'}》",
        payload={"targetWorkId": target_work_id, "sourceWorkIds": sources},
        inverse=inverse,
        now=now,
    )
    execute_work_facet_write(db, facet_write)
    return {
        "targetWorkId": target_work_id,
        "sourceWorkIds": sources,
        "operation": operation_view(operation),
    }


def _merge_categories(
    db: Session,
    kind: str,
    source_ids: list[str],
    target_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    target = library_categories.get_facet_of_kind(db, target_id, normalized_kind)
    sources = [value for value in dict.fromkeys(source_ids) if value != target_id]
    source_rows = library_categories.list_facets_of_kind(db, sources, normalized_kind)
    if not target or not source_rows or len(source_rows) != len(sources):
        raise ValueError("请选择同一分类中的有效合并项")
    all_facet_ids = [target_id, *sources]
    work_links = library_categories.list_work_facet_links(db, all_facet_ids)
    volume_links = library_categories.list_volume_facet_links(db, all_facet_ids)
    work_ids = list(dict.fromkeys(str(row["workId"]) for row in work_links))
    volume_ids = list(dict.fromkeys(str(row["volumeId"]) for row in volume_links))
    affected_works = library_works.list_works_by_ids(db, tuple(work_ids))
    affected_volumes = library_categories.list_volumes_by_ids(db, volume_ids)
    inverse = {
        "facets": [target, *source_rows],
        "workLinks": work_links,
        "volumeLinks": volume_links,
        "works": affected_works,
        "volumes": affected_volumes,
        "kind": normalized_kind,
    }
    source_names = {_normalized_name(row.get("name")) for row in source_rows}
    target_name = str(target["name"])
    now = _now()
    facet_overrides: dict[str, dict[str, Any]] = {}
    for work in affected_works:
        work_id = str(work["id"])
        if normalized_kind == "TAG":
            tags = [
                target_name if _normalized_name(tag) in source_names else tag
                for tag in _work_tags(work.get("tags"))
            ]
            facet_overrides[work_id] = {"tags": _json(_unique_names(tags))}
        elif normalized_kind == "AUTHOR":
            authors = [
                target_name if _normalized_name(author) in source_names else author
                for author in split_authors(work.get("author"))
            ]
            facet_overrides[work_id] = {
                "author": "、".join(_unique_names(authors)) or target_name
            }
        elif normalized_kind == "SERIES":
            facet_overrides[work_id] = {"seriesName": target_name}
    facet_write = _prepare_record_facet_write(
        affected_works,
        now=now,
        overrides=facet_overrides,
    )
    work_updates: list[tuple[str, dict[str, Any]]] = []
    for work in affected_works:
        work_id = str(work["id"])
        values = facet_overrides.get(work_id, {})
        if normalized_kind == "TAG":
            work_updates.append((work_id, {"tags": values["tags"], "updatedAt": now}))
        elif normalized_kind == "AUTHOR":
            author_text = str(values["author"])
            work_updates.append(
                (
                    work_id,
                    {
                        "author": author_text,
                        "normalizedAuthor": _normalized_name(author_text),
                        "mergeKey": identity_merge_key(
                            str(work.get("title") or ""), author_text
                        ),
                        "updatedAt": now,
                    },
                )
            )
        elif normalized_kind == "SERIES":
            work_updates.append(
                (work_id, {"seriesName": target_name, "updatedAt": now})
            )
    library_works.update_work_fields_bulk(db, tuple(work_updates))
    if normalized_kind == "PUBLISHER":
        library_categories.update_volume_fields_bulk(
            db,
            [
                {"id": str(volume["id"]), "publisher": target_name, "updated_at": now}
                for volume in affected_volumes
            ],
        )

    aliases = _unique_names(
        [
            *_parse_json(target.get("aliases"), []),
            *(row.get("name") for row in source_rows),
            *(
                alias
                for row in source_rows
                for alias in _parse_json(row.get("aliases"), [])
            ),
        ]
    )
    library_categories.update_facet_aliases(
        db,
        facet_id=target_id,
        aliases_json=_json(aliases),
        now=now,
    )
    library_categories.delete_facets(db, sources)
    operation = library_operations.create_operation(
        db,
        user_id=user_id,
        action="MERGE_FACETS",
        target_type="facet",
        target_id=target_id,
        summary=f"已合并 {len(source_rows) + 1} 个{normalized_kind.lower()}分类",
        payload={"kind": normalized_kind, "targetId": target_id, "sourceIds": sources},
        inverse=inverse,
        now=now,
    )
    execute_work_facet_write(db, facet_write)
    return {
        "targetId": target_id,
        "mergedIds": sources,
        "operation": operation_view(operation),
    }


def _rename_category(
    db: Session, facet_id: str, name: str, user_id: str | None
) -> dict[str, Any]:
    facet = library_categories.get_facet(db, facet_id)
    next_name = re.sub(r"\s+", " ", name).strip()
    if not facet or not next_name:
        raise ValueError("分类不存在或名称无效")
    normalized = _normalized_name(next_name)
    conflict = library_categories.find_normalized_name_conflict(
        db,
        kind=str(facet["kind"]),
        normalized_name=normalized,
        exclude_facet_id=facet_id,
    )
    if conflict:
        raise ValueError("同名分类已存在，请使用合并")
    source_name = str(facet["name"])
    linked_works: list[dict[str, Any]] = []
    linked_volumes: list[dict[str, Any]] = []
    now = _now()
    facet_write = _prepare_record_facet_write((), now=now)
    if facet["kind"] == "PUBLISHER":
        volume_ids = library_categories.list_volume_ids_for_facet(db, facet_id)
        linked_volumes = library_categories.list_volumes_by_ids(db, volume_ids)
        library_categories.update_volume_fields_bulk(
            db,
            [
                {"id": volume_id, "publisher": next_name, "updated_at": now}
                for volume_id in volume_ids
            ],
        )
    else:
        work_ids = library_categories.list_work_ids_for_facet(db, facet_id)
        linked_works = library_works.list_works_by_ids(db, tuple(work_ids))
        facet_overrides: dict[str, dict[str, Any]] = {}
        for work in linked_works:
            work_id = str(work["id"])
            if facet["kind"] == "TAG":
                values = [
                    next_name
                    if _normalized_name(tag) == _normalized_name(source_name)
                    else tag
                    for tag in _work_tags(work.get("tags"))
                ]
                facet_overrides[work_id] = {"tags": _json(_unique_names(values))}
            elif facet["kind"] == "AUTHOR":
                values = [
                    next_name
                    if _normalized_name(author) == _normalized_name(source_name)
                    else author
                    for author in split_authors(work.get("author"))
                ]
                facet_overrides[work_id] = {"author": "、".join(_unique_names(values))}
            elif facet["kind"] == "SERIES":
                facet_overrides[work_id] = {"seriesName": next_name}
        facet_write = _prepare_record_facet_write(
            linked_works,
            now=now,
            overrides=facet_overrides,
        )
        work_updates: list[tuple[str, dict[str, Any]]] = []
        for work in linked_works:
            work_id = str(work["id"])
            values = facet_overrides.get(work_id, {})
            if facet["kind"] == "TAG":
                work_updates.append(
                    (work_id, {"tags": values["tags"], "updatedAt": now})
                )
            elif facet["kind"] == "AUTHOR":
                author_text = str(values["author"])
                work_updates.append(
                    (
                        work_id,
                        {
                            "author": author_text,
                            "normalizedAuthor": _normalized_name(author_text),
                            "mergeKey": identity_merge_key(
                                str(work.get("title") or ""), author_text
                            ),
                            "updatedAt": now,
                        },
                    )
                )
            elif facet["kind"] == "SERIES":
                work_updates.append(
                    (work_id, {"seriesName": next_name, "updatedAt": now})
                )
        library_works.update_work_fields_bulk(db, tuple(work_updates))
    aliases = _unique_names([*_parse_json(facet.get("aliases"), []), source_name])
    library_categories.update_facet_name(
        db,
        facet_id=facet_id,
        name=next_name,
        normalized_name=normalized,
        aliases_json=_json(aliases),
        now=now,
    )
    operation = library_operations.create_operation(
        db,
        user_id=user_id,
        action="RENAME_FACET",
        target_type="facet",
        target_id=facet_id,
        summary=f"已将“{source_name}”重命名为“{next_name}”",
        payload={"facetId": facet_id, "name": next_name},
        inverse={"facet": facet, "works": linked_works, "volumes": linked_volumes},
        now=now,
    )
    execute_work_facet_write(db, facet_write)
    return {
        "facetId": facet_id,
        "name": next_name,
        "operation": operation_view(operation),
    }


def _delete_category(db: Session, facet_id: str, user_id: str | None) -> dict[str, Any]:
    facet = library_categories.get_facet(db, facet_id)
    if not facet:
        raise ValueError("分类不存在")

    kind = str(facet["kind"])
    source_name = str(facet["name"])
    work_links = library_categories.list_work_facet_links(db, [facet_id])
    volume_links = library_categories.list_volume_facet_links(db, [facet_id])
    affected_works = library_works.list_works_by_ids(
        db, tuple(str(link["workId"]) for link in work_links)
    )
    affected_volumes = library_categories.list_volumes_by_ids(
        db, [str(link["volumeId"]) for link in volume_links]
    )
    now = _now()
    facet_overrides: dict[str, dict[str, Any]] = {}
    for work in affected_works:
        work_id = str(work["id"])
        if kind == "TAG":
            tags = [
                tag
                for tag in _work_tags(work.get("tags"))
                if _normalized_name(tag) != _normalized_name(source_name)
            ]
            facet_overrides[work_id] = {"tags": _json(tags)}
        elif kind == "AUTHOR":
            authors = [
                author
                for author in split_authors(work.get("author"))
                if _normalized_name(author) != _normalized_name(source_name)
            ]
            facet_overrides[work_id] = {"author": "、".join(authors) or UNKNOWN_AUTHOR}
        elif kind == "SERIES":
            facet_overrides[work_id] = {"seriesName": None}
    facet_write = _prepare_record_facet_write(
        affected_works,
        now=now,
        overrides=facet_overrides,
    )

    work_updates: list[tuple[str, dict[str, Any]]] = []
    for work in affected_works:
        work_id = str(work["id"])
        values = facet_overrides.get(work_id, {})
        if kind == "TAG":
            work_updates.append((work_id, {"tags": values["tags"], "updatedAt": now}))
        elif kind == "AUTHOR":
            author_text = str(values["author"])
            work_updates.append(
                (
                    work_id,
                    {
                        "author": author_text,
                        "normalizedAuthor": _normalized_name(author_text),
                        "mergeKey": identity_merge_key(
                            str(work.get("title") or ""), author_text
                        ),
                        "updatedAt": now,
                    },
                )
            )
        elif kind == "SERIES":
            work_updates.append(
                (
                    work_id,
                    {"seriesName": None, "seriesIndex": None, "updatedAt": now},
                )
            )
    library_works.update_work_fields_bulk(db, tuple(work_updates))
    if kind == "PUBLISHER":
        library_categories.update_volume_fields_bulk(
            db,
            [
                {"id": str(volume["id"]), "publisher": None, "updated_at": now}
                for volume in affected_volumes
            ],
        )
    elif kind not in {"TAG", "AUTHOR", "SERIES"}:
        raise ValueError("分类类型无效")

    library_categories.delete_facets(db, [facet_id])
    operation = library_operations.create_operation(
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
            "volumeLinks": volume_links,
            "works": affected_works,
            "volumes": affected_volumes,
        },
        now=now,
    )
    execute_work_facet_write(db, facet_write)
    return {
        "facetId": facet_id,
        "kind": kind,
        "name": source_name,
        "affectedBookCount": len(
            {
                *(str(link["workId"]) for link in work_links),
                *(str(volume["workId"]) for volume in affected_volumes),
            }
        ),
        "operation": operation_view(operation),
    }


def _undo_operation(
    db: Session,
    operation_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    operation = library_operations.get_operation(db, operation_id)
    if not operation:
        raise ValueError("操作记录不存在")
    owner_id = operation.get("userId")
    if user_id is not None and owner_id != user_id:
        raise ValueError("操作记录不存在")
    if operation.get("status") == "UNDONE":
        raise ValueError("该操作已经撤销")
    if operation.get("status") != "COMPLETED":
        raise ValueError("该操作不可撤销")
    expires_at = to_timestamp_ms(operation.get("expiresAt"))
    if expires_at is not None and expires_at < now_timestamp_ms():
        raise ValueError("撤销期限已过")

    inverse = _parse_json(operation.get("inverseJson"), {})
    action = str(operation.get("action") or "")
    now = _now()
    restored_work_rows: list[dict[str, Any]] = []
    if action == "MERGE_WORKS":
        restored_work_rows = [
            inverse.get("targetWork") or {},
            *(inverse.get("sourceWorks") or []),
        ]
    elif action in {"MOVE_VOLUME", "SPLIT_VOLUME"}:
        source_work = inverse.get("sourceWork")
        if isinstance(source_work, dict):
            restored_work_rows = [source_work]
    elif action in {"MERGE_FACETS", "RENAME_FACET", "DELETE_FACET"}:
        restored_work_rows = [
            work for work in inverse.get("works") or [] if isinstance(work, dict)
        ]
    facet_write = _prepare_record_facet_write(restored_work_rows, now=now)
    if action == "MERGE_WORKS":
        target = inverse.get("targetWork") or {}
        sources = inverse.get("sourceWorks") or []
        work_ids = [
            str(target.get("id") or ""),
            *(str(item.get("id") or "") for item in sources),
        ]
        shelf_ids = list(
            dict.fromkeys(
                str(item.get("shelfId")) for item in inverse.get("shelfWorks") or []
            )
        )
        for shelf_id in shelf_ids:
            for work_id in work_ids:
                library_operations.delete_shelf_work_link(
                    db,
                    shelf_id=shelf_id,
                    work_id=work_id,
                )
        library_operations.insert_snapshot(db, "LibraryWork", target)
        for source in sources:
            library_operations.insert_snapshot(db, "LibraryWork", source)
        for media_version in inverse.get("mediaVersions") or []:
            library_operations.insert_snapshot(
                db,
                "LibraryMediaVersion",
                media_version,
            )
        for volume in inverse.get("volumes") or []:
            library_operations.insert_snapshot(db, "LibraryVolume", volume)
        for shelf in inverse.get("shelfWorks") or []:
            library_operations.insert_snapshot(db, "ShelfWork", shelf)
    elif action in {"MOVE_VOLUME", "SPLIT_VOLUME"}:
        source_work = inverse.get("sourceWork")
        if isinstance(source_work, dict) and source_work:
            library_operations.insert_snapshot(db, "LibraryWork", source_work)
            source_dependents = inverse.get("sourceWorkDependents") or {}
            if isinstance(source_dependents, dict):
                library_operations.restore_rows(db, source_dependents)
        source_version = inverse.get("sourceVersion") or {}
        volume = inverse.get("volume") or {}
        if not source_version or not volume:
            raise ValueError("撤销数据不完整")
        library_operations.insert_snapshot(
            db,
            "LibraryVersion",
            source_version,
        )
        library_operations.insert_snapshot(db, "LibraryVolume", volume)
        target_version_id = str(inverse.get("targetVersionId") or "")
        if inverse.get("targetVersionCreated") and target_version_id:
            library_operations.delete_version_if_empty(
                db,
                target_version_id,
            )
        new_work_id = str(inverse.get("newWorkId") or "")
        if new_work_id:
            library_operations.delete_work_if_empty(db, new_work_id)
    elif action == "RECLASSIFY_VOLUME":
        volumes = inverse.get("volumes") or []
        volume = inverse.get("volume")
        if not volumes and isinstance(volume, dict) and volume:
            volumes = [volume]
        if not volumes:
            raise ValueError("撤销数据不完整")
        for row in volumes:
            library_operations.insert_snapshot(db, "LibraryVolume", row)
    elif action == "DELETE_VOLUME":
        snapshot = inverse.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("撤销数据不完整")
        library_operations.restore_volume_delete_snapshot(db, snapshot)
    elif action == "MERGE_FACETS":
        for work in inverse.get("works") or []:
            library_operations.restore_work_row(db, str(work["id"]), work)
        for volume in inverse.get("volumes") or []:
            library_operations.restore_volume_row(db, volume)
        for facet in inverse.get("facets") or []:
            library_operations.insert_snapshot(db, "LibraryFacet", facet)
        work_ids = list(
            dict.fromkeys(
                str(item["workId"]) for item in inverse.get("workLinks") or []
            )
        )
        volume_ids = list(
            dict.fromkeys(
                str(item["volumeId"]) for item in inverse.get("volumeLinks") or []
            )
        )
        for work_id in work_ids:
            library_operations.delete_work_facets_for_work(db, work_id)
        for volume_id in volume_ids:
            library_operations.delete_volume_facets_for_volume(db, volume_id)
        for link in inverse.get("workLinks") or []:
            library_operations.insert_snapshot(db, "LibraryWorkFacet", link)
        for link in inverse.get("volumeLinks") or []:
            library_operations.insert_snapshot(db, "LibraryVolumeFacet", link)
    elif action == "RENAME_FACET":
        facet = inverse.get("facet") or {}
        if not facet:
            raise ValueError("撤销数据不完整")
        for work in inverse.get("works") or []:
            library_operations.restore_work_row(db, str(work["id"]), work)
        for volume in inverse.get("volumes") or []:
            library_operations.restore_volume_row(db, volume)
        library_operations.restore_facet_row(db, str(facet["id"]), facet)
    elif action == "DELETE_FACET":
        facet = inverse.get("facet") or {}
        if not facet:
            raise ValueError("撤销数据不完整")
        for work in inverse.get("works") or []:
            library_operations.restore_work_row(db, str(work["id"]), work)
        for volume in inverse.get("volumes") or []:
            library_operations.restore_volume_row(db, volume)
        library_operations.insert_snapshot(db, "LibraryFacet", facet)
        for link in inverse.get("workLinks") or []:
            library_operations.insert_snapshot(db, "LibraryWorkFacet", link)
        for link in inverse.get("volumeLinks") or []:
            library_operations.insert_snapshot(db, "LibraryVolumeFacet", link)
    else:
        raise ValueError("该操作不支持撤销")

    execute_work_facet_write(db, facet_write)
    library_operations.mark_operation_undone(
        db,
        operation_id=operation_id,
        now=now,
    )
    updated_operation = {
        **operation,
        "status": "UNDONE",
        "undoneAt": timestamp_ms_to_iso(now),
        "updatedAt": timestamp_ms_to_iso(now),
    }
    return {
        "operation": operation_view(updated_operation),
        "restored": True,
    }


def operation_view(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(operation.get("id") or ""),
        "action": str(operation.get("action") or ""),
        "status": str(operation.get("status") or ""),
        "summary": str(operation.get("summary") or ""),
        "targetType": operation.get("targetType"),
        "targetId": operation.get("targetId"),
        "expiresAt": operation.get("expiresAt"),
        "undoneAt": operation.get("undoneAt"),
        "createdAt": operation.get("createdAt"),
        "updatedAt": operation.get("updatedAt"),
        "undoAvailable": operation.get("status") == "COMPLETED"
        and (
            not operation.get("expiresAt")
            or (to_timestamp_ms(operation.get("expiresAt")) or 0) >= now_timestamp_ms()
        ),
    }


def merge_works(
    db: Session, target_work_id: str, source_work_ids: list[str], user_id: str | None
) -> dict[str, Any]:
    result = MergeLibraryWorks(_LibraryManagementGateway(db), db).execute(
        target_work_id, source_work_ids, user_id
    )
    return dict(result)


def merge_categories(
    db: Session,
    kind: str,
    source_ids: list[str],
    target_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    result = MergeLibraryCategories(_LibraryManagementGateway(db), db).execute(
        kind, source_ids, target_id, user_id
    )
    return dict(result)


def rename_category(
    db: Session, facet_id: str, name: str, user_id: str | None
) -> dict[str, Any]:
    result = RenameLibraryCategory(_LibraryManagementGateway(db), db).execute(
        facet_id, name, user_id
    )
    return dict(result)


def delete_category(db: Session, facet_id: str, user_id: str | None) -> dict[str, Any]:
    result = DeleteLibraryCategory(_LibraryManagementGateway(db), db).execute(
        facet_id, user_id
    )
    return dict(result)


def undo_operation(
    db: Session,
    operation_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    result = UndoLibraryOperation(_LibraryManagementGateway(db), db).execute(
        operation_id, user_id
    )
    return dict(result)
