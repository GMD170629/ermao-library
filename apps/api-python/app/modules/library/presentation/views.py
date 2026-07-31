"""Library HTTP projections and work detail views."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi.responses import Response
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.bootstrap.library import (
    library_facet_queries,
    library_join_queries,
    library_projections,
    library_storage,
    library_works,
)
from app.bootstrap.organize import organize_jobs
from app.bootstrap.system import get_setting
from app.core.authorization import authorization_context, can_access_work, can_manage_system
from app.core.config import Settings
from app.core.time import timestamp_ms_to_iso
from app.models.auth import User
from app.modules.reader.public import (
    choose_continue_volume as _choose_continue_volume,
    continue_progress_for_edition as _continue_progress_for_edition,
    display_progress_percent as _display_progress_percent,
    latest_progress as _latest_progress,
    number_or_none as _number_or_none,
    progress_chapter_label as _progress_chapter_label,
    progress_extra as _progress_extra,
    progress_for_volume as _progress_for_volume,
    progress_navigation as _progress_navigation,
    progress_percent_with_navigation as _progress_percent_with_navigation,
)
from app.modules.system.public import (
    DETAIL_TAB_KEYS,
    normalize_detail_tab_order as _normalize_detail_tab_order,
)
from app.schemas.responses import fail
from app.services.book_identity import normalize_identity_part
from app.services.library_filters import library_filter_schema
from app.services.library_management import list_categories
from app.services.organize_service import context_for_job, ensure_organize_job_for_work
from app.services.text_conversion import CONVERTIBLE_TEXT_EXTS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _has_column(db: Session, table: str, column: str) -> bool:
    try:
        return any(item.get("name") == column for item in inspect(db.connection()).get_columns(table))
    except Exception:
        return False


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return timestamp_ms_to_iso(value) or str(value)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    boolean_keys = {
        "enabled",
        "ignoreHidden",
        "downloadAvailable",
        "duplicate",
        "primary",
        "hidden",
        "organized",
        "abridged",
        "pinned",
    }
    for key in boolean_keys & row.keys():
        if row[key] in (0, 1):
            row[key] = bool(row[key])
    return row


def _get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    return library_works.get_work(db, work_id)


def _visible_work_or_none(db: Session, user: User, work_id: str) -> dict[str, Any] | None:
    if not can_access_work(db, user, work_id):
        return None
    return _get_work(db, work_id)


def _require_work_manager(db: Session, user: User, work_id: str) -> Response | None:
    if not can_access_work(db, user, work_id):
        return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    if not can_manage_system(user):
        return fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    return None

def _cover_url(kind: str, row_id: str, row: dict[str, Any] | None = None, **params: Any) -> str:
    query = {key: value for key, value in params.items() if value is not None}
    version_source = ""
    if row:
        version_source = "|".join([str(row.get("coverPath") or ""), _dt(row.get("updatedAt")) or ""])
    if version_source.strip("|"):
        query["v"] = hashlib.sha1(version_source.encode("utf-8")).hexdigest()[:12]
    suffix = f"?{urlencode(query)}" if query else ""
    return f"/api/{kind}/{row_id}/cover{suffix}"


def _format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.0f} {units[index]}" if index == 0 else f"{size:.1f} {units[index]}"


def _coerce_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _labels() -> dict[str, dict[str, str]]:
    return {
        "format": {
            "EPUB": "EPUB", "COMIC": "漫画", "PDF": "PDF", "AUDIO": "音频",
            "MOBI": "MOBI", "AZW": "AZW", "AZW3": "AZW3", "PRC": "PRC", "FB2": "FB2", "TXT": "TXT",
        },
        "status": {"UNREAD": "未读", "READING": "在读", "FINISHED": "已读"},
        "publication": {"UNKNOWN": "未知", "ONGOING": "连载中", "COMPLETED": "已完结", "HIATUS": "休刊", "CANCELLED": "已取消"},
        "tracking": {"NOT_TRACKING": "未追踪", "TRACKING": "追踪中", "PAUSED": "已暂停", "IGNORED": "已忽略"},
    }


DETAIL_TAB_LABELS = {"EBOOK": "电子书", "COMIC": "漫画", "AUDIOBOOK": "有声书", "STRUCTURE": "内容结构"}


def _edition_media_kind(edition: dict[str, Any]) -> str:
    stored = str(edition.get("mediaKind") or "").strip().upper()
    if stored in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        return stored
    fmt = str(edition.get("format") or "").strip().upper()
    return "COMIC" if fmt == "COMIC" else "AUDIOBOOK" if fmt == "AUDIO" else "EBOOK"


def _detail_tab_order(db: Session) -> list[str]:
    from app.bootstrap.system import get_setting

    value = get_setting(db, "workDetail.tabOrder")
    return _normalize_detail_tab_order(value)


def _detail_tabs(db: Session, available_media_kinds: set[str]) -> list[dict[str, Any]]:
    visible = available_media_kinds | {"STRUCTURE"}
    return [
        {"key": key, "label": DETAIL_TAB_LABELS[key], "sortOrder": index}
        for index, key in enumerate(_detail_tab_order(db))
        if key in visible
    ]


def _saved_detail_tab(db: Session, user_id: str | None, work_id: str) -> str | None:
    if not user_id or not _has_table(db, "WorkDetailPreference"):
        return None
    row = library_projections.get_detail_preference(
        db,
        user_id=user_id,
        work_id=work_id,
    )
    selected = str((row or {}).get("selectedTab") or "").strip().upper()
    return selected if selected in DETAIL_TAB_KEYS else None


def _resolve_detail_tab(
    db: Session,
    user_id: str | None,
    work_id: str,
    detail_tabs: list[dict[str, Any]],
    requested: str | None = None,
) -> str:
    visible = [str(item["key"]) for item in detail_tabs]
    explicit = str(requested or "").strip().upper()
    if explicit and explicit in visible:
        return explicit
    saved = _saved_detail_tab(db, user_id, work_id)
    if saved in visible:
        return str(saved)
    return next((key for key in visible if key != "STRUCTURE"), "STRUCTURE")


def _status_from_progress(progress: dict[str, Any] | None, fallback: str = "UNREAD") -> str:
    if not progress:
        return _reading_status(fallback)
    percent = float(progress.get("percent") or 0)
    return "FINISHED" if percent >= 100 else "READING" if percent > 0 else "UNREAD"


def _set_consumption_status(
    db: Session,
    user_id: str,
    work_id: str,
    media_kind: str,
    status: str,
    *,
    edition_id: str | None = None,
    volume_id: str | None = None,
    unit_id: str | None = None,
) -> None:
    if not _has_table(db, "LibraryConsumptionState"):
        return
    now = _now()
    existing = library_projections.get_consumption_state(
        db,
        user_id=user_id,
        work_id=work_id,
        media_kind=media_kind,
    )
    edition_changed = bool(edition_id and existing and edition_id != existing.get("lastEditionId"))
    volume_changed = bool(
        volume_id is not None
        and (existing or {}).get("lastVolumeId") is not None
        and volume_id != (existing or {}).get("lastVolumeId")
    )
    library_projections.save_consumption_state(
        db,
        user_id=user_id,
        work_id=work_id,
        media_kind=media_kind,
        status=status,
        last_edition_id=edition_id or (existing or {}).get("lastEditionId"),
        last_volume_id=(
            volume_id
            if volume_id is not None
            else None
            if edition_changed
            else (existing or {}).get("lastVolumeId")
        ),
        last_unit_id=(
            unit_id
            if unit_id is not None
            else None
            if edition_changed or volume_changed
            else (existing or {}).get("lastUnitId")
        ),
        now=now,
    )


def _resolve_consumption_target(
    db: Session,
    work_id: str,
    media_kind: str,
    *,
    edition_id: str | None,
    volume_id: str | None,
    unit_id: str | None,
) -> tuple[dict[str, str | None] | None, str | None]:
    """Validate and normalize the optional consumption-state hierarchy."""

    resolved_edition_id = edition_id
    resolved_volume_id = volume_id
    resolved_unit_id = unit_id

    if edition_id:
        edition = library_projections.get_edition(db, edition_id)
        if (
            not edition
            or str(edition.get("workId")) != work_id
            or _edition_media_kind(edition) != media_kind
            or bool(edition.get("hidden"))
        ):
            return None, "editionId 不属于该作品的当前媒介"

    if volume_id:
        volume = library_join_queries.get_volume_with_edition(db, volume_id)
        if (
            not volume
            or str(volume.get("workId")) != work_id
            or _edition_media_kind(volume) != media_kind
            or bool(volume.get("editionHidden"))
            or (resolved_edition_id is not None and str(volume.get("editionId")) != resolved_edition_id)
        ):
            return None, "volumeId 不属于指定作品、媒介或版本"
        resolved_edition_id = str(volume["editionId"])

    if unit_id:
        unit = library_join_queries.get_unit_with_edition(db, unit_id)
        if (
            not unit
            or str(unit.get("workId")) != work_id
            or _edition_media_kind(unit) != media_kind
            or bool(unit.get("editionHidden"))
            or (resolved_edition_id is not None and str(unit.get("editionId")) != resolved_edition_id)
            or (resolved_volume_id is not None and str(unit.get("volumeId") or "") != resolved_volume_id)
        ):
            return None, "unitId 不属于指定作品、媒介、版本或卷册"
        resolved_edition_id = str(unit["editionId"])
        if unit.get("volumeId") is not None:
            resolved_volume_id = str(unit["volumeId"])

    return {
        "editionId": resolved_edition_id,
        "volumeId": resolved_volume_id,
        "unitId": resolved_unit_id,
    }, None


def _project_work_status_for_user(db: Session, user_id: str, work_id: str) -> str:
    if not _has_table(db, "LibraryConsumptionState") or not _has_table(db, "LibraryEdition"):
        return "UNREAD"
    user = db.get(User, user_id)
    context = authorization_context(db, user) if user is not None else None
    edition_rows = library_works.list_visible_editions_for_work(
        db, work_id=work_id, context=context
    )
    media_kinds = {_edition_media_kind(item) for item in edition_rows}
    states = {
        str(item.get("mediaKind")): _reading_status(item.get("status"))
        for item in library_projections.list_consumption_states(
            db,
            user_id=user_id,
            work_id=work_id,
        )
    }
    if not any(kind in states for kind in media_kinds):
        return "UNREAD"
    if media_kinds and all(states.get(kind) == "FINISHED" for kind in media_kinds):
        return "FINISHED"
    if any(states.get(kind) in {"READING", "FINISHED"} for kind in media_kinds):
        return "READING"
    return "UNREAD"




def _format_duration(duration_ms: Any) -> str:
    total_seconds = max(0, int(float(duration_ms or 0) / 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _media_position_label(db: Session, media_kind: str, progress: dict[str, Any] | None) -> str:
    if not progress:
        return "未开始"
    if media_kind != "AUDIOBOOK":
        page = progress.get("page")
        return f"第 {page} 页" if page else "继续上次位置"
    location = _parse_json(progress.get("locationJson"), {})
    extra = _progress_extra(progress)
    position_ms = _number_or_none(location.get("positionMs") if isinstance(location, dict) else None)
    if position_ms is None:
        position_ms = _number_or_none(extra.get("positionMs"))
    if position_ms is None:
        try:
            position_ms = int(float(progress.get("position") or 0))
        except (TypeError, ValueError):
            position_ms = 0
    chapter_id = location.get("chapterId") if isinstance(location, dict) else extra.get("chapterId")
    chapter_title = (
        library_projections.get_reading_unit_title(db, str(chapter_id))
        if chapter_id and _has_table(db, "LibraryReadingUnit")
        else None
    )
    prefix = f"{chapter_title} · " if chapter_title else ""
    return f"{prefix}{_format_duration(position_ms)}"


def _reading_status(value: Any) -> str:
    normalized = str(value or "UNREAD").strip().upper()
    if normalized == "WANT":
        return "UNREAD"
    return normalized if normalized in {"UNREAD", "READING", "FINISHED"} else "UNREAD"


def _bookshelf_work_view(work: dict[str, Any]) -> dict[str, Any]:
    work_type = str(work.get("workType") or "EPUB").upper()
    labels = _labels()
    return {
        "id": work["id"],
        "title": work.get("title") or "未命名作品",
        "author": work.get("author") or "未知作者",
        "format": labels["format"].get(work_type, "未知"),
        "gradient": "from-slate-950 via-blue-800 to-cyan-500",
        "coverStatus": work.get("coverStatus") or "PENDING",
        "coverUrl": _cover_url("works", work["id"], work, size="medium"),
    }


def _bookshelf_item_view(work: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": work["id"],
        "title": work.get("title") or "未命名作品",
        "author": work.get("author") or "未知作者",
        "coverUrl": _cover_url("works", work["id"], work, size="medium"),
    }


def _book_search_item_view(work: dict[str, Any]) -> dict[str, Any]:
    work_type = str(work.get("workType") or "EPUB").upper()
    return {
        **_bookshelf_item_view(work),
        "format": _labels()["format"].get(work_type, "未知"),
    }


def _management_work_views(
    db: Session,
    works: list[dict[str, Any]],
    user_id: str,
) -> list[dict[str, Any]]:
    """Serialize a page of works without loading detail-only files and structure."""

    if not works:
        return []

    work_ids = [str(work["id"]) for work in works]
    user = db.get(User, user_id)
    context = authorization_context(db, user) if user is not None else None
    editions_by_work: dict[str, list[dict[str, Any]]] = {work_id: [] for work_id in work_ids}
    if _has_table(db, "LibraryEdition"):
        for work_id in work_ids:
            editions_by_work[work_id] = library_works.list_visible_editions_for_work(
                db, work_id=work_id, context=context
            )

    states_by_work: dict[str, dict[str, str]] = {work_id: {} for work_id in work_ids}
    if _has_table(db, "LibraryConsumptionState") and work_ids:
        from sqlalchemy import select
        from app.models.library import LibraryConsumptionState, LibraryEdition, LibraryReadingProgress

        for state in db.execute(
            select(
                LibraryConsumptionState.work_id,
                LibraryConsumptionState.media_kind,
                LibraryConsumptionState.status,
            ).where(
                LibraryConsumptionState.user_id == user_id,
                LibraryConsumptionState.work_id.in_(work_ids),
            )
        ).all():
            states_by_work.setdefault(str(state.work_id), {})[
                str(state.media_kind or "").upper()
            ] = _reading_status(state.status)

    last_read_by_work: dict[str, str | None] = {}
    if _has_table(db, "LibraryReadingProgress") and _has_table(db, "LibraryEdition") and work_ids:
        from sqlalchemy import func, select
        from app.models.library import LibraryEdition, LibraryReadingProgress
        from app.core.authorization import edition_visibility_predicate

        filters = [
            LibraryReadingProgress.user_id == user_id,
            LibraryReadingProgress.work_id.in_(work_ids),
            func.coalesce(LibraryEdition.hidden, False).is_(False),
        ]
        if context is not None:
            filters.append(edition_visibility_predicate(context))
        for progress in db.execute(
            select(
                LibraryReadingProgress.work_id,
                func.max(LibraryReadingProgress.updated_at).label("lastReadAt"),
            )
            .join(LibraryEdition, LibraryEdition.id == LibraryReadingProgress.edition_id)
            .where(*filters)
            .group_by(LibraryReadingProgress.work_id)
        ).all():
            last_read_by_work[str(progress.work_id)] = _dt(progress.lastReadAt)

    labels = _labels()
    media_kind_order = [
        key for key in _detail_tab_order(db)
        if key in {"EBOOK", "COMIC", "AUDIOBOOK"}
    ]
    result = []
    for work in works:
        work_id = str(work["id"])
        editions = editions_by_work.get(work_id, [])
        primary_edition_id = work.get("primaryEditionId")
        display = (
            next((edition for edition in editions if edition["id"] == primary_edition_id), None)
            or next((edition for edition in editions if bool(edition.get("primary"))), None)
            or (editions[0] if editions else None)
        )
        available_kinds = {_edition_media_kind(edition) for edition in editions}
        available_media_kinds = [
            media_kind for media_kind in media_kind_order
            if media_kind in available_kinds
        ]
        states = states_by_work.get(work_id, {})
        if available_kinds and all(states.get(kind) == "FINISHED" for kind in available_kinds):
            status_value = "FINISHED"
        elif any(states.get(kind) in {"READING", "FINISHED"} for kind in available_kinds):
            status_value = "READING"
        else:
            status_value = "UNREAD"
        work_type = str((display or {}).get("format") or work.get("workType") or "EPUB").upper()
        result.append(
            {
                **_bookshelf_work_view(work),
                "publisher": (display or {}).get("publisher"),
                "seriesName": work.get("seriesName"),
                "tags": _parse_json(work.get("tags"), []),
                "type": "comic" if work_type == "COMIC" else "audiobook" if work_type == "AUDIO" else "ebook",
                "format": labels["format"].get(work_type, work_type),
                "availableMediaKinds": available_media_kinds,
                "statusValue": status_value,
                "lastReadAt": last_read_by_work.get(work_id),
                "importedAt": _dt(work.get("createdAt")),
            }
        )
    return result


def _work_view(db: Session, work: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    editions = []
    files_by_edition: dict[str, list[dict[str, Any]]] = {}
    volumes_by_edition: dict[str, list[dict[str, Any]]] = {}
    progresses_by_edition: dict[str, list[dict[str, Any]]] = {}
    conversion_by_edition: dict[str, dict[str, Any]] = {}
    if _has_table(db, "LibraryEdition"):
        user = db.get(User, user_id) if user_id else None
        context = authorization_context(db, user) if user is not None else None
        editions = library_works.list_visible_editions_for_work(
            db, work_id=str(work["id"]), context=context
        )
    edition_ids = [item["id"] for item in editions]
    if edition_ids and _has_table(db, "LibraryFile"):
        for edition in editions:
            files_by_edition[edition["id"]] = library_projections.list_files_for_edition(
                db, str(edition["id"])
            )
    if edition_ids and _has_table(db, "LibraryVolume"):
        for edition in editions:
            volumes_by_edition[edition["id"]] = library_projections.list_volumes_for_edition(
                db, str(edition["id"])
            )
    if edition_ids and _has_table(db, "LibraryMetadata"):
        for edition in editions:
            conversion_metadata = library_projections.latest_conversion_metadata(
                db, str(edition["id"])
            )
            raw_conversion = _parse_json((conversion_metadata or {}).get("rawJson"), {})
            if isinstance(raw_conversion, dict) and raw_conversion:
                conversion_by_edition[edition["id"]] = {
                    "sourceFormat": raw_conversion.get("sourceFormat"),
                    "targetFormat": raw_conversion.get("targetFormat"),
                    "converter": raw_conversion.get("converter"),
                    "converterVersion": raw_conversion.get("converterVersion"),
                    "cached": bool(raw_conversion.get("cached")),
                }
    if edition_ids and user_id and _has_table(db, "LibraryReadingProgress"):
        for edition in editions:
            progresses = library_projections.list_progress_for_edition(
                db,
                edition_id=str(edition["id"]),
                user_id=user_id,
            )
            if progresses:
                progresses_by_edition[edition["id"]] = progresses

    primary = next((item for item in editions if item["id"] == work.get("primaryEditionId")), None) or next((item for item in editions if item.get("primary")), None)
    display = primary or (editions[0] if editions else None)
    progress_by_edition = {
        edition["id"]: _continue_progress_for_edition(edition, progresses_by_edition.get(edition["id"], []), volumes_by_edition.get(edition["id"], []))
        for edition in editions
        if progresses_by_edition.get(edition["id"])
    }
    latest_read_progress = _latest_progress([row for rows in progresses_by_edition.values() for row in rows])
    recent = sorted((item for item in progress_by_edition.values() if item), key=lambda item: _dt(item.get("updatedAt")) or "", reverse=True)
    progress = recent[0] if recent else (progress_by_edition.get(display["id"]) if display else None)
    progress_edition = next((item for item in editions if progress and item["id"] == progress.get("editionId")), None) or display
    progress_volumes = volumes_by_edition.get(progress_edition["id"], []) if progress_edition else []
    progress_units = (
        library_projections.list_reading_units(
            db,
            edition_id=str(progress_edition["id"]),
            volume_id=(
                str(progress.get("volumeId"))
                if progress and progress.get("volumeId") is not None
                else None
            ),
        )
        if progress_edition and _has_table(db, "LibraryReadingUnit")
        else []
    )
    progress_navigation = _progress_navigation(progress, progress_units)
    percent = _progress_percent_with_navigation(progress, progress_units) if progress_edition and progress_edition.get("format") == "EPUB" else _display_progress_percent(
        progress_edition,
        progress,
        progress_volumes,
        progresses_by_edition.get(str(progress_edition["id"]), []) if progress_edition else [],
    )
    labels = _labels()
    total_size = sum(int(file.get("sizeBytes") or 0) for files in files_by_edition.values() for file in files)

    def volume_view(volume: dict[str, Any], progress_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        volume_progress = _progress_for_volume(progress_rows or [], volume["id"])
        volume_units = (
            library_projections.list_reading_units(
                db,
                edition_id=str(volume["editionId"]),
                volume_id=str(volume["id"]),
            )
            if volume_progress and _has_table(db, "LibraryReadingUnit")
            else []
        )
        return {
            "id": volume["id"],
            "editionId": volume["editionId"],
            "title": volume.get("title") or "未命名卷",
            "volumeIndex": volume.get("volumeIndex"),
            "sortOrder": volume.get("sortOrder") or 0,
            "pageCount": volume.get("pageCount"),
            "chapterCount": volume.get("chapterCount"),
            "durationMs": volume.get("durationMs"),
            "coverUrl": _cover_url("volumes", volume["id"], volume, workId=work["id"]),
            "progress": _progress_percent_with_navigation(volume_progress, volume_units),
            "lastReadAt": _dt(volume_progress.get("updatedAt")) if volume_progress else None,
            "position": volume_progress.get("position") if volume_progress else None,
            "currentPage": volume_progress.get("page") if volume_progress else None,
            **_progress_navigation(volume_progress, volume_units),
        }

    def file_view(file: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": file["id"],
            "editionId": file.get("editionId"),
            "volumeId": file.get("volumeId"),
            "path": file.get("path") or "",
            "mimeType": file.get("mimeType") or "application/octet-stream",
            "kind": file.get("kind") or work.get("workType"),
            "sortOrder": file.get("sortOrder") or 0,
            "sizeBytes": int(file.get("sizeBytes") or 0),
            "size": _format_bytes(file.get("sizeBytes")),
            "durationMs": file.get("durationMs"),
            "codec": file.get("codec"),
            "bitrate": file.get("bitrate"),
            "sampleRate": file.get("sampleRate"),
            "channels": file.get("channels"),
            "discNumber": file.get("discNumber"),
            "trackNumber": file.get("trackNumber"),
            "url": f"/api/files/{quote(str(file['id']), safe='')}",
        }

    edition_views = []
    for edition in editions:
        e_progress = progress_by_edition.get(edition["id"])
        e_progress_rows = progresses_by_edition.get(edition["id"], [])
        edition_files = files_by_edition.get(edition["id"], [])
        edition_volumes = [volume_view(volume, e_progress_rows) for volume in volumes_by_edition.get(edition["id"], [])]
        raw_edition_volumes = volumes_by_edition.get(edition["id"], [])
        edition_format = str(edition.get("format") or work.get("workType") or "").upper()
        edition_views.append(
            {
                "id": edition["id"],
                "workId": edition["workId"],
                "mediaKind": _edition_media_kind(edition),
                "formatValue": edition_format,
                "format": labels["format"].get(edition.get("format"), edition.get("format") or "未知"),
                "versionName": edition.get("versionName") or "默认版本",
                "description": edition.get("description"),
                "publisher": edition.get("publisher"),
                "publishedAt": _dt(edition.get("publishedAt")),
                "language": edition.get("language"),
                "identifier": edition.get("identifier"),
                "isbn": edition.get("isbn"),
                "origin": edition.get("origin"),
                "sourcePath": edition_files[0].get("path") if edition_files else None,
                "primary": edition["id"] == work.get("primaryEditionId") or bool(edition.get("primary")),
                "hidden": bool(edition.get("hidden")),
                "size": _format_bytes(edition.get("sizeBytes")),
                "pageCount": edition.get("pageCount"),
                "chapterCount": edition.get("chapterCount"),
                "durationMs": edition.get("durationMs"),
                "trackCount": edition.get("trackCount"),
                "narrator": edition.get("narrator"),
                "abridged": edition.get("abridged"),
                "progress": _display_progress_percent(edition, e_progress, raw_edition_volumes, e_progress_rows),
                "lastReadAt": _dt(e_progress.get("updatedAt")) if e_progress else None,
                "coverUrl": _cover_url("editions", edition["id"], edition, size="medium"),
                "conversion": conversion_by_edition.get(edition["id"]),
                "readable": edition_format
                in {"EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT", "PDF", "COMIC", "AUDIO"},
                "conversionAvailable": f".{edition_format.lower()}" in CONVERTIBLE_TEXT_EXTS,
                "files": [file_view(file) for file in edition_files],
                "volumes": edition_volumes,
            }
        )

    consumption_by_kind: dict[str, dict[str, Any]] = {}
    if user_id and _has_table(db, "LibraryConsumptionState"):
        consumption_by_kind = {
            str(item.get("mediaKind") or "").upper(): item
            for item in library_projections.list_consumption_states(
                db,
                user_id=user_id,
                work_id=str(work["id"]),
            )
        }
    media_groups_by_kind: dict[str, dict[str, Any]] = {}
    for media_kind in ("EBOOK", "COMIC", "AUDIOBOOK"):
        raw_group = [item for item in editions if _edition_media_kind(item) == media_kind]
        if not raw_group:
            continue
        group_views = [item for item in edition_views if item.get("mediaKind") == media_kind]
        group_primary = next((item for item in raw_group if bool(item.get("primary"))), None) or raw_group[0]
        group_progresses = [
            value
            for edition in raw_group
            for value in progresses_by_edition.get(str(edition["id"]), [])
        ]
        latest_group_progress = _latest_progress(group_progresses)
        state = consumption_by_kind.get(media_kind)
        selected_edition_id = (
            (state or {}).get("lastEditionId")
            if any(item["id"] == (state or {}).get("lastEditionId") for item in raw_group)
            else (latest_group_progress or {}).get("editionId") or group_primary["id"]
        )
        selected_edition = next((item for item in raw_group if item["id"] == selected_edition_id), group_primary)
        selected_progress = _continue_progress_for_edition(
            selected_edition,
            progresses_by_edition.get(str(selected_edition["id"]), []),
            volumes_by_edition.get(str(selected_edition["id"]), []),
        )
        state_status = _reading_status((state or {}).get("status")) if state else _status_from_progress(selected_progress)
        group_percent = _display_progress_percent(
            selected_edition,
            selected_progress,
            volumes_by_edition.get(str(selected_edition["id"]), []),
            progresses_by_edition.get(str(selected_edition["id"]), []),
        )
        media_groups_by_kind[media_kind] = {
            "kind": media_kind,
            "primaryEditionId": group_primary.get("id"),
            "recentEditionId": (latest_group_progress or {}).get("editionId") or selected_edition.get("id"),
            "recentVolumeId": (latest_group_progress or {}).get("volumeId") or (state or {}).get("lastVolumeId"),
            "status": state_status,
            "progress": group_percent,
            "positionLabel": _media_position_label(db, media_kind, selected_progress),
            "durationMs": selected_edition.get("durationMs"),
            "chapterCount": selected_edition.get("chapterCount"),
            "volumeCount": len(volumes_by_edition.get(str(selected_edition["id"]), [])),
            "editions": group_views,
        }
    tabs = _detail_tabs(db, set(media_groups_by_kind))
    selected_detail_tab = _resolve_detail_tab(db, user_id, str(work["id"]), tabs)
    media_groups = [
        media_groups_by_kind[key]
        for key in _detail_tab_order(db)
        if key in media_groups_by_kind
    ]
    available_media_kinds = [str(item["kind"]) for item in media_groups]

    first_files = files_by_edition.get(display["id"], []) if display else []
    first_file = first_files[0] if first_files else None
    volumes = [volume for edition in edition_views for volume in edition["volumes"]]
    work_type = (display.get("format") if display else None) or work.get("workType") or "EPUB"
    lookup = (
        library_projections.latest_metadata_lookup_for_work(db, str(work["id"]))
        if _has_table(db, "MetadataLookupTask")
        else None
    )
    reading_status = (
        _project_work_status_for_user(db, user_id, str(work["id"]))
        if user_id
        else _reading_status(work.get("status"))
    )
    return {
        "id": work["id"],
        "workId": work["id"],
        "editionId": display["id"] if display else None,
        "monitorFolderId": display.get("monitorFolderId") if display else work.get("monitorFolderId"),
        "title": work.get("title") or "未命名作品",
        "author": work.get("author") or "未知作者",
        "publisher": display.get("publisher") if display else None,
        "type": "comic" if work_type == "COMIC" else "audiobook" if work_type == "AUDIO" else "ebook",
        "formatValue": display.get("format") if display else work_type,
        "format": labels["format"].get(display.get("format") if display else work_type, "未知"),
        "size": _format_bytes(total_size or (display.get("sizeBytes") if display else 0)),
        "progress": percent,
        **progress_navigation,
        "statusValue": reading_status,
        "status": labels["status"][reading_status],
        "publicationStatusValue": work.get("publicationStatus") or "UNKNOWN",
        "publicationStatus": labels["publication"].get(work.get("publicationStatus"), "未知"),
        "trackingStatusValue": work.get("trackingStatus") or "NOT_TRACKING",
        "trackingStatus": labels["tracking"].get(work.get("trackingStatus"), "未追踪"),
        "localLatestVolume": work.get("localLatestVolume"),
        "localLatestChapter": work.get("localLatestChapter"),
        "localLatestTitle": work.get("localLatestTitle"),
        "localLatestAt": _dt(work.get("localLatestAt")),
        "ignored": bool(work.get("hidden")),
        "organized": bool(work.get("organized")),
        "organizeStatus": work.get("organizeStatus") or "REVIEWING",
        "metadataQuality": work.get("metadataQuality") or 0,
        "metadataLookupStatus": (lookup or {}).get("status"),
        "metadataLookupSource": (lookup or {}).get("resultSource"),
        "metadataLookupError": (lookup or {}).get("errorSummary"),
        "tags": _parse_json(work.get("tags"), []),
        "seriesName": work.get("seriesName"),
        "seriesIndex": work.get("seriesIndex"),
        "publishedYear": work.get("publishedYear"),
        "added": (_dt(work.get("createdAt")) or "")[:10],
        "lastRead": (_dt(latest_read_progress.get("updatedAt")) or "")[:10] if latest_read_progress else "尚未阅读",
        "lastReadAt": _dt(latest_read_progress.get("updatedAt")) if latest_read_progress else None,
        "chapter": _progress_chapter_label(progress, progress_volumes, progress_units),
        "chapterCount": display.get("chapterCount") if display else None,
        "pageCount": display.get("pageCount") if display else None,
        "desc": work.get("description") or (display.get("description") if display else None) or "暂无简介，可在详情页补充元数据。",
        "path": first_file.get("path") if first_file else "",
        "fileHash": first_file.get("fullHash") if first_file else "",
        "gradient": "from-slate-950 via-blue-800 to-cyan-500",
        "coverStatus": work.get("coverStatus") or "PENDING",
        "coverUrl": _cover_url("works", work["id"], work, size="medium"),
        "totalUnits": (display.get("pageCount") if display and display.get("format") == "COMIC" else display.get("chapterCount")) if display else 0,
        "readingProgress": percent,
        "importStatus": display.get("importStatus") if display else "PENDING",
        "importError": display.get("importError") if display else None,
        "importedAt": _dt(work.get("createdAt")),
        "files": [file_view(file) for file in first_files],
        "versionCount": len(editions),
        "volumeCount": len(volumes),
        "primaryEditionId": primary.get("id") if primary else None,
        "primaryEditionName": primary.get("versionName") if primary else None,
        "recentEditionId": progress.get("editionId") if progress else (display["id"] if display else None),
        "recentVolumeId": progress.get("volumeId") if progress else None,
        "volumes": volumes,
        "editions": edition_views,
        "availableMediaKinds": available_media_kinds,
        "defaultMediaKind": available_media_kinds[0] if available_media_kinds else None,
        "mediaGroups": media_groups,
        "detailTabs": tabs,
        "selectedDetailTab": selected_detail_tab,
    }


def _get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    return library_works.get_work(db, work_id)


def _active_media_view(
    db: Session,
    book: dict[str, Any],
    selected_tab: str,
    user_id: str,
    requested_edition_id: str | None,
    requested_volume_id: str | None,
    unit_page: int,
    unit_page_size: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if selected_tab == "STRUCTURE":
        return None, {
            "readingUnits": [],
            "volumeSections": [],
            "readingUnitsPage": _empty_reading_units_page(min(200, max(1, unit_page_size))),
        }
    group = next((item for item in book.get("mediaGroups", []) if item.get("kind") == selected_tab), None)
    if not group:
        return None, {
            "readingUnits": [],
            "volumeSections": [],
            "readingUnitsPage": _empty_reading_units_page(min(200, max(1, unit_page_size))),
        }
    editions = list(group.get("editions") or [])
    selected_edition = (
        next((item for item in editions if item.get("id") == requested_edition_id), None)
        if requested_edition_id
        else None
    )
    selected_edition = selected_edition or next(
        (item for item in editions if item.get("id") == group.get("recentEditionId")),
        None,
    ) or next((item for item in editions if item.get("id") == group.get("primaryEditionId")), None) or (editions[0] if editions else None)
    if not selected_edition:
        return None, {
            "readingUnits": [],
            "volumeSections": [],
            "readingUnitsPage": _empty_reading_units_page(min(200, max(1, unit_page_size))),
        }
    edition_id = str(selected_edition["id"])
    navigation = _work_detail_navigation(
        db,
        edition_id,
        user_id,
        requested_volume_id,
        unit_page,
        unit_page_size,
    )
    selected_progress_rows = (
        library_projections.list_progress_for_edition(
            db,
            edition_id=edition_id,
            user_id=user_id,
        )
        if _has_table(db, "LibraryReadingProgress")
        else []
    )
    if requested_volume_id:
        selected_progress = _progress_for_volume(selected_progress_rows, requested_volume_id)
    else:
        selected_progress = _latest_progress(selected_progress_rows)
    progress = float(selected_edition.get("progress") or 0)
    started = progress > 0
    if selected_tab == "AUDIOBOOK":
        action_label = "继续听" if started else "开始听"
        action_href = (
            f"/works/{quote(str(book['id']), safe='')}"
            f"?detailTab=AUDIOBOOK&editionId={quote(edition_id, safe='')}"
        )
    elif selected_tab == "COMIC":
        action_label = "继续看" if started else "开始看"
        action_href = f"/reader/{quote(edition_id, safe='')}"
    else:
        action_label = "继续阅读" if started else "开始阅读"
        action_href = f"/reader/{quote(edition_id, safe='')}"
    return {
        "key": selected_tab,
        "formatLabel": selected_edition.get("format") or "未知",
        "selectedEditionId": edition_id,
        "selectedEditionName": selected_edition.get("versionName"),
        "status": group.get("status") or "UNREAD",
        "progressStatus": _status_from_progress(selected_progress),
        "progress": progress,
        "positionLabel": _media_position_label(db, selected_tab, selected_progress),
        "durationMs": selected_edition.get("durationMs"),
        "narrator": selected_edition.get("narrator"),
        "primaryAction": {"label": action_label, "href": action_href} if selected_edition.get("readable") else None,
        "units": navigation.get("readingUnits", []),
        "volumes": selected_edition.get("volumes", []),
        "tracks": selected_edition.get("files", []) if selected_tab == "AUDIOBOOK" else [],
    }, navigation



def _reading_unit_view(unit: dict[str, Any]) -> dict[str, Any]:
    return {**unit, "metadataJson": _parse_json(unit.get("metadataJson"), {})}


def _empty_reading_units_page(page_size: int) -> dict[str, int]:
    return {"page": 1, "pageSize": page_size, "total": 0, "totalPages": 1}


def _reading_units_page(db: Session, edition_id: str, page: int, page_size: int, volume_id: str | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    resolved_page_size = min(200, max(1, int(page_size or 120)))
    requested_page = max(1, int(page or 1))
    if not _has_table(db, "LibraryReadingUnit"):
        return [], _empty_reading_units_page(resolved_page_size)
    _initial_rows, total = library_projections.reading_units_page(
        db,
        edition_id=edition_id,
        volume_id=volume_id,
        limit=1,
        offset=0,
    )
    total_pages = max(1, (total + resolved_page_size - 1) // resolved_page_size)
    resolved_page = min(requested_page, total_pages)
    units: list[dict[str, Any]] = []
    if total > 0:
        rows, _total = library_projections.reading_units_page(
            db,
            edition_id=edition_id,
            volume_id=volume_id,
            limit=resolved_page_size,
            offset=(resolved_page - 1) * resolved_page_size,
        )
        units = [_normalize_row(dict(row)) for row in rows]
    return units, {"page": resolved_page, "pageSize": resolved_page_size, "total": total, "totalPages": total_pages}


def _volume_section_view(volume: dict[str, Any], fmt: str, count_override: int | None = None, progress: dict[str, Any] | None = None, units: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    count_key = "pageCount" if fmt in {"COMIC", "PDF"} else "chapterCount"
    return {
        "id": volume["id"],
        "editionId": volume.get("editionId"),
        "title": volume.get("title") or "未命名卷",
        "index": volume.get("volumeIndex") or volume.get("sortOrder") or 0,
        "fileId": volume.get("fileId") or volume["id"],
        "pageCount": count_override if count_override is not None else (volume.get(count_key) or 0),
        "coverUrl": _cover_url("volumes", volume["id"], volume, editionId=volume.get("editionId")),
        "progress": _progress_percent_with_navigation(progress, units or []),
        "lastReadAt": _dt(progress.get("updatedAt")) if progress else None,
        "position": progress.get("position") if progress else None,
        "currentPage": progress.get("page") if progress else None,
        **_progress_navigation(progress, units or []),
    }


def _work_detail_navigation(db: Session, edition_id: str | None, user_id: str | None = None, requested_volume_id: str | None = None, chapter_page: int = 1, chapter_page_size: int = 120) -> dict[str, Any]:
    resolved_page_size = min(200, max(1, int(chapter_page_size or 120)))
    if not edition_id or not _has_table(db, "LibraryEdition"):
        return {"readingUnits": [], "volumeSections": [], "readingUnitsPage": _empty_reading_units_page(resolved_page_size)}
    edition = library_projections.get_edition(db, edition_id)
    if not edition:
        return {"readingUnits": [], "volumeSections": [], "readingUnitsPage": _empty_reading_units_page(resolved_page_size)}
    progresses = (
        library_projections.list_progress_for_edition(
            db,
            edition_id=edition_id,
            user_id=user_id,
        )
        if user_id and _has_table(db, "LibraryReadingProgress")
        else []
    )
    if edition.get("format") == "COMIC":
        volumes = library_projections.list_volumes_for_edition(db, edition_id) if _has_table(db, "LibraryVolume") else []
        return {
            "readingUnits": [],
            "volumeSections": [_volume_section_view(volume, "COMIC", progress=_progress_for_volume(progresses, volume["id"])) for volume in volumes],
            "readingUnitsPage": _empty_reading_units_page(resolved_page_size),
        }
    if edition.get("format") == "PDF":
        volumes = library_projections.list_volumes_for_edition(db, edition_id) if _has_table(db, "LibraryVolume") else []
        return {
            "readingUnits": [],
            "volumeSections": [_volume_section_view(volume, "PDF", progress=_progress_for_volume(progresses, volume["id"])) for volume in volumes],
            "readingUnitsPage": _empty_reading_units_page(resolved_page_size),
        }
    volumes = library_projections.list_volumes_for_edition(db, edition_id) if _has_table(db, "LibraryVolume") else []
    if len(volumes) > 1:
        selected_volume = next((item for item in volumes if item["id"] == requested_volume_id), None) if requested_volume_id else None
        selected_volume = selected_volume or _choose_continue_volume(volumes, progresses) or volumes[0]
        units, units_page = _reading_units_page(db, edition_id, chapter_page, resolved_page_size, selected_volume["id"])
        units_by_volume = (
            {
                volume["id"]: library_projections.list_reading_units(
                    db,
                    edition_id=edition_id,
                    volume_id=str(volume["id"]),
                )
                for volume in volumes
            }
            if _has_table(db, "LibraryReadingUnit")
            else {}
        )
        return {
            "readingUnits": [_reading_unit_view(unit) for unit in units],
            "volumeSections": [_volume_section_view(volume, "EPUB", progress=_progress_for_volume(progresses, volume["id"]), units=units_by_volume.get(volume["id"], [])) for volume in volumes],
            "readingUnitsPage": units_page,
        }
    units, units_page = _reading_units_page(db, edition_id, chapter_page, resolved_page_size)
    return {"readingUnits": [_reading_unit_view(unit) for unit in units], "volumeSections": [], "readingUnitsPage": units_page}


def _preferred_work_cover_path(db: Session, work_id: str) -> str | None:
    return library_storage.preferred_work_cover_path(db, work_id)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _metadata_context_for_work(db: Session, work_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    job = ensure_organize_job_for_work(db, work_id)
    if not job:
        return None, None
    return job, context_for_job(db, job)


def _metadata_field_patch(candidate: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    selected = set(fields)
    if "title" in selected and isinstance(candidate.get("title"), str) and candidate.get("title").strip():
        patch["title"] = candidate["title"].strip()
        patch["normalizedTitle"] = normalize_identity_part(candidate["title"])
    if "author" in selected and isinstance(candidate.get("author"), str):
        patch["author"] = candidate["author"].strip() or None
        patch["normalizedAuthor"] = normalize_identity_part(candidate["author"]) or None
    if "description" in selected and isinstance(candidate.get("description"), str):
        patch["description"] = candidate["description"].strip() or None
    if "tags" in selected and isinstance(candidate.get("tags"), list):
        tags = sorted({str(tag).strip() for tag in candidate.get("tags") or [] if str(tag).strip()})
        patch["tags"] = _json_text(tags)
    if "seriesName" in selected and isinstance(candidate.get("seriesName"), str):
        patch["seriesName"] = candidate["seriesName"].strip() or None
    if "seriesIndex" in selected and candidate.get("seriesIndex") is not None:
        try:
            patch["seriesIndex"] = float(candidate["seriesIndex"])
        except (TypeError, ValueError):
            pass
    if "publishedYear" in selected and candidate.get("publishedYear") is not None:
        try:
            patch["publishedYear"] = int(candidate["publishedYear"])
        except (TypeError, ValueError):
            pass
    return patch


def _finish_metadata_organize_work(db: Session, work_id: str) -> list[str]:
    if not _has_table(db, "OrganizeJob"):
        return []
    return organize_jobs.finish_unresolved_jobs_for_work(
        db,
        work_id=work_id,
        now=_now(),
    )


def _apply_remote_cover(work_id: str, cover_url: str, settings: Settings) -> dict[str, Any]:
    if not cover_url.startswith(("http://", "https://")):
        return {}
    request = UrlRequest(cover_url, headers={"Accept": "image/*,*/*", "User-Agent": "Shuku Starship Python", "Referer": "https://book.douban.com/"})
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get("content-type") or ""
        data = response.read(8 * 1024 * 1024)
    suffix = ".jpg"
    if "png" in content_type:
        suffix = ".png"
    elif "webp" in content_type:
        suffix = ".webp"
    elif "." in cover_url.rsplit("/", 1)[-1].split("?", 1)[0]:
        suffix = Path(cover_url.rsplit("/", 1)[-1].split("?", 1)[0]).suffix[:12] or suffix
    target_dir = settings.resolved_storage_root / "covers"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{work_id}{suffix}"
    target.write_bytes(data)
    return {"coverPath": str(target.relative_to(settings.resolved_storage_root)), "coverStatus": "READY", "updatedAt": _now()}

