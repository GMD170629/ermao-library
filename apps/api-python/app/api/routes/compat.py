from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from time import monotonic, time_ns
from typing import Any
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from app.core.auth import get_current_user
from app.core.authorization import (
    authorization_context,
    can_access_edition,
    can_access_file,
    can_access_monitor_folder,
    can_access_volume,
    can_access_work,
    can_manage_system,
)
from app.core.config import Settings, get_settings
from app.core.i18n import SUPPORTED_LOCALES, configured_locale, normalize_locale
from app.core.time import timestamp_ms_to_iso, to_timestamp_ms
from app.db.session import get_db
from app.models.auth import User
from app.schemas.responses import fail, ok
from app.services.book_identity import UNKNOWN_AUTHOR, identity_merge_key, normalize_identity_part
from app.services.backup_service import create_backup as create_backup_archive
from app.services.backup_service import list_backups as list_backup_archives
from app.services.backup_service import restore_backup as restore_backup_archive
from app.services.download_executor import execute_download_task
from app.services.health import run_system_health_checks
from app.bootstrap.compat_adapters import (
    import_http_store,
    library_dashboard,
    library_deletion,
    library_facet_queries,
    library_join_queries,
    library_operation_store,
    library_projections,
    library_storage,
    library_works,
    media_page_index,
    organize_job_queries,
    organize_jobs,
    organize_runs,
    shelf_store,
)
from app.bootstrap.library import (
    list_works as list_library_works,
    move_volume_to_work,
    reorder_volume,
)
from app.modules.library.public import (
    WorkListQuery,
    parse_media_kinds,
)
from app.services.library_filters import library_filter_schema, normalize_filter_rules
from app.services.library_management import (
    count_categories,
    delete_category,
    duplicate_groups,
    list_categories,
    merge_categories,
    merge_works,
    operation_view,
    rename_category,
    smart_shelf_work_ids,
    split_edition,
    sync_work_facets,
    undo_operation,
)
from app.services.metadata_provider_registry import (
    get_metadata_provider,
    list_metadata_provider_pipelines,
    list_metadata_providers,
    metadata_provider_registry,
    search_with_metadata_provider,
    test_metadata_provider,
    update_metadata_provider_pipeline,
    update_metadata_provider,
)
from app.services.organize_service import (
    context_for_job,
    ensure_organize_job_for_work,
)
from app.bootstrap.download import (
    create_download_task as create_download_task_command,
    delete_download_task as delete_download_task_command,
    get_download_task as get_download_task_query,
    list_download_tasks as list_download_tasks_query,
    update_download_task as update_download_task_command,
)
from app.modules.download.public import (
    CreateDownloadTask,
    UpdateDownloadTask,
)
from app.services.organize_scheduler import (
    delete_organize_job,
    get_organize_policy,
    list_organize_runs,
    organize_candidate_summary,
    recognize_organize_job,
    update_organize_policy,
)
from app.services.system_events import (
    prune_system_events as prune_structured_events,
    record_system_event as record_structured_event,
    system_event_storage_view,
    system_event_size_bytes,
)
from app.services.default_cover import cover_status, ensure_default_cover, is_default_cover_path
from app.services.import_preferences import (
    IMPORT_PREFERENCE_KEYS,
    extension_is_allowed,
    load_import_preferences,
    matches_ignore_patterns,
    normalize_import_setting_value,
)
from app.services.text_conversion import CONVERTIBLE_TEXT_EXTS
from app.worker.importer import is_supported_import_file, parse_series_volume_info
from app.services.audio_metadata import collect_audio_bundle_files, is_supported_audio_file
from app.worker.persistent_import_queue import enqueue_import_task
from app.worker.watcher import MonitorFolderConfig, load_known_import_paths, monitor_folder_config, scan_directory_for_imports

router = APIRouter()
logger = logging.getLogger(__name__)
_active_file_streams_by_user: dict[str, int] = {}
_active_file_streams_lock = threading.Lock()
# Test/legacy override. Production uses Settings.file_streams_per_user_limit.
STREAMS_PER_USER_LIMIT: int | None = None
SLOW_REQUEST_LOG_THRESHOLD_MS = 1500
COMIC_PAGE_DATA_SAVER_VARIANT = "data-saver"
COMIC_PAGE_ORIGINAL_VARIANT = "original"
COMIC_PAGE_DATA_SAVER_MEDIA_TYPE = "image/avif"
COMIC_PAGE_DATA_SAVER_QUALITY = 12
COMIC_PAGE_DATA_SAVER_SPEED = 9
COMIC_PAGE_DATA_SAVER_CACHE_VERSION = 3
SMALL_COVER_MAX_BYTES = 50 * 1024
SMALL_COVER_MAX_DIMENSION = 600
SMALL_COVER_MEDIA_TYPE = "image/webp"
SMALL_COVER_CACHE_VERSION = 1
SMALL_COVER_QUALITIES = (82, 74, 66, 58, 50, 42, 34, 26, 18, 10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _positive_env_int(name: str, fallback: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return fallback
    return value if value >= 0 else fallback


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


def _auth(db: Session, request: Request, settings: Settings) -> tuple[User | None, Response | None]:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401)
    return user, None


def _system_auth(db: Session, request: Request, settings: Settings) -> tuple[User | None, Response | None]:
    user, error = _auth(db, request, settings)
    if error is not None:
        return None, error
    if user is None or not can_manage_system(user):
        return None, fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    return user, None


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


def _visible_import_task_or_none(db: Session, user: User, task_id: str) -> dict[str, Any] | None:
    task = import_http_store.get_import_task(db, task_id)
    if task is None or not can_access_monitor_folder(db, user, task.get("monitorFolderId")):
        return None
    return task


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


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _nullable_float(value: Any, field_label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_label}格式不正确") from None


def _nullable_int(value: Any, field_label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value) if isinstance(value, str) else value
        if int(parsed) != parsed:
            raise ValueError
        return int(parsed)
    except (TypeError, ValueError):
        raise ValueError(f"{field_label}格式不正确") from None


def _positive_int(value: Any, fallback: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed < 1:
        return fallback
    return min(parsed, maximum)


def _safe_upload_name(value: str | None) -> str:
    name = Path(value or "upload").name
    sanitized = re.sub(r"[^A-Za-z0-9._()（）\-\u4e00-\u9fff]+", "_", name).strip("._")
    return sanitized or "upload"


def _audio_bundle_upload_title(file_names: list[str], requested_title: Any = None) -> str:
    explicit = re.sub(r"\s+", " ", str(requested_title or "")).strip()
    if explicit:
        return _safe_upload_name(explicit)
    stems = [Path(_safe_upload_name(name)).stem for name in file_names]
    common = os.path.commonprefix(stems).rstrip(" ._-(（[")
    common = re.sub(r"(?:cd|disc|disk|track|音轨)?\s*\d+\s*$", "", common, flags=re.I).rstrip(" ._-")
    if len(common) >= 2 and not common.isdigit():
        return _safe_upload_name(common)
    first = re.sub(r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:track\s*)?\d+[ ._-]*", "", stems[0], flags=re.I).strip()
    if re.fullmatch(r"(?:序章|前言|尾声|正文|第?\s*\d+\s*[章节集部])", first, re.I):
        first = "未命名有声书"
    return _safe_upload_name(first or "未命名有声书")


def _copy_upload_stream(source: Any, target: Path, max_bytes: int | None = None) -> int:
    copied = 0
    with target.open("xb") as handle:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if max_bytes is not None and copied > max_bytes:
                raise ValueError(f"上传内容超过上限 {max_bytes} bytes")
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    return copied


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return timestamp_ms_to_iso(value) or str(value)


def _timestamp_sql(column: str) -> str:
    """Read both v12 Unix milliseconds and pre-migration datetime text safely."""

    value = f"CAST({column} AS TEXT)"
    return (
        f"CASE WHEN {value} GLOB '*[^0-9]*' "
        f"THEN CAST(ROUND((julianday({column}) - 2440587.5) * 86400000) AS INTEGER) "
        f"ELSE CAST({column} AS INTEGER) END"
    )


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


def _system_event_size_bytes(db: Session) -> int:
    return system_event_size_bytes(db)


def _prune_system_events(db: Session, max_bytes: int | None = None) -> dict[str, Any]:
    result = prune_structured_events(db, max_bytes, commit=True)
    return {**result, "lastPrunedAt": system_event_storage_view(db).get("lastPrunedAt")}


def _record_system_event(
    db: Session,
    *,
    level: str = "info",
    source: str,
    action: str,
    message: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_structured_event(
        db,
        level=level,
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        message=message,
        metadata=metadata,
        commit=True,
        prune=True,
    )


def _coerce_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _raw_progress_percent(progress: dict[str, Any] | None) -> int:
    return max(0, min(100, round(float(progress.get("percent", 0) if progress else 0))))


def _display_progress_percent(
    edition: dict[str, Any] | None,
    progress: dict[str, Any] | None,
    volumes: list[dict[str, Any]],
    progresses: list[dict[str, Any]] | None = None,
) -> int:
    if edition and str(edition.get("format") or "").upper() == "AUDIO" and len(volumes) > 1:
        progress_rows = progresses or ([progress] if progress else [])
        weighted_total = 0.0
        duration_total = 0.0
        for volume in volumes:
            duration = max(1.0, float(volume.get("durationMs") or 0))
            volume_progress = _progress_for_volume(progress_rows, str(volume["id"]))
            weighted_total += duration * _raw_progress_percent(volume_progress)
            duration_total += duration
        return max(0, min(100, round(weighted_total / duration_total))) if duration_total else 0
    return _raw_progress_percent(progress)


def _normalize_reader_href(value: Any, include_fragment: bool = True) -> str:
    if not isinstance(value, str) or not value:
        return ""
    raw_path, separator, raw_fragment = value.strip().replace("\\", "/").partition("#")
    path = unquote(raw_path).lstrip("./").lower()
    fragment = unquote(raw_fragment)
    return f"{path}#{fragment}" if include_fragment and separator else path


def _reader_unit_index(current_href: Any, units: list[dict[str, Any]]) -> int | None:
    full_href = _normalize_reader_href(current_href)
    if not full_href:
        return None
    exact_matches = [index for index, unit in enumerate(units) if _normalize_reader_href(unit.get("href")) == full_href]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if "#" in full_href:
        return None
    resource_href = _normalize_reader_href(current_href, include_fragment=False)
    resource_matches = [
        index
        for index, unit in enumerate(units)
        if _normalize_reader_href(unit.get("href"), include_fragment=False) == resource_href
    ]
    return resource_matches[0] if len(resource_matches) == 1 else None


def _number_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _progress_extra(progress: dict[str, Any] | None) -> dict[str, Any]:
    if not progress:
        return {}
    parsed = _parse_json(progress.get("extra"), {})
    return parsed if isinstance(parsed, dict) else {}


def _progress_navigation(progress: dict[str, Any] | None, units: list[dict[str, Any]]) -> dict[str, Any]:
    extra = _progress_extra(progress)
    current_href = extra.get("chapterHref") or extra.get("currentHref")
    section_index = _number_or_none(extra.get("chapterSectionIndex") if extra.get("chapterSectionIndex") is not None else extra.get("sectionIndex") if extra.get("sectionIndex") is not None else extra.get("chapterIndex"))
    sort_order = _number_or_none(extra.get("chapterSortOrder"))
    unit = None
    unit_index = _reader_unit_index(current_href, units)
    if unit_index is not None:
        unit = units[unit_index]
    if unit is None and sort_order is not None:
        unit = next((item for item in units if _number_or_none(item.get("sortOrder")) == sort_order), None)
    if unit is None and not current_href and section_index is not None and 0 <= section_index < len(units):
        unit = units[section_index]
    return {
        "progressExtra": extra,
        "currentHref": unit.get("href") if unit else (current_href if isinstance(current_href, str) else None),
        "currentSectionIndex": section_index,
        "currentChapterTitle": (unit.get("title") if unit else None) or (extra.get("chapterTitle") if isinstance(extra.get("chapterTitle"), str) else None),
        "currentChapterSortOrder": _number_or_none(unit.get("sortOrder")) if unit else sort_order,
    }


def _progress_percent_with_navigation(progress: dict[str, Any] | None, units: list[dict[str, Any]]) -> int:
    raw_percent = _raw_progress_percent(progress)
    if raw_percent > 0 or not progress or not units:
        return raw_percent
    extra = _progress_extra(progress)
    current_href = extra.get("chapterHref") or extra.get("currentHref")
    sort_order = _number_or_none(extra.get("chapterSortOrder"))
    section_index = _number_or_none(extra.get("chapterSectionIndex") if extra.get("chapterSectionIndex") is not None else extra.get("sectionIndex") if extra.get("sectionIndex") is not None else extra.get("chapterIndex"))
    unit_index = _reader_unit_index(current_href, units)
    if unit_index is None and sort_order is not None:
        unit_index = next((index for index, unit in enumerate(units) if _number_or_none(unit.get("sortOrder")) == sort_order), None)
    if unit_index is None and not current_href and section_index is not None and 0 <= section_index < len(units):
        unit_index = section_index
    if unit_index is None:
        return raw_percent
    section_page = _number_or_none(extra.get("sectionPage"))
    section_total = _number_or_none(extra.get("sectionTotalPages"))
    section_offset = (max(0, min(section_total - 1, section_page - 1)) / section_total) if section_page and section_total and section_total > 1 else 0
    return max(0, min(100, round(((unit_index + section_offset) / len(units)) * 100)))


def _latest_progress(progresses: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(iter(sorted(progresses, key=lambda item: _dt(item.get("updatedAt")) or "", reverse=True)), None)


def _progress_for_volume(progresses: list[dict[str, Any]], volume_id: str | None) -> dict[str, Any] | None:
    if volume_id:
        specific = next((item for item in progresses if item.get("volumeId") == volume_id), None)
        if specific:
            return specific
    return next((item for item in progresses if not item.get("volumeId")), None)


def _choose_continue_volume(volumes: list[dict[str, Any]], progresses: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not volumes:
        return None
    progress_by_volume = {volume["id"]: _raw_progress_percent(_progress_for_volume(progresses, volume["id"])) for volume in volumes}
    for volume in volumes:
        percent = progress_by_volume.get(volume["id"], 0)
        if 0 < percent < 100:
            return volume
    if not any(percent > 0 for percent in progress_by_volume.values()):
        latest_volume_progress = next((item for item in sorted(progresses, key=lambda row: _dt(row.get("updatedAt")) or "", reverse=True) if item.get("volumeId")), None)
        if latest_volume_progress:
            latest_volume = next((volume for volume in volumes if volume.get("id") == latest_volume_progress.get("volumeId")), None)
            if latest_volume:
                return latest_volume
    for volume in volumes:
        if progress_by_volume.get(volume["id"], 0) <= 0:
            return volume
    return volumes[-1]


def _empty_progress_for_volume(edition: dict[str, Any] | None, volume: dict[str, Any] | None) -> dict[str, Any] | None:
    if not edition or not volume:
        return None
    return {"editionId": edition.get("id"), "workId": edition.get("workId"), "volumeId": volume.get("id"), "position": "0", "page": None, "percent": 0, "extra": "{}", "updatedAt": None}


def _continue_progress_for_edition(edition: dict[str, Any] | None, progresses: list[dict[str, Any]], volumes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if edition and edition.get("format") in {"EPUB", "COMIC", "AUDIO"} and len(volumes) > 1:
        volume = _choose_continue_volume(volumes, progresses)
        volume_progress = _progress_for_volume(progresses, volume.get("id") if volume else None)
        return volume_progress or _empty_progress_for_volume(edition, volume)
    return _latest_progress(progresses)


def _progress_chapter_label(progress: dict[str, Any] | None, volumes: list[dict[str, Any]], units: list[dict[str, Any]] | None = None) -> str:
    if not progress or not progress.get("page"):
        return "未开始"
    navigation = _progress_navigation(progress, units or [])
    volume_id = progress.get("volumeId")
    volume = next((item for item in volumes if item.get("id") == volume_id), None) if volume_id else None
    prefix = f"{volume.get('title') or '未命名卷'} · " if volume and len(volumes) > 1 else ""
    if navigation.get("currentChapterTitle"):
        return f"{prefix}{navigation['currentChapterTitle']} · 第 {progress.get('page')} 页"
    return f"{prefix}第 {progress.get('page')} 页"


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


DETAIL_TAB_KEYS = ("EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE")
DETAIL_TAB_LABELS = {"EBOOK": "电子书", "COMIC": "漫画", "AUDIOBOOK": "有声书", "STRUCTURE": "内容结构"}


def _edition_media_kind(edition: dict[str, Any]) -> str:
    stored = str(edition.get("mediaKind") or "").strip().upper()
    if stored in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        return stored
    fmt = str(edition.get("format") or "").strip().upper()
    return "COMIC" if fmt == "COMIC" else "AUDIOBOOK" if fmt == "AUDIO" else "EBOOK"


def _normalize_detail_tab_order(value: Any) -> list[str]:
    parsed = _parse_json(value, value)
    if not isinstance(parsed, list):
        parsed = []
    result: list[str] = []
    for raw in parsed:
        key = str(raw or "").strip().upper()
        if key in DETAIL_TAB_KEYS and key not in result:
            result.append(key)
    result.extend(key for key in DETAIL_TAB_KEYS if key not in result)
    return result


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
                "readable": edition_format in {"EPUB", "PDF", "COMIC", "AUDIO"},
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


def _storage_managed_path(path_value: str | None, settings: Settings) -> Path | None:
    path = _stored_path(path_value, settings)
    if not path:
        return None
    try:
        storage = settings.resolved_storage_root.resolve()
        resolved = path.resolve()
    except OSError:
        return None
    if resolved == storage or storage in resolved.parents:
        return resolved
    return None


def _collect_work_storage_paths(db: Session, work_id: str, settings: Settings) -> list[Path]:
    paths: list[Path] = []

    def add(path_value: str | None) -> None:
        path = _storage_managed_path(path_value, settings)
        if path:
            paths.append(path)

    work_cover, editions, volumes, files = library_storage.collect_storage_values(
        db, work_id
    )
    add(work_cover)
    for edition in editions:
        add(edition.get("coverPath"))
    for volume in volumes:
        add(volume.get("coverPath"))
    for file in files:
        add(file.get("path"))
    return list(dict.fromkeys(paths))


def _delete_storage_paths(paths: list[Path], settings: Settings) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    storage = settings.resolved_storage_root.resolve()
    for path in paths:
        try:
            resolved = path.resolve()
            if resolved != storage and storage not in resolved.parents:
                continue
            if resolved.is_file() or resolved.is_symlink():
                resolved.unlink()
                deleted.append(str(resolved))
                parent = resolved.parent
                while parent != storage and storage in parent.parents:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        except OSError as exc:
            failed.append({"path": str(path), "message": str(exc)})
            logger.warning("failed to delete managed storage file: %s", path, exc_info=exc)
    return {"deletedFiles": len(deleted), "failedFileDeletes": failed}


def _monitor_source_roots(db: Session, settings: Settings) -> list[Path]:
    roots: list[Path] = []
    if settings.resolved_monitor_root:
        roots.append(settings.resolved_monitor_root)
    roots.extend(
        Path(root_path).expanduser()
        for root_path in import_http_store.list_monitor_root_paths(db)
        if root_path.strip()
    )
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(root.resolve())
        except OSError:
            continue
    return list(dict.fromkeys(resolved))


def _source_delete_roots(db: Session, settings: Settings) -> list[Path]:
    return list(dict.fromkeys([settings.resolved_storage_root, *_monitor_source_roots(db, settings)]))


def _source_delete_path(path_value: str | None, db: Session, settings: Settings, roots: list[Path] | None = None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    allowed_roots = roots if roots is not None else _source_delete_roots(db, settings)
    if any(resolved != root and root in resolved.parents for root in allowed_roots):
        return resolved
    return None


def _collect_work_source_paths(db: Session, work_id: str, settings: Settings) -> list[Path]:
    paths: list[Path] = []
    delete_roots = _source_delete_roots(db, settings)

    def add(path_value: str | None, roots: list[Path]) -> None:
        path = _source_delete_path(path_value, db, settings, roots)
        if path:
            paths.append(path)

    for source_path in import_http_store.list_import_source_paths_for_work(
        db, work_id
    ):
        add(source_path, delete_roots)
    # Older records may not retain an ImportTask link. In that case a library
    # file living in a monitor folder is the best available source-file signal.
    if not paths and _has_table(db, "LibraryEdition") and _has_table(db, "LibraryFile"):
        monitor_roots = _monitor_source_roots(db, settings)
        for path_value in library_join_queries.list_file_paths_for_work(db, work_id):
            add(path_value, monitor_roots)
    return list(dict.fromkeys(paths))


def _delete_source_paths(paths: list[Path]) -> dict[str, Any]:
    deleted: list[str] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []
    for path in paths:
        try:
            if not path.exists() and not path.is_symlink():
                missing.append(str(path))
                continue
            if not path.is_file() and not path.is_symlink():
                failed.append({"path": str(path), "message": "目标不是文件"})
                continue
            path.unlink()
            deleted.append(str(path))
        except OSError as exc:
            failed.append({"path": str(path), "message": str(exc)})
            logger.warning("failed to delete source file: %s", path, exc_info=exc)
    return {"deletedFiles": len(deleted), "missingFiles": missing, "failedFileDeletes": failed}


def _conversion_output_paths(conversion: dict[str, Any] | None, settings: Settings) -> list[Path]:
    output_value = (conversion or {}).get("outputPath")
    if not output_value:
        return []
    try:
        output = Path(str(output_value)).expanduser().resolve()
        conversion_root = settings.conversion_root.resolve()
    except OSError:
        return []
    if output == conversion_root or conversion_root not in output.parents:
        return []
    paths = [output]
    sidecar = output.with_name("normalization.json")
    if sidecar.exists() or sidecar.is_symlink():
        paths.append(sidecar)
    return paths


def _delete_work_records(db: Session, work_id: str) -> dict[str, Any]:
    return library_deletion.delete_work_records(db, work_id)


def _delete_work_and_storage(db: Session, work_id: str, settings: Settings, *, delete_source: bool = False) -> dict[str, Any]:
    managed_paths = _collect_work_storage_paths(db, work_id, settings)
    source_paths = _collect_work_source_paths(db, work_id, settings)
    managed_paths = [path for path in managed_paths if path not in source_paths]
    record_cleanup = _delete_work_records(db, work_id)
    deleted = bool(record_cleanup["deleted"])
    if deleted:
        db.commit()
    managed_cleanup = _delete_storage_paths(managed_paths, settings) if deleted else {"deletedFiles": 0, "failedFileDeletes": []}
    source_cleanup = _delete_source_paths(source_paths) if deleted and delete_source else {"deletedFiles": 0, "missingFiles": [], "failedFileDeletes": []}
    return {
        "deleted": deleted,
        "id": work_id,
        "deleteSource": delete_source,
        "deletedDatabaseRecords": record_cleanup["deletedDatabaseRecords"],
        "deletedFiles": int(managed_cleanup["deletedFiles"]) + int(source_cleanup["deletedFiles"]),
        "deletedSourceFiles": source_cleanup["deletedFiles"],
        "missingSourceFiles": source_cleanup["missingFiles"],
        "failedFileDeletes": [*managed_cleanup["failedFileDeletes"], *source_cleanup["failedFileDeletes"]],
    }


def _delete_import_linked_library_scope(
    db: Session,
    task: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Delete only the volume/edition produced by one import task.

    The parent work is retained while any edition remains. This deliberately
    avoids the work-wide cleanup used by the library's explicit delete action.
    """

    work_id = str(task.get("workId") or "").strip()
    edition_id = str(task.get("editionId") or "").strip()
    volume_id = str(task.get("volumeId") or "").strip()
    if not work_id or not edition_id or not _has_table(db, "LibraryEdition"):
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    edition = library_deletion.get_edition_for_work(db, edition_id=edition_id, work_id=work_id)
    if not edition:
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    managed_paths: list[Path] = []
    deleted_records = 0

    def add_path(value: Any) -> None:
        path = _storage_managed_path(str(value), settings) if value else None
        if path:
            managed_paths.append(path)

    deleted_scope = False
    if volume_id and _has_table(db, "LibraryVolume"):
        volume = library_deletion.get_volume_for_edition(
            db, volume_id=volume_id, edition_id=edition_id
        )
        if volume:
            files = library_deletion.list_files_for_volume(db, volume_id)
            add_path(volume.get("coverPath"))
            for item in files:
                add_path(item.get("path"))
            deleted_records += library_deletion.delete_volume_scope(db, volume_id)
            deleted_scope = True

            remaining_volumes = library_deletion.count_volumes_for_edition(db, edition_id)
            remaining_files = library_deletion.count_files_for_edition(db, edition_id)
            if remaining_volumes == 0 and remaining_files == 0:
                files = library_deletion.list_files_for_edition(db, edition_id)
                volumes = library_deletion.list_volume_covers_for_edition(db, edition_id)
                add_path(edition.get("coverPath"))
                for item in files:
                    add_path(item.get("path"))
                for item in volumes:
                    add_path(item.get("coverPath"))
                deleted_records += library_deletion.delete_edition_scope(db, edition_id)
    else:
        files = library_deletion.list_files_for_edition(db, edition_id)
        volumes = library_deletion.list_volume_covers_for_edition(db, edition_id)
        add_path(edition.get("coverPath"))
        for item in files:
            add_path(item.get("path"))
        for item in volumes:
            add_path(item.get("coverPath"))
        deleted_records += library_deletion.delete_edition_scope(db, edition_id)
        deleted_scope = True

    if not deleted_scope:
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    remaining_editions = library_deletion.count_editions_for_work(db, work_id)
    deleted_work = remaining_editions == 0
    if deleted_work:
        work_cleanup = _delete_work_records(db, work_id)
        deleted_records += int(work_cleanup.get("deletedDatabaseRecords") or 0)
    else:
        primary_id = library_deletion.preferred_primary_edition_id(db, work_id)
        if primary_id:
            library_deletion.set_work_primary_edition(db, work_id=work_id, primary_id=primary_id)
        cover_path = _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings)
        library_deletion.update_work_after_scope_delete(
            db,
            work_id=work_id,
            primary_id=primary_id,
            cover_path=cover_path,
            cover_status=cover_status(cover_path, settings),
            now=_now(),
        )
        db.commit()

    storage_cleanup = _delete_storage_paths(list(dict.fromkeys(managed_paths)), settings)
    return {
        "deleted": True,
        "deletedWorkRecord": deleted_work,
        "deletedDatabaseRecords": deleted_records,
        "deletedFiles": storage_cleanup["deletedFiles"],
        "failedFileDeletes": storage_cleanup["failedFileDeletes"],
    }


def _path_tree(paths: list[str], root_label: str) -> dict[str, Any]:
    root = {"name": root_label, "path": root_label, "type": "folder", "children": [], "fileCount": 0, "sizeBytes": 0}
    children_by_path: dict[str, dict[str, Any]] = {root_label: root}
    for raw_path in sorted({path for path in paths if path}):
        parts = [part for part in Path(raw_path).parts if part not in {"/", ""}]
        current = root
        current_path = root_label
        for index, part in enumerate(parts):
            current_path = f"{current_path}/{part}"
            node = children_by_path.get(current_path)
            if not node:
                node = {"name": part, "path": current_path, "type": "file" if index == len(parts) - 1 else "folder", "children": [], "fileCount": 0, "sizeBytes": 0}
                children_by_path[current_path] = node
                current["children"].append(node)
            current = node
            current["fileCount"] = int(current.get("fileCount") or 0) + (1 if index == len(parts) - 1 else 0)
    return root


def _source_folder_preview(root_path: str) -> dict[str, Any]:
    path = Path(root_path)
    readable = path.exists() and path.is_dir() and os.access(path, os.R_OK)
    writable = path.exists() and path.is_dir() and os.access(path, os.W_OK)
    children: list[dict[str, Any]] = []
    if readable:
        try:
            for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:80]:
                try:
                    stat = child.stat()
                    children.append({"name": child.name, "path": str(child), "type": "folder" if child.is_dir() else "file", "sizeBytes": 0 if child.is_dir() else stat.st_size, "mtimeMs": int(stat.st_mtime * 1000)})
                except OSError:
                    children.append({"name": child.name, "path": str(child), "type": "unknown", "sizeBytes": 0, "error": "无法读取"})
        except OSError:
            readable = False
    return {"readable": readable, "writable": writable, "children": children}


def _is_inside_path(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _monitor_directory_tree_node(settings: Settings, requested_path: str | None) -> tuple[dict[str, Any] | None, str | None, int]:
    monitor_root = settings.resolved_monitor_root
    if monitor_root is None:
        return None, "监控根目录未配置", 400

    try:
        real_monitor_root = monitor_root.resolve()
    except OSError:
        return None, "监控根目录不存在或不可读", 400

    if not real_monitor_root.exists() or not real_monitor_root.is_dir():
        return None, "监控根目录不存在或不可读", 400

    raw_path = str(requested_path or "").strip()
    if raw_path:
        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            return None, "请输入监控根目录下的绝对路径", 400
    else:
        target = real_monitor_root

    if not target.exists():
        return None, "路径不存在或不可读", 404

    try:
        real_target = target.resolve()
    except OSError:
        return None, "路径不存在或不可读", 404

    if not _is_inside_path(real_monitor_root, real_target):
        return None, "路径真实位置不在监控根目录内", 403
    if not real_target.is_dir():
        return None, "监控文件夹路径必须是目录", 400

    children: list[dict[str, Any]] = []
    readable = os.access(real_target, os.R_OK)
    error: str | None = None
    if readable:
        try:
            for child in sorted(real_target.iterdir(), key=lambda item: item.name.lower()):
                try:
                    real_child = child.resolve()
                except OSError:
                    continue
                if not _is_inside_path(real_monitor_root, real_child) or not real_child.is_dir():
                    continue
                children.append({
                    "name": child.name,
                    "path": str(real_child),
                    "readable": os.access(real_child, os.R_OK),
                })
        except OSError:
            readable = False
            error = "目录不可读取"
    else:
        error = "目录不可读取"

    return {
        "name": real_target.name or str(real_target),
        "path": str(real_target),
        "readable": readable,
        "error": error,
        "children": children[:200],
    }, None, 200


def _serialize_system_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = _parse_json(event.get("metadata"), {})
    return {
        "id": event.get("id"),
        "level": event.get("level") or "info",
        "source": event.get("source") or "system",
        "actorType": event.get("actorType") or "system",
        "actorId": event.get("actorId"),
        "action": event.get("action") or "",
        "targetType": event.get("targetType"),
        "targetId": event.get("targetId"),
        "message": event.get("message") or "",
        "metadata": metadata if isinstance(metadata, dict) else {},
        "createdAt": _dt(event.get("createdAt")),
    }


def _normalize_monitor_root_path(value: Any) -> str:
    root_path = str(value or "").strip()
    if not root_path:
        return ""
    return os.path.normpath(root_path)


def _monitor_folder_by_root_path(db: Session, root_path: str, exclude_id: str | None = None) -> dict[str, Any] | None:
    return import_http_store.get_monitor_folder_by_root_path(db, root_path, exclude_id=exclude_id)


def _optional_shelf_id(db: Session, value: Any) -> tuple[str | None, str | None]:
    shelf_id = str(value or "").strip()
    if not shelf_id:
        return None, None
    if not _has_table(db, "Shelf") or not shelf_store.shelf_exists(db, shelf_id):
        return None, "选择的目标书架不存在，请重新选择"
    return shelf_id, None


def _system_setting_value(db: Session, key: str) -> str | None:
    from app.bootstrap.system import get_setting

    parsed = get_setting(db, key)
    return str(parsed).strip() if parsed is not None and str(parsed).strip() else None


def _enabled_monitor_folder_for_path(db: Session, target: Path) -> dict[str, Any] | None:
    if not _has_table(db, "MonitorFolder"):
        return None
    try:
        real_target = target.expanduser().resolve()
    except OSError:
        return None
    for folder in import_http_store.list_enabled_monitor_folder_rows(db):
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if root == real_target or _is_inside_path(root, real_target):
            return folder
    return None


def _save_system_setting(db: Session, key: str, value: Any) -> None:
    from app.bootstrap.system import upsert_setting

    upsert_setting(db, key, value)


async def _request_json_or_empty(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _target_directory_from_path(settings: Settings, target_path: Any, action_label: str) -> Path:
    raw_path = str(target_path or "").strip()
    if not raw_path:
        raise ValueError(f"请选择{action_label}目录")
    monitor_root = settings.resolved_monitor_root
    if monitor_root is None:
        raise ValueError("监控根目录未配置")
    try:
        real_monitor_root = monitor_root.expanduser().resolve()
    except OSError:
        raise ValueError("监控根目录不存在或不可读")
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise ValueError(f"请选择监控根目录内的{action_label}目录")
    try:
        real_target = target.resolve()
    except OSError:
        raise ValueError(f"所选{action_label}目录不存在或不可读")
    if not (real_monitor_root == real_target or _is_inside_path(real_monitor_root, real_target)):
        raise ValueError(f"请选择监控根目录内的{action_label}目录")
    if not real_target.exists() or not real_target.is_dir():
        raise ValueError(f"所选{action_label}目录不存在或不可读")
    if not os.access(real_target, os.W_OK):
        raise ValueError(f"无法写入所选{action_label}目录，请检查 NAS 目录权限。")
    return real_target


def _unique_file_in_directory(directory: Path, filename: str) -> Path:
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_upload_name(filename)
    parsed = Path(safe_name)
    stem = parsed.stem or "upload"
    suffix = parsed.suffix
    index = 0
    while True:
        candidate = directory / safe_name if index == 0 else directory / f"{stem}-{index}{suffix}"
        resolved = candidate.resolve()
        if directory != resolved and directory not in resolved.parents:
            raise ValueError("目标路径越界")
        if not resolved.exists():
            return resolved
        index += 1


@router.get("/dashboard/summary")
def dashboard_summary(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    context = authorization_context(db, user)
    summary = library_dashboard.dashboard_summary(db, context, user.id)
    return ok(
        {
            "totalBooks": summary["totalBooks"],
            "comicBooks": summary["comicBooks"],
            "novelBooks": summary["novelBooks"],
            "storageUsedBytes": int(summary["storageUsedBytes"] or 0),
            "monitorFolderCount": summary["monitorFolderCount"],
            "lastImportAt": _dt(summary.get("lastImportAt")),
            "latestSyncAt": _dt(summary.get("latestSyncAt")),
        }
    )


@router.get("/dashboard/recent-books")
def dashboard_recent_books(request: Request, limit: int = 5, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    take = min(24, max(1, limit))
    context = authorization_context(db, user)
    works = library_dashboard.recent_books(db, context, limit=take)
    return ok({"books": [_bookshelf_item_view(work) for work in works]})


@router.get("/dashboard/recent-reading")
def dashboard_recent_reading(request: Request, limit: int = 10, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    take = min(24, max(1, limit))
    context = authorization_context(db, user)
    works = library_dashboard.recent_reading(db, context, user.id, limit=take)
    return ok({"books": [_bookshelf_item_view(work) for work in works]})


@router.get("/dashboard/continue-reading")
def dashboard_continue_reading(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    progress = None
    if all(_has_table(db, table) for table in ("LibraryReadingProgress", "LibraryWork", "LibraryEdition")):
        context = authorization_context(db, user)
        progress = library_dashboard.continue_reading_progress(db, context, user.id)
    if not progress:
        return ok({"item": None})
    work = _get_work(db, progress["workId"])
    if not work or work.get("hidden"):
        return ok({"item": None})
    book = _work_view(db, work, user.id)
    recent_edition_id = book.get("recentEditionId")
    media_group = next(
        (
            group
            for group in book.get("mediaGroups") or []
            if group.get("recentEditionId") == recent_edition_id
        ),
        None,
    )
    media_kind = (
        (media_group or {}).get("kind")
        or ("AUDIOBOOK" if book.get("type") == "audiobook" else "COMIC" if book.get("type") == "comic" else "EBOOK")
    )
    if media_kind == "AUDIOBOOK":
        audio_group = next(
            (group for group in book.get("mediaGroups") or [] if group.get("kind") == "AUDIOBOOK"),
            None,
        )
        resume_edition_id = (
            (audio_group or {}).get("recentEditionId")
            or (audio_group or {}).get("primaryEditionId")
            or next(
                (
                    edition.get("id")
                    for edition in book.get("editions") or []
                    if edition.get("mediaKind") == "AUDIOBOOK"
                ),
                None,
            )
        )
    else:
        resume_edition_id = recent_edition_id or book.get("editionId")
    resume_edition = next(
        (
            edition
            for edition in book.get("editions") or []
            if edition.get("id") == resume_edition_id
        ),
        None,
    )
    chapter = book.get("chapter")
    if chapter == "未开始":
        chapter = None
    return ok(
        {
            "item": {
                "workId": book.get("id"),
                "title": book.get("title"),
                "author": book.get("author"),
                "coverUrl": book.get("coverUrl"),
                "mediaKind": media_kind,
                "resumeEditionId": resume_edition_id,
                "resumeVolumeId": book.get("recentVolumeId"),
                "progress": book.get("progress") or 0,
                "chapter": chapter,
                "lastReadAt": _dt(progress.get("updatedAt")),
                "versionName": (resume_edition or {}).get("versionName"),
                "narrator": (resume_edition or {}).get("narrator"),
            }
        }
    )


@router.get("/dashboard/system-status")
def dashboard_system_status(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    health = run_system_health_checks(db, settings)
    checks = {item["name"]: item for item in health["checks"]}
    enabled = import_http_store.list_enabled_monitor_folder_rows(db)
    current_task, latest_task, failed_count = import_http_store.import_status_snapshot(db)
    return ok(
        {
            "database": checks.get("database", {"status": "unknown", "message": "待检测"}),
            "worker": {"status": "ok", "message": "正在监听监控文件夹"} if enabled else {"status": "unknown", "message": "未启用监控文件夹"},
            "enabledMonitorFolders": enabled,
            "currentImportTask": current_task,
            "latestImportTask": latest_task,
            "errorFileCount": failed_count,
            "monitorRootReadable": checks.get("monitorRootReadable", {"status": "unknown", "message": "待检测"}),
            "storageWritable": checks.get("storageWritable", {"status": "unknown", "message": "待检测"}),
        }
    )


@router.get("/management/overview")
def management_overview(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    health = run_system_health_checks(db, settings)
    event_storage = _prune_system_events(db)
    cards = library_dashboard.management_card_counts(db)
    failed_imports = cards["failedImports"]
    failed_downloads = cards["failedDownloads"]
    pending_organize = cards["pendingOrganize"]
    file_paths = library_dashboard.list_library_file_paths(db)
    orphan_count = 0
    library_root = settings.resolved_storage_root / "library"
    if library_root.exists():
        try:
            for path in library_root.rglob("*"):
                if path.is_file() and str(path) not in file_paths:
                    orphan_count += 1
                    if orphan_count > 1000:
                        break
        except OSError:
            orphan_count = 0
    checks = {item["name"]: item for item in health["checks"]}
    recent_events = library_dashboard.recent_system_events(db, limit=8)
    storage = cards["managedStorageBytes"]
    return ok(
        {
            "cards": {
                "failedImports": failed_imports,
                "failedDownloads": failed_downloads,
                "orphanFiles": orphan_count,
                "pendingOrganize": pending_organize,
                "managedStorageBytes": int(storage or 0),
                "eventLogSizeBytes": event_storage["sizeBytes"],
                "eventLogMaxBytes": event_storage["maxBytes"],
            },
            "checks": {
                "database": checks.get("database", {"status": "unknown", "message": "待检测"}),
                "monitorRootReadable": checks.get("monitorRootReadable", {"status": "unknown", "message": "待检测"}),
                "storageWritable": checks.get("storageWritable", {"status": "unknown", "message": "待检测"}),
            },
            "recentEvents": [_serialize_system_event(event) for event in recent_events],
        }
    )


@router.get("/management/events")
def list_system_events(request: Request, page: int = 1, pageSize: int = 50, level: str | None = None, source: str | None = None, targetType: str | None = None, search: str | None = None, dateFrom: str | None = None, dateTo: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    if not _has_table(db, "SystemEvent"):
        return ok({"events": [], "page": page, "pageSize": page_size, "total": 0, "totalPages": 1, "storage": {"sizeBytes": 0, "maxBytes": 5 * 1024 * 1024}})
    storage = _prune_system_events(db)
    date_from_ms = to_timestamp_ms(f"{dateFrom}T00:00:00") if dateFrom else None
    date_to_ms = to_timestamp_ms(f"{dateTo}T00:00:00") if dateTo else None
    events, total = library_dashboard.list_system_events_page(
        db,
        page=page,
        page_size=page_size,
        level=level,
        source=source,
        target_type=targetType,
        search=search,
        date_from_ms=date_from_ms,
        date_to_ms=date_to_ms,
    )
    from sqlalchemy import func, select
    from app.models.settings import SystemEvent
    sources = [
        {"source": row.source, "count": int(row.count or 0)}
        for row in db.execute(
            select(SystemEvent.source, func.count().label("count")).group_by(SystemEvent.source).order_by(SystemEvent.source.asc())
        ).all()
    ] if _has_table(db, "SystemEvent") else []
    levels = [
        {"level": row.level, "count": int(row.count or 0)}
        for row in db.execute(
            select(SystemEvent.level, func.count().label("count")).group_by(SystemEvent.level).order_by(SystemEvent.level.asc())
        ).all()
    ] if _has_table(db, "SystemEvent") else []
    return ok({"events": [_serialize_system_event(event) for event in events], "page": page, "pageSize": page_size, "total": total, "totalPages": max(1, (total + page_size - 1) // page_size), "storage": storage, "facets": {"sources": sources, "levels": levels}})


@router.delete("/management/events")
def clear_system_events(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "SystemEvent"):
        return ok({"deleted": 0})
    deleted = library_dashboard.clear_info_warning_events(db)
    db.commit()
    _record_system_event(db, level="info", source="system", action="events.cleared", actor_type="admin", actor_id=user.id, target_type="events", message=f"清理结构化日志 {deleted} 条", metadata={"deleted": deleted})
    return ok({"deleted": deleted, "storage": _prune_system_events(db)})


@router.get("/management/folders")
def management_folders(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    monitor_folders = import_http_store.list_monitor_folders(db)
    source_nodes = [{**folder, **_source_folder_preview(str(folder.get("rootPath") or ""))} for folder in monitor_folders]
    works = library_dashboard.list_management_works(db, limit=300)
    editions = []
    if _has_table(db, "LibraryEdition"):
        from sqlalchemy import func, select
        from app.models.library import LibraryEdition
        editions = [
            {
                "workId": row.workId,
                "sizeBytes": int(row.sizeBytes or 0),
                "editionCount": int(row.editionCount or 0),
            }
            for row in db.execute(
                select(
                    LibraryEdition.work_id.label("workId"),
                    func.coalesce(func.sum(LibraryEdition.size_bytes), 0).label("sizeBytes"),
                    func.count().label("editionCount"),
                )
                .where(LibraryEdition.hidden.is_(False))
                .group_by(LibraryEdition.work_id)
            ).all()
        ]
    size_by_work = {row.get("workId"): row for row in editions}
    work_items = [{**work, "sizeBytes": int((size_by_work.get(work.get("id")) or {}).get("sizeBytes") or 0), "editionCount": int((size_by_work.get(work.get("id")) or {}).get("editionCount") or 0)} for work in works]

    def grouped(key: str, fallback: str) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for work in work_items:
            value = str(work.get(key) or fallback).strip() or fallback
            buckets.setdefault(value, []).append(work)
        return [{"name": name, "count": len(items), "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items), "items": items[:20]} for name, items in sorted(buckets.items(), key=lambda item: item[0])]

    def grouped_series() -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for work in work_items:
            value = str(work.get("seriesName") or "").strip()
            if not value:
                continue
            buckets.setdefault(value, []).append(work)
        return [
            {"name": name, "count": len(items), "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items), "items": items[:20]}
            for name, items in sorted(buckets.items(), key=lambda item: item[0])
            if len(items) >= 2
        ]

    source_names = {folder.get("id"): folder.get("name") for folder in monitor_folders}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for work in work_items:
        name = source_names.get(work.get("monitorFolderId")) or "手动导入"
        by_source.setdefault(str(name), []).append(work)
    file_rows = library_dashboard.list_management_file_rows(db, limit=2000)
    managed_paths = []
    storage_root = settings.resolved_storage_root
    for file in file_rows:
        path_value = str(file.get("path") or "")
        try:
            resolved = Path(path_value).resolve()
            managed_paths.append(str(resolved.relative_to(storage_root.resolve())))
        except Exception:
            managed_paths.append(path_value)
    return ok(
        {
            "logical": {
                "series": grouped_series(),
                "authors": grouped("author", "未知作者"),
                "formats": grouped("workType", "未知格式"),
                "sources": [{"name": name, "count": len(items), "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items), "items": items[:20]} for name, items in sorted(by_source.items(), key=lambda item: item[0])],
            },
            "disk": {
                "sources": source_nodes,
                "managed": {"rootPath": str(storage_root / "library"), "tree": _path_tree(managed_paths, "library")},
            },
            "works": work_items,
        }
    )


@router.get("/series")
def list_series(request: Request, visibility: str = "active", limit: int = 50, minBooks: int = 2, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "LibraryWork") or not _has_column(db, "LibraryWork", "seriesName"):
        return ok({"series": [], "total": 0})

    take = min(100, max(1, limit))
    min_books = max(1, minBooks)
    rows, total = library_facet_queries.list_series_groups(
        db,
        authorization_context(db, user),
        visibility=visibility,
        limit=take,
        min_books=min_books,
    )
    return ok({
        "series": [
            {
                "name": row.get("name"),
                "bookCount": int(row.get("bookCount") or 0),
                "latestUpdatedAt": _dt(row.get("latestUpdatedAt")),
            }
            for row in rows
        ],
        "total": total,
    })


@router.get("/works")
def list_works(request: Request, page: int = 1, pageSize: int = 24, visibility: str = "active", search: str | None = None, keyword: str | None = None, seriesName: str | None = None, sort: str = "updated", sortDirection: str | None = None, view: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    raw_filters = (request.query_params.get("filters") or "").strip()
    filter_rules: dict[str, Any] | None = None
    if raw_filters:
        try:
            filter_rules = json.loads(raw_filters)
        except json.JSONDecodeError:
            return fail("筛选规则格式不正确", status_code=400)
    status = (request.query_params.get("status") or "").strip().upper()
    if status == "WANT":
        status = "UNREAD"
    query = WorkListQuery(
        page=page,
        page_size=page_size,
        visibility=visibility,
        search=search,
        keyword=keyword,
        series_name=seriesName,
        sort=sort,
        sort_direction=sortDirection,
        type_filter=(request.query_params.get("type") or request.query_params.get("format") or "").strip(),
        media_kinds=parse_media_kinds(
            (request.query_params.get("mediaKinds") or request.query_params.get("mediaKind") or "").strip()
        ),
        status=status or None,
        publication_status=(request.query_params.get("publicationStatus") or "").strip().upper() or None,
        tracking_status=(request.query_params.get("trackingStatus") or "").strip().upper() or None,
        tag=(request.query_params.get("tag") or "").strip() or None,
        missing_cover=(request.query_params.get("missingCover") or "").lower() == "true",
        new_import=(request.query_params.get("newImport") or "").lower() == "true",
        filter_rules=filter_rules,
    )
    try:
        result = list_library_works(db, user, query)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    bookshelf_view = view == "bookshelf"
    search_view = view == "search"
    management_view = view == "management"
    default_direction = "DESC" if sort in {"updated", "recent_read", "recent_import", "progress"} else "ASC"
    direction = sortDirection.upper() if sortDirection and sortDirection.lower() in {"asc", "desc"} else default_direction
    if result.progress_sort:
        work_views = [(work, _work_view(db, work, user.id)) for work in result.works]
        work_views.sort(
            key=lambda item: (
                int(item[1].get("progress") or 0),
                item[1].get("lastReadAt") or "",
                _dt(item[0].get("updatedAt")) or "",
                str(item[0].get("id") or ""),
            ),
            reverse=direction == "DESC",
        )
        start = (page - 1) * page_size
        page_items = work_views[start : start + page_size]
        book_views = (
            [_bookshelf_item_view(work) for work, _item_view in page_items]
            if bookshelf_view
            else [_book_search_item_view(work) for work, _item_view in page_items]
            if search_view
            else _management_work_views(db, [work for work, _item_view in page_items], user.id)
            if management_view
            else [item_view for _work, item_view in page_items]
        )
    else:
        works = result.works
        book_views = (
            [_bookshelf_item_view(work) for work in works]
            if bookshelf_view
            else [_book_search_item_view(work) for work in works]
            if search_view
            else _management_work_views(db, works, user.id)
            if management_view
            else [_work_view(db, work, user.id) for work in works]
        )
    return ok(
        {
            "books": book_views,
            "page": result.page,
            "pageSize": result.page_size,
            "total": result.total,
            "totalPages": max(1, (result.total + result.page_size - 1) // result.page_size),
        }
    )


@router.get("/works/{work_id}")
def get_work(
    work_id: str,
    request: Request,
    detailTab: str | None = None,
    editionId: str | None = None,
    volumeId: str | None = None,
    unitPage: int | None = None,
    chapterPage: int = 1,
    chapterPageSize: int = 120,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    work = _visible_work_or_none(db, user, work_id)
    if not work:
        return fail("作品不存在", status_code=404)
    book = _work_view(db, work, user.id)
    selected_tab = _resolve_detail_tab(db, user.id, work_id, book.get("detailTabs", []), detailTab)
    book["selectedDetailTab"] = selected_tab
    active_media, navigation = _active_media_view(
        db,
        book,
        selected_tab,
        user.id,
        editionId,
        volumeId,
        unitPage if unitPage is not None else chapterPage,
        chapterPageSize,
    )
    return ok({"book": book, "activeMedia": active_media, **navigation})


@router.put("/works/{work_id}/detail-preference")
async def save_work_detail_preference(
    work_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    work = _visible_work_or_none(db, user, work_id)
    if not work:
        return fail("作品不存在", status_code=404)
    payload = await request.json()
    requested = str(payload.get("selectedTab") or "").strip().upper()
    book = _work_view(db, work, user.id)
    tabs = book.get("detailTabs", [])
    visible = {str(item.get("key")) for item in tabs}
    if requested not in DETAIL_TAB_KEYS:
        return fail("详情选项卡无效", status_code=400)
    if requested not in visible:
        return fail("该作品没有对应的媒介版本", status_code=409)
    now = _now()
    if not _has_table(db, "WorkDetailPreference"):
        return fail("详情偏好表尚未初始化", status_code=503)
    library_projections.save_detail_preference(
        db,
        user_id=user.id,
        work_id=work_id,
        selected_tab=requested,
        now=now,
    )
    db.commit()
    return ok({"selectedDetailTab": requested, "detailTabs": tabs})


@router.patch("/works/{work_id}")
async def update_work(work_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    existing_work = _visible_work_or_none(db, user, work_id)
    if not existing_work:
        return fail("作品不存在", status_code=404)
    allowed = {"title", "author", "description", "status", "publicationStatus", "trackingStatus", "tags", "seriesName", "seriesIndex", "publishedYear", "hidden", "organized", "metadataQuality"}
    values = {key: (_json_text(value) if key == "tags" and isinstance(value, list) else value) for key, value in payload.items() if key in allowed}
    global_fields = set(values) - {"status"}
    if "ignored" in payload:
        global_fields.add("hidden")
    if global_fields and not can_manage_system(user):
        return fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    media_kind = str(payload.get("mediaKind") or "").strip().upper()
    if media_kind and media_kind not in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        return fail("媒介类型无效", status_code=400)
    if "status" in values:
        status = str(values["status"] or "").strip().upper()
        if status == "WANT":
            status = "UNREAD"
        if status not in {"UNREAD", "READING", "FINISHED"}:
            return fail("阅读状态无效", status_code=400)
        book_before_update = _work_view(db, existing_work, user.id)
        available = {
            str(item)
            for item in book_before_update.get("availableMediaKinds", [])
        }
        target_media_kinds = [media_kind] if media_kind else sorted(available)
        if not target_media_kinds or any(kind not in available for kind in target_media_kinds):
            return fail("该作品没有对应的媒介版本", status_code=409)
        requested_edition_id = str(payload.get("editionId") or "").strip() or None
        requested_volume_id = str(payload.get("volumeId") or "").strip() or None
        if requested_edition_id and not can_access_edition(db, user, requested_edition_id):
            return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
        if requested_volume_id and not can_access_volume(db, user, requested_volume_id):
            return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
        for target_media_kind in target_media_kinds:
            target, target_error = _resolve_consumption_target(
                db,
                work_id,
                target_media_kind,
                edition_id=requested_edition_id if len(target_media_kinds) == 1 else None,
                volume_id=requested_volume_id if len(target_media_kinds) == 1 else None,
                unit_id=str(payload.get("unitId") or "").strip() or None,
            )
            if target_error:
                return fail(target_error, status_code=422)
            _set_consumption_status(
                db,
                user.id,
                work_id,
                target_media_kind,
                status,
                edition_id=(target or {}).get("editionId"),
                volume_id=(target or {}).get("volumeId"),
                unit_id=(target or {}).get("unitId"),
            )
        values.pop("status", None)
    if "ignored" in payload:
        values["hidden"] = bool(payload.get("ignored"))
    try:
        if "seriesIndex" in values:
            values["seriesIndex"] = _nullable_float(values["seriesIndex"], "系列序号")
        if "publishedYear" in values:
            values["publishedYear"] = _nullable_int(values["publishedYear"], "出版年")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    if "title" in values or "author" in values:
        title = str(values.get("title", existing_work.get("title")) or "").strip()
        author = str(values.get("author", existing_work.get("author")) or "").strip() or UNKNOWN_AUTHOR
        if not title:
            return fail("标题不能为空", status_code=400)
        merge_key = identity_merge_key(title, author)
        values.update(
            {
                "title": title,
                "author": author,
                "normalizedTitle": normalize_identity_part(title),
                "normalizedAuthor": normalize_identity_part(author),
                "mergeKey": merge_key,
            }
        )
    if not values:
        db.commit()
        return ok({"book": _work_view(db, existing_work, user.id)})
    work = library_works.update_work_fields(db, work_id, values)
    if not work:
        return fail("作品不存在", status_code=404)
    sync_work_facets(db, work_id)
    work = _get_work(db, work_id) or work
    return ok({"book": _work_view(db, work, user.id)})


@router.delete("/works/{work_id}")
async def delete_work(work_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    payload = await _request_json_or_empty(request)
    delete_source = payload.get("deleteSource") is True
    work = _get_work(db, work_id)
    result = _delete_work_and_storage(db, work_id, settings, delete_source=delete_source)
    if result.get("deleted"):
        _record_system_event(
            db,
            level="error",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="deleted",
            target_type="work",
            target_id=work_id,
            message=f"删除书库记录：{(work or {}).get('title') or work_id}",
            metadata={"workTitle": (work or {}).get("title"), "deleteSource": delete_source, "deletedFiles": result.get("deletedFiles"), "deletedSourceFiles": result.get("deletedSourceFiles"), "failedFileDeletes": result.get("failedFileDeletes")},
        )
    return ok(result)


_BULK_TEXT_FIELDS: dict[str, tuple[str, str]] = {
    "title": ("LibraryWork", "title"),
    "author": ("LibraryWork", "author"),
    "description": ("LibraryWork", "description"),
    "seriesName": ("LibraryWork", "seriesName"),
    "tags": ("LibraryWork", "tags"),
    "publisher": ("LibraryEdition", "publisher"),
    "language": ("LibraryEdition", "language"),
    "isbn": ("LibraryEdition", "isbn"),
    "identifier": ("LibraryEdition", "identifier"),
    "versionName": ("LibraryEdition", "versionName"),
    "narrator": ("LibraryEdition", "narrator"),
}
_BULK_TEMPLATE_VARIABLES = {"value", "match", "index", "index0", "number", "letter", "letter_upper"}
_BULK_TEMPLATE_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s*\|\s*(lower|upper|title|trim))?\s*}}")


def _bulk_work_ids(raw_ids: Any, *, maximum: int = 500) -> list[str]:
    if not isinstance(raw_ids, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in raw_ids if str(item).strip()))[:maximum]


def _primary_edition(db: Session, work_id: str) -> dict[str, Any] | None:
    return library_join_queries.get_primary_edition_row(db, work_id)


def _sequence_letters(value: int) -> str:
    number = max(1, value)
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(97 + remainder) + result
    return result


def _render_bulk_template(template: str, *, value: str, match: str, index: int, number: int) -> str:
    invalid = [name for name in re.findall(r"{{\s*([^}|\s]+)", template) if name not in _BULK_TEMPLATE_VARIABLES]
    if invalid:
        raise ValueError(f"不支持的模板变量：{invalid[0]}")
    context: dict[str, Any] = {
        "value": value,
        "match": match,
        "index": index + 1,
        "index0": index,
        "number": number,
        "letter": _sequence_letters(number),
        "letter_upper": _sequence_letters(number).upper(),
    }

    def replace_variable(template_match: re.Match[str]) -> str:
        variable, filter_name = template_match.groups()
        rendered = str(context[variable])
        if filter_name == "lower":
            return rendered.lower()
        if filter_name == "upper":
            return rendered.upper()
        if filter_name == "title":
            return rendered.title()
        if filter_name == "trim":
            return rendered.strip()
        return rendered

    return _BULK_TEMPLATE_PATTERN.sub(replace_variable, template)


def _bulk_replace_text(
    value: str,
    *,
    find: str,
    replacement: str,
    regex: bool,
    case_sensitive: bool,
    index: int,
    number: int,
) -> str:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(find if regex else re.escape(find), flags)
    except re.error as exc:
        raise ValueError(f"正则表达式无效：{exc}") from None

    def replace_match(match: re.Match[str]) -> str:
        return _render_bulk_template(
            replacement,
            value=value,
            match=match.group(0),
            index=index,
            number=number,
        )

    return pattern.sub(replace_match, value)


def _bulk_find_replace_rows(db: Session, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    work_ids = _bulk_work_ids(payload.get("ids") or payload.get("bookIds"))
    field = str(payload.get("field") or "").strip()
    find = str(payload.get("find") or "")
    replacement = str(payload.get("replacement") or "")
    if not work_ids:
        return [], "请选择至少一本图书"
    if field not in _BULK_TEXT_FIELDS:
        return [], "请选择可查找替换的元数据字段"
    if not find:
        return [], "查找内容不能为空"
    regex = payload.get("regex") is True
    case_sensitive = payload.get("caseSensitive") is True
    start_number = max(1, _coerce_int(payload.get("startNumber"), 1))
    try:
        _render_bulk_template(replacement, value="", match="", index=0, number=start_number)
    except ValueError as exc:
        return [], str(exc)
    table, column = _BULK_TEXT_FIELDS[field]
    results: list[dict[str, Any]] = []
    for index, work_id in enumerate(work_ids):
        work = _get_work(db, work_id)
        if not work:
            continue
        target = work if table == "LibraryWork" else _primary_edition(db, work_id)
        if not target:
            continue
        raw_value = target.get(column)
        if field == "tags":
            current_tags = [str(item) for item in _parse_json(raw_value, []) if str(item).strip()]
            try:
                next_tags = [
                    _bulk_replace_text(
                        item,
                        find=find,
                        replacement=replacement,
                        regex=regex,
                        case_sensitive=case_sensitive,
                        index=index,
                        number=start_number + index,
                    ).strip()
                    for item in current_tags
                ]
            except ValueError as exc:
                return [], str(exc)
            next_tags = list(dict.fromkeys(item for item in next_tags if item))
            before_value: Any = current_tags
            after_value: Any = next_tags
        else:
            before_value = str(raw_value or "")
            try:
                after_value = _bulk_replace_text(
                    before_value,
                    find=find,
                    replacement=replacement,
                    regex=regex,
                    case_sensitive=case_sensitive,
                    index=index,
                    number=start_number + index,
                )
            except ValueError as exc:
                return [], str(exc)
        if before_value == after_value:
            continue
        results.append(
            {
                "workId": work_id,
                "title": work.get("title") or "未命名图书",
                "targetId": target.get("id"),
                "table": table,
                "column": column,
                "before": before_value,
                "after": after_value,
            }
        )
    return results, None


def _apply_bulk_reading_status(db: Session, user: User, work_ids: list[str], status: str) -> int:
    updated = 0
    now = _now()
    context = authorization_context(db, user)
    for work_id in work_ids:
        work = _get_work(db, work_id)
        if not work:
            continue
        editions = (
            library_works.list_visible_editions_for_work(db, work_id=work_id, context=context)
            if _has_table(db, "LibraryEdition")
            else []
        )
        if not editions:
            continue
        media_editions: dict[str, dict[str, Any]] = {}
        for edition in editions:
            media_editions.setdefault(_edition_media_kind(edition), edition)
        if status == "UNREAD":
            library_works.clear_reading_state_for_work(
                db,
                user_id=user.id,
                work_id=work_id,
            )
        else:
            for media_kind, edition in media_editions.items():
                _set_consumption_status(
                    db,
                    user.id,
                    work_id,
                    media_kind,
                    status,
                    edition_id=str(edition["id"]),
                )
            if status != "FINISHED":
                updated += 1
                continue
            for edition in editions:
                if not _has_table(db, "LibraryReadingProgress"):
                    continue
                media_kind = _edition_media_kind(edition)
                library_works.mark_edition_finished(
                    db,
                    user_id=user.id,
                    work_id=work_id,
                    edition=edition,
                    reader_type=(
                        "comic"
                        if media_kind == "COMIC"
                        else "audio"
                        if media_kind == "AUDIOBOOK"
                        else "pdf"
                        if str(edition.get("format")).upper() == "PDF"
                        else "epub"
                    ),
                    now=now,
                )
        updated += 1
    db.commit()
    return updated


@router.post("/works/bulk")
async def bulk_works(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    ids = payload.get("ids") or payload.get("bookIds") or []
    action = payload.get("action")
    updated = 0
    if action is None and "ignored" in payload:
        action = "ignore" if payload.get("ignored") else "restore"
    if action is None and payload.get("deleteRecords"):
        action = "delete_records"
    normalized_scope_ids = _bulk_work_ids(ids)
    if normalized_scope_ids:
        inaccessible = [
            work_id
            for work_id in normalized_scope_ids
            if not can_access_work(db, user, work_id)
        ]
        if inaccessible:
            return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    personal_actions = {"set_status", "reading_status", "shelf_membership", "add_to_shelf", "remove_from_shelf"}
    if action not in personal_actions and not can_manage_system(user):
        return fail("需要系统管理权限", status_code=403, code="SYSTEM_MANAGER_REQUIRED")
    if _has_table(db, "LibraryWork") and ids and action in {"delete", "delete_records"}:
        deleted_files = 0
        failed_file_deletes: list[dict[str, str]] = []
        for work_id in ids:
            result = _delete_work_and_storage(db, str(work_id), settings)
            if result["deleted"]:
                updated += 1
                deleted_files += int(result.get("deletedFiles") or 0)
                failed_file_deletes.extend(result.get("failedFileDeletes") or [])
        if updated:
            _record_system_event(db, level="error", source="library", actor_type="admin", actor_id=user.id, action="bulk.deleted", target_type="work", message=f"批量删除书库记录 {updated} 个", metadata={"ids": ids, "deletedFiles": deleted_files, "failedFileDeletes": failed_file_deletes})
        return ok({"updated": updated, "deleted": updated, "deletedFiles": deleted_files, "failedFileDeletes": failed_file_deletes, "ids": ids})
    if _has_table(db, "LibraryWork") and ids and action in {"hide", "ignore", "restore", "unignore", "mark_organized"}:
        hidden = action in {"hide", "ignore"}
        organized = action == "mark_organized"
        for work_id in ids:
            values = {"hidden": hidden} if action != "mark_organized" else {"organized": organized}
            if library_works.update_work_fields(db, str(work_id), values):
                updated += 1
        if updated:
            _record_system_event(db, level="info", source="library", actor_type="admin", actor_id=user.id, action=f"bulk.{action}", target_type="work", message=f"批量更新作品 {updated} 个", metadata={"ids": ids, "action": action})
    elif _has_table(db, "LibraryWork") and ids and action in {"add_tags", "remove_tags", "set_status", "add_to_shelf", "remove_from_shelf", "update_fields", "update_metadata", "shelf_membership", "reading_status", "find_replace"}:
        normalized_ids = _bulk_work_ids(ids)
        tags = [str(item).strip() for item in payload.get("tags") or [] if str(item).strip()]
        status = str(payload.get("status") or "").strip().upper()
        if action == "set_status" and status not in {"UNREAD", "READING", "FINISHED"}:
            return fail("阅读状态无效", status_code=400)
        if action == "reading_status" and status not in {"UNREAD", "FINISHED"}:
            return fail("批量阅读状态仅支持未读或已读", status_code=400)
        shelf_id = str(payload.get("shelfId") or "").strip()
        membership = str(payload.get("membership") or ("REMOVE" if action == "remove_from_shelf" else "ADD")).strip().upper()
        if action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
            shelf = _owned_shelf(db, shelf_id, user.id) if shelf_id else None
            if not shelf or str(shelf.get("kind") or "STATIC").upper() != "STATIC":
                return fail("请选择普通书架", status_code=400)
            if membership not in {"ADD", "REMOVE"}:
                return fail("书架操作无效", status_code=400)
        editable = {"author", "description", "publicationStatus", "trackingStatus", "seriesName", "seriesIndex", "publishedYear"}
        raw_fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        fields = {key: value for key, value in raw_fields.items() if key in editable}
        if action == "find_replace":
            replacements, replace_error = _bulk_find_replace_rows(db, payload)
            if replace_error:
                return fail(replace_error, status_code=400)
            changed_work_ids: set[str] = set()
            now = _now()
            for replacement in replacements:
                if replacement["column"] == "versionName" and not str(replacement["after"] or "").strip():
                    return fail("版本名称替换后不能为空", status_code=400)
                value = _json_text(replacement["after"]) if replacement["column"] == "tags" else replacement["after"] or None
                if replacement["column"] in {"title", "author"}:
                    work = _get_work(db, replacement["workId"]) or {}
                    title_value = str(value if replacement["column"] == "title" else work.get("title") or "").strip()
                    author_value = str(value if replacement["column"] == "author" else work.get("author") or "").strip() or UNKNOWN_AUTHOR
                    if not title_value:
                        return fail("查找替换后的标题不能为空", status_code=400)
                    library_works.update_work_fields(
                        db,
                        str(replacement["workId"]),
                        {
                            "title": title_value,
                            "author": author_value,
                            "normalizedTitle": normalize_identity_part(title_value),
                            "normalizedAuthor": normalize_identity_part(author_value),
                            "mergeKey": identity_merge_key(title_value, author_value),
                            "updatedAt": now,
                        },
                    )
                else:
                    update_values = {
                        replacement["column"]: value,
                        "updatedAt": now,
                    }
                    if replacement["table"] == "LibraryWork":
                        library_works.update_work_fields(
                            db,
                            str(replacement["targetId"]),
                            update_values,
                        )
                    else:
                        library_works.update_edition_fields(
                            db,
                            str(replacement["targetId"]),
                            update_values,
                        )
                changed_work_ids.add(str(replacement["workId"]))
            for work_id in changed_work_ids:
                sync_work_facets(db, work_id, commit=False)
            db.commit()
            updated = len(changed_work_ids)
            if updated:
                _record_system_event(db, level="info", source="library", actor_type="admin", actor_id=user.id, action="bulk.find_replace", target_type="work", message=f"批量查找替换 {updated} 本图书", metadata={"ids": normalized_ids, "field": payload.get("field"), "changedValues": len(replacements)})
            return ok({"updated": updated, "changedValues": len(replacements), "ids": normalized_ids})
        if action in {"set_status", "reading_status"}:
            updated = _apply_bulk_reading_status(db, user, normalized_ids, status)
            if updated:
                _record_system_event(db, level="info", source="library", actor_type="user", actor_id=user.id, action=f"bulk.reading_status.{status.lower()}", target_type="work", message=f"批量设置阅读状态 {updated} 本图书", metadata={"ids": normalized_ids, "status": status})
            return ok({"updated": updated, "ids": normalized_ids, "status": status})
        metadata_fields = payload.get("fields") if action == "update_metadata" and isinstance(payload.get("fields"), dict) else {}
        add_tags = [str(item).strip() for item in payload.get("addTags") or [] if str(item).strip()]
        remove_tags = [str(item).strip() for item in payload.get("removeTags") or [] if str(item).strip()]
        for work_id in normalized_ids:
            work = _get_work(db, work_id)
            if not work:
                continue
            if action in {"add_tags", "remove_tags"}:
                current_tags = [str(item) for item in _parse_json(work.get("tags"), [])]
                if action == "add_tags":
                    next_tags = list(dict.fromkeys([*current_tags, *tags]))
                else:
                    removed = {item.casefold() for item in tags}
                    next_tags = [item for item in current_tags if item.casefold() not in removed]
                library_works.update_work_fields(
                    db,
                    work_id,
                    {"tags": _json_text(next_tags), "updatedAt": _now()},
                )
            elif action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
                if membership == "ADD":
                    shelf_store.add_shelf_work(
                        db, shelf_id=shelf_id, work_id=work_id, now=_now()
                    )
                else:
                    shelf_store.remove_shelf_work(db, shelf_id=shelf_id, work_id=work_id)
                db.commit()
            elif action == "update_metadata":
                work_values: dict[str, Any] = {"updatedAt": _now()}
                if "author" in metadata_fields:
                    author = str(metadata_fields.get("author") or "").strip() or UNKNOWN_AUTHOR
                    work_values.update({"author": author, "normalizedAuthor": normalize_identity_part(author), "mergeKey": identity_merge_key(str(work.get("title") or ""), author)})
                if "seriesName" in metadata_fields:
                    work_values["seriesName"] = str(metadata_fields.get("seriesName") or "").strip() or None
                current_tags = [str(item) for item in _parse_json(work.get("tags"), []) if str(item).strip()]
                if add_tags:
                    current_tags = list(dict.fromkeys([*current_tags, *add_tags]))
                if remove_tags:
                    removed = {item.casefold() for item in remove_tags}
                    current_tags = [item for item in current_tags if item.casefold() not in removed]
                if add_tags or remove_tags:
                    work_values["tags"] = _json_text(current_tags)
                if len(work_values) > 1:
                    library_works.update_work_fields(db, work_id, work_values)
                if "publisher" in metadata_fields:
                    edition = _primary_edition(db, work_id)
                    if edition:
                        library_works.update_edition_fields(
                            db,
                            str(edition["id"]),
                            {
                                "publisher": str(
                                    metadata_fields.get("publisher") or ""
                                ).strip()
                                or None,
                                "updatedAt": _now(),
                            },
                        )
            elif fields:
                library_works.update_work_fields(
                    db,
                    work_id,
                    {**fields, "updatedAt": _now()},
                )
            sync_work_facets(db, work_id)
            updated += 1
        if updated:
            _record_system_event(db, level="info", source="library", actor_type="admin", actor_id=user.id, action=f"bulk.{action}", target_type="work", message=f"批量更新作品 {updated} 个", metadata={"ids": normalized_ids, "action": action})
    return ok({"updated": updated, "ids": ids})


@router.post("/works/bulk/find-replace/preview")
async def preview_bulk_find_replace(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _system_auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    for work_id in _bulk_work_ids(payload.get("ids") or payload.get("bookIds") or []):
        if not can_access_work(db, user, work_id):
            return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    replacements, replace_error = _bulk_find_replace_rows(db, payload)
    if replace_error:
        return fail(replace_error, status_code=400)
    return ok({"changedWorks": len({item["workId"] for item in replacements}), "changedValues": len(replacements), "items": replacements[:30]})


def _prepare_cover_image(image: Image.Image, *, ratio: str | None, max_dimension: int, quality: int) -> tuple[Image.Image, int]:
    prepared = ImageOps.exif_transpose(image).convert("RGB")
    ratios = {"2:3": 2 / 3, "3:4": 3 / 4, "1:1": 1.0}
    target_ratio = ratios.get(str(ratio or ""))
    if target_ratio:
        width, height = prepared.size
        current_ratio = width / height if height else target_ratio
        if current_ratio > target_ratio:
            crop_width = max(1, round(height * target_ratio))
            left = max(0, (width - crop_width) // 2)
            prepared = prepared.crop((left, 0, left + crop_width, height))
        elif current_ratio < target_ratio:
            crop_height = max(1, round(width / target_ratio))
            top = max(0, (height - crop_height) // 2)
            prepared = prepared.crop((0, top, width, top + crop_height))
    if max(prepared.size) > max_dimension:
        prepared.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    return prepared, quality


@router.post("/works/bulk/cover")
async def bulk_work_covers(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    form = await request.form()
    try:
        raw_ids = json.loads(str(form.get("ids") or "[]"))
    except json.JSONDecodeError:
        return fail("图书选择无效", status_code=400)
    work_ids = _bulk_work_ids(raw_ids)
    action = str(form.get("action") or "").strip().lower()
    if not work_ids:
        return fail("请选择至少一本图书", status_code=400)
    if any(not can_access_work(db, user, work_id) for work_id in work_ids):
        return fail("作品不存在", status_code=404, code="WORK_NOT_FOUND")
    if action not in {"crop", "regenerate", "compress", "replace"}:
        return fail("封面操作无效", status_code=400)
    ratio = str(form.get("ratio") or "2:3")
    if action == "crop" and ratio not in {"2:3", "3:4", "1:1"}:
        return fail("封面裁剪比例无效", status_code=400)
    quality = max(40, min(95, _coerce_int(form.get("quality"), 82)))
    max_dimension = max(600, min(3200, _coerce_int(form.get("maxDimension"), 1600)))
    upload = form.get("cover")
    uploaded_image: Image.Image | None = None
    if action == "replace":
        if not upload or not hasattr(upload, "read"):
            return fail("请选择替换封面", status_code=400)
        raw_image = await upload.read()
        if not raw_image or len(raw_image) > 12 * 1024 * 1024:
            return fail("封面文件为空或超过 12 MB", status_code=400)
        try:
            uploaded_image = Image.open(io.BytesIO(raw_image))
            uploaded_image.load()
        except (UnidentifiedImageError, OSError):
            return fail("封面文件不是可识别的图片", status_code=400)

    target_dir = settings.resolved_storage_root / "covers" / "bulk"
    target_dir.mkdir(parents=True, exist_ok=True)
    created_paths: list[Path] = []
    pending_updates: list[tuple[str, str, str]] = []
    skipped: list[dict[str, str]] = []
    try:
        for work_id in work_ids:
            work = _get_work(db, work_id)
            if not work:
                skipped.append({"workId": work_id, "reason": "作品不存在"})
                continue
            if action == "regenerate":
                relative = _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings)
                path = _stored_path(relative, settings)
                if path is None or not path.is_file():
                    relative = ensure_default_cover(settings)
                pending_updates.append((work_id, relative, cover_status(relative, settings)))
                continue
            source_image: Image.Image
            if uploaded_image is not None:
                source_image = uploaded_image.copy()
            else:
                source_relative = str(work.get("coverPath") or _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings))
                source_path = _stored_path(source_relative, settings)
                if source_path is None or not source_path.is_file():
                    source_path = _stored_path(ensure_default_cover(settings), settings)
                if source_path is None:
                    skipped.append({"workId": work_id, "reason": "找不到可处理的封面"})
                    continue
                try:
                    source_image = Image.open(source_path)
                    source_image.load()
                except (UnidentifiedImageError, OSError):
                    skipped.append({"workId": work_id, "reason": "当前封面无法读取"})
                    continue
            processed, output_quality = _prepare_cover_image(
                source_image,
                ratio=ratio if action == "crop" else None,
                max_dimension=max_dimension,
                quality=quality,
            )
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", work_id)[:100] or "work"
            target = target_dir / f"{safe_id}-{time_ns()}.jpg"
            processed.save(target, format="JPEG", quality=output_quality, optimize=True, progressive=True)
            created_paths.append(target)
            relative = str(target.relative_to(settings.resolved_storage_root))
            pending_updates.append((work_id, relative, "READY"))
        now = _now()
        for work_id, relative, status in pending_updates:
            library_storage.update_work_cover(
                db,
                work_id=work_id,
                cover_path=relative,
                cover_status=status,
                now=now,
            )
        db.commit()
    except Exception:
        db.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    updated = len(pending_updates)
    if updated:
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action=f"bulk.cover.{action}",
            target_type="work",
            message=f"批量处理封面 {updated} 本图书",
            metadata={"ids": work_ids, "action": action, "ratio": ratio if action == "crop" else None, "quality": quality, "maxDimension": max_dimension, "skipped": skipped},
        )
    return ok({"updated": updated, "ids": [item[0] for item in pending_updates], "skipped": skipped})


@router.post("/works/import")
async def import_work(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    form = await request.form()
    files = [value for _key, value in form.multi_items() if hasattr(value, "filename")]
    if not files:
        return fail("请选择要导入的文件", status_code=400)
    upload_file_names = [_safe_upload_name(getattr(upload, "filename", None)) for upload in files]
    unsupported = [name for name in upload_file_names if not is_supported_import_file(Path(name))]
    if unsupported:
        return fail(
            "当前版本仅支持 EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT、CBZ、ZIP、PDF、M4B、M4A、MP3 格式。",
            status_code=400,
            details={"files": unsupported},
        )
    import_preferences = load_import_preferences(db)
    disabled_extensions = [name for name in upload_file_names if not extension_is_allowed(Path(name), import_preferences)]
    if disabled_extensions:
        return fail("部分文件后缀已在导入偏好中关闭。", status_code=400, details={"files": disabled_extensions})
    try:
        upload_dir = _target_directory_from_path(settings, form.get("targetPath"), "上传")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    ignored_files = [name for name in upload_file_names if matches_ignore_patterns(upload_dir / name, import_preferences.ignore_patterns)]
    if ignored_files:
        return fail("部分文件命中全局导入忽略规则。", status_code=400, details={"files": ignored_files})
    monitor_folder = _enabled_monitor_folder_for_path(db, upload_dir)
    monitor_folder_id = str((monitor_folder or {}).get("id") or "") or None
    if not can_access_monitor_folder(db, user, monitor_folder_id):
        return fail("目标文件夹不存在或无权访问", status_code=404, code="MONITOR_FOLDER_NOT_FOUND")
    auto_import = True
    tasks: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    audio_uploads = [upload for upload in files if is_supported_audio_file(_safe_upload_name(getattr(upload, "filename", None)))]
    explicit_requested_title = re.sub(r"\s+", " ", str(form.get("bookTitle") or "")).strip()[:500] or None
    explicit_requested_author = re.sub(
        r"\s+", " ", str(form.get("bookAuthor") or form.get("author") or "")
    ).strip()[:500] or None
    audio_bundle_dir: Path | None = None
    audio_bundle_staging_dir: Path | None = None
    if len(audio_uploads) > 1:
        bundle_directory_title = _audio_bundle_upload_title(
            [_safe_upload_name(getattr(upload, "filename", None)) for upload in audio_uploads],
            explicit_requested_title,
        )
        audio_bundle_dir = _unique_file_in_directory(upload_dir, f"{bundle_directory_title}-有声书")
        audio_bundle_staging_dir = upload_dir / f".upload-{time_ns()}.part"
        audio_bundle_staging_dir.mkdir(parents=False, exist_ok=False)
    known_audio_sizes = [
        int(size)
        for upload in audio_uploads
        if (size := getattr(upload, "size", None)) is not None
    ]
    if any(size > settings.audiobook_max_file_bytes for size in known_audio_sizes):
        if audio_bundle_staging_dir is not None:
            audio_bundle_staging_dir.rmdir()
        return fail(f"音频文件超过单文件上限 {settings.audiobook_max_file_bytes} bytes", status_code=400)
    if sum(known_audio_sizes) > settings.audiobook_max_bundle_bytes:
        if audio_bundle_staging_dir is not None:
            audio_bundle_staging_dir.rmdir()
        return fail(f"有声书文件总量超过上限 {settings.audiobook_max_bundle_bytes} bytes", status_code=400)
    staged_uploads: list[tuple[str, Path, bool, Path]] = []
    finalized_paths: list[Path] = []
    remaining_audio_bytes = settings.audiobook_max_bundle_bytes
    try:
        for upload in files:
            file_name = _safe_upload_name(getattr(upload, "filename", None))
            is_bundle_asset = audio_bundle_dir is not None and is_supported_audio_file(file_name)
            if is_bundle_asset:
                assert audio_bundle_staging_dir is not None
                staged_target = _unique_file_in_directory(audio_bundle_staging_dir, file_name)
                target = audio_bundle_dir / staged_target.name
            else:
                target = _unique_file_in_directory(upload_dir, file_name)
                staged_target = target.with_name(f".{target.name}.{time_ns()}.part")
            is_audio_asset = is_supported_audio_file(file_name)
            max_bytes = min(settings.audiobook_max_file_bytes, remaining_audio_bytes) if is_audio_asset else None
            staged_uploads.append((file_name, target, is_bundle_asset, staged_target))
            copied = _copy_upload_stream(upload.file, staged_target, max_bytes=max_bytes)
            if is_audio_asset:
                remaining_audio_bytes -= copied

        if audio_bundle_dir is not None and audio_bundle_staging_dir is not None:
            audio_bundle_staging_dir.rename(audio_bundle_dir)
            finalized_paths.append(audio_bundle_dir)
        for _file_name, target, is_bundle_asset, staged_target in staged_uploads:
            if is_bundle_asset:
                continue
            staged_target.rename(target)
            finalized_paths.append(target)
    except Exception as exc:
        for _file_name, _target, _is_bundle_asset, staged_target in staged_uploads:
            staged_target.unlink(missing_ok=True)
        if audio_bundle_staging_dir is not None and audio_bundle_staging_dir.exists():
            shutil.rmtree(audio_bundle_staging_dir)
        for path in reversed(finalized_paths):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        return fail(
            f"保存上传文件失败：{exc}",
            status_code=400 if isinstance(exc, ValueError) else 500,
        )

    saved_uploads: list[tuple[str, Path, bool]] = [
        (file_name, target, is_bundle_asset)
        for file_name, target, is_bundle_asset, _staged_target in staged_uploads
    ]

    queue_items: list[tuple[str, Path, list[tuple[str, Path, bool]]]] = [
        (file_name, target, [(file_name, target, is_bundle_asset)])
        for file_name, target, is_bundle_asset in saved_uploads
        if not is_bundle_asset
    ]
    if audio_bundle_dir is not None:
        queue_items.append((audio_bundle_dir.name, audio_bundle_dir, [item for item in saved_uploads if item[2]]))

    for original_name, source_path, grouped_uploads in queue_items:
        is_audio_queue = all(is_supported_audio_file(file_name) for file_name, _target, _asset in grouped_uploads)
        task, _created = (
            enqueue_import_task(
                db,
                source_path,
                origin="MANUAL",
                original_name=original_name,
                requested_title=explicit_requested_title if is_audio_queue else None,
                requested_author=explicit_requested_author if is_audio_queue else None,
                monitor_folder_id=monitor_folder.get("id") if monitor_folder else None,
                message="有声书分轨已合并，等待后台处理" if len(grouped_uploads) > 1 else "已保存到所选目录，等待后台处理",
            )
            if _has_table(db, "ImportTask")
            else ({"id": None, "sourcePath": str(source_path)}, True)
        )
        tasks.append(task)
        for file_name, target, _is_bundle_asset in grouped_uploads:
            _record_system_event(
                db,
                level="info",
                source="import",
                actor_type="admin",
                actor_id=user.id,
                action="uploaded",
                target_type="importTask",
                target_id=task.get("id"),
                message=f"上传到所选目录：{file_name}",
                metadata={"file": file_name, "sourcePath": str(target), "bundleSourcePath": str(source_path), "autoImport": True},
            )
            results.append(
                {
                    "sourcePath": str(target),
                    "file": file_name,
                    "importTaskId": task.get("id"),
                    "importStatus": "pending",
                    "autoImport": True,
                    "message": "已合并为一个有声书任务" if len(grouped_uploads) > 1 else "已加入后台导入队列",
                }
            )

    _save_system_setting(db, "library.lastUploadTargetPath", str(upload_dir))
    db.commit()
    task_kind = str(tasks[0].get("taskKind") or "FILE") if len(tasks) == 1 else "MULTI_FILE"
    asset_count = sum(int(task.get("assetCount") or 1) for task in tasks)
    return ok({
        "tasks": tasks,
        "results": results,
        "queued": len(tasks),
        "saved": len(files),
        "imported": 0,
        "autoImport": auto_import,
        "taskKind": task_kind,
        "bundleKey": tasks[0].get("bundleKey") if len(tasks) == 1 else None,
        "assetCount": asset_count,
        "processedAssetCount": sum(int(task.get("processedAssetCount") or 0) for task in tasks),
    })


@router.get("/monitor-folders")
def list_monitor_folders(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    folders = import_http_store.list_monitor_folders(db)
    return ok({
        "folders": folders,
        "monitorRoot": str(settings.resolved_monitor_root.resolve()) if settings.resolved_monitor_root else None,
        "lastUploadTargetPath": _system_setting_value(db, "library.lastUploadTargetPath"),
        "lastDownloadTargetPath": _system_setting_value(db, "library.lastDownloadTargetPath"),
    })


@router.get("/monitor-folders/tree")
def monitor_folder_tree(request: Request, path: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    node, error, status_code = _monitor_directory_tree_node(settings, path)
    if error:
        return fail(error, status_code=status_code)
    return ok({"node": node, "monitorRoot": str(settings.resolved_monitor_root.resolve()) if settings.resolved_monitor_root else None})


@router.post("/monitor-folders")
async def create_monitor_folder(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    root_path = _normalize_monitor_root_path(payload.get("rootPath"))
    if not root_path:
        return fail("请填写监控文件夹路径", status_code=400)
    if _monitor_folder_by_root_path(db, root_path):
        return fail("监控文件夹路径已存在", status_code=409, details={"rootPath": root_path})
    if payload.get("shelfId"):
        return fail(
            "监控文件夹不再绑定全局书架，请创建个人来源文件夹智能书架",
            status_code=400,
            code="MONITOR_FOLDER_SHELF_RETIRED",
        )
    raw_min_file_size = payload.get("minFileSizeBytes")
    try:
        min_file_size_bytes = int(10240 if raw_min_file_size is None else raw_min_file_size)
    except (TypeError, ValueError):
        return fail("最小文件大小必须是非负整数", status_code=400)
    if min_file_size_bytes < 0:
        return fail("最小文件大小必须是非负整数", status_code=400)
    try:
        folder = import_http_store.create_monitor_folder(
            db,
            {
                "id": f"py_{time_ns()}",
                "name": payload.get("name") or Path(root_path).name or "监控文件夹",
                "rootPath": root_path,
                "shelfId": None,
                "enabled": bool(payload.get("enabled", True)),
                "ignorePatterns": payload.get("ignorePatterns"),
                "ignoreHidden": bool(payload.get("ignoreHidden", True)),
                "minFileSizeBytes": min_file_size_bytes,
                "description": payload.get("description"),
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
    except IntegrityError:
        db.rollback()
        return fail("监控文件夹路径已存在", status_code=409, details={"rootPath": root_path})
    _record_system_event(db, level="info", source="folder", actor_type="admin", actor_id=user.id, action="created", target_type="monitorFolder", target_id=folder.get("id"), message=f"新增来源目录：{folder.get('name')}", metadata={"rootPath": root_path})
    return ok({"folder": folder}, status_code=201)


@router.put("/monitor-folders/{folder_id}")
@router.patch("/monitor-folders/{folder_id}")
async def update_monitor_folder(folder_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    if payload.get("shelfId"):
        return fail(
            "监控文件夹不再绑定全局书架，请创建个人来源文件夹智能书架",
            status_code=400,
            code="MONITOR_FOLDER_SHELF_RETIRED",
        )
    mapping = {"rootPath": "rootPath", "minFileSizeBytes": "minFileSizeBytes", "ignorePatterns": "ignorePatterns", "ignoreHidden": "ignoreHidden", "enabled": "enabled", "name": "name", "description": "description"}
    values = {mapping[key]: value for key, value in payload.items() if key in mapping}
    existing = import_http_store.get_monitor_folder(db, folder_id)
    if not existing:
        return fail("监控文件夹不存在", status_code=404)
    if "rootPath" in values:
        root_path = _normalize_monitor_root_path(values["rootPath"])
        if not root_path:
            return fail("请填写监控文件夹路径", status_code=400)
        if _monitor_folder_by_root_path(db, root_path, exclude_id=folder_id):
            return fail("监控文件夹路径已存在", status_code=409, details={"rootPath": root_path})
        values["rootPath"] = root_path
    if "minFileSizeBytes" in values:
        try:
            values["minFileSizeBytes"] = int(values["minFileSizeBytes"])
        except (TypeError, ValueError):
            return fail("最小文件大小必须是非负整数", status_code=400)
        if values["minFileSizeBytes"] < 0:
            return fail("最小文件大小必须是非负整数", status_code=400)
    if values:
        values["updatedAt"] = _now()
    try:
        folder = import_http_store.update_monitor_folder(db, folder_id, values)
    except IntegrityError:
        db.rollback()
        return fail("监控文件夹路径已存在", status_code=409, details={"rootPath": values.get("rootPath")})
    if values:
        _record_system_event(db, level="info", source="folder", actor_type="admin", actor_id=user.id, action="updated", target_type="monitorFolder", target_id=folder_id, message=f"更新来源目录：{(folder or existing).get('name')}", metadata={"changes": values, "rootPath": (folder or existing).get("rootPath")})
    return ok({"folder": folder})


@router.delete("/monitor-folders/{folder_id}")
def delete_monitor_folder(folder_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    existing = import_http_store.get_monitor_folder(db, folder_id)
    deleted, affected_user_ids = import_http_store.delete_monitor_folder(db, folder_id, updated_at=_now())
    db.commit()
    if deleted:
        _record_system_event(
            db,
            level="warning",
            source="folder",
            actor_type="admin",
            actor_id=user.id,
            action="deleted",
            target_type="monitorFolder",
            target_id=folder_id,
            message=f"删除来源目录：{(existing or {}).get('name') or folder_id}",
            metadata={
                "rootPath": (existing or {}).get("rootPath"),
                "authorizationInvalidatedFor": len(affected_user_ids),
            },
        )
    return ok({"deleted": deleted, "id": folder_id})


_SENSITIVE_SYSTEM_SETTING_KEYS = {
    "email.smtp.password",
    "metadata.bangumi.accessToken",
    "metadata.ai.apiKey",
}

_RETIRED_SYSTEM_SETTING_KEYS = {
    "systemName",
    "metadata.douban.mode",
    "metadata.douban.baseUrl",
    "metadata.douban.apiKey",
    "download.qbittorrent.url",
    "download.qbittorrent.username",
    "download.qbittorrent.password",
    "download.qbittorrent.category",
    "download.qbittorrent.savePath",
}


def _public_system_settings(values: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {f"{key}Configured": False for key in _SENSITIVE_SYSTEM_SETTING_KEYS}
    for key, value in values.items():
        if key in _RETIRED_SYSTEM_SETTING_KEYS:
            continue
        if key in _SENSITIVE_SYSTEM_SETTING_KEYS:
            public[f"{key}Configured"] = bool(str(value).strip()) if value is not None else False
        else:
            public[key] = value
    return public


@router.get("/app-config")
def get_public_app_config(db: Session = Depends(get_db)):
    return ok({
        "language": configured_locale(db),
        "supportedLocales": list(SUPPORTED_LOCALES),
    })


@router.get("/system-settings")
def get_system_settings(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    from app.bootstrap.system import list_settings

    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"settings": _public_system_settings(list_settings(db))})


@router.get("/metadata/providers")
def list_registered_metadata_providers(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"providers": list_metadata_providers(db), "pipelines": list_metadata_provider_pipelines(db)})


@router.put("/metadata/provider-pipelines/{work_type}")
async def update_registered_metadata_provider_pipeline(work_type: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    try:
        pipelines = update_metadata_provider_pipeline(db, work_type, items)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    _record_system_event(
        db,
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="metadata_provider_pipeline.updated",
        target_type="metadataProviderPipeline",
        target_id=work_type,
        message=f"更新{work_type}数据源组合",
        metadata={"providerIds": [item.get("providerId") for item in items]},
    )
    return ok({"pipelines": pipelines, "providers": list_metadata_providers(db)})


@router.get("/metadata/providers/{provider_id}")
def get_registered_metadata_provider(provider_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    provider = get_metadata_provider(db, provider_id)
    if not provider:
        return fail("元数据插件不存在", status_code=404)
    return ok({"provider": provider})


@router.patch("/metadata/providers/{provider_id}")
@router.put("/metadata/providers/{provider_id}")
async def update_registered_metadata_provider(provider_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    if not isinstance(payload, dict):
        return fail("插件配置格式不正确", status_code=400)
    try:
        provider = update_metadata_provider(db, provider_id, payload)
    except ValueError as exc:
        return fail(str(exc), status_code=404 if "不存在" in str(exc) else 400)
    _record_system_event(
        db,
        level="warning",
        source="system",
        actor_type="admin",
        actor_id=user.id,
        action="metadata_provider.updated",
        target_type="metadataProvider",
        target_id=provider_id,
        message=f"更新元数据插件：{provider.get('name') or provider_id}",
        metadata={"enabled": provider.get("enabled"), "priority": provider.get("priority")},
    )
    return ok({"provider": provider})


@router.post("/metadata/providers/{provider_id}/test")
def test_registered_metadata_provider(provider_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result, provider = test_metadata_provider(db, provider_id)
    except ValueError as exc:
        return fail(str(exc), status_code=404 if "不存在" in str(exc) else 400)
    return ok({"result": result, "provider": provider})


@router.put("/system-settings")
@router.patch("/system-settings")
async def update_system_settings(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    values = payload.get("settings", {key: value for key, value in payload.items() if key != "clearSensitiveKeys"})
    requested_clear_keys = payload.get("clearSensitiveKeys", [])
    if not isinstance(values, dict):
        return fail("设置格式不正确", status_code=400)
    if not isinstance(requested_clear_keys, list):
        return fail("清除凭据格式不正确", status_code=400)
    if "language" in values:
        language = normalize_locale(values.get("language"), fallback=None)
        if language is None:
            return fail(
                "不支持的界面语言",
                status_code=400,
                code="INVALID_LOCALE",
                params={"supportedLocales": list(SUPPORTED_LOCALES)},
            )
        values = {**values, "language": language}
    unsupported_keys = sorted(str(key) for key in values if str(key) in _RETIRED_SYSTEM_SETTING_KEYS)
    if unsupported_keys:
        return fail("包含不支持修改的设置项", status_code=400, details={"keys": unsupported_keys})
    from app.bootstrap.system import delete_settings, upsert_setting

    clear_keys = {str(key) for key in requested_clear_keys if str(key) in _SENSITIVE_SYSTEM_SETTING_KEYS}
    saved = {}
    for raw_key, value in values.items():
        key = str(raw_key)
        if key in clear_keys:
            continue
        if key in _SENSITIVE_SYSTEM_SETTING_KEYS and (value is None or not str(value).strip()):
            continue
        if key == "workDetail.tabOrder":
            value = _normalize_detail_tab_order(value)
        if key in IMPORT_PREFERENCE_KEYS:
            value = normalize_import_setting_value(key, value)
        upsert_setting(db, key, value)
        saved[key] = value
    if clear_keys:
        delete_settings(db, clear_keys)
        for key in clear_keys:
            saved[key] = ""
    db.commit()
    _record_system_event(db, level="warning", source="system", actor_type="admin", actor_id=user.id, action="settings.updated", target_type="settings", message=f"更新系统设置 {len(saved)} 项", metadata={"keys": list(saved.keys())})
    return ok({"settings": _public_system_settings(saved)})


def _reader_v1_retired(replacement: str) -> Response:
    return fail(
        "READER_V1_RETIRED",
        status_code=410,
        details={"replacement": replacement},
    )


@router.get("/reader/preferences", status_code=410)
def list_reader_preferences():
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.put("/reader/preferences", status_code=410)
async def save_reader_preferences():
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.get("/reader/preferences/{reader_type}", status_code=410)
def get_reader_preference(reader_type: str):
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.put("/reader/preferences/{reader_type}", status_code=410)
@router.patch("/reader/preferences/{reader_type}", status_code=410)
async def save_reader_preference(reader_type: str):
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.get("/reader/{edition_id}/bootstrap", status_code=410)
def reader_bootstrap(edition_id: str):
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/bootstrap")


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


@router.get("/editions/{edition_id}/progress", status_code=410)
def get_progress(edition_id: str):
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/progress")


@router.post("/editions/{edition_id}/progress", status_code=410)
@router.put("/editions/{edition_id}/progress", status_code=410)
@router.patch("/editions/{edition_id}/progress", status_code=410)
async def save_progress(edition_id: str):
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/progress")


def _stored_path(path_value: str | None, settings: Settings) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = settings.resolved_storage_root / path
    try:
        resolved = path.expanduser().resolve()
        storage = settings.resolved_storage_root.resolve()
        if resolved == storage or storage in resolved.parents:
            return resolved
        monitor = settings.resolved_monitor_root
        if monitor:
            monitor = monitor.resolve()
            if resolved == monitor or monitor in resolved.parents:
                return resolved
    except OSError:
        return None
    return None


def _parse_byte_range(header: str | None, size: int) -> tuple[str, tuple[int, int] | None]:
    if not header:
        return "none", None
    match = re.match(r"^bytes=(\d*)-(\d*)$", header.strip())
    if not match:
        return "invalid", None
    raw_start, raw_end = match.groups()
    if not raw_start and not raw_end:
        return "invalid", None
    if size <= 0:
        return "unsatisfiable", None
    if not raw_start:
        try:
            suffix_length = int(raw_end)
        except ValueError:
            return "unsatisfiable", None
        if suffix_length <= 0:
            return "unsatisfiable", None
        return "range", (max(0, size - suffix_length), size - 1)
    try:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    except ValueError:
        return "unsatisfiable", None
    if start < 0 or end < start or start >= size:
        return "unsatisfiable", None
    return "range", (start, min(end, size - 1))


def _weak_etag(size: int, mtime_ms: int, extra: str = "") -> str:
    suffix = f"-{extra.encode('utf-8').hex()}" if extra else ""
    return f'W/"{size:x}-{mtime_ms:x}{suffix}"'


def _not_modified(request: Request, etag: str, last_modified: str) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        tags = [tag.strip() for tag in if_none_match.split(",")]
        return "*" in tags or etag in tags
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        try:
            since = parsedate_to_datetime(if_modified_since)
            modified = parsedate_to_datetime(last_modified)
            return modified <= since
        except (TypeError, ValueError):
            return False
    return False


def _should_use_range(request: Request, etag: str, last_modified: str) -> bool:
    if_range = request.headers.get("if-range")
    if not if_range:
        return True
    if if_range.startswith("W/"):
        # RFC 9110 requires strong comparison for an entity-tag in If-Range.
        return False
    if if_range.startswith('"'):
        return not etag.startswith("W/") and if_range == etag
    try:
        if_range_date = parsedate_to_datetime(if_range)
        modified = parsedate_to_datetime(last_modified)
        return modified <= if_range_date
    except (TypeError, ValueError):
        return False


def _response_headers(size: int, mtime: float, media_type: str, name: str, extra: str = "") -> dict[str, str]:
    modified = datetime.fromtimestamp(mtime, timezone.utc).replace(microsecond=0)
    return {
        "Accept-Ranges": "bytes",
        "Content-Type": media_type,
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "private, max-age=86400" if media_type.lower().startswith("image/") else "private, max-age=60",
        "Vary": "Cookie",
        "ETag": _weak_etag(size, int(mtime * 1000), extra),
        "Last-Modified": format_datetime(modified, usegmt=True),
    }


def _bytes_response(data: bytes, request: Request, media_type: str, name: str, mtime: float | None = None, extra: str = "") -> Response:
    started_at = monotonic()
    size = len(data)
    user_id = str(getattr(request.state, "user_id", "") or "")
    cache_identity = f"{extra}|user:{user_id}" if user_id else extra
    headers = _response_headers(size, mtime or _now().timestamp(), media_type, name, cache_identity)
    if not request.headers.get("range") and _not_modified(request, headers["ETag"], headers["Last-Modified"]):
        return Response(status_code=304, headers=headers)
    range_header = request.headers.get("range")
    byte_range = None
    if range_header and _should_use_range(request, headers["ETag"], headers["Last-Modified"]):
        kind, parsed = _parse_byte_range(range_header, size)
        if kind == "invalid":
            response = fail("Range 请求格式不正确", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        if kind == "unsatisfiable":
            response = fail("Range 超出文件大小", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        byte_range = parsed
    if byte_range:
        start, end = byte_range
        body = data[start : end + 1]
        headers["Content-Length"] = str(len(body))
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        _log_slow_file_request(request, "bytes", "memory", request.headers.get("range"), len(body), 206, started_at)
        return Response(content=body, status_code=206, headers=headers, media_type=media_type)
    headers["Content-Length"] = str(size)
    _log_slow_file_request(request, "bytes", "memory", request.headers.get("range"), size, 200, started_at)
    return Response(content=data, headers=headers, media_type=media_type)


def _base_media_type(media_type: str | None) -> str:
    return (media_type or "").split(";", 1)[0].strip().lower()


def _comic_page_image_variant(request: Request) -> str:
    value = (request.query_params.get("imageVariant") or request.query_params.get("image_variant") or "").strip().lower()
    return COMIC_PAGE_DATA_SAVER_VARIANT if value in {COMIC_PAGE_DATA_SAVER_VARIANT, "saver", "compressed", "webp", "avif"} else COMIC_PAGE_ORIGINAL_VARIANT


def _is_comic_page_image(media_type: str | None) -> bool:
    return _base_media_type(media_type).startswith("image/")


def _comic_page_cache_path(settings: Settings, cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return settings.resolved_storage_root / "cache" / "comic-pages" / digest[:2] / f"{digest}.avif"


def _write_cache_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{time_ns()}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _small_cover_cache_key(path: Path, stat: os.stat_result) -> str:
    return (
        f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"small-cover-v{SMALL_COVER_CACHE_VERSION}:"
        f"max-{SMALL_COVER_MAX_DIMENSION}:bytes-{SMALL_COVER_MAX_BYTES}"
    )


def _small_cover_cache_path(settings: Settings, cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return settings.resolved_storage_root / "cache" / "covers" / digest[:2] / f"{digest}.webp"


def _image_has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)


def _image_for_webp(image: Image.Image) -> Image.Image:
    if image.mode in {"RGB", "RGBA"}:
        return image
    return image.convert("RGBA" if _image_has_alpha(image) else "RGB")


def _small_cover_webp_bytes(path: Path) -> bytes | None:
    try:
        with Image.open(path) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            prepared = _image_for_webp(ImageOps.exif_transpose(source))
            prepared.thumbnail(
                (SMALL_COVER_MAX_DIMENSION, SMALL_COVER_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            while True:
                for quality in SMALL_COVER_QUALITIES:
                    output = io.BytesIO()
                    prepared.save(output, format="WEBP", quality=quality, method=6)
                    data = output.getvalue()
                    if len(data) <= SMALL_COVER_MAX_BYTES:
                        return data
                width, height = prepared.size
                next_size = (
                    max(1, int(width * 0.85)),
                    max(1, int(height * 0.85)),
                )
                if next_size == prepared.size:
                    return None
                prepared = prepared.resize(next_size, Image.Resampling.LANCZOS)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        logger.debug("failed to create small cover image path=%s error=%s", path, exc)
        return None


def _small_cover_response(path: Path, request: Request, user_id: str, settings: Settings) -> Response | None:
    stat = path.stat()
    cache_key = _small_cover_cache_key(path, stat)
    cache_path = _small_cover_cache_path(settings, cache_key)
    data = cache_path.read_bytes() if cache_path.is_file() else None
    if data is None or len(data) > SMALL_COVER_MAX_BYTES:
        data = _small_cover_webp_bytes(path)
        if data is None:
            return None
        _write_cache_bytes(cache_path, data)
    request.state.user_id = user_id
    cache_identity = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    return _bytes_response(
        data,
        request,
        SMALL_COVER_MEDIA_TYPE,
        str(path.with_suffix(".webp").name),
        mtime=stat.st_mtime,
        extra=f"small-cover-{cache_identity}",
    )


def _comic_page_avif_image(image: Image.Image) -> Image.Image:
    prepared = ImageOps.exif_transpose(image)
    if prepared.mode == "RGB":
        red, green, blue = prepared.split()
        if ImageChops.difference(red, green).getbbox() is None and ImageChops.difference(red, blue).getbbox() is None:
            return red
        return prepared
    if prepared.mode in {"L", "RGBA"}:
        return prepared
    return prepared.convert("RGBA" if _image_has_alpha(prepared) else "RGB")


def _comic_page_avif_bytes(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if getattr(source, "is_animated", False):
                return None
            image = _comic_page_avif_image(source)
            output = io.BytesIO()
            image.save(
                output,
                format="AVIF",
                quality=COMIC_PAGE_DATA_SAVER_QUALITY,
                speed=COMIC_PAGE_DATA_SAVER_SPEED,
            )
            optimized = output.getvalue()
            return optimized if len(optimized) < len(data) else None
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        logger.debug("skipping comic page data-saver image variant: %s", exc)
        return None


def _avif_page_name(name: str) -> str:
    return str(Path(name or "page").with_suffix(".avif"))


def _comic_page_avif_response(data: bytes, request: Request, name: str, source_mtime: float, source_size: int, cache_extra: str) -> Response:
    variant_extra = hashlib.sha256(cache_extra.encode("utf-8")).hexdigest()[:24]
    response = _bytes_response(
        data,
        request,
        COMIC_PAGE_DATA_SAVER_MEDIA_TYPE,
        _avif_page_name(name),
        mtime=source_mtime,
        extra=f"extreme-avif-v{COMIC_PAGE_DATA_SAVER_CACHE_VERSION}-{variant_extra}",
    )
    response.headers["X-Comic-Image-Variant"] = COMIC_PAGE_DATA_SAVER_VARIANT
    response.headers["X-Comic-Image-Quality"] = (
        f"avif;q={COMIC_PAGE_DATA_SAVER_QUALITY};"
        f"speed={COMIC_PAGE_DATA_SAVER_SPEED};mode=extreme"
    )
    if source_size > 0:
        response.headers["X-Comic-Image-Compression-Ratio"] = f"{len(data) / source_size:.3f}"
    return response


def _file_stream_limit_response() -> Response:
    return fail("同时文件流请求过多，请稍后重试", status_code=429)


def _acquire_file_stream_slot(user_id: str):
    limit = STREAMS_PER_USER_LIMIT
    if limit is None:
        limit = get_settings().file_streams_per_user_limit
    if limit <= 0:
        return lambda: None
    with _active_file_streams_lock:
        current = _active_file_streams_by_user.get(user_id, 0)
        if current >= limit:
            return None
        _active_file_streams_by_user[user_id] = current + 1

    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        with _active_file_streams_lock:
            next_count = max(0, _active_file_streams_by_user.get(user_id, 1) - 1)
            if next_count == 0:
                _active_file_streams_by_user.pop(user_id, None)
            else:
                _active_file_streams_by_user[user_id] = next_count

    return release


def _log_slow_file_request(request: Request, route: str, file_id: str, range_header: str | None, bytes_sent: int, status_code: int, started_at: float) -> None:
    threshold_ms = SLOW_REQUEST_LOG_THRESHOLD_MS
    duration_ms = int((monotonic() - started_at) * 1000)
    if duration_ms < threshold_ms:
        return
    logger.warning(
        "[slow-file-request] route=%s userId=%s fileId=%s range=%s bytes=%s status=%s durationMs=%s",
        route,
        getattr(request.state, "user_id", "unknown"),
        file_id,
        range_header,
        bytes_sent,
        status_code,
        duration_ms,
    )


def _file_response(path: Path | None, request: Request, user_id: str, media_type: str | None = None, name: str | None = None, missing_message: str = "文件不存在", route: str = "file", file_id: str | None = None) -> Response:
    if path is None or not path.exists() or not path.is_file():
        return fail(missing_message, status_code=404)
    request.state.user_id = user_id
    stat = path.stat()
    resolved_media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = _response_headers(
        stat.st_size,
        stat.st_mtime,
        resolved_media_type,
        name or path.name,
        extra=f"user:{user_id}",
    )
    if not request.headers.get("range") and _not_modified(request, headers["ETag"], headers["Last-Modified"]):
        return Response(status_code=304, headers=headers)
    byte_range = None
    range_header = request.headers.get("range")
    if range_header and _should_use_range(request, headers["ETag"], headers["Last-Modified"]):
        kind, parsed = _parse_byte_range(range_header, stat.st_size)
        if kind == "invalid":
            response = fail("Range 请求格式不正确", status_code=416)
            response.headers["Content-Range"] = f"bytes */{stat.st_size}"
            return response
        if kind == "unsatisfiable":
            response = fail("Range 超出文件大小", status_code=416)
            response.headers["Content-Range"] = f"bytes */{stat.st_size}"
            return response
        byte_range = parsed

    # Metadata probes from HTMLAudioElement and proxies frequently use HEAD.
    # Return exactly the GET headers/status without consuming a stream slot or
    # opening a multi-gigabyte audio file.
    if request.method == "HEAD":
        if byte_range:
            start, end = byte_range
            headers["Content-Length"] = str(end - start + 1)
            headers["Content-Range"] = f"bytes {start}-{end}/{stat.st_size}"
            return Response(status_code=206, headers=headers, media_type=resolved_media_type)
        headers["Content-Length"] = str(stat.st_size)
        return Response(status_code=200, headers=headers, media_type=resolved_media_type)

    def iterator(release, started_at: float, status_code: int, bytes_sent: int, start: int = 0, end: int | None = None):
        try:
            remaining = None if end is None else end - start + 1
            with path.open("rb") as handle:
                handle.seek(start)
                while True:
                    chunk_size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
                    if chunk_size <= 0:
                        break
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    if remaining is not None:
                        remaining -= len(chunk)
                    yield chunk
        finally:
            release()
            _log_slow_file_request(request, route, file_id or str(path), range_header, bytes_sent, status_code, started_at)

    release = _acquire_file_stream_slot(user_id)
    if release is None:
        return _file_stream_limit_response()
    started_at = monotonic()
    if byte_range:
        start, end = byte_range
        bytes_sent = end - start + 1
        headers["Content-Length"] = str(bytes_sent)
        headers["Content-Range"] = f"bytes {start}-{end}/{stat.st_size}"
        return StreamingResponse(iterator(release, started_at, 206, bytes_sent, start, end), status_code=206, headers=headers, media_type=resolved_media_type)
    headers["Content-Length"] = str(stat.st_size)
    return StreamingResponse(iterator(release, started_at, 200, stat.st_size), headers=headers, media_type=resolved_media_type)


def _send_file(path: Path | None, request: Request, user_id: str, media_type: str | None = None, name: str | None = None, route: str = "file", file_id: str | None = None) -> Response:
    return _file_response(path, request, user_id=user_id, media_type=media_type, name=name, route=route, file_id=file_id)


def _send_zip_entry(archive_path: Path | None, entry_name: str | None, request: Request, user_id: str, media_type: str | None = None, route: str = "zip-entry", file_id: str | None = None) -> Response:
    if archive_path is None or not archive_path.exists() or not archive_path.is_file() or not entry_name:
        return fail("页面不存在", status_code=404)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            info = archive.getinfo(entry_name)
    except (KeyError, OSError, zipfile.BadZipFile):
        return fail("页面不存在", status_code=404)
    request.state.user_id = user_id
    resolved_media_type = media_type or mimetypes.guess_type(entry_name)[0] or "application/octet-stream"
    size = int(info.file_size)
    headers = _response_headers(
        size,
        archive_path.stat().st_mtime,
        resolved_media_type,
        Path(entry_name).name,
        extra=f"{entry_name}|user:{user_id}",
    )
    if not request.headers.get("range") and _not_modified(request, headers["ETag"], headers["Last-Modified"]):
        return Response(status_code=304, headers=headers)
    byte_range = None
    range_header = request.headers.get("range")
    if range_header and _should_use_range(request, headers["ETag"], headers["Last-Modified"]):
        kind, parsed = _parse_byte_range(range_header, size)
        if kind == "invalid":
            response = fail("Range 请求格式不正确", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        if kind == "unsatisfiable":
            response = fail("Range 超出文件大小", status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        byte_range = parsed

    def iterator(release, started_at: float, status_code: int, bytes_sent: int, start: int = 0, end: int | None = None):
        try:
            with zipfile.ZipFile(archive_path) as archive:
                with archive.open(entry_name, "r") as handle:
                    remaining_skip = start
                    while remaining_skip > 0:
                        skipped = handle.read(min(1024 * 1024, remaining_skip))
                        if not skipped:
                            return
                        remaining_skip -= len(skipped)
                    remaining = None if end is None else end - start + 1
                    while True:
                        chunk_size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
                        if chunk_size <= 0:
                            break
                        chunk = handle.read(chunk_size)
                        if not chunk:
                            break
                        if remaining is not None:
                            remaining -= len(chunk)
                        yield chunk
        finally:
            release()
            _log_slow_file_request(request, route, file_id or entry_name, range_header, bytes_sent, status_code, started_at)

    release = _acquire_file_stream_slot(user_id)
    if release is None:
        return _file_stream_limit_response()
    started_at = monotonic()
    if byte_range:
        start, end = byte_range
        bytes_sent = end - start + 1
        headers["Content-Length"] = str(bytes_sent)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(iterator(release, started_at, 206, bytes_sent, start, end), status_code=206, headers=headers, media_type=resolved_media_type)
    headers["Content-Length"] = str(size)
    return StreamingResponse(iterator(release, started_at, 200, size), headers=headers, media_type=resolved_media_type)


def _with_comic_page_variant_header(response: Response, variant: str) -> Response:
    response.headers["X-Comic-Image-Variant"] = variant
    return response


def _send_original_comic_page_file(path: Path | None, request: Request, user_id: str, media_type: str | None = None, route: str = "volume-page", file_id: str | None = None) -> Response:
    return _with_comic_page_variant_header(
        _send_file(path, request, user_id, media_type=media_type, route=route, file_id=file_id),
        COMIC_PAGE_ORIGINAL_VARIANT,
    )


def _send_original_comic_page_zip_entry(archive_path: Path | None, entry_name: str | None, request: Request, user_id: str, media_type: str | None = None, route: str = "volume-page-zip", file_id: str | None = None) -> Response:
    return _with_comic_page_variant_header(
        _send_zip_entry(archive_path, entry_name, request, user_id, media_type=media_type, route=route, file_id=file_id),
        COMIC_PAGE_ORIGINAL_VARIANT,
    )


def _send_comic_page_file(path: Path | None, request: Request, user_id: str, settings: Settings, media_type: str | None = None, route: str = "volume-page", file_id: str | None = None) -> Response:
    variant = _comic_page_image_variant(request)
    if path is None or not path.exists() or not path.is_file():
        return fail("文件不存在", status_code=404)
    resolved_media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if variant != COMIC_PAGE_DATA_SAVER_VARIANT or not _is_comic_page_image(resolved_media_type):
        return _send_original_comic_page_file(path, request, user_id, media_type=resolved_media_type, route=route, file_id=file_id)

    request.state.user_id = user_id
    stat = path.stat()
    cache_key = (
        f"file:{path}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"extreme-avif-v{COMIC_PAGE_DATA_SAVER_CACHE_VERSION}:"
        f"q-{COMIC_PAGE_DATA_SAVER_QUALITY}:"
        f"speed-{COMIC_PAGE_DATA_SAVER_SPEED}"
    )
    cache_path = _comic_page_cache_path(settings, cache_key)
    if cache_path.exists() and cache_path.is_file():
        return _comic_page_avif_response(cache_path.read_bytes(), request, path.name, stat.st_mtime, stat.st_size, cache_key)
    try:
        source = path.read_bytes()
    except OSError:
        return fail("文件不存在", status_code=404)
    optimized = _comic_page_avif_bytes(source)
    if optimized is None:
        return _send_original_comic_page_file(path, request, user_id, media_type=resolved_media_type, route=route, file_id=file_id)
    _write_cache_bytes(cache_path, optimized)
    return _comic_page_avif_response(optimized, request, path.name, stat.st_mtime, len(source), cache_key)


def _send_comic_page_zip_entry(archive_path: Path | None, entry_name: str | None, request: Request, user_id: str, settings: Settings, media_type: str | None = None, route: str = "volume-page-zip", file_id: str | None = None) -> Response:
    variant = _comic_page_image_variant(request)
    if archive_path is None or not archive_path.exists() or not archive_path.is_file() or not entry_name:
        return fail("页面不存在", status_code=404)
    if variant != COMIC_PAGE_DATA_SAVER_VARIANT:
        return _send_original_comic_page_zip_entry(archive_path, entry_name, request, user_id, media_type=media_type, route=route, file_id=file_id)

    try:
        with zipfile.ZipFile(archive_path) as archive:
            info = archive.getinfo(entry_name)
            resolved_media_type = media_type or mimetypes.guess_type(entry_name)[0] or "application/octet-stream"
            if not _is_comic_page_image(resolved_media_type):
                return _send_original_comic_page_zip_entry(archive_path, entry_name, request, user_id, media_type=resolved_media_type, route=route, file_id=file_id)
            archive_stat = archive_path.stat()
            cache_key = (
                f"zip:{archive_path}:{archive_stat.st_size}:{archive_stat.st_mtime_ns}:"
                f"{entry_name}:{info.file_size}:{info.CRC}:"
                f"extreme-avif-v{COMIC_PAGE_DATA_SAVER_CACHE_VERSION}:"
                f"q-{COMIC_PAGE_DATA_SAVER_QUALITY}:"
                f"speed-{COMIC_PAGE_DATA_SAVER_SPEED}"
            )
            cache_path = _comic_page_cache_path(settings, cache_key)
            if cache_path.exists() and cache_path.is_file():
                return _comic_page_avif_response(cache_path.read_bytes(), request, Path(entry_name).name, archive_stat.st_mtime, info.file_size, cache_key)
            source = archive.read(entry_name)
    except (KeyError, OSError, zipfile.BadZipFile):
        return fail("页面不存在", status_code=404)

    optimized = _comic_page_avif_bytes(source)
    if optimized is None:
        return _send_original_comic_page_zip_entry(archive_path, entry_name, request, user_id, media_type=resolved_media_type, route=route, file_id=file_id)
    _write_cache_bytes(cache_path, optimized)
    return _comic_page_avif_response(optimized, request, Path(entry_name).name, archive_stat.st_mtime, len(source), cache_key)


@router.get("/files/{file_id}")
@router.head("/files/{file_id}")
def get_file(file_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_file(db, user, file_id):
        return fail("文件不存在", status_code=404, code="FILE_NOT_FOUND")
    file = library_storage.get_file(db, file_id)
    return _send_file(_stored_path((file or {}).get("path"), settings), request, user.id, media_type=(file or {}).get("mimeType"), name=Path((file or {}).get("path") or "file").name, route="files", file_id=file_id)


@router.get("/editions/{edition_id}/file")
def get_edition_file(edition_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_edition(db, user, edition_id):
        return fail("版本不存在", status_code=404, code="EDITION_NOT_FOUND")
    volume_id = request.query_params.get("volume")
    if volume_id and not can_access_volume(db, user, volume_id):
        return fail("版本不存在", status_code=404, code="EDITION_NOT_FOUND")
    if volume_id and _has_table(db, "LibraryFile"):
        file = library_storage.first_file_for_edition(
            db,
            edition_id=edition_id,
            volume_id=volume_id,
        )
    else:
        file = None
    file = file or library_storage.first_file_for_edition(
        db,
        edition_id=edition_id,
    )
    return _send_file(_stored_path((file or {}).get("path"), settings), request, user.id, media_type=(file or {}).get("mimeType"), name=Path((file or {}).get("path") or "file").name, route="edition-file", file_id=(file or {}).get("id") or edition_id)


@router.get("/works/{work_id}/cover")
@router.get("/editions/{edition_id}/cover")
@router.get("/volumes/{volume_id}/cover")
def get_cover(request: Request, work_id: str | None = None, edition_id: str | None = None, volume_id: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if work_id and not can_access_work(db, user, work_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    if edition_id and not can_access_edition(db, user, edition_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    if volume_id and not can_access_volume(db, user, volume_id):
        return fail("条目不存在", status_code=404, code="COVER_NOT_FOUND")
    row = None
    table = None
    row_id = None
    if work_id and _has_table(db, "LibraryWork"):
        table, row_id = "LibraryWork", work_id
        row = library_storage.get_cover_record(db, work_id=work_id)
    elif edition_id and _has_table(db, "LibraryEdition"):
        table, row_id = "LibraryEdition", edition_id
        row = library_storage.get_cover_record(db, edition_id=edition_id)
    elif volume_id and _has_table(db, "LibraryVolume"):
        table, row_id = "LibraryVolume", volume_id
        row = library_storage.get_cover_record(db, volume_id=volume_id)
    cover_id = work_id or edition_id or volume_id or "cover"
    if row is None:
        return fail("条目不存在", status_code=404)
    cover_path = _stored_path(row.get("coverPath"), settings)
    if cover_path is None or not cover_path.is_file() or is_default_cover_path(row.get("coverPath"), settings):
        stored_default = ensure_default_cover(settings)
        if row.get("coverPath") != stored_default:
            library_storage.update_cover_record(
                db,
                record_type=str(table),
                record_id=str(row_id),
                cover_path=stored_default,
                cover_status=(
                    cover_status(stored_default, settings)
                    if table != "LibraryVolume"
                    else None
                ),
                now=_now(),
            )
            db.commit()
        cover_path = _stored_path(stored_default, settings)
    if request.query_params.get("size") == "small" and cover_path is not None:
        response = _small_cover_response(cover_path, request, user.id, settings)
        if response is not None:
            return response
        default_path = _stored_path(ensure_default_cover(settings), settings)
        if default_path is not None and default_path != cover_path:
            response = _small_cover_response(default_path, request, user.id, settings)
            if response is not None:
                return response
    return _send_file(cover_path, request, user.id, route="cover", file_id=cover_id)


@router.get("/metadata/cover-proxy")
def metadata_cover_proxy(url: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not url.startswith(("http://", "https://")):
        return fail("封面地址不支持", status_code=400)
    remote_request = UrlRequest(url, headers={"Accept": "image/*,*/*", "User-Agent": "Shuku Starship Python", "Referer": "https://book.douban.com/"})
    try:
        with urlopen(remote_request, timeout=20) as remote_response:
            content_type = remote_response.headers.get("content-type") or "image/jpeg"
            if not content_type.lower().startswith("image/"):
                return fail("远程地址不是图片", status_code=400)
            data = remote_response.read(8 * 1024 * 1024)
    except Exception as exc:
        logger.warning("failed to proxy metadata cover url=%s error=%s", url, exc)
        return fail("封面预览加载失败", status_code=502)
    return Response(data, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})


def _preferred_work_cover_path(db: Session, work_id: str) -> str | None:
    return library_storage.preferred_work_cover_path(db, work_id)


@router.post("/works/{work_id}/cover/upload")
async def upload_cover(work_id: str, request: Request, cover: UploadFile = File(...), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    target_dir = settings.resolved_storage_root / "covers"
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(cover.filename or "cover.jpg").suffix or ".jpg"
    target = target_dir / f"{work_id}{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(cover.file, handle)
    relative = str(target.relative_to(settings.resolved_storage_root))
    library_storage.update_work_cover(
        db,
        work_id=work_id,
        cover_path=relative,
        cover_status="READY",
        now=_now(),
    )
    db.commit()
    return ok({"bookId": work_id, "coverUrl": f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}"})


@router.post("/works/{work_id}/cover/regenerate")
def regenerate_cover(work_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    work = _get_work(db, work_id)
    if not work:
        return fail("作品不存在", status_code=404)
    cover_path = _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings)
    if _stored_path(cover_path, settings) is None or not _stored_path(cover_path, settings).is_file():
        cover_path = ensure_default_cover(settings)
    library_storage.update_work_cover(
        db,
        work_id=work_id,
        cover_path=cover_path,
        cover_status=cover_status(cover_path, settings),
        now=_now(),
    )
    db.commit()
    return ok({"bookId": work_id, "coverUrl": f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}"})


@router.get("/volumes/{volume_id}/pages")
def list_volume_pages(volume_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("页面不存在", status_code=404, code="VOLUME_NOT_FOUND")
    units = media_page_index.list_page_units_for_volume(db, volume_id)
    if not units:
        media_page_index.ensure_volume_page_index(db, settings, volume_id)
        units = media_page_index.list_page_units_for_volume(db, volume_id)
    return ok({"pages": units, "total": len(units)})


@router.get("/volumes/{volume_id}/pages/{page_index}")
def get_volume_page(volume_id: str, page_index: int, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("页面不存在", status_code=404, code="VOLUME_NOT_FOUND")
    unit = media_page_index.get_page_unit(db, volume_id, page_index)
    if not unit:
        media_page_index.ensure_volume_page_index(db, settings, volume_id)
        unit = media_page_index.get_page_unit(db, volume_id, page_index)
        if not unit:
            return fail("页面不存在", status_code=404)
    file = media_page_index.get_library_file(db, unit.get("fileId")) if unit.get("fileId") else None
    if file and file.get("kind") == "COMIC":
        metadata = _parse_json(unit.get("metadataJson"), {})
        entry_name = metadata.get("zipEntryName") or unit.get("href")
        return _send_comic_page_zip_entry(_stored_path(file.get("path"), settings), entry_name, request, user.id, settings, unit.get("mediaType"), route="volume-page-zip", file_id=unit.get("id") or f"{volume_id}:{page_index}")
    return _send_comic_page_file(_stored_path(unit.get("href"), settings), request, user.id, settings, media_type=unit.get("mediaType"), route="volume-page", file_id=unit.get("id") or f"{volume_id}:{page_index}")


def _organize_job_view(
    db: Session,
    job: dict[str, Any],
    user_id: str | None,
    pending_only: bool = False,
    *,
    lookup: dict[str, Any] | None = None,
    executions: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    work = _get_work(db, str(job.get("workId") or ""))
    if not work:
        return None
    if lookup is None:
        lookup = organize_job_queries.latest_lookup_rows_by_job(
            db, [str(job.get("id") or "")]
        ).get(str(job.get("id") or ""))
    if executions is None:
        executions = organize_job_queries.execution_rows_by_job(
            db, [str(job.get("id") or "")]
        ).get(str(job.get("id") or ""), [])
    raw_status = str(job.get("status") or "REVIEWING").upper()
    lookup_status = str((lookup or {}).get("status") or "").upper()
    if raw_status in {"APPLIED", "COMPLETED"}:
        status_category = "SUCCESS"
    elif raw_status in {"FAILED", "REVIEWING", "DISMISSED", "CANCELLED"}:
        status_category = "FAILED"
    elif raw_status == "RUNNING" or lookup_status == "RUNNING":
        status_category = "RECOGNIZING"
    else:
        status_category = "WAITING"
    provider_order = _parse_json((lookup or {}).get("providerOrder"), [])
    if not isinstance(provider_order, list):
        provider_order = []
    metadata_sources: list[str] = []
    for source in [
        (lookup or {}).get("resultSource"),
        *[execution.get("providerId") for execution in executions],
        *provider_order,
    ]:
        normalized_source = str(source or "").strip()
        if normalized_source and normalized_source not in metadata_sources:
            metadata_sources.append(normalized_source)
    return {
        "id": job.get("id"),
        "runId": job.get("runId"),
        "trigger": job.get("trigger") or "LEGACY",
        "status": raw_status,
        "statusCategory": status_category,
        "issueCodes": _parse_json(job.get("issueCodes"), []),
        "reasonCodes": _parse_json(job.get("reasonCodes"), []),
        "summary": job.get("summary"),
        "errorSummary": job.get("errorSummary"),
        "metadataLookupStatus": (lookup or {}).get("status"),
        "metadataLookupSource": (lookup or {}).get("resultSource"),
        "metadataLookupProviders": provider_order,
        "metadataSources": metadata_sources,
        "metadataLookupError": (lookup or {}).get("errorSummary"),
        "providerExecutions": executions,
        "startedAt": _dt(job.get("startedAt")),
        "finishedAt": _dt(job.get("finishedAt")),
        "createdAt": _dt(job.get("createdAt")),
        "updatedAt": _dt(job.get("updatedAt")),
        "book": _work_view(db, work, user_id),
    }


def _friendly_import_error(message: str | None, error_code: str | None = None) -> str | None:
    text_value = message or ""
    code = (error_code or "").upper()
    if code == "SOURCE_NOT_FOUND":
        return "文件不存在：可能已被移动、删除，或监控目录配置已变化。"
    if code == "IMPORT_WORKER_FAILED":
        return "导入工作进程意外中断，本次任务已经结束，可以稍后重试。"
    if code == "CONVERTER_UNAVAILABLE":
        return "转换服务暂时不可用，请检查 libmobi 是否已安装后重试。"
    if code == "DRM_PROTECTED":
        return "文件可能受 DRM 保护，无法自动转换。原文件已保留。"
    if code == "TEXT_ENCODING_UNCERTAIN":
        return "无法可靠识别 TXT 编码。原文件已保留，可在后续高级模式中手动指定。"
    if code == "CONVERSION_TIMEOUT":
        return "自动转换超时。原文件已保留，可以稍后重试。"
    if code == "INVALID_EPUB_OUTPUT":
        return "转换结果未通过 EPUB 完整性检查。原文件已保留，可以重试。"
    if code == "EPUB_NORMALIZATION_FAILED":
        return "转换结果无法在保留章节锚点和链接的前提下安全拆分。原文件已保留，可以重试。"
    if re.search(r"EACCES|permission|权限", text_value, re.I):
        return "权限不足：请确认容器用户可以读取该目录和文件。"
    if re.search(r"ENOENT|not found|不存在", text_value, re.I):
        return "文件不存在：可能已被移动、删除，或监控目录配置已变化。"
    if re.search(r"unsupported|format|格式", text_value, re.I):
        return "格式暂不支持：请确认文件属于当前支持的图书格式。"
    if re.search(r"zip|archive|corrupt|invalid|损坏", text_value, re.I):
        return "压缩包可能损坏：请重新复制文件或用本地工具测试压缩包。"
    return "导入失败：请检查文件完整性和格式。" if text_value else None


def _display_path_name(value: Any) -> str:
    text_value = str(value or "")
    parts = [part for part in re.split(r"[\\/]+", text_value) if part]
    return parts[-1] if parts else text_value


def _serialize_import_log(log: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": log.get("id"),
        "level": log.get("level") or "info",
        "message": log.get("message") or "",
        "createdAt": _dt(log.get("createdAt")),
    }


def _import_task_view(db: Session, task: dict[str, Any], log_limit: int = 20) -> dict[str, Any]:
    monitor_folder = None
    if task.get("monitorFolderId") and _has_table(db, "MonitorFolder"):
        monitor_folder = import_http_store.get_monitor_folder(db, str(task.get("monitorFolderId")))
    book = None
    if task.get("workId") and _has_table(db, "LibraryWork"):
        work = library_works.get_work(db, str(task.get("workId")))
        if work:
            book = {"id": work.get("id"), "title": work.get("title") or "未命名作品"}
    logs = import_http_store.list_import_logs(db, str(task.get("id") or ""), limit=log_limit)[0]
    conversion = (
        import_http_store.get_conversion_for_import(db, str(task.get("id") or ""))
        if _has_table(db, "BookConversionTask")
        else None
    )
    source_file_exists = Path(str(task.get("sourcePath") or "")).is_file()
    converted_file_exists = bool(conversion and conversion.get("outputPath") and Path(str(conversion.get("outputPath"))).is_file())
    if conversion:
        conversion = {
            **conversion,
            "sourcePath": _display_path_name(conversion.get("sourcePath")),
            "outputPath": _display_path_name(conversion.get("outputPath")),
            "options": _parse_json(conversion.get("optionsJson"), {}),
            "startedAt": _dt(conversion.get("startedAt")),
            "finishedAt": _dt(conversion.get("finishedAt")),
            "createdAt": _dt(conversion.get("createdAt")),
            "updatedAt": _dt(conversion.get("updatedAt")),
            "retryable": bool(conversion.get("retryable")),
        }
        conversion.pop("optionsJson", None)
    view = dict(task)
    view.update(
        {
            "sourcePath": _display_path_name(task.get("sourcePath")),
            "sourceFileExists": source_file_exists,
            "convertedFileExists": converted_file_exists,
            "progress": task.get("progress") or 0,
            "friendlyError": _friendly_import_error(task.get("errorSummary"), task.get("errorCode")),
            "retryable": bool(task.get("retryable")),
            "createdAt": _dt(task.get("createdAt")),
            "finishedAt": _dt(task.get("finishedAt")),
            "monitorFolder": monitor_folder,
            "book": book,
            "logs": [_serialize_import_log(log) for log in logs],
            "conversion": conversion,
        }
    )
    view.pop("duplicate", None)
    return view


@router.get("/sources")
def list_sources(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"sources": []})


@router.post("/sources")
async def create_source(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("外部资源功能已移除", status_code=410)


@router.put("/sources/{source_id}")
@router.patch("/sources/{source_id}")
async def update_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    await request.json()
    return fail("来源不存在", status_code=404)


@router.get("/sources/{source_id}")
def get_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("来源不存在", status_code=404)


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("来源不存在", status_code=404)


@router.post("/sources/{source_id}/test")
def test_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("源不存在", status_code=404)


@router.post("/sources/{source_id}/search")
async def search_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    keyword = str(payload.get("keyword") or payload.get("query") or "").strip()
    if not keyword:
        return fail("请输入搜索关键词", status_code=400)
    return fail("源不存在", status_code=404)


@router.get("/source-search-records")
def list_source_records(request: Request, sourceId: str | None = None, status: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"records": [], "total": 0})


@router.post("/source-search-records")
async def create_source_record(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    await request.json()
    return fail("源不存在", status_code=404)


@router.post("/source-search-records/create-download-task")
async def create_download_from_search_result(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    await request.json()
    return fail("源不存在", status_code=404)


@router.get("/source-search-records/{record_id}")
def get_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.delete("/source-search-records/{record_id}")
def delete_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.put("/source-search-records/{record_id}")
async def update_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.post("/source-search-records/{record_id}/ignore")
@router.post("/source-search-records/{record_id}/save")
def mark_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.post("/source-search-records/{record_id}/create-download-task")
async def create_download_from_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.get("/download-tasks")
def list_download_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    tasks = [task.to_legacy_dict() for task in list_download_tasks_query(db, limit=1000)]
    return ok({
        "tasks": [
            {
                **task,
                "remoteRef": _parse_json(task.get("remoteRef"), task.get("remoteRef")),
                "sourceName": None,
                "autoImport": _enabled_monitor_folder_for_path(db, Path(str(task.get("savePath") or ""))) is not None,
            }
            for task in tasks
        ]
    })


@router.post("/download-tasks")
async def create_download_task(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        target_dir = _target_directory_from_path(settings, payload.get("targetPath"), "下载")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    save_path = str(target_dir)
    task = create_download_task_command(
        db,
        CreateDownloadTask(
            id=f"py_{time_ns()}",
            source_id=str(payload["sourceId"]) if payload.get("sourceId") is not None else None,
            search_record_id=str(payload["searchRecordId"]) if payload.get("searchRecordId") is not None else None,
            book_id=str(payload["bookId"]) if payload.get("bookId") is not None else None,
            task_type=str(payload.get("type") or "manual"),
            status=str(payload.get("status") or "queued"),
            display_name=str(payload.get("displayName") or payload.get("name") or "下载任务"),
            remote_ref=_json_text(payload.get("remoteRef", {})),
            save_path=save_path,
            file_path=str(payload["filePath"]) if payload.get("filePath") is not None else None,
            error_message=str(payload["errorMessage"]) if payload.get("errorMessage") is not None else None,
            progress=float(payload.get("progress") if payload.get("progress") is not None else 0),
        ),
    ).to_legacy_dict()
    _save_system_setting(db, "library.lastDownloadTargetPath", save_path)
    db.commit()
    _record_system_event(db, level="info", source="download", actor_type="admin", actor_id=user.id, action="created", target_type="downloadTask", target_id=task.get("id"), message=f"创建下载任务：{task.get('displayName')}", metadata={"status": task.get("status"), "type": task.get("type")})
    return ok({"task": task, "autoImport": _enabled_monitor_folder_for_path(db, target_dir) is not None}, status_code=201)


@router.get("/download-tasks/{task_id}")
def get_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task_dto = get_download_task_query(db, task_id)
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    return ok({"task": task})


@router.delete("/download-tasks/{task_id}")
def delete_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task_dto = get_download_task_query(db, task_id)
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    deleted = delete_download_task_command(db, task_id)
    if deleted:
        _record_system_event(db, level="warning", source="download", actor_type="admin", actor_id=user.id, action="deleted", target_type="downloadTask", target_id=task_id, message=f"删除下载任务：{(task or {}).get('displayName') or task_id}", metadata={"status": (task or {}).get("status")})
    return ok({"deleted": deleted, "id": task_id})


@router.put("/download-tasks/{task_id}")
async def update_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    allowed = {"type", "status", "displayName", "savePath", "filePath", "errorMessage", "progress"}
    values = {key: value for key, value in payload.items() if key in allowed}
    if "remoteRef" in payload:
        values["remoteRef"] = _json_text(payload["remoteRef"])
    task_dto = update_download_task_command(
        db,
        task_id,
        UpdateDownloadTask(
            task_type=str(values["type"]) if "type" in values and values["type"] is not None else None,
            status=str(values["status"]) if "status" in values and values["status"] is not None else None,
            display_name=str(values["displayName"]) if "displayName" in values and values["displayName"] is not None else None,
            save_path=str(values["savePath"]) if "savePath" in values and values["savePath"] is not None else None,
            file_path=str(values["filePath"]) if "filePath" in values and values["filePath"] is not None else None,
            error_message=str(values["errorMessage"]) if "errorMessage" in values and values["errorMessage"] is not None else None,
            progress=float(values["progress"]) if "progress" in values and values["progress"] is not None else None,
            remote_ref=str(values["remoteRef"]) if "remoteRef" in values and values["remoteRef"] is not None else None,
            changed_fields=frozenset(values),
        ),
    )
    if task_dto is None:
        return fail("下载任务不存在", status_code=404)
    task = task_dto.to_legacy_dict()
    _record_system_event(db, level="error" if task.get("status") == "failed" else "info", source="download", actor_type="admin", actor_id=user.id, action="updated", target_type="downloadTask", target_id=task_id, message=f"更新下载任务：{task.get('displayName')}", metadata={"changes": values, "status": task.get("status"), "errorMessage": task.get("errorMessage")})
    return ok({"task": task})


@router.post("/download-tasks/{task_id}/start")
@router.post("/download-tasks/{task_id}/retry")
@router.post("/download-tasks/{task_id}/cancel")
@router.post("/download-tasks/{task_id}/import")
def mutate_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    action = request.url.path.rsplit("/", 1)[-1]
    task_dto = get_download_task_query(db, task_id)
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    if action in {"start", "retry"}:
        if action == "retry":
            if task.get("status") not in {"queued", "failed", "cancelled", "PENDING", "FAILED", "CANCELLED"}:
                return fail("只有等待中、失败或已取消的任务可以重新排队", status_code=400)
            updated = update_download_task_command(
                db,
                task_id,
                UpdateDownloadTask(
                    status="queued",
                    progress=0,
                    error_message=None,
                    changed_fields=frozenset({"status", "progress", "errorMessage"}),
                ),
            )
            task = updated.to_legacy_dict() if updated is not None else task
            _record_system_event(db, level="info", source="download", actor_type="admin", actor_id=user.id, action="retry", target_type="downloadTask", target_id=task_id, message=f"重新排队下载任务：{task.get('displayName')}", metadata={"status": task.get("status")})
            return ok({"task": task, "action": action})
        if task.get("status") not in {"queued", "failed", "PENDING", "FAILED"}:
            return fail("只有等待中或失败的任务可以开始下载", status_code=400)
        result = execute_download_task(db, settings, task_id)
        _record_system_event(db, level="error" if result.task.get("status") == "failed" else "info", source="download", actor_type="admin", actor_id=user.id, action="start", target_type="downloadTask", target_id=task_id, message=f"执行下载任务：{result.task.get('displayName')}", metadata={"status": result.task.get("status"), "errorMessage": result.task.get("errorMessage"), "filePath": result.task.get("filePath")})
        return ok({"task": result.task, "action": action})
    if action == "cancel":
        updated = update_download_task_command(
            db,
            task_id,
            UpdateDownloadTask(
                status="cancelled",
                changed_fields=frozenset({"status"}),
            ),
        )
        task = updated.to_legacy_dict() if updated is not None else task
        _record_system_event(db, level="warning", source="download", actor_type="admin", actor_id=user.id, action="cancelled", target_type="downloadTask", target_id=task_id, message=f"取消下载任务：{task.get('displayName')}", metadata={"status": task.get("status")})
        return ok({"task": task, "action": action})
    return fail("下载文件会由监控文件夹自动识别入库，无需手动导入", status_code=400)


@router.get("/import-tasks")
def list_import_tasks(
    request: Request,
    page: int = 1,
    pageSize: int = 10,
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(50, max(1, pageSize))
    context = authorization_context(db, user)
    normalized_status = str(status or "").strip().upper()
    if normalized_status and normalized_status != "ALL":
        if normalized_status not in {"PENDING", "PARSING", "COMPLETED", "FAILED"}:
            return fail("导入状态无效", status_code=400)
    tasks, total, summary = import_http_store.list_import_tasks_page(
        db,
        context,
        page=page,
        page_size=page_size,
        status=normalized_status or None,
        keyword=keyword,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    views = [_import_task_view(db, task, log_limit=20) for task in tasks]
    return ok({"tasks": views, "summary": summary, "page": page, "pageSize": page_size, "total": total, "totalPages": total_pages})


@router.post("/import-tasks/scan-directory")
async def scan_import_directory(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await _request_json_or_empty(request)
    requested_path = str(payload.get("path") or "").strip()
    node, error, status_code = _monitor_directory_tree_node(settings, requested_path)
    if error or not node:
        return fail(error or "目录不可用", status_code=status_code)
    target_path = Path(str(node["path"])).resolve()
    folder_rows = import_http_store.list_enabled_monitor_folder_rows(db)
    matching_folders = []
    for folder in folder_rows:
        try:
            folder_path = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if _is_inside_path(folder_path, target_path):
            matching_folders.append((folder_path, folder))
    if not matching_folders:
        return fail("所选目录不在已启用的监控文件夹内，请先添加或启用对应监控文件夹", status_code=400)
    _folder_path, folder = max(matching_folders, key=lambda item: len(item[0].parts))
    if not can_access_monitor_folder(db, user, str(folder.get("id"))):
        return fail("目录不可用", status_code=404, code="MONITOR_FOLDER_NOT_FOUND")
    folder_config = monitor_folder_config(folder, preferences=load_import_preferences(db))

    class PersistentQueue:
        def __init__(self) -> None:
            self.queued = 0

        def enqueue(self, path: Path, selected_folder: MonitorFolderConfig) -> None:
            _task, created = enqueue_import_task(
                db,
                path,
                origin="WATCH",
                original_name=path.name,
                monitor_folder_id=selected_folder.id,
                message="从文件管理手动加入导入队列",
                allow_terminal_requeue=path.is_dir(),
            )
            if created:
                self.queued += 1

    queue = PersistentQueue()
    summary = scan_directory_for_imports(
        target_path,
        folder_config,
        queue,
        known_paths=load_known_import_paths(db),
    )
    data = {
        "path": str(target_path),
        "monitorFolderId": folder_config.id,
        "monitorFolderName": folder.get("name"),
        "directoriesScanned": summary.directories_scanned,
        "filesScanned": summary.files_scanned,
        "candidatesFound": summary.candidates_found,
        "queued": queue.queued,
        "skipped": summary.cached_files + summary.ignored_files,
        "errors": summary.errors,
    }
    _record_system_event(
        db,
        level="warning" if summary.errors else "info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="scan.directory.requested",
        target_type="monitorFolder",
        target_id=folder_config.id,
        message=f"从文件管理识别目录：{target_path}",
        metadata=data,
    )
    return ok(data)


@router.delete("/import-tasks")
def clear_import_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    deleted = 0
    if _has_table(db, "ImportTask"):
        context = authorization_context(db, user)
        deleted = import_http_store.clear_terminal_import_tasks(db, context)
        db.commit()
    if deleted:
        _record_system_event(db, level="info", source="import", actor_type="admin", actor_id=user.id, action="tasks.cleared", target_type="importTask", message=f"清空已结束导入记录 {deleted} 条", metadata={"deleted": deleted})
    return ok({"deleted": deleted})


@router.delete("/import-tasks/{task_id}")
async def delete_import_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        return fail("导入记录不存在", status_code=404)
    if task.get("status") not in {"COMPLETED", "FAILED"}:
        return fail("导入任务仍在处理中，完成或失败后才能删除记录", status_code=409)

    payload = await _request_json_or_empty(request)
    delete_mode = str(payload.get("deleteMode") or "record").strip().lower()
    delete_library_record = payload.get("deleteLibraryRecord") is True
    if delete_mode not in {"record", "source", "converted"}:
        return fail("删除范围无效", status_code=400)
    work_id = str(task.get("workId") or "").strip()
    work = _get_work(db, work_id) if work_id else None
    if delete_library_record and not work:
        return fail("该导入记录没有可删除的关联书库图书", status_code=400)

    conversion = import_http_store.get_conversion_for_import(db, task_id)
    selected_paths: list[Path] = []
    if delete_mode == "source":
        source_path = _source_delete_path(task.get("sourcePath"), db, settings)
        if not source_path:
            return fail("源文件路径不在允许删除的书库或监控目录中", status_code=400)
        selected_paths = [source_path]
    elif delete_mode == "converted":
        selected_paths = _conversion_output_paths(conversion, settings)
        if not selected_paths:
            return fail("该导入记录没有可删除的转换文件", status_code=400)

    cleanup = _delete_source_paths(selected_paths)
    if cleanup["failedFileDeletes"]:
        return fail("文件删除失败，导入记录已保留，请检查文件权限后重试", status_code=500, details={"failedFileDeletes": cleanup["failedFileDeletes"]})

    library_cleanup = (
        _delete_import_linked_library_scope(db, task, settings)
        if delete_library_record and work
        else {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}
    )

    deleted = import_http_store.delete_import_task_row(db, task_id)
    db.commit()
    if deleted:
        _record_system_event(
            db,
            level="warning" if delete_mode != "record" or delete_library_record else "info",
            source="import",
            actor_type="admin",
            actor_id=user.id,
            action="task.deleted",
            target_type="importTask",
            target_id=task_id,
            message=f"删除导入记录{'及关联书库图书' if delete_library_record else ''}：{task.get('originalName') or task.get('sourcePath')}",
            metadata={
                "deleteMode": delete_mode,
                "deleteLibraryRecord": delete_library_record,
                "deletedLibraryRecord": bool(library_cleanup.get("deleted")),
                "deletedWorkRecord": bool(library_cleanup.get("deletedWorkRecord")),
                "deletedLibraryDatabaseRecords": int(library_cleanup.get("deletedDatabaseRecords") or 0),
                "libraryRecordId": work_id or None,
                "deletedFiles": int(cleanup["deletedFiles"]) + int(library_cleanup.get("deletedFiles") or 0),
                "missingFiles": cleanup["missingFiles"],
                "failedFileDeletes": library_cleanup.get("failedFileDeletes") or [],
            },
        )
    return ok({
        "deleted": deleted,
        "id": task_id,
        "deleteMode": delete_mode,
        "deleteLibraryRecord": delete_library_record,
        "deletedLibraryRecord": bool(library_cleanup.get("deleted")),
        "deletedWorkRecord": bool(library_cleanup.get("deletedWorkRecord")),
        "deletedLibraryDatabaseRecords": int(library_cleanup.get("deletedDatabaseRecords") or 0),
        "libraryRecordId": work_id or None,
        "deletedFiles": int(cleanup["deletedFiles"]) + int(library_cleanup.get("deletedFiles") or 0),
        "missingFiles": cleanup["missingFiles"],
        "failedFileDeletes": library_cleanup.get("failedFileDeletes") or [],
    })


@router.post("/import-tasks/rescan")
def rescan_import_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    requested_at = _now().isoformat()
    context = authorization_context(db, user)
    requested_value = (
        requested_at
        if context.is_admin
        else _json_text(
            {
                "requestedAt": requested_at,
                "monitorFolderIds": list(context.monitor_folder_ids),
            }
        )
    )
    if not context.is_admin and not context.monitor_folder_ids:
        return fail("没有可重新识别的授权文件夹", status_code=403, code="NO_IMPORT_SCOPE")
    if _has_table(db, "SystemSetting"):
        import_http_store.request_monitor_rescan(db, requested_value)
        db.commit()
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="rescan.requested",
        target_type="monitorFolder",
        message="请求重新识别监控文件夹",
        metadata={
            "requestedAt": requested_at,
            "monitorFolderIds": None if context.is_admin else list(context.monitor_folder_ids),
        },
    )
    return ok(
        {
            "requestedAt": requested_at,
            "monitorFolderIds": None if context.is_admin else list(context.monitor_folder_ids),
        }
    )


@router.post("/import-tasks/{task_id}/retry")
def retry_import_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        return fail("导入任务不存在", status_code=404)
    if task.get("status") != "FAILED":
        return fail("只有失败的任务可以重试", status_code=400)
    if not bool(task.get("retryable")):
        return fail("该错误无法通过自动重试解决，原文件已保留", status_code=400)
    source_path = Path(str(task.get("sourcePath") or ""))
    try:
        source_available = source_path.is_file() or (source_path.is_dir() and bool(collect_audio_bundle_files(source_path)))
    except ValueError:
        source_available = False
    if not source_available:
        return fail("原文件不存在，无法重试", status_code=400)
    updated_at = _now()
    task = import_http_store.reset_import_task_for_retry(
        db,
        task_id,
        updated_at=updated_at,
    )
    if _has_table(db, "ImportAsset"):
        import_http_store.reset_import_assets_for_retry(db, task_id, updated_at=_now())
        db.commit()
    conversion = import_http_store.reset_conversion_for_retry(
        db,
        task_id,
        updated_at=updated_at,
    )
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="retry",
        target_type="importTask",
        target_id=task_id,
        message=f"重新排队导入任务：{task.get('originalName') or task.get('sourcePath')}",
        metadata={"errorCode": conversion.get("errorCode") if conversion else None},
    )
    return ok({"task": _import_task_view(db, task or {}, log_limit=100)})


@router.get("/import-tasks/{task_id}")
def get_import_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        return fail("导入任务不存在", status_code=404)
    return ok({"task": _import_task_view(db, task, log_limit=100)})


@router.get("/import-tasks/{task_id}/logs")
def get_import_logs(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if _visible_import_task_or_none(db, user, task_id) is None:
        return fail("导入任务不存在", status_code=404)
    page = _positive_int(request.query_params.get("page"), 1, 100000)
    page_size = _positive_int(request.query_params.get("pageSize"), 100, 200)
    level = request.query_params.get("level")
    logs, total = import_http_store.list_import_logs(
        db,
        task_id,
        limit=page_size,
        offset=(page - 1) * page_size,
        level=level,
    )
    return ok(
        {
            "logs": [_serialize_import_log(log) for log in logs],
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        }
    )


@router.get("/shelves")
def list_shelves(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelves = shelf_store.list_shelves_for_user(db, user.id)
    return ok({"shelves": [_shelf_summary_view(db, shelf, user) for shelf in shelves]})


def _owned_shelf(db: Session, shelf_id: str, user_id: str) -> dict[str, Any] | None:
    return shelf_store.get_owned_shelf(db, shelf_id, user_id)


def _shelf_work_ids(db: Session, shelf: dict[str, Any], user: User) -> list[str]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    rules = _parse_json(shelf.get("rulesJson"), {})
    work_ids = (
        smart_shelf_work_ids(db, rules, user.id)
        if kind == "SMART"
        else shelf_store.list_static_shelf_work_ids(db, str(shelf["id"]))
    )
    if not work_ids:
        return []
    context = authorization_context(db, user)
    return shelf_store.filter_visible_work_ids(db, work_ids, context)


def _shelf_book_views(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    works = shelf_store.list_work_cards(db, work_ids)
    return [_bookshelf_item_view(work) for work in works]


def _shelf_base_view(shelf: dict[str, Any], work_ids: list[str]) -> dict[str, Any]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    return {
        **shelf,
        "kind": kind,
        "rules": _parse_json(shelf.get("rulesJson"), {}),
        "bookCount": len(work_ids),
    }


def _shelf_summary_view(db: Session, shelf: dict[str, Any], user: User) -> dict[str, Any]:
    work_ids = _shelf_work_ids(db, shelf, user)
    return {
        **_shelf_base_view(shelf, work_ids),
        "books": _shelf_book_views(db, work_ids[:3]),
    }


def _shelf_detail_view(
    db: Session,
    shelf: dict[str, Any],
    user: User,
    *,
    page: int = 1,
    page_size: int = 24,
    include_book_ids: bool = True,
) -> dict[str, Any]:
    work_ids = _shelf_work_ids(db, shelf, user)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = len(work_ids)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_ids = work_ids[start:start + page_size]
    result = {
        **_shelf_base_view(shelf, work_ids),
        "books": _shelf_book_views(db, page_ids),
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }
    if include_book_ids:
        result["bookIds"] = work_ids
    return result


def _normalized_smart_shelf_rules(value: Any) -> tuple[dict[str, Any], str | None]:
    if value is None:
        return {}, None
    if not isinstance(value, dict):
        return {}, "智能书架规则格式不正确"
    rules: dict[str, Any] = {}
    search = str(value.get("search") or "").strip()
    if search:
        rules["search"] = search[:200]
    statuses = [str(item).upper() for item in value.get("statuses") or []]
    if any(item not in {"UNREAD", "READING", "FINISHED"} for item in statuses):
        return {}, "阅读状态规则无效"
    if statuses:
        rules["statuses"] = list(dict.fromkeys(statuses))
    media_kinds = [str(item).upper() for item in value.get("mediaKinds") or []]
    if any(item not in {"EBOOK", "COMIC", "AUDIOBOOK"} for item in media_kinds):
        return {}, "媒介类型规则无效"
    if media_kinds:
        rules["mediaKinds"] = list(dict.fromkeys(media_kinds))
    for key in ("tags", "authors", "publishers"):
        values = [str(item).strip() for item in value.get(key) or [] if str(item).strip()]
        if values:
            rules[key] = list(dict.fromkeys(values))[:100]
    dynamic_rules, dynamic_error = normalize_filter_rules(
        {"combinator": value.get("combinator", "ALL"), "conditions": value.get("conditions") or []}
    )
    if dynamic_error:
        return {}, dynamic_error
    if dynamic_rules["conditions"]:
        rules.update(dynamic_rules)
    included_work_ids = [
        str(item).strip()
        for item in value.get("includedWorkIds") or []
        if str(item).strip()
    ]
    if included_work_ids:
        rules["includedWorkIds"] = list(dict.fromkeys(included_work_ids))[:500]
    return rules, None


def _normalized_shelf_work_ids(db: Session, value: Any, user: User) -> tuple[list[str], str | None]:
    if not isinstance(value, list):
        return [], "图书列表格式不正确"
    work_ids: list[str] = []
    for item in value:
        work_id = str(item or "").strip()
        if work_id and work_id not in work_ids:
            work_ids.append(work_id)
    if not work_ids:
        return [], None
    if not _has_table(db, "LibraryWork"):
        return [], "选择的图书不存在，请刷新后重试"
    existing_ids = {work_id for work_id in work_ids if _get_work(db, work_id)}
    if missing := [work_id for work_id in work_ids if work_id not in existing_ids]:
        return [], f"有 {len(missing)} 本图书已不存在，请刷新后重试"
    inaccessible = [work_id for work_id in work_ids if not can_access_work(db, user, work_id)]
    if inaccessible:
        return [], "选择的图书不存在，请刷新后重试"
    return work_ids, None


def _replace_shelf_works(db: Session, shelf_id: str, work_ids: list[str]) -> None:
    shelf_store.replace_shelf_works(db, shelf_id, work_ids, now=_now())


@router.get("/shelves/{shelf_id}")
def get_shelf(
    shelf_id: str,
    request: Request,
    page: int = 1,
    pageSize: int = 24,
    includeBookIds: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf = _owned_shelf(db, shelf_id, user.id)
    if not shelf:
        return fail("书架不存在", status_code=404)
    return ok({
        "shelf": _shelf_detail_view(
            db,
            shelf,
            user,
            page=page,
            page_size=pageSize,
            include_book_ids=includeBookIds,
        )
    })


@router.post("/shelves")
async def create_shelf(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    name = str(payload.get("name") or "").strip()
    if not name:
        return fail("请填写书架名称", status_code=400)
    kind = str(payload.get("kind") or "STATIC").strip().upper()
    if kind not in {"STATIC", "SMART"}:
        return fail("书架类型无效", status_code=400)
    rules, rules_error = _normalized_smart_shelf_rules(payload.get("rules"))
    if rules_error:
        return fail(rules_error, status_code=400)
    work_ids, work_error = _normalized_shelf_work_ids(db, payload.get("bookIds", payload.get("workIds", [])), user)
    if work_error:
        return fail(work_error, status_code=400)
    shelf = shelf_store.create_shelf(
        db,
        {
            "id": f"py_{time_ns()}",
            "ownerUserId": user.id,
            "name": name,
            "description": str(payload.get("description") or "").strip() or None,
            "kind": kind,
            "rulesJson": _json_text(rules),
            "pinned": bool(payload.get("pinned")),
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    if kind == "STATIC":
        _replace_shelf_works(db, shelf["id"], work_ids)
    return ok({"shelf": _shelf_detail_view(db, shelf, user)}, status_code=201)


@router.patch("/shelves/{shelf_id}")
async def update_shelf(shelf_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    values = {key: payload[key] for key in ("name", "description", "pinned") if key in payload}
    if "name" in values:
        values["name"] = str(values["name"] or "").strip()
        if not values["name"]:
            return fail("请填写书架名称", status_code=400)
    if "description" in values:
        values["description"] = str(values["description"] or "").strip() or None
    existing_shelf = _owned_shelf(db, shelf_id, user.id)
    if not existing_shelf:
        return fail("书架不存在", status_code=404)
    kind = str(payload.get("kind") or existing_shelf.get("kind") or "STATIC").strip().upper()
    if kind not in {"STATIC", "SMART"}:
        return fail("书架类型无效", status_code=400)
    rules, rules_error = _normalized_smart_shelf_rules(payload.get("rules", _parse_json(existing_shelf.get("rulesJson"), {})))
    if rules_error:
        return fail(rules_error, status_code=400)
    values.update({"kind": kind, "rulesJson": _json_text(rules)})
    works = payload.get("bookIds", payload.get("workIds"))
    work_ids: list[str] | None = None
    if works is not None:
        work_ids, work_error = _normalized_shelf_work_ids(db, works, user)
        if work_error:
            return fail(work_error, status_code=400)
    values["updatedAt"] = _now()
    shelf = shelf_store.update_shelf(db, shelf_id, values)
    if not shelf:
        return fail("书架不存在", status_code=404)
    if work_ids is not None and kind == "STATIC":
        _replace_shelf_works(db, shelf_id, work_ids)
    elif kind == "SMART" and str(existing_shelf.get("kind") or "STATIC").upper() != "SMART":
        _replace_shelf_works(db, shelf_id, [])
    else:
        db.commit()
    return ok({"shelf": _shelf_detail_view(db, shelf, user)})


@router.delete("/shelves/{shelf_id}")
def delete_shelf(shelf_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf = _owned_shelf(db, shelf_id, user.id)
    if not shelf:
        return fail("书架不存在", status_code=404)
    shelf_store.clear_monitor_folder_shelf_links(db, shelf_id, now=_now())
    deleted = shelf_store.delete_shelf(db, shelf_id)
    return ok({"deleted": deleted, "id": shelf_id})


@router.get("/library/facets")
def library_facets(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    facets = {kind.lower(): _visible_categories(db, user, kind) for kind in ("AUTHOR", "TAG", "SERIES", "PUBLISHER")}
    context = authorization_context(db, user)
    visible_works = library_facet_queries.list_visible_works(db, context)
    status_counts: dict[str, int] = {}
    for work in visible_works:
        status = str(_work_view(db, work, user.id).get("status") or "UNREAD")
        status_counts[status] = status_counts.get(status, 0) + 1
    status_rows = [{"value": value, "count": count} for value, count in sorted(status_counts.items())]
    media_rows = library_facet_queries.media_kind_counts(db, context)
    return ok({"facets": facets, "statuses": status_rows, "mediaKinds": media_rows})


def _visible_categories(db: Session, user: User, kind: str) -> list[dict[str, Any]]:
    normalized_kind = kind.upper()
    if user.role == "admin":
        return list_categories(db, normalized_kind)
    context = authorization_context(db, user)
    rows = library_facet_queries.visible_categories(db, context, normalized_kind)
    return [
        {**row, "aliases": _parse_json(row.get("aliases"), []), "bookCount": int(row.get("bookCount") or 0)}
        for row in rows
    ]


def _scoped_filter_schema(db: Session, user: User) -> dict[str, Any]:
    schema = library_filter_schema(db)
    context = authorization_context(db, user)
    options_by_source: dict[str, list[dict[str, Any]]] = {}
    if context.is_admin:
        options_by_source = {}
    else:
        work_rows = library_facet_queries.visible_work_option_rows(db, context)
        edition_rows = library_facet_queries.visible_edition_option_rows(db, context)

        def counted(values: list[str]) -> list[dict[str, Any]]:
            counts: dict[str, int] = {}
            for value in values:
                normalized = value.strip()
                if normalized:
                    counts[normalized] = counts.get(normalized, 0) + 1
            return [
                {"value": value, "label": value, "count": count}
                for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
            ]

        authors = [
            part.strip()
            for row in work_rows
            for part in re.split(r"[、,，;/；|]+", str(row.get("author") or ""))
            if part.strip()
        ]
        tags = [
            str(tag).strip()
            for row in work_rows
            for tag in _parse_json(row.get("tags"), [])
            if str(tag).strip()
        ]
        options_by_source.update({
            "authors": counted(authors),
            "tags": counted(tags),
            "series": counted([str(row.get("seriesName") or "") for row in work_rows]),
            "publishers": counted([str(row.get("publisher") or "") for row in edition_rows]),
            "languages": counted([str(row.get("language") or "") for row in edition_rows]),
            "formats": counted([str(row.get("format") or "") for row in edition_rows]),
            "importStatuses": counted([str(row.get("importStatus") or "") for row in edition_rows]),
            "origins": counted([
                *[str(row.get("origin") or "") for row in work_rows],
                *[str(row.get("origin") or "") for row in edition_rows],
            ]),
        })
        visible_media_kinds = {str(row.get("mediaKind") or "") for row in edition_rows}
        existing_media = next(
            (field.get("options", []) for field in schema["fields"] if field.get("optionSource") == "mediaKinds"),
            [],
        )
        options_by_source["mediaKinds"] = [
            option for option in existing_media if option.get("value") in visible_media_kinds
        ]

    if context.is_admin:
        monitor_rows = sorted(
            (
                {"id": row.get("id"), "name": row.get("name"), "rootPath": row.get("rootPath")}
                for row in import_http_store.list_monitor_folders(db)
            ),
            key=lambda row: str(row.get("name") or "").casefold(),
        )
    elif context.monitor_folder_ids:
        allowed = set(context.monitor_folder_ids)
        monitor_rows = sorted(
            (
                {"id": row.get("id"), "name": row.get("name"), "rootPath": row.get("rootPath")}
                for row in import_http_store.list_monitor_folders(db)
                if str(row.get("id")) in allowed
            ),
            key=lambda row: str(row.get("name") or "").casefold(),
        )
    else:
        monitor_rows = []
    options_by_source["monitorFolders"] = [
        {"value": str(row["id"]), "label": str(row["name"]), "rootPath": row.get("rootPath")}
        for row in monitor_rows
    ]
    shelf_rows = shelf_store.list_shelves_for_user(db, user.id)
    options_by_source["shelves"] = [
        {"value": str(row["id"]), "label": str(row["name"])}
        for row in sorted(
            (row for row in shelf_rows if str(row.get("kind") or "STATIC").upper() == "STATIC"),
            key=lambda row: str(row.get("name") or "").casefold(),
        )
    ]
    schema["fields"] = [
        {
            **field,
            "options": options_by_source.get(str(field.get("optionSource")), field.get("options", [])),
        }
        for field in schema["fields"]
    ]
    return schema


@router.get("/library/filter-schema")
def library_filter_options(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok(_scoped_filter_schema(db, user))


@router.get("/library/categories")
def library_categories(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        kind = request.query_params.get("kind", "TAG")
        search = request.query_params.get("search", "")
        page = max(1, int(request.query_params.get("page", "1")))
        page_size = min(100, max(1, int(request.query_params.get("pageSize", "20"))))
        total = count_categories(db, kind, search)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        items = list_categories(db, kind, search, limit=page_size, offset=(page - 1) * page_size)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok({"categories": items, "page": page, "pageSize": page_size, "total": total, "totalPages": total_pages})


@router.patch("/library/categories/{facet_id}")
async def update_library_category(facet_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        result = rename_category(db, facet_id, str(payload.get("name") or ""), user.id)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok(result)


@router.delete("/library/categories/{facet_id}")
def delete_library_category(facet_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = delete_category(db, facet_id, user.id)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok(result)


@router.post("/library/categories/merge")
async def merge_library_categories(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        result = merge_categories(
            db,
            str(payload.get("kind") or "TAG"),
            [str(item) for item in payload.get("sourceIds") or []],
            str(payload.get("targetId") or ""),
            user.id,
        )
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok(result)


@router.get("/library/duplicates")
def library_duplicates(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    groups = duplicate_groups(db)
    for group in groups:
        group["works"] = [_work_view(db, work, user.id) for work in group.get("works") or []]
    return ok({"groups": groups, "total": len(groups)})


@router.post("/library/duplicates/merge")
async def merge_library_duplicates(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        result = merge_works(
            db,
            str(payload.get("targetWorkId") or ""),
            [str(item) for item in payload.get("sourceWorkIds") or []],
            user.id,
        )
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok(result)


@router.get("/library/operations")
def library_operations(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    operations = library_operation_store.list_operations_for_user(db, user.id)
    return ok({"operations": [operation_view(item) for item in operations]})


@router.post("/library/operations/{operation_id}/undo")
def undo_library_operation(operation_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = undo_operation(db, operation_id, user.id)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok(result)


@router.get("/organize/policy")
def get_organize_policy_route(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return ok({"policy": get_organize_policy(db)})
    except ValueError as exc:
        return fail(str(exc), status_code=503)


@router.put("/organize/policy")
async def update_organize_policy_route(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        payload = await request.json()
        policy = update_organize_policy(db, payload)
        db.commit()
        return ok({"policy": policy})
    except ValueError as exc:
        return fail(str(exc), status_code=400)


@router.get("/organize/candidates")
def get_organize_candidates_route(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return ok({"candidates": organize_candidate_summary(db)})
    except ValueError as exc:
        return fail(str(exc), status_code=503)


@router.get("/organize/runs")
def list_organize_runs_route(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    limit = _positive_int(request.query_params.get("limit"), 20, 100)
    return ok({"runs": list_organize_runs(db, limit)})


@router.get("/organize/jobs")
def list_organize_jobs(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    requested_page = _positive_int(request.query_params.get("page"), 1, 1_000_000)
    page_size = _positive_int(request.query_params.get("pageSize"), 20, 100)
    search = str(request.query_params.get("search") or "").strip().lower()
    status = str(request.query_params.get("status") or "ALL").strip().upper()
    if status not in {"ALL", "SUCCESS", "FAILED", "RECOGNIZING", "WAITING"}:
        status = "ALL"
    provider_ids = organize_job_queries.provider_ids_matching_search(
        search,
        list_metadata_providers(db),
    )
    page_result = organize_job_queries.paginate_organize_jobs(
        db,
        requested_page=requested_page,
        page_size=page_size,
        status=status,
        search=search,
        provider_ids=provider_ids,
    )
    rows = page_result.rows
    job_ids = [str(row.get("id") or "") for row in rows]
    lookups = organize_job_queries.latest_lookup_rows_by_job(db, job_ids)
    executions_by_job = organize_job_queries.execution_rows_by_job(db, job_ids)
    jobs = [
        view
        for row in rows
        if (
            view := _organize_job_view(
                db,
                row,
                getattr(user, "id", None),
                lookup=lookups.get(str(row.get("id") or "")),
                executions=executions_by_job.get(str(row.get("id") or ""), []),
            )
        )
        is not None
    ]
    referenced_provider_ids: set[str] = set()
    for job in jobs:
        for source in [
            *(job.get("metadataSources") or []),
            job.get("metadataLookupSource"),
            *(job.get("metadataLookupProviders") or []),
        ]:
            if str(source or "").strip():
                referenced_provider_ids.add(str(source).strip())
        for execution in job.get("providerExecutions") or []:
            provider_id = str((execution or {}).get("providerId") or "").strip()
            if provider_id:
                referenced_provider_ids.add(provider_id)
    provider_names = {
        str(provider.get("id")): str(provider.get("name"))
        for provider in list_metadata_providers(db)
        if str(provider.get("id") or "") in referenced_provider_ids and provider.get("name")
    }
    return ok(
        {
            "jobs": jobs,
            "books": [job["book"] for job in jobs],
            "page": page_result.page,
            "pageSize": page_result.page_size,
            "total": page_result.total,
            "totalPages": page_result.total_pages,
            "statusCounts": page_result.status_counts,
            "providerNames": provider_names,
        }
    )


@router.get("/organize/pending")
def list_pending_organize(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page_size = _positive_int(request.query_params.get("pageSize"), 50, 200)
    rows = organize_job_queries.list_pending_job_rows(db, limit=page_size)
    job_ids = [str(row.get("id") or "") for row in rows]
    lookups = organize_job_queries.latest_lookup_rows_by_job(db, job_ids)
    executions_by_job = organize_job_queries.execution_rows_by_job(db, job_ids)
    jobs = [
        view
        for row in rows
        if (
            view := _organize_job_view(
                db,
                row,
                getattr(user, "id", None),
                pending_only=True,
                lookup=lookups.get(str(row.get("id") or "")),
                executions=executions_by_job.get(str(row.get("id") or ""), []),
            )
        )
        is not None
    ]
    return ok({"jobs": jobs, "books": [job["book"] for job in jobs], "total": len(jobs)})


@router.get("/organize/jobs/{job_id}")
def get_organize_job(job_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    job = organize_runs.get_job_row(db, job_id) if organize_runs.has_job_table(db) else None
    if not job:
        return fail("整理任务不存在", status_code=404)
    view = _organize_job_view(db, job, getattr(user, "id", None))
    if not view:
        return fail("整理任务不存在", status_code=404)
    return ok({"job": view})


@router.post("/organize/jobs/{job_id}/recognize")
def recognize_organize_job_route(job_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        recognize_organize_job(db, job_id)
        job = organize_runs.get_job_row(db, job_id) or {}
        return ok({"job": _organize_job_view(db, job, getattr(user, "id", None))})
    except ValueError as exc:
        return fail(str(exc), status_code=404 if "不存在" in str(exc) else 400)


@router.delete("/organize/jobs/{job_id}")
def delete_organize_job_route(job_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return ok(delete_organize_job(db, job_id))
    except ValueError as exc:
        return fail(str(exc), status_code=404 if "不存在" in str(exc) else 400)


@router.get("/backups")
def list_backups(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"backups": list_backup_archives(settings)})


@router.get("/backups/{backup_id}")
def get_backup(backup_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if not path.exists():
        return fail("备份不存在", status_code=404)
    backup = next((item for item in list_backup_archives(settings) if item["id"] == backup_id), None)
    return ok({"backup": backup or {"id": backup_id, "name": path.name, "sizeBytes": path.stat().st_size, "createdAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}})


@router.post("/backups")
def create_backup(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    backup = create_backup_archive(db, settings)
    return ok({"backup": {"id": backup.id, "name": backup.filename, "filename": backup.filename, "sizeBytes": backup.size_bytes, "createdAt": backup.created_at, "counts": backup.counts}}, status_code=201)


@router.get("/backups/{backup_id}/download")
def download_backup(backup_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return _send_file(settings.resolved_storage_root / "backups" / f"{backup_id}.zip", request, user.id, media_type="application/zip", name=f"{backup_id}.zip", route="backup-download", file_id=backup_id)


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if not path.exists():
        return fail("备份不存在", status_code=404)
    try:
        result = restore_backup_archive(db, settings, backup_id)
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    return ok(result)


@router.delete("/backups/{backup_id}")
def delete_backup(backup_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    path = settings.resolved_storage_root / "backups" / f"{backup_id}.zip"
    if path.exists():
        path.unlink()
        return ok({"deleted": True, "id": backup_id})
    return ok({"deleted": False, "id": backup_id})


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


@router.post("/works/{work_id}/metadata/search")
async def metadata_search(work_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    payload = await request.json()
    source = str(payload.get("providerId") or payload.get("source") or "bangumi")
    if source not in metadata_provider_registry().ids():
        return fail("不支持的元数据来源", status_code=400)
    job, context = _metadata_context_for_work(db, work_id)
    if not job or not context:
        return fail("读物不存在或无权访问", status_code=404)
    query = str(payload.get("query") or "").strip() or None
    try:
        result = search_with_metadata_provider(db, context, source, query)
    except Exception as exc:
        return fail(str(exc), status_code=400)
    candidates = result.get("candidates") or []
    return ok({"candidates": candidates, "results": candidates, "query": query or context["work"].get("title"), "source": source, "message": result.get("message")})


@router.patch("/works/{work_id}/editions/{edition_id}")
async def update_work_edition(work_id: str, edition_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    if not can_access_edition(db, user, edition_id):
        return fail("版本不存在或不属于该作品", status_code=404, code="EDITION_NOT_FOUND")
    edition = (
        library_works.get_visible_edition_for_work(
            db,
            edition_id=edition_id,
            work_id=work_id,
        )
        if _has_table(db, "LibraryEdition")
        else None
    )
    if not edition:
        return fail("版本不存在或不属于该作品", status_code=404)
    payload = await request.json()
    allowed = {"versionName", "description", "publisher", "publishedAt", "language", "identifier", "isbn", "narrator", "abridged"}
    values = {key: payload.get(key) for key in allowed if key in payload}
    for key in ("versionName", "publisher", "language", "identifier", "isbn", "narrator"):
        if key in values:
            values[key] = str(values[key] or "").strip() or None
    values["updatedAt"] = _now()
    updated = library_works.update_edition_fields(db, edition_id, values)
    sync_work_facets(db, work_id, commit=False)
    db.commit()
    work = _get_work(db, work_id)
    return ok({"edition": updated, "book": _work_view(db, work, user.id) if work else None})


@router.post("/works/{work_id}/editions/{edition_id}/convert")
def convert_work_edition(work_id: str, edition_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    if not can_access_edition(db, user, edition_id):
        return fail("版本不存在或不属于该作品", status_code=404, code="EDITION_NOT_FOUND")
    work = _get_work(db, work_id)
    edition = library_deletion.get_edition_for_work(
        db,
        edition_id=edition_id,
        work_id=work_id,
    )
    if edition and bool(edition.get("hidden")):
        edition = None
    if not work or not edition:
        return fail("版本不存在或不属于该作品", status_code=404)
    source_format = str(edition.get("format") or "").strip().lower()
    if f".{source_format}" not in CONVERTIBLE_TEXT_EXTS:
        return fail("该版本不支持转换为 EPUB", status_code=400)
    source_file = library_storage.first_file_for_edition(
        db,
        edition_id=edition_id,
    )
    source_path = Path(str((source_file or {}).get("path") or "")).expanduser()
    if not source_file or not source_path.is_file():
        return fail("原始文件不存在，无法转换", status_code=409)
    task, created = enqueue_import_task(
        db,
        source_path,
        origin="DEFERRED_CONVERSION",
        original_name=source_path.name,
        requested_title=str(work.get("title") or "").strip() or None,
        requested_author=str(work.get("author") or "").strip() or None,
        work_id=work_id,
        monitor_folder_id=edition.get("monitorFolderId"),
        message="已加入 EPUB 转换队列",
        allow_terminal_requeue=True,
    )
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="conversion.queued",
        target_type="importTask",
        target_id=task.get("id"),
        message=f"加入后置转换队列：{source_path.name}",
        metadata={"workId": work_id, "editionId": edition_id, "sourceFormat": source_format.upper()},
    )
    return ok({"task": task, "created": created}, status_code=202)


@router.post("/works/{work_id}/metadata/apply")
@router.post("/works/{work_id}/editions/{edition_id}/primary")
@router.post("/works/{work_id}/editions/{edition_id}/split")
@router.post("/works/{work_id}/volumes/{volume_id}/move-to")
@router.post("/works/{work_id}/volumes/{volume_id}/move")
async def compatible_work_action(work_id: str, request: Request, edition_id: str | None = None, volume_id: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    if edition_id and not can_access_edition(db, user, edition_id):
        return fail("版本不存在或不属于该作品", status_code=404, code="EDITION_NOT_FOUND")
    if volume_id and not can_access_volume(db, user, volume_id):
        return fail("卷不存在或不属于该作品", status_code=404, code="VOLUME_NOT_FOUND")
    if request.url.path.endswith("/metadata/apply"):
        payload = await request.json()
        candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
        fields = [str(field) for field in payload.get("fields") or []]
        if not candidate or not fields:
            return fail("请选择要应用的元数据字段", status_code=400)
        existing_work = _get_work(db, work_id)
        if not existing_work:
            return fail("作品不存在", status_code=404)
        patch = _metadata_field_patch(candidate, fields)
        if "title" in patch or "author" in patch:
            title = str(patch.get("title", existing_work.get("title")) or "").strip()
            author = str(patch.get("author", existing_work.get("author")) or "").strip() or UNKNOWN_AUTHOR
            merge_key = identity_merge_key(title, author)
            patch.update(
                {
                    "title": title,
                    "author": author,
                    "normalizedTitle": normalize_identity_part(title),
                    "normalizedAuthor": normalize_identity_part(author),
                    "mergeKey": merge_key,
                }
            )
        publisher = str(candidate.get("publisher") or "").strip() if "publisher" in fields else ""
        if "coverUrl" in fields and isinstance(candidate.get("coverUrl"), str) and candidate.get("coverUrl").strip():
            try:
                patch.update(_apply_remote_cover(work_id, candidate["coverUrl"].strip(), settings))
            except Exception as exc:
                logger.warning("failed to apply remote cover work=%s url=%s error=%s", work_id, candidate.get("coverUrl"), exc)
        if not patch and not publisher:
            return fail("候选中没有可应用的字段", status_code=400)
        patch.update({"organized": True, "organizeStatus": "APPLIED", "metadataQuality": 85, "updatedAt": _now()})
        work = library_works.update_work_fields(db, work_id, patch)
        if not work:
            return fail("作品不存在", status_code=404)
        if publisher and _has_table(db, "LibraryEdition"):
            primary_edition_id = str(work.get("primaryEditionId") or "")
            if not primary_edition_id:
                first_editions = library_works.list_visible_editions_for_work(
                    db,
                    work_id=work_id,
                )
                primary_edition_id = str(
                    (first_editions[0] if first_editions else {}).get("id") or ""
                )
            if primary_edition_id:
                library_works.update_edition_fields(
                    db,
                    primary_edition_id,
                    {"publisher": publisher, "updatedAt": _now()},
                )
        sync_work_facets(db, work_id, commit=False)
        finished_job_ids = _finish_metadata_organize_work(db, work_id)
        db.commit()
        return ok({"book": _work_view(db, work, user.id), "appliedFields": fields, "finishedOrganizeJobIds": finished_job_ids})
    if request.url.path.endswith("/split"):
        payload = await request.json()
        try:
            result = split_edition(
                db,
                work_id,
                str(edition_id or ""),
                title=str(payload.get("title") or ""),
                author=str(payload.get("author") or "").strip() or None,
                copy_shelves=payload.get("copyShelves") is not False,
                user_id=user.id,
            )
        except ValueError as exc:
            return fail(str(exc), status_code=400)
        return ok(result)
    if request.url.path.endswith("/primary") and edition_id:
        edition = (
            library_projections.get_edition(db, edition_id)
            if _has_table(db, "LibraryEdition")
            else None
        )
        if edition and (
            str(edition.get("workId") or "") != work_id or bool(edition.get("hidden"))
        ):
            edition = None
        if not edition:
            return fail("版本不存在或不属于该作品", status_code=404)
        if not _get_work(db, work_id):
            return fail("作品不存在", status_code=404)
        now = _now()
        media_kind = _edition_media_kind(edition)
        has_media_kind = _has_column(db, "LibraryEdition", "mediaKind")
        compatible_formats = None if has_media_kind else (("EPUB", "PDF") if media_kind == "EBOOK" else (edition.get("format"),))
        library_works.clear_primary_for_media_kind(
            db,
            work_id=work_id,
            media_kind=media_kind,
            formats=compatible_formats,
            now=now,
            has_media_kind_column=has_media_kind,
        )
        library_works.mark_edition_primary_for_work(
            db,
            work_id=work_id,
            edition_id=edition_id,
            work_type=edition.get("format") or "EPUB",
            now=now,
        )
        db.commit()
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="edition.primary",
            target_type="edition",
            target_id=edition_id,
            message="已更新主版本",
            metadata={"workId": work_id, "editionId": edition_id},
        )
        work = _get_work(db, work_id)
        return ok({"book": _work_view(db, work, user.id) if work else None, "workId": work_id, "editionId": edition_id})
    if request.url.path.endswith("/move-to") and volume_id:
        payload = await request.json()
        target_edition_id = str(payload.get("targetEditionId") or "").strip()
        if not target_edition_id:
            return fail("请选择目标版本", status_code=400)
        source = library_join_queries.get_volume_for_work(db, volume_id=volume_id, work_id=work_id)
        if not source:
            return fail("卷册不存在或不属于该作品", status_code=404)
        target = library_join_queries.get_edition_with_work_title(db, target_edition_id)
        if not target:
            return fail("目标版本不存在", status_code=404)
        target_work_id = target.get("workId")
        if target_work_id == work_id:
            return fail("请选择另一部目标图书", status_code=400)
        result = move_volume_to_work(
            db,
            source_work_id=work_id,
            volume_id=volume_id,
            target_work_id=str(target_work_id),
            source_format=str(source.get("sourceFormat") or ""),
            now=_now(),
        )
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="volume.moved" if result.merged_volume else "edition.moved",
            target_type="volume" if result.merged_volume else "edition",
            target_id=volume_id if result.merged_volume else result.source_edition_id,
            message=("合并卷册" if result.merged_volume else "转移版本") + f"到《{target.get('targetWorkTitle') or target_work_id}》",
            metadata={"sourceWorkId": work_id, "targetWorkId": target_work_id, "sourceEditionId": result.source_edition_id, "targetEditionId": result.target_edition_id, "transferMode": result.transfer_mode},
        )
        source_work = _get_work(db, work_id)
        target_work = _get_work(db, target_work_id) if target_work_id else None
        return ok({
            "book": _work_view(db, source_work, user.id) if source_work else None,
            "targetBook": _work_view(db, target_work, user.id) if target_work else None,
            "workId": work_id,
            "targetWorkId": target_work_id,
            "volumeId": volume_id,
            "targetEditionId": result.target_edition_id,
            "transferMode": result.transfer_mode,
        })
    if request.url.path.endswith("/move") and volume_id:
        payload = await request.json()
        direction = str(payload.get("direction") or "").lower()
        if direction not in {"up", "down"}:
            return fail("请选择上移或下移", status_code=400)
        volume = library_join_queries.get_volume_belonging_to_work(db, volume_id=volume_id, work_id=work_id)
        if not volume:
            return fail("卷册不存在或不属于该作品", status_code=404)
        changed = reorder_volume(
            db,
            volume_id=volume_id,
            edition_id=str(volume["editionId"]),
            direction=direction,
            now=_now(),
        )
        if not changed:
            work = _get_work(db, work_id)
            return ok({"book": _work_view(db, work, user.id) if work else None, "workId": work_id, "volumeId": volume_id})
        db.commit()
        work = _get_work(db, work_id)
        return ok({"book": _work_view(db, work, user.id) if work else None, "workId": work_id, "volumeId": volume_id})
    work = _get_work(db, work_id)
    return ok({"book": _work_view(db, work, user.id) if work else None, "workId": work_id, "editionId": edition_id, "volumeId": volume_id})


@router.get("/tracking/release-title-parser")
def release_title_parser_get(request: Request, title: str = "", db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    volume_info = parse_series_volume_info(Path(f"{title}.epub"), f"{title}.epub", "MANUAL")
    chapter = re.search(r"(?:ch(?:apter)?\.?|第)\s*(\d+(?:\.\d+)?)\s*(?:话|章|ch)?", title, flags=re.IGNORECASE)
    return ok({"parsed": {"title": title, "volume": volume_info.series_index if volume_info else None, "chapter": float(chapter.group(1)) if chapter else None}})


@router.post("/tracking/release-title-parser")
async def release_title_parser(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    title = str(payload.get("title") or "")
    volume_info = parse_series_volume_info(Path(f"{title}.epub"), f"{title}.epub", "MANUAL")
    chapter = re.search(r"(?:ch(?:apter)?\.?|第)\s*(\d+(?:\.\d+)?)\s*(?:话|章|ch)?", title, flags=re.IGNORECASE)
    return ok({"parsed": {"title": title, "volume": volume_info.series_index if volume_info else None, "chapter": float(chapter.group(1)) if chapter else None}})
