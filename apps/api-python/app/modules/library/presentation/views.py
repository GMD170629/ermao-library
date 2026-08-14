"""Library HTTP projections and work detail views."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from fastapi.responses import Response
from sqlalchemy import case, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.bootstrap.library import (
    library_projections,
    library_storage,
    library_works,
)
from app.bootstrap.organize import organize_jobs
from app.bootstrap.system import get_setting
from app.contracts.media_capabilities import (
    kindle_send_available_for_format,
    reader_type_for_format,
)
from app.core.authorization import (
    authorization_context,
    can_access_work,
    can_manage_system,
    volume_visibility_predicate,
)
from app.core.time import timestamp_ms_to_iso
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    UserMediaHistory,
)
from app.modules.library.application.bookshelf import BookshelfItemSummary
from app.modules.reader.public import (
    build_volume_content_fingerprint,
)
from app.modules.reader.public import (
    number_or_none as _number_or_none,
)
from app.modules.reader.public import (
    progress_location as _progress_location,
)
from app.modules.reader.public import (
    progress_navigation as _progress_navigation,
)
from app.modules.system.public import (
    DETAIL_TAB_KEYS,
)
from app.modules.system.public import (
    normalize_detail_tab_order as _normalize_detail_tab_order,
)
from app.schemas.responses import fail
from app.services.book_identity import normalize_identity_part
from app.services.organize_service import context_for_job, ensure_organize_job_for_work


def _now() -> datetime:
    return datetime.now(UTC)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except SQLAlchemyError:
        return False


def _has_column(db: Session, table: str, column: str) -> bool:
    try:
        return any(
            item.get("name") == column
            for item in inspect(db.connection()).get_columns(table)
        )
    except SQLAlchemyError:
        return False


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
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


def _visible_work_or_none(
    db: Session, user: User, work_id: str
) -> dict[str, Any] | None:
    if not can_access_work(db, user, work_id):
        return None
    return _get_work(db, work_id)


def _require_work_manager(db: Session, user: User, work_id: str) -> Response | None:
    if not can_access_work(db, user, work_id):
        return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    if not can_manage_system(user):
        return fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    return None


def _cover_url(
    kind: str, row_id: str, row: dict[str, Any] | None = None, **params: Any
) -> str:
    query = {key: value for key, value in params.items() if value is not None}
    version_source = ""
    if row:
        version_source = "|".join(
            [str(row.get("coverPath") or ""), _dt(row.get("updatedAt")) or ""]
        )
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
            "EPUB": "EPUB",
            "COMIC": "漫画",
            "PDF": "PDF",
            "AUDIO": "音频",
            "MOBI": "MOBI",
            "AZW": "AZW",
            "AZW3": "AZW3",
            "PRC": "PRC",
            "FB2": "FB2",
            "TXT": "TXT",
        },
        "status": {"UNREAD": "未读", "READING": "在读", "FINISHED": "已读"},
        "publication": {
            "UNKNOWN": "未知",
            "ONGOING": "连载中",
            "COMPLETED": "已完结",
            "HIATUS": "休刊",
            "CANCELLED": "已取消",
        },
        "tracking": {
            "NOT_TRACKING": "未追踪",
            "TRACKING": "追踪中",
            "PAUSED": "已暂停",
            "IGNORED": "已忽略",
        },
    }


DETAIL_TAB_LABELS = {
    "EBOOK": "电子书",
    "COMIC": "漫画",
    "AUDIOBOOK": "有声书",
    "STRUCTURE": "内容结构",
}


def _detail_tab_order(db: Session) -> list[str]:

    value = get_setting(db, "workDetail.tabOrder")
    return _normalize_detail_tab_order(value)


def _detail_tabs(db: Session, available_media_kinds: set[str]) -> list[dict[str, Any]]:
    return _detail_tabs_from_order(_detail_tab_order(db), available_media_kinds)


def _detail_tabs_from_order(
    tab_order: list[str] | tuple[str, ...], available_media_kinds: set[str]
) -> list[dict[str, Any]]:
    visible = available_media_kinds | {"STRUCTURE"}
    return [
        {"key": key, "label": DETAIL_TAB_LABELS[key], "sortOrder": index}
        for index, key in enumerate(tab_order)
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


def _status_from_progress(
    progress: dict[str, Any] | None, fallback: str = "UNREAD"
) -> str:
    if not progress:
        return _reading_status(fallback)
    percent = float(progress.get("percent") or 0)
    return "FINISHED" if percent >= 100 else "READING" if percent > 0 else "UNREAD"


def _format_duration(duration_ms: Any) -> str:
    total_seconds = max(0, int(float(duration_ms or 0) / 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    )


def _media_position_label(
    db: Session, reader_type: str, progress: dict[str, Any] | None
) -> str:
    if not progress:
        return "未开始"
    if reader_type != "audio":
        location = _progress_location(progress)
        payload = (
            location.get("payload")
            if location.get("engine") == "readium"
            and isinstance(location.get("payload"), dict)
            else {}
        )
        href = payload.get("href")
        page = _number_or_none(
            href.removeprefix("page-")
            if isinstance(href, str) and href.startswith("page-")
            else None
        )
        if page is not None:
            return f"第 {page} 页"
        return "继续上次位置"
    location = _progress_location(progress)
    position_ms = _number_or_none(
        location.get("positionMs") if isinstance(location, dict) else None
    )
    if position_ms is None:
        position_ms = 0
    chapter_id = location.get("chapterId") if isinstance(location, dict) else None
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


def _available_media_kinds(db: Session, work_id: str) -> list[str]:
    return list(
        db.scalars(
            select(LibraryMediaVersion.media_kind)
            .where(LibraryMediaVersion.work_id == work_id)
            .order_by(
                case(
                    (LibraryMediaVersion.media_kind == "EBOOK", 0),
                    (LibraryMediaVersion.media_kind == "COMIC", 1),
                    (LibraryMediaVersion.media_kind == "AUDIOBOOK", 2),
                    else_=3,
                ),
                LibraryMediaVersion.id.asc(),
            )
        ).all()
    )


def _available_media_kinds_by_work(
    db: Session, work_ids: list[str]
) -> dict[str, list[str]]:
    if not work_ids:
        return {}
    rows = db.execute(
        select(LibraryMediaVersion.work_id, LibraryMediaVersion.media_kind)
        .where(LibraryMediaVersion.work_id.in_(work_ids))
        .order_by(
            LibraryMediaVersion.work_id.asc(),
            case(
                (LibraryMediaVersion.media_kind == "EBOOK", 0),
                (LibraryMediaVersion.media_kind == "COMIC", 1),
                (LibraryMediaVersion.media_kind == "AUDIOBOOK", 2),
                else_=3,
            ),
            LibraryMediaVersion.id.asc(),
        )
    ).all()
    media_kinds = {work_id: [] for work_id in work_ids}
    for row in rows:
        media_kinds.setdefault(str(row.work_id), []).append(str(row.media_kind))
    return media_kinds


def _bookshelf_work_view(
    work: dict[str, Any], media_kinds: list[str]
) -> dict[str, Any]:
    return {
        "id": work["id"],
        "title": work.get("title") or "未命名作品",
        "author": work.get("author") or "未知作者",
        "availableMediaKinds": media_kinds,
        "gradient": "from-slate-950 via-blue-800 to-cyan-500",
        "coverStatus": work.get("coverStatus") or "PENDING",
        "coverUrl": _cover_url("works", work["id"], work, size="medium"),
    }


def bookshelf_item_view(item: BookshelfItemSummary) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "author": item.author,
        "coverUrl": _cover_url(
            "works",
            item.id,
            {"coverPath": item.cover_path, "updatedAt": item.updated_at},
            size="medium",
        ),
        "availableMediaKinds": list(item.available_media_kinds),
        "progress": item.progress,
    }


def bookshelf_item_views(
    items: tuple[BookshelfItemSummary, ...],
) -> list[dict[str, Any]]:
    return [bookshelf_item_view(item) for item in items]


def _management_work_views(
    db: Session,
    works: list[dict[str, Any]],
    user_id: str,
) -> list[dict[str, Any]]:
    if not works:
        return []
    work_ids = [str(work["id"]) for work in works]
    user = db.get(User, user_id)
    context = authorization_context(db, user) if user is not None else None
    filters = [
        LibraryMediaVersion.work_id.in_(work_ids),
        LibraryVolume.hidden.is_(False),
    ]
    if context is not None:
        filters.append(volume_visibility_predicate(context))
    rows = db.execute(
        select(LibraryMediaVersion, LibraryVolume)
        .join(LibraryVolume, LibraryVolume.media_version_id == LibraryMediaVersion.id)
        .where(*filters)
        .order_by(
            LibraryMediaVersion.work_id,
            LibraryVolume.sort_order,
            LibraryVolume.created_at,
            LibraryVolume.id,
        )
    ).all()
    resources: dict[str, list[tuple[LibraryMediaVersion, LibraryVolume]]] = {
        work_id: [] for work_id in work_ids
    }
    volume_ids: list[str] = []
    for media_version, volume in rows:
        resources.setdefault(media_version.work_id, []).append((media_version, volume))
        volume_ids.append(volume.id)
    progresses = (
        {
            progress.volume_id: progress
            for progress in db.scalars(
                select(LibraryReadingProgress).where(
                    LibraryReadingProgress.user_id == user_id,
                    LibraryReadingProgress.volume_id.in_(volume_ids),
                )
            ).all()
        }
        if volume_ids
        else {}
    )
    result: list[dict[str, Any]] = []
    for work in works:
        work_resources = resources.get(str(work["id"]), [])
        media_kinds = list(
            dict.fromkeys(media.media_kind for media, _volume in work_resources)
        )
        percents = [
            float(progresses[volume.id].percent) if volume.id in progresses else 0.0
            for _media, volume in work_resources
        ]
        latest = max(
            (
                progresses[volume.id].updated_at
                for _media, volume in work_resources
                if volume.id in progresses
            ),
            default=None,
        )
        completed = bool(percents) and all(percent >= 100 for percent in percents)
        reading = any(percent > 0 for percent in percents)
        result.append(
            {
                **_bookshelf_work_view(work, media_kinds),
                "seriesName": work.get("seriesName"),
                "tags": _parse_json(work.get("tags"), []),
                "statusValue": "FINISHED"
                if completed
                else "READING"
                if reading
                else "UNREAD",
                "lastReadAt": _dt(latest),
                "importedAt": _dt(work.get("createdAt")),
            }
        )
    return result


def _volume_file_view(file: LibraryFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "volumeId": file.volume_id,
        "path": file.path,
        "mimeType": file.mime_type,
        "kind": file.kind,
        "sortOrder": file.sort_order,
        "sizeBytes": file.size_bytes,
        "size": _format_bytes(file.size_bytes),
        "durationMs": file.duration_ms,
        "discNumber": file.disc_number,
        "trackNumber": file.track_number,
        "url": f"/api/files/{quote(file.id, safe='')}",
    }


def _volume_file_summary_view(file: LibraryFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "path": file.path,
        "sizeBytes": file.size_bytes,
        "size": _format_bytes(file.size_bytes),
    }


def _library_volume_view(
    volume: LibraryVolume,
    *,
    media_version_id: str,
    progress: LibraryReadingProgress | None,
    files: list[LibraryFile],
) -> dict[str, Any]:
    percent = min(100.0, max(0.0, float(progress.percent if progress else 0)))
    reader_type = reader_type_for_format(volume.format)
    return {
        "id": volume.id,
        "mediaVersionId": media_version_id,
        "title": volume.title,
        "volumeIndex": volume.volume_index,
        "sortOrder": volume.sort_order,
        "format": volume.format,
        "readerType": reader_type.value if reader_type else "reflowable",
        "classification": {
            "source": volume.classification_source,
            "reason": volume.classification_reason,
            "suggestedMediaKind": volume.suggested_media_kind,
        },
        "readable": reader_type is not None,
        "kindleSendAvailable": kindle_send_available_for_format(volume.format),
        "derivedFromVolumeId": volume.derived_from_volume_id,
        "publisher": volume.publisher,
        "publishedAt": _dt(volume.published_at),
        "language": volume.language,
        "isbn": volume.isbn,
        "identifier": volume.identifier,
        "narrator": volume.narrator,
        "abridged": volume.abridged,
        "origin": volume.origin,
        "importStatus": volume.import_status,
        "importError": volume.import_error,
        "coverStatus": volume.cover_status,
        "coverUrl": _cover_url(
            "volumes",
            volume.id,
            {"coverPath": volume.cover_path, "updatedAt": volume.updated_at},
        ),
        "sizeBytes": volume.size_bytes,
        "pageCount": volume.page_count,
        "chapterCount": volume.chapter_count,
        "durationMs": volume.duration_ms,
        "trackCount": volume.track_count,
        "progress": percent,
        "completed": percent >= 100,
        "lastReadAt": _dt(progress.updated_at) if progress else None,
        "files": [_volume_file_view(file) for file in files],
    }


def _library_volume_page_view(
    volume: LibraryVolume,
    *,
    media_version_id: str,
    progress: LibraryReadingProgress | None,
    files: list[LibraryFile],
) -> dict[str, Any]:
    legacy_view = _library_volume_view(
        volume,
        media_version_id=media_version_id,
        progress=progress,
        files=[],
    )
    return _work_detail_volume_view(
        legacy_view,
        files=[_volume_file_summary_view(file) for file in files],
    )


def _work_detail_volume_view(
    volume: dict[str, Any],
    *,
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_files = files if files is not None else volume.get("files", [])
    return {
        "id": volume["id"],
        "mediaVersionId": volume["mediaVersionId"],
        "title": volume["title"],
        "volumeIndex": volume.get("volumeIndex"),
        "sortOrder": volume["sortOrder"],
        "format": volume["format"],
        "readerType": volume["readerType"],
        "classification": volume["classification"],
        "readable": volume["readable"],
        "kindleSendAvailable": volume["kindleSendAvailable"],
        "derivedFromVolumeId": volume.get("derivedFromVolumeId"),
        "publisher": volume.get("publisher"),
        "publishedAt": volume.get("publishedAt"),
        "language": volume.get("language"),
        "isbn": volume.get("isbn"),
        "identifier": volume.get("identifier"),
        "narrator": volume.get("narrator"),
        "coverUrl": volume["coverUrl"],
        "sizeBytes": volume["sizeBytes"],
        "pageCount": volume.get("pageCount"),
        "chapterCount": volume.get("chapterCount"),
        "durationMs": volume.get("durationMs"),
        "trackCount": volume.get("trackCount"),
        "progress": volume["progress"],
        "files": [
            {
                "id": file["id"],
                "path": file["path"],
                "sizeBytes": file["sizeBytes"],
                "size": file["size"],
            }
            for file in source_files
        ],
    }


def _work_detail_summary_view(book: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "description": book.get("description"),
        "tags": book["tags"],
        "seriesName": book.get("seriesName"),
        "seriesIndex": book.get("seriesIndex"),
        "seriesFacet": book.get("seriesFacet"),
        "authorFacets": book.get("authorFacets", []),
        "coverStatus": book["coverStatus"],
        "coverUrl": book["coverUrl"],
        "recentMediaKind": book.get("recentMediaKind"),
        "continueVolumeId": book.get("continueVolumeId"),
        "completed": book["completed"],
        "mediaVersions": [
            {
                "id": media_version["id"],
                "mediaKind": media_version["mediaKind"],
                "completed": media_version["completed"],
                "volumeCount": media_version["volumeCount"],
                "sizeBytes": media_version["sizeBytes"],
                "volumes": [
                    _work_detail_volume_view(volume)
                    for volume in media_version["volumes"]
                ],
            }
            for media_version in book["mediaVersions"]
        ],
        "availableMediaKinds": book["availableMediaKinds"],
        "detailTabs": book["detailTabs"],
        "selectedDetailTab": book["selectedDetailTab"],
    }


def _reading_unit_view(unit: LibraryReadingUnit) -> dict[str, Any]:
    return {
        "id": unit.id,
        "volumeId": unit.volume_id,
        "fileId": unit.file_id,
        "unitType": unit.unit_type,
        "title": unit.title,
        "href": unit.href,
        "mediaType": unit.media_type,
        "sortOrder": unit.sort_order,
        "startMs": unit.start_ms,
        "endMs": unit.end_ms,
        "durationMs": unit.duration_ms,
        "width": unit.width,
        "height": unit.height,
        "size": unit.size,
        "metadataJson": _parse_json(unit.metadata_json, {}),
        "createdAt": _dt(unit.created_at),
        "updatedAt": _dt(unit.updated_at),
    }


@dataclass(frozen=True, slots=True)
class _WorkViewBatch:
    metadata_lookups: dict[str, dict[str, object]]
    rows_by_work: dict[str, list[tuple[LibraryMediaVersion, LibraryVolume]]]
    progresses: dict[str, LibraryReadingProgress]
    histories: dict[str, UserMediaHistory]
    files: dict[str, list[LibraryFile]]
    tab_order: tuple[str, ...]
    saved_tabs: dict[str, str]


def _load_work_view_batch(
    db: Session,
    works: list[dict[str, Any]],
    user_id: str | None,
    *,
    include_files: bool,
) -> _WorkViewBatch:
    work_ids = [str(work["id"]) for work in works]
    user = db.get(User, user_id) if user_id else None
    context = authorization_context(db, user) if user is not None else None
    filters = [
        LibraryMediaVersion.work_id.in_(work_ids),
        LibraryVolume.hidden.is_(False),
    ]
    if context is not None:
        filters.append(volume_visibility_predicate(context))
    rows = db.execute(
        select(LibraryMediaVersion, LibraryVolume)
        .join(LibraryVolume, LibraryVolume.media_version_id == LibraryMediaVersion.id)
        .where(*filters)
        .order_by(
            LibraryMediaVersion.work_id.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    rows_by_work: dict[str, list[tuple[LibraryMediaVersion, LibraryVolume]]] = {
        work_id: [] for work_id in work_ids
    }
    volume_ids: list[str] = []
    media_version_ids: list[str] = []
    for media_version, volume in rows:
        rows_by_work.setdefault(media_version.work_id, []).append(
            (media_version, volume)
        )
        volume_ids.append(volume.id)
        media_version_ids.append(media_version.id)

    progresses = (
        {
            progress.volume_id: progress
            for progress in db.scalars(
                select(LibraryReadingProgress).where(
                    LibraryReadingProgress.user_id == user_id,
                    LibraryReadingProgress.volume_id.in_(volume_ids),
                )
            ).all()
        }
        if user_id and volume_ids
        else {}
    )
    histories = (
        {
            history.media_version_id: history
            for history in db.scalars(
                select(UserMediaHistory).where(
                    UserMediaHistory.user_id == user_id,
                    UserMediaHistory.media_version_id.in_(media_version_ids),
                )
            ).all()
        }
        if user_id and media_version_ids
        else {}
    )
    files: dict[str, list[LibraryFile]] = {volume_id: [] for volume_id in volume_ids}
    if include_files and volume_ids:
        for file in db.scalars(
            select(LibraryFile)
            .where(LibraryFile.volume_id.in_(volume_ids))
            .order_by(LibraryFile.volume_id, LibraryFile.sort_order, LibraryFile.id)
        ).all():
            files[file.volume_id].append(file)

    preferences = (
        library_projections.get_detail_preferences(
            db,
            user_id=user_id,
            work_ids=work_ids,
        )
        if user_id and _has_table(db, "WorkDetailPreference")
        else {}
    )
    return _WorkViewBatch(
        metadata_lookups=library_projections.latest_metadata_lookups_for_works(
            db, work_ids
        ),
        rows_by_work=rows_by_work,
        progresses=progresses,
        histories=histories,
        files=files,
        tab_order=tuple(_detail_tab_order(db)),
        saved_tabs={
            work_id: str(preference.get("selectedTab") or "").strip().upper()
            for work_id, preference in preferences.items()
        },
    )


def _work_views(
    db: Session,
    works: list[dict[str, Any]],
    user_id: str | None = None,
    *,
    include_files: bool = True,
) -> list[dict[str, Any]]:
    if not works:
        return []
    batch = _load_work_view_batch(
        db,
        works,
        user_id,
        include_files=include_files,
    )
    return [
        _work_view(
            db,
            work,
            user_id,
            include_files=include_files,
            batch=batch,
        )
        for work in works
    ]


def _work_view(
    db: Session,
    work: dict[str, Any],
    user_id: str | None = None,
    *,
    volume_limit_per_media: int | None = None,
    include_files: bool = True,
    batch: _WorkViewBatch | None = None,
) -> dict[str, Any]:
    work_id = str(work["id"])
    metadata_lookup = (
        batch.metadata_lookups.get(work_id)
        if batch is not None
        else library_projections.latest_metadata_lookup_for_work(db, work_id)
    )
    if batch is not None:
        rows = batch.rows_by_work.get(work_id, [])
    else:
        user = db.get(User, user_id) if user_id else None
        context = authorization_context(db, user) if user is not None else None
        filters = [
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
        ]
        if context is not None:
            filters.append(volume_visibility_predicate(context))
        rows = db.execute(
            select(LibraryMediaVersion, LibraryVolume)
            .join(
                LibraryVolume,
                LibraryVolume.media_version_id == LibraryMediaVersion.id,
            )
            .where(*filters)
            .order_by(
                LibraryVolume.sort_order.asc(),
                LibraryVolume.created_at.asc(),
                LibraryVolume.id.asc(),
            )
        ).all()
    grouped: dict[str, tuple[LibraryMediaVersion, list[LibraryVolume]]] = {}
    for media_version, volume in rows:
        grouped.setdefault(media_version.id, (media_version, []))[1].append(volume)
    volume_ids = [volume.id for _media, volume in rows]
    progresses = (
        batch.progresses
        if batch is not None
        else (
            {
                progress.volume_id: progress
                for progress in db.scalars(
                    select(LibraryReadingProgress).where(
                        LibraryReadingProgress.user_id == user_id,
                        LibraryReadingProgress.volume_id.in_(volume_ids),
                    )
                ).all()
            }
            if user_id and volume_ids
            else {}
        )
    )
    histories = (
        batch.histories
        if batch is not None
        else (
            {
                history.media_version_id: history
                for history in db.scalars(
                    select(UserMediaHistory).where(
                        UserMediaHistory.user_id == user_id,
                        UserMediaHistory.media_version_id.in_(grouped),
                    )
                ).all()
            }
            if user_id and grouped
            else {}
        )
    )
    media_order = {"EBOOK": 0, "COMIC": 1, "AUDIOBOOK": 2}
    ordered = sorted(
        grouped.values(), key=lambda item: media_order.get(item[0].media_kind, 99)
    )
    incomplete: dict[str, list[LibraryVolume]] = {}
    all_volumes: list[LibraryVolume] = []
    for media_version, volumes in ordered:
        all_volumes.extend(volumes)
        incomplete[media_version.id] = [
            volume
            for volume in volumes
            if float(progresses[volume.id].percent if volume.id in progresses else 0)
            < 100
        ]
    candidates = [item for item in ordered if incomplete[item[0].id]]
    recent_media: LibraryMediaVersion | None = None
    continue_volume: LibraryVolume | None = None
    if candidates:
        with_history = [item for item in candidates if item[0].id in histories]
        if with_history:
            recent_media, _ = max(
                with_history, key=lambda item: histories[item[0].id].updated_at
            )
        else:
            recent_media = candidates[0][0]
        continue_volume = incomplete[recent_media.id][0]
    elif ordered:
        with_history = [item for item in ordered if item[0].id in histories]
        recent_media, recent_volumes = (
            max(with_history, key=lambda item: histories[item[0].id].updated_at)
            if with_history
            else ordered[0]
        )
        history = histories.get(recent_media.id)
        continue_volume = next(
            (
                volume
                for volume in recent_volumes
                if history and volume.id == history.last_volume_id
            ),
            recent_volumes[0],
        )
    response_volumes: dict[str, list[LibraryVolume]] = {}
    for media_version, volumes in ordered:
        selected = (
            list(volumes)
            if volume_limit_per_media is None
            else list(volumes[:volume_limit_per_media])
        )
        if (
            continue_volume is not None
            and continue_volume.media_version_id == media_version.id
            and all(volume.id != continue_volume.id for volume in selected)
        ):
            selected.append(continue_volume)
        response_volumes[media_version.id] = selected
    response_volume_ids = [
        volume.id for volumes in response_volumes.values() for volume in volumes
    ]
    files: dict[str, list[LibraryFile]] = (
        batch.files
        if batch is not None
        else {volume_id: [] for volume_id in response_volume_ids}
    )
    if batch is None and include_files and response_volume_ids:
        for file in db.scalars(
            select(LibraryFile)
            .where(LibraryFile.volume_id.in_(response_volume_ids))
            .order_by(LibraryFile.volume_id, LibraryFile.sort_order, LibraryFile.id)
        ).all():
            files[file.volume_id].append(file)
    media_views = [
        {
            "id": media_version.id,
            "mediaKind": media_version.media_kind,
            "completed": bool(volumes) and not incomplete[media_version.id],
            "volumeCount": len(volumes),
            "sizeBytes": sum(volume.size_bytes for volume in volumes),
            "volumes": [
                _library_volume_view(
                    volume,
                    media_version_id=media_version.id,
                    progress=progresses.get(volume.id),
                    files=files.get(volume.id, []),
                )
                for volume in response_volumes[media_version.id]
            ],
        }
        for media_version, volumes in ordered
    ]
    kinds = [str(item["mediaKind"]) for item in media_views]
    tabs = (
        _detail_tabs_from_order(batch.tab_order, set(kinds))
        if batch is not None
        else _detail_tabs(db, set(kinds))
    )
    last_progress = max(
        progresses.values(), key=lambda progress: progress.updated_at, default=None
    )
    return {
        "id": work_id,
        "title": work.get("title") or "未命名作品",
        "author": work.get("author") or "未知作者",
        "description": work.get("description"),
        "publicationStatus": work.get("publicationStatus") or "UNKNOWN",
        "trackingStatus": work.get("trackingStatus") or "NOT_TRACKING",
        "tags": _parse_json(work.get("tags"), []),
        "seriesName": work.get("seriesName"),
        "seriesIndex": work.get("seriesIndex"),
        "organized": bool(work.get("organized")),
        "organizeStatus": work.get("organizeStatus") or "REVIEWING",
        "metadataQuality": int(work.get("metadataQuality") or 0),
        "metadataLookupStatus": (metadata_lookup or {}).get("status"),
        "metadataLookupSource": (metadata_lookup or {}).get("resultSource"),
        "metadataLookupError": (metadata_lookup or {}).get("errorSummary"),
        "coverStatus": work.get("coverStatus") or "PENDING",
        "coverUrl": _cover_url("works", work_id, work, size="medium"),
        "recentMediaKind": recent_media.media_kind if recent_media else None,
        "continueVolumeId": continue_volume.id if continue_volume else None,
        "continueVolumeTitle": continue_volume.title if continue_volume else None,
        "continueVolumeProgress": float(progresses[continue_volume.id].percent)
        if continue_volume and continue_volume.id in progresses
        else 0.0,
        "completed": bool(all_volumes)
        and all(
            float(progresses[volume.id].percent if volume.id in progresses else 0)
            >= 100
            for volume in all_volumes
        ),
        "lastReadAt": _dt(last_progress.updated_at) if last_progress else None,
        "addedAt": _dt(work.get("createdAt")),
        "mediaVersions": media_views,
        "availableMediaKinds": kinds,
        "detailTabs": tabs,
        "selectedDetailTab": (
            batch.saved_tabs.get(work_id)
            if batch is not None
            and batch.saved_tabs.get(work_id) in {str(tab["key"]) for tab in tabs}
            else next(
                (str(tab["key"]) for tab in tabs if tab["key"] != "STRUCTURE"),
                "STRUCTURE",
            )
            if batch is not None
            else _resolve_detail_tab(db, user_id, work_id, tabs)
        ),
    }


def _selected_detail_volume_id(
    book: dict[str, Any],
    selected_tab: str,
    requested_volume_id: str | None,
) -> str | None:
    if selected_tab == "STRUCTURE":
        return None
    media_version = next(
        (
            item
            for item in book.get("mediaVersions", [])
            if item.get("mediaKind") == selected_tab
        ),
        None,
    )
    if media_version is None:
        return None
    volumes = list(media_version.get("volumes") or [])
    selected_volume = next(
        (
            volume
            for volume in volumes
            if requested_volume_id and volume.get("id") == requested_volume_id
        ),
        None,
    )
    selected_volume = (
        selected_volume
        or next(
            (
                volume
                for volume in volumes
                if volume.get("id") == book.get("continueVolumeId")
            ),
            None,
        )
        or next(
            (volume for volume in volumes if not bool(volume.get("completed"))), None
        )
        or (volumes[0] if volumes else None)
    )
    return str(selected_volume["id"]) if selected_volume is not None else None


def _active_media_view(
    db: Session,
    book: dict[str, Any],
    selected_tab: str,
    user_id: str,
    requested_volume_id: str | None,
    unit_page: int,
    unit_page_size: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    page_size = min(200, max(1, unit_page_size))
    empty_navigation = {
        "readingUnits": [],
        "volumeSections": [],
        "readingUnitsPage": _empty_reading_units_page(page_size),
    }
    volume_id = _selected_detail_volume_id(
        book,
        selected_tab,
        requested_volume_id,
    )
    if volume_id is None:
        return None, empty_navigation
    media_version = next(
        (
            item
            for item in book.get("mediaVersions", [])
            if item.get("mediaKind") == selected_tab
        ),
        None,
    )
    if media_version is None:
        return None, empty_navigation
    volumes = list(media_version.get("volumes") or [])
    selected_volume = next(
        (volume for volume in volumes if str(volume.get("id")) == volume_id),
        None,
    )
    if selected_volume is None:
        return None, empty_navigation
    unit_rows = db.scalars(
        select(LibraryReadingUnit)
        .where(LibraryReadingUnit.volume_id == volume_id)
        .order_by(LibraryReadingUnit.sort_order, LibraryReadingUnit.id)
    ).all()
    total = len(unit_rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, unit_page), total_pages)
    all_reading_units = [_reading_unit_view(unit) for unit in unit_rows]
    reading_units = all_reading_units[(page - 1) * page_size : page * page_size]
    progress = db.scalar(
        select(LibraryReadingProgress).where(
            LibraryReadingProgress.user_id == user_id,
            LibraryReadingProgress.volume_id == volume_id,
        )
    )
    progress_view = (
        {
            "volumeId": progress.volume_id,
            "percent": progress.percent,
            "locationJson": progress.location_json,
            "updatedAt": progress.updated_at,
        }
        if progress is not None
        else None
    )
    percent = float(selected_volume.get("progress") or 0)
    files = list(selected_volume.get("files") or [])
    reader_type = str(selected_volume.get("readerType") or "reflowable")
    action_href = (
        f"/listen/{quote(volume_id, safe='')}"
        if reader_type == "audio"
        else f"/reader/{quote(volume_id, safe='')}"
    )
    navigation = {
        "readingUnits": reading_units,
        "volumeSections": [],
        "readingUnitsPage": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
        },
    }
    progress_navigation = _progress_navigation(progress_view, all_reading_units)
    return {
        "key": selected_tab,
        "formatLabel": selected_volume.get("format") or "UNKNOWN",
        "mediaVersionId": media_version["id"],
        "selectedVolumeId": volume_id,
        "selectedVolumeTitle": selected_volume.get("title") or "未命名卷册",
        "status": "FINISHED"
        if media_version.get("completed")
        else "READING"
        if percent > 0
        else "UNREAD",
        "progressStatus": _status_from_progress(progress_view),
        "progress": percent,
        "positionLabel": (
            progress_navigation.get("currentChapterTitle")
            or _media_position_label(db, reader_type, progress_view)
        ),
        "durationMs": selected_volume.get("durationMs"),
        "narrator": selected_volume.get("narrator") if reader_type == "audio" else None,
        "primaryAction": {
            "label": "继续" if percent > 0 else "开始",
            "href": action_href,
        },
        "units": reading_units,
        "volumes": volumes,
        "tracks": files if reader_type == "audio" else [],
        "localProgressScope": {
            "userId": user_id,
            "volumeId": volume_id,
            "contentFingerprint": build_volume_content_fingerprint(
                selected_volume, files
            ),
        },
        **progress_navigation,
    }, navigation


def _work_volume_page_view(
    db: Session,
    *,
    user: User,
    work_id: str,
    media_version_id: str,
    page: int,
    page_size: int,
) -> dict[str, Any] | None:
    context = authorization_context(db, user)
    media_version = db.scalar(
        select(LibraryMediaVersion).where(
            LibraryMediaVersion.id == media_version_id,
            LibraryMediaVersion.work_id == work_id,
        )
    )
    if media_version is None:
        return None
    filters = [
        LibraryVolume.media_version_id == media_version_id,
        LibraryVolume.hidden.is_(False),
        volume_visibility_predicate(context),
    ]
    total = int(db.scalar(select(func.count(LibraryVolume.id)).where(*filters)) or 0)
    bounded_page_size = min(100, max(1, page_size))
    total_pages = max(1, (total + bounded_page_size - 1) // bounded_page_size)
    bounded_page = min(max(1, page), total_pages)
    volumes = db.scalars(
        select(LibraryVolume)
        .where(*filters)
        .order_by(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
        .limit(bounded_page_size)
        .offset((bounded_page - 1) * bounded_page_size)
    ).all()
    volume_ids = [volume.id for volume in volumes]
    progresses = (
        {
            progress.volume_id: progress
            for progress in db.scalars(
                select(LibraryReadingProgress).where(
                    LibraryReadingProgress.user_id == user.id,
                    LibraryReadingProgress.volume_id.in_(volume_ids),
                )
            ).all()
        }
        if volume_ids
        else {}
    )
    files: dict[str, list[LibraryFile]] = {volume_id: [] for volume_id in volume_ids}
    if volume_ids:
        for file in db.scalars(
            select(LibraryFile)
            .where(LibraryFile.volume_id.in_(volume_ids))
            .order_by(LibraryFile.volume_id, LibraryFile.sort_order, LibraryFile.id)
        ).all():
            files[file.volume_id].append(file)
    return {
        "mediaVersionId": media_version.id,
        "mediaKind": media_version.media_kind,
        "volumes": [
            _library_volume_page_view(
                volume,
                media_version_id=media_version.id,
                progress=progresses.get(volume.id),
                files=files.get(volume.id, []),
            )
            for volume in volumes
        ],
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "total": total,
        "totalPages": total_pages,
    }


def _work_reading_units_view(
    db: Session,
    *,
    user: User,
    work_id: str,
    volume_id: str,
    page: int,
    page_size: int,
) -> dict[str, Any] | None:
    context = authorization_context(db, user)
    volume = db.scalar(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryVolume.id == volume_id,
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
            volume_visibility_predicate(context),
        )
    )
    if volume is None:
        return None
    bounded_page_size = min(200, max(1, page_size))
    total = int(
        db.scalar(
            select(func.count(LibraryReadingUnit.id)).where(
                LibraryReadingUnit.volume_id == volume_id
            )
        )
        or 0
    )
    total_pages = max(1, (total + bounded_page_size - 1) // bounded_page_size)
    bounded_page = min(max(1, page), total_pages)
    all_units = db.scalars(
        select(LibraryReadingUnit)
        .where(LibraryReadingUnit.volume_id == volume_id)
        .order_by(LibraryReadingUnit.sort_order, LibraryReadingUnit.id)
    ).all()
    all_unit_views = [_reading_unit_view(unit) for unit in all_units]
    unit_views = all_unit_views[
        (bounded_page - 1) * bounded_page_size : bounded_page * bounded_page_size
    ]
    progress = db.scalar(
        select(LibraryReadingProgress).where(
            LibraryReadingProgress.user_id == user.id,
            LibraryReadingProgress.volume_id == volume_id,
        )
    )
    progress_view = (
        {
            "volumeId": progress.volume_id,
            "percent": progress.percent,
            "locationJson": progress.location_json,
            "updatedAt": progress.updated_at,
        }
        if progress is not None
        else None
    )
    navigation = _progress_navigation(progress_view, all_unit_views)
    return {
        "units": unit_views,
        "page": {
            "page": bounded_page,
            "pageSize": bounded_page_size,
            "total": total,
            "totalPages": total_pages,
        },
        "progress": min(
            100.0, max(0.0, float(progress.percent if progress is not None else 0))
        ),
        "currentHref": navigation.get("currentHref"),
        "currentChapterIndex": navigation.get("currentChapterIndex"),
        "currentChapterTitle": navigation.get("currentChapterTitle"),
        "currentChapterSortOrder": navigation.get("currentChapterSortOrder"),
        "currentPageNumber": navigation.get("currentPageNumber"),
    }


def _empty_reading_units_page(page_size: int) -> dict[str, int]:
    return {"page": 1, "pageSize": page_size, "total": 0, "totalPages": 1}


def _preferred_work_cover_path(db: Session, work_id: str) -> str | None:
    return library_storage.preferred_work_cover_path(db, work_id)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _metadata_context_for_work(
    db: Session, work_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    job = ensure_organize_job_for_work(db, work_id)
    if not job:
        return None, None
    return job, context_for_job(db, job)


def _metadata_field_patch(
    candidate: dict[str, Any], fields: list[str]
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    selected = set(fields)
    if (
        "title" in selected
        and isinstance(candidate.get("title"), str)
        and candidate.get("title").strip()
    ):
        patch["title"] = candidate["title"].strip()
        patch["normalizedTitle"] = normalize_identity_part(candidate["title"])
    if "author" in selected and isinstance(candidate.get("author"), str):
        patch["author"] = candidate["author"].strip() or None
        patch["normalizedAuthor"] = normalize_identity_part(candidate["author"]) or None
    if "description" in selected and isinstance(candidate.get("description"), str):
        patch["description"] = candidate["description"].strip() or None
    if "tags" in selected and isinstance(candidate.get("tags"), list):
        tags = sorted(
            {
                str(tag).strip()
                for tag in candidate.get("tags") or []
                if str(tag).strip()
            }
        )
        patch["tags"] = _json_text(tags)
    if "seriesName" in selected and isinstance(candidate.get("seriesName"), str):
        patch["seriesName"] = candidate["seriesName"].strip() or None
    if "seriesIndex" in selected and candidate.get("seriesIndex") is not None:
        try:
            patch["seriesIndex"] = float(candidate["seriesIndex"])
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
