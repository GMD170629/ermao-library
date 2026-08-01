"""Library management use cases: merge/split works, category edits, undo, smart shelves."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha1
from typing import Any, Concatenate, ParamSpec, TypeVar

from sqlalchemy.orm import Session

from app.bootstrap.library import smart_shelf_work_ids as _query_smart_shelf_work_ids
from app.core.time import now_timestamp_ms, timestamp_ms_to_iso, to_timestamp_ms
from app.modules.library.application.commands import execute_library_write
from app.modules.library.infrastructure import categories as library_categories
from app.modules.library.infrastructure import operations as library_operations
from app.modules.library.infrastructure import works as library_works
from app.modules.library.infrastructure.facets import (
    FACET_KINDS,
    count_categories,
    list_categories,
    split_authors,
)
from app.modules.library.infrastructure.facets import (
    normalized_name as _normalized_name,
)
from app.modules.library.infrastructure.facets import (
    parse_json as _parse_json,
)
from app.modules.library.infrastructure.facets import (
    sync_work_facets as _sync_work_facets,
)
from app.modules.library.infrastructure.facets import (
    unique_names as _unique_names,
)
from app.modules.library.infrastructure.facets import (
    work_tags as _work_tags,
)
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
)

STATUS_RANK = library_works.STATUS_RANK
P = ParamSpec("P")
R = TypeVar("R")

__all__ = ["count_categories", "list_categories"]


def _transactional_write(
    operation: Callable[Concatenate[Session, P], R],
) -> Callable[Concatenate[Session, P], R]:
    """Own one transaction for a compatibility write use case."""

    @wraps(operation)
    def execute(db: Session, *args: P.args, **kwargs: P.kwargs) -> R:
        return execute_library_write(
            db,
            lambda: operation(db, *args, **kwargs),
        )

    return execute


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
    *,
    commit: bool = True,
) -> None:
    """Compatibility command; infrastructure only flushes."""

    _sync_work_facets(db, work_id)
    if commit:
        db.commit()


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


def _shelf_snapshot(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids or not library_operations.has_table(db, "ShelfWork"):
        return []
    return library_works.list_shelf_links_for_works(db, work_ids)


@_transactional_write
def merge_works(
    db: Session, target_work_id: str, source_work_ids: list[str], user_id: str | None
) -> dict[str, Any]:
    sources = [
        value
        for value in dict.fromkeys(source_work_ids)
        if value and value != target_work_id
    ]
    target = library_works.get_visible_work(db, target_work_id)
    if not target:
        raise ValueError("主作品不存在")
    source_rows = [
        row
        for work_id in sources
        if (row := library_works.get_visible_work(db, work_id))
    ]
    if len(source_rows) != len(sources) or not source_rows:
        raise ValueError("请选择至少一条可合并的作品")

    all_work_ids = [target_work_id, *sources]
    media_versions = library_works.list_media_versions_for_works(db, all_work_ids)
    media_histories = library_works.list_media_histories_for_works(db, all_work_ids)
    inverse = {
        "targetWork": target,
        "sourceWorks": source_rows,
        "mediaVersions": media_versions,
        "volumes": library_operations.snapshot_volumes_for_media_versions(
            db,
            [str(item["id"]) for item in media_versions],
        ),
        "mediaHistories": media_histories,
        "shelfWorks": _shelf_snapshot(db, all_work_ids),
    }

    target_tags = _work_tags(target.get("tags"))
    for source in source_rows:
        target_tags = _unique_names([*target_tags, *_work_tags(source.get("tags"))])
    now = _now()
    library_works.update_merged_target_work(
        db,
        work_id=target_work_id,
        tags_json=_json(target_tags),
        description=next(
            (row.get("description") for row in source_rows if row.get("description")),
            None,
        ),
        series_name=next(
            (row.get("seriesName") for row in source_rows if row.get("seriesName")),
            None,
        ),
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
    sync_work_facets(db, target_work_id, commit=False)
    return {
        "targetWorkId": target_work_id,
        "sourceWorkIds": sources,
        "operation": operation_view(operation),
    }


@_transactional_write
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
    target = library_categories.get_facet_of_kind(db, target_id, normalized_kind)
    sources = [value for value in dict.fromkeys(source_ids) if value != target_id]
    source_rows = [
        row
        for source_id in sources
        if (row := library_categories.get_facet_of_kind(db, source_id, normalized_kind))
    ]
    if not target or not source_rows or len(source_rows) != len(sources):
        raise ValueError("请选择同一分类中的有效合并项")
    all_facet_ids = [target_id, *sources]
    work_links = library_categories.list_work_facet_links(db, all_facet_ids)
    volume_links = library_categories.list_volume_facet_links(db, all_facet_ids)
    work_ids = list(dict.fromkeys(str(row["workId"]) for row in work_links))
    volume_ids = list(dict.fromkeys(str(row["volumeId"]) for row in volume_links))
    affected_works = [
        row for work_id in work_ids if (row := library_categories.get_work(db, work_id))
    ]
    affected_volumes = [
        row
        for volume_id in volume_ids
        if (row := library_categories.get_volume(db, volume_id))
    ]
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
    if normalized_kind == "TAG":
        for work in affected_works:
            tags = [
                target_name if _normalized_name(tag) in source_names else tag
                for tag in _work_tags(work.get("tags"))
            ]
            library_categories.update_work_tags(
                db,
                work_id=str(work["id"]),
                tags_json=_json(_unique_names(tags)),
                now=now,
            )
    elif normalized_kind == "AUTHOR":
        for work in affected_works:
            authors = [
                target_name if _normalized_name(author) in source_names else author
                for author in split_authors(work.get("author"))
            ]
            author_text = "、".join(_unique_names(authors)) or target_name
            library_categories.update_work_author(
                db,
                work_id=str(work["id"]),
                author=author_text,
                normalized_author=_normalized_name(author_text),
                merge_key=identity_merge_key(str(work.get("title") or ""), author_text),
                now=now,
            )
    elif normalized_kind == "SERIES":
        for work in affected_works:
            library_categories.update_work_series_name(
                db,
                work_id=str(work["id"]),
                series_name=target_name,
                now=now,
            )
    else:
        for volume in affected_volumes:
            library_categories.update_volume_publisher(
                db,
                volume_id=str(volume["id"]),
                publisher=target_name,
                now=now,
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
    for work_id in work_ids:
        sync_work_facets(db, work_id, commit=False)
    return {
        "targetId": target_id,
        "mergedIds": sources,
        "operation": operation_view(operation),
    }


@_transactional_write
def rename_category(
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
    if facet["kind"] == "PUBLISHER":
        volume_ids = library_categories.list_volume_ids_for_facet(db, facet_id)
        linked_volumes = [
            item
            for volume_id in volume_ids
            if (item := library_categories.get_volume(db, volume_id))
        ]
        for volume_id in volume_ids:
            library_categories.update_volume_publisher(
                db,
                volume_id=volume_id,
                publisher=next_name,
                now=now,
            )
    else:
        work_ids = library_categories.list_work_ids_for_facet(db, facet_id)
        linked_works = [
            item
            for work_id in work_ids
            if (item := library_categories.get_work(db, work_id))
        ]
        for work_id in work_ids:
            work = library_categories.get_work(db, work_id) or {}
            if facet["kind"] == "TAG":
                values = [
                    next_name
                    if _normalized_name(tag) == _normalized_name(source_name)
                    else tag
                    for tag in _work_tags(work.get("tags"))
                ]
                library_categories.update_work_tags(
                    db,
                    work_id=work_id,
                    tags_json=_json(_unique_names(values)),
                    now=now,
                )
            elif facet["kind"] == "AUTHOR":
                values = [
                    next_name
                    if _normalized_name(author) == _normalized_name(source_name)
                    else author
                    for author in split_authors(work.get("author"))
                ]
                author_text = "、".join(_unique_names(values))
                library_categories.update_work_author(
                    db,
                    work_id=work_id,
                    author=author_text,
                    normalized_author=_normalized_name(author_text),
                    merge_key=identity_merge_key(
                        str(work.get("title") or ""), author_text
                    ),
                    now=now,
                )
            elif facet["kind"] == "SERIES":
                library_categories.update_work_series_name(
                    db,
                    work_id=work_id,
                    series_name=next_name,
                    now=now,
                )
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
    work_ids_to_sync = {
        *(str(work["id"]) for work in linked_works),
        *(str(volume["workId"]) for volume in linked_volumes),
    }
    for work_id in work_ids_to_sync:
        sync_work_facets(db, work_id, commit=False)
    return {
        "facetId": facet_id,
        "name": next_name,
        "operation": operation_view(operation),
    }


@_transactional_write
def delete_category(db: Session, facet_id: str, user_id: str | None) -> dict[str, Any]:
    facet = library_categories.get_facet(db, facet_id)
    if not facet:
        raise ValueError("分类不存在")

    kind = str(facet["kind"])
    source_name = str(facet["name"])
    work_links = library_categories.list_work_facet_links(db, [facet_id])
    volume_links = library_categories.list_volume_facet_links(db, [facet_id])
    affected_works = [
        row
        for link in work_links
        if (row := library_categories.get_work(db, str(link["workId"])))
    ]
    affected_volumes = [
        row
        for link in volume_links
        if (row := library_categories.get_volume(db, str(link["volumeId"])))
    ]
    now = _now()

    if kind == "TAG":
        for work in affected_works:
            tags = [
                tag
                for tag in _work_tags(work.get("tags"))
                if _normalized_name(tag) != _normalized_name(source_name)
            ]
            library_categories.update_work_tags(
                db,
                work_id=str(work["id"]),
                tags_json=_json(tags),
                now=now,
            )
    elif kind == "AUTHOR":
        for work in affected_works:
            authors = [
                author
                for author in split_authors(work.get("author"))
                if _normalized_name(author) != _normalized_name(source_name)
            ]
            author_text = "、".join(authors) or UNKNOWN_AUTHOR
            library_categories.update_work_author(
                db,
                work_id=str(work["id"]),
                author=author_text,
                normalized_author=_normalized_name(author_text),
                merge_key=identity_merge_key(str(work.get("title") or ""), author_text),
                now=now,
            )
    elif kind == "SERIES":
        for work in affected_works:
            library_categories.clear_work_series(db, work_id=str(work["id"]), now=now)
    elif kind == "PUBLISHER":
        for volume in affected_volumes:
            library_categories.clear_volume_publisher(
                db, volume_id=str(volume["id"]), now=now
            )
    else:
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
    work_ids_to_sync = {
        *(str(link["workId"]) for link in work_links),
        *(str(volume["workId"]) for volume in affected_volumes),
    }
    for work_id in work_ids_to_sync:
        sync_work_facets(db, work_id, commit=False)
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


@_transactional_write
def undo_operation(
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
    expires_at = to_timestamp_ms(operation.get("expiresAt"))
    if expires_at is not None and expires_at < now_timestamp_ms():
        raise ValueError("撤销期限已过")

    inverse = _parse_json(operation.get("inverseJson"), {})
    action = str(operation.get("action") or "")
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
        for history in inverse.get("mediaHistories") or []:
            library_operations.insert_snapshot(db, "UserMediaHistory", history)
        for shelf in inverse.get("shelfWorks") or []:
            library_operations.insert_snapshot(db, "ShelfWork", shelf)
        for work_id in work_ids:
            if work_id:
                sync_work_facets(db, work_id, commit=False)
    elif action in {"MOVE_VOLUME", "SPLIT_VOLUME"}:
        source_work = inverse.get("sourceWork")
        if isinstance(source_work, dict) and source_work:
            library_operations.insert_snapshot(db, "LibraryWork", source_work)
            source_dependents = inverse.get("sourceWorkDependents") or {}
            if isinstance(source_dependents, dict):
                library_operations.restore_rows(db, source_dependents)
        source_media = inverse.get("sourceMediaVersion") or {}
        volume = inverse.get("volume") or {}
        if not source_media or not volume:
            raise ValueError("撤销数据不完整")
        library_operations.insert_snapshot(
            db,
            "LibraryMediaVersion",
            source_media,
        )
        library_operations.insert_snapshot(db, "LibraryVolume", volume)
        for history in inverse.get("mediaHistories") or []:
            library_operations.insert_snapshot(db, "UserMediaHistory", history)
        target_media_version_id = str(inverse.get("targetMediaVersionId") or "")
        if inverse.get("targetMediaVersionCreated") and target_media_version_id:
            library_operations.delete_media_version_if_empty(
                db,
                target_media_version_id,
            )
        new_work_id = str(inverse.get("newWorkId") or "")
        if new_work_id:
            library_operations.delete_work_if_empty(db, new_work_id)
        source_work_id = str(source_media.get("workId") or "")
        if source_work_id:
            sync_work_facets(db, source_work_id, commit=False)
    elif action == "DELETE_VOLUME":
        snapshot = inverse.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("撤销数据不完整")
        library_operations.restore_volume_delete_snapshot(db, snapshot)
        restored_volume = (snapshot.get("LibraryVolume") or [{}])[0]
        media_version_id = str(restored_volume.get("mediaVersionId") or "")
        if media_version_id:
            media_version = next(
                iter(snapshot.get("LibraryMediaVersion") or []),
                None,
            )
            if media_version and media_version.get("workId"):
                sync_work_facets(
                    db,
                    str(media_version["workId"]),
                    commit=False,
                )
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

    now = _now()
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
