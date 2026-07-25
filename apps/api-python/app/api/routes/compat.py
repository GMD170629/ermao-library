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
from sqlalchemy import inspect, text
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
    edition_visibility_sql,
    monitor_folder_visibility_sql,
    work_visibility_sql,
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
from app.services.download_executor import (
    create_remote_ref_from_search_record,
    execute_download_task,
    find_active_download_task,
    has_usable_download_meta,
    infer_download_task_type,
)
from app.services.health import run_system_health_checks
from app.services.library_filters import compile_filter_rules, library_filter_schema, normalize_filter_rules
from app.services.library_management import (
    count_categories,
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
from app.services.organize_scheduler import (
    delete_organize_job,
    get_organize_policy,
    list_organize_runs,
    organize_candidate_summary,
    recognize_organize_job,
    update_organize_policy,
)
from app.services.source_providers import PROVIDER_CAPABILITIES, search_source_provider, test_source_provider
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
from app.worker.importer import is_supported_import_file, parse_comic_archive, parse_series_volume_info
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
    task = (
        _row(db, "SELECT * FROM `ImportTask` WHERE `id` = :id", {"id": task_id})
        if _has_table(db, "ImportTask")
        else None
    )
    if task is None or not can_access_monitor_folder(db, user, task.get("monitorFolderId")):
        return None
    return task


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [_normalize_row(dict(row)) for row in db.execute(text(sql), params or {}).mappings().all()]


def _row(db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = db.execute(text(sql), params or {}).mappings().first()
    return _normalize_row(dict(result)) if result else None


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


def _scalar(db: Session, sql: str, params: dict[str, Any] | None = None, default: Any = 0) -> Any:
    try:
        value = db.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        return default


def _table_count(db: Session, table: str, where: str = "", params: dict[str, Any] | None = None) -> int:
    if not _has_table(db, table):
        return 0
    suffix = f" WHERE {where}" if where else ""
    return int(_scalar(db, f"SELECT COUNT(*) FROM `{table}`{suffix}", params, 0))


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


SOURCE_PROVIDER_LABELS = {
    "manual": "手动源",
    "http": "HTTP",
    "pt_rss": "PT RSS",
    "rss": "RSS",
    "comic_api": "漫画 API",
}

ACTIVE_SOURCE_PROVIDER = "__removed__"

SOURCE_KIND_LABELS = {
    "novel": "小说",
    "comic": "漫画",
    "mixed": "混合",
    "metadata": "元数据",
    "search": "搜索",
}

MASKED_SECRET = "********"


def _masked_secret(value: Any) -> dict[str, Any] | None:
    return {"configured": True, "masked": MASKED_SECRET} if isinstance(value, str) and value.strip() else None


def _is_masked_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("configured") is True
    return isinstance(value, str) and value.strip() == MASKED_SECRET


def _source_config_for_client(source: dict[str, Any]) -> dict[str, Any]:
    config = _parse_json(source.get("config"), {})
    if not isinstance(config, dict):
        return {}
    if source.get("providerType") == ACTIVE_SOURCE_PROVIDER and config.get("password"):
        config = {**config, "password": _masked_secret(config.get("password"))}
    return config


def _source_view(source: dict[str, Any]) -> dict[str, Any]:
    provider_type = source.get("providerType") or "manual"
    kind = source.get("kind") or "mixed"
    return {
        **source,
        "config": _source_config_for_client(source),
        "capabilities": _parse_json(source.get("capabilities"), {}),
        "rateLimit": _parse_json(source.get("rateLimit"), {}),
        "providerTypeLabel": SOURCE_PROVIDER_LABELS.get(provider_type, str(provider_type)),
        "kindLabel": SOURCE_KIND_LABELS.get(kind, str(kind)),
    }


def _active_source(db: Session, source_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "Source"):
        return None
    return _row(
        db,
        "SELECT * FROM `Source` WHERE `id` = :id AND `providerType` = :provider_type",
        {"id": source_id, "provider_type": ACTIVE_SOURCE_PROVIDER},
    )


def _merge_source_config_for_write(existing: dict[str, Any] | None, provider_type: str, incoming: Any) -> Any:
    config = _parse_json(incoming, {}) if not isinstance(incoming, dict) else incoming
    if not isinstance(config, dict):
        return config
    if provider_type != ACTIVE_SOURCE_PROVIDER:
        return config
    password = config.get("password")
    if password is None or password == "" or _is_masked_secret(password):
        existing_config = _parse_json((existing or {}).get("config"), {})
        if isinstance(existing_config, dict) and existing_config.get("password"):
            return {**config, "password": existing_config.get("password")}
        return {key: value for key, value in config.items() if key != "password"}
    return config


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
    value = None
    if _has_table(db, "SystemSetting"):
        row = _row(db, "SELECT `value` FROM `SystemSetting` WHERE `key` = :key", {"key": "workDetail.tabOrder"})
        value = (row or {}).get("value")
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
    row = _row(
        db,
        "SELECT `selectedTab` FROM `WorkDetailPreference` WHERE `userId` = :user_id AND `workId` = :work_id",
        {"user_id": user_id, "work_id": work_id},
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
    existing = _row(
        db,
        "SELECT * FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id AND `mediaKind` = :media_kind",
        {"user_id": user_id, "work_id": work_id, "media_kind": media_kind},
    )
    edition_changed = bool(edition_id and existing and edition_id != existing.get("lastEditionId"))
    volume_changed = bool(
        volume_id is not None
        and (existing or {}).get("lastVolumeId") is not None
        and volume_id != (existing or {}).get("lastVolumeId")
    )
    values = {
        "status": status,
        "lastEditionId": edition_id or (existing or {}).get("lastEditionId"),
        "lastVolumeId": volume_id if volume_id is not None else None if edition_changed else (existing or {}).get("lastVolumeId"),
        "lastUnitId": unit_id if unit_id is not None else None if edition_changed or volume_changed else (existing or {}).get("lastUnitId"),
        "updatedAt": now,
    }
    if existing:
        assignments = ", ".join(f"`{key}` = :{key}" for key in values)
        db.execute(text(f"UPDATE `LibraryConsumptionState` SET {assignments} WHERE `id` = :id"), {**values, "id": existing["id"]})
    else:
        db.execute(
            text(
                "INSERT INTO `LibraryConsumptionState` "
                "(`id`, `userId`, `workId`, `mediaKind`, `status`, `lastEditionId`, `lastVolumeId`, `lastUnitId`, `createdAt`, `updatedAt`) "
                "VALUES (:id, :user_id, :work_id, :media_kind, :status, :lastEditionId, :lastVolumeId, :lastUnitId, :now, :now)"
            ),
            {
                "id": f"consume_{time_ns()}",
                "user_id": user_id,
                "work_id": work_id,
                "media_kind": media_kind,
                "now": now,
                **values,
            },
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
        edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
        if (
            not edition
            or str(edition.get("workId")) != work_id
            or _edition_media_kind(edition) != media_kind
            or bool(edition.get("hidden"))
        ):
            return None, "editionId 不属于该作品的当前媒介"

    if volume_id:
        volume = _row(
            db,
            "SELECT volume.*, edition.`workId`, edition.`mediaKind`, edition.`format`, edition.`hidden` AS `editionHidden` "
            "FROM `LibraryVolume` volume JOIN `LibraryEdition` edition ON edition.`id` = volume.`editionId` "
            "WHERE volume.`id` = :id",
            {"id": volume_id},
        )
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
        unit = _row(
            db,
            "SELECT unit.*, edition.`workId`, edition.`mediaKind`, edition.`format`, edition.`hidden` AS `editionHidden` "
            "FROM `LibraryReadingUnit` unit JOIN `LibraryEdition` edition ON edition.`id` = unit.`editionId` "
            "WHERE unit.`id` = :id",
            {"id": unit_id},
        )
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
    edition_scope = "1 = 1"
    edition_params: dict[str, Any] = {"work_id": work_id}
    if user is not None:
        edition_scope, scope_params = edition_visibility_sql(
            authorization_context(db, user),
            alias="e",
            prefix="status_projection",
        )
        edition_params.update(scope_params)
    edition_rows = _rows(
        db,
        "SELECT e.* FROM `LibraryEdition` e WHERE e.`workId` = :work_id "
        f"AND COALESCE(e.`hidden`, 0) = 0 AND {edition_scope}",
        edition_params,
    )
    media_kinds = {_edition_media_kind(item) for item in edition_rows}
    states = {
        str(item.get("mediaKind")): _reading_status(item.get("status"))
        for item in _rows(
            db,
            "SELECT `mediaKind`, `status` FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id",
            {"user_id": user_id, "work_id": work_id},
        )
    }
    if not any(kind in states for kind in media_kinds):
        return "UNREAD"
    if media_kinds and all(states.get(kind) == "FINISHED" for kind in media_kinds):
        return "FINISHED"
    if any(states.get(kind) in {"READING", "FINISHED"} for kind in media_kinds):
        return "READING"
    return "UNREAD"


def _user_status_filter_sql(
    db: Session,
    status: str,
    context: Any,
) -> tuple[str | None, dict[str, Any]]:
    """Build the current-user aggregate status filter for LibraryWork."""

    if not (_has_table(db, "LibraryConsumptionState") and _has_table(db, "LibraryEdition")):
        if status == "UNREAD":
            return "`status` IN ('UNREAD', 'WANT')", {}
        if status in {"READING", "FINISHED"}:
            return "`status` = :status", {}
        return None, {}
    edition_scope, scope_params = edition_visibility_sql(
        context,
        alias="edition_state",
        prefix="status_filter",
    )
    media_expression = (
        "edition_state.`mediaKind`"
        if _has_column(db, "LibraryEdition", "mediaKind")
        else "CASE WHEN edition_state.`format` = 'COMIC' THEN 'COMIC' WHEN edition_state.`format` = 'AUDIO' THEN 'AUDIOBOOK' ELSE 'EBOOK' END"
    )
    visible_state_exists = (
        "EXISTS (SELECT 1 FROM `LibraryConsumptionState` consumption_state "
        "WHERE consumption_state.`userId` = :current_user_id "
        "AND consumption_state.`workId` = `LibraryWork`.`id` "
        "AND EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        "WHERE edition_state.`workId` = `LibraryWork`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope} AND {media_expression} = consumption_state.`mediaKind`))"
    )
    any_visible_edition = (
        "EXISTS (SELECT 1 FROM `LibraryEdition` edition_state WHERE edition_state.`workId` = `LibraryWork`.`id` "
        f"AND COALESCE(edition_state.`hidden`, 0) = 0 AND {edition_scope})"
    )
    all_finished = (
        f"({any_visible_edition} AND NOT EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        "WHERE edition_state.`workId` = `LibraryWork`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope} AND NOT EXISTS (SELECT 1 FROM `LibraryConsumptionState` finished_state "
        "WHERE finished_state.`userId` = :current_user_id AND finished_state.`workId` = `LibraryWork`.`id` "
        f"AND finished_state.`mediaKind` = {media_expression} AND finished_state.`status` = 'FINISHED')))"
    )
    has_started = (
        "EXISTS (SELECT 1 FROM `LibraryConsumptionState` started_state "
        "WHERE started_state.`userId` = :current_user_id AND started_state.`workId` = `LibraryWork`.`id` "
        "AND started_state.`status` IN ('READING', 'FINISHED') "
        "AND EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        "WHERE edition_state.`workId` = `LibraryWork`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope} AND {media_expression} = started_state.`mediaKind`))"
    )
    if status == "FINISHED":
        return f"({visible_state_exists} AND {all_finished})", scope_params
    if status == "READING":
        return f"({visible_state_exists} AND NOT {all_finished} AND {has_started})", scope_params
    if status == "UNREAD":
        return f"(NOT {has_started})", scope_params
    return None, scope_params


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
    chapter = (
        _row(db, "SELECT `title` FROM `LibraryReadingUnit` WHERE `id` = :id", {"id": chapter_id})
        if chapter_id and _has_table(db, "LibraryReadingUnit")
        else None
    )
    prefix = f"{chapter.get('title')} · " if chapter and chapter.get("title") else ""
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


def _work_view(db: Session, work: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    editions = []
    files_by_edition: dict[str, list[dict[str, Any]]] = {}
    volumes_by_edition: dict[str, list[dict[str, Any]]] = {}
    progresses_by_edition: dict[str, list[dict[str, Any]]] = {}
    conversion_by_edition: dict[str, dict[str, Any]] = {}
    if _has_table(db, "LibraryEdition"):
        edition_where = "1 = 1"
        edition_params: dict[str, Any] = {"work_id": work["id"]}
        user = db.get(User, user_id) if user_id else None
        if user is not None:
            context = authorization_context(db, user)
            edition_where, scope_params = edition_visibility_sql(
                context,
                alias="LibraryEdition",
                prefix="work_view",
            )
            edition_params.update(scope_params)
        editions = _rows(
            db,
            "SELECT * FROM `LibraryEdition` WHERE `workId` = :work_id AND `hidden` = 0 "
            f"AND {edition_where} ORDER BY `primary` DESC, `createdAt` ASC",
            edition_params,
        )
    edition_ids = [item["id"] for item in editions]
    if edition_ids and _has_table(db, "LibraryFile"):
        for edition in editions:
            files_by_edition[edition["id"]] = _rows(
                db,
                "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC",
                {"edition_id": edition["id"]},
            )
    if edition_ids and _has_table(db, "LibraryVolume"):
        for edition in editions:
            volumes_by_edition[edition["id"]] = _rows(
                db,
                "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC",
                {"edition_id": edition["id"]},
            )
    if edition_ids and _has_table(db, "LibraryMetadata"):
        for edition in editions:
            conversion_metadata = _row(
                db,
                "SELECT `rawJson` FROM `LibraryMetadata` WHERE `editionId` = :edition_id AND `source` = 'conversion' ORDER BY `createdAt` DESC LIMIT 1",
                {"edition_id": edition["id"]},
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
            progresses = _rows(
                db,
                "SELECT * FROM `LibraryReadingProgress` WHERE `editionId` = :edition_id AND `userId` = :user_id ORDER BY `updatedAt` DESC",
                {"edition_id": edition["id"], "user_id": user_id},
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
        _rows(
            db,
            "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND (:volume_id IS NULL OR `volumeId` = :volume_id) ORDER BY `sortOrder` ASC",
            {"edition_id": progress_edition["id"], "volume_id": progress.get("volumeId") if progress else None},
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
            _rows(
                db,
                "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND `volumeId` = :volume_id ORDER BY `sortOrder` ASC",
                {"edition_id": volume["editionId"], "volume_id": volume["id"]},
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
            for item in _rows(
                db,
                "SELECT * FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id",
                {"user_id": user_id, "work_id": work["id"]},
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
        _row(
            db,
            "SELECT `status`, `resultSource`, `errorSummary` FROM `MetadataLookupTask` WHERE `workId` = :work_id ORDER BY `createdAt` DESC, `id` DESC LIMIT 1",
            {"work_id": work["id"]},
        )
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
    if not _has_table(db, "LibraryWork"):
        return None
    return _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": work_id})


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
        _rows(
            db,
            "SELECT * FROM `LibraryReadingProgress` WHERE `editionId` = :edition_id AND `userId` = :user_id ORDER BY `updatedAt` DESC, `id` DESC",
            {"edition_id": edition_id, "user_id": user_id},
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


def _set_columns(db: Session, table: str) -> set[str]:
    if not _has_table(db, table):
        return set()
    return {column["name"] for column in inspect(db.connection()).get_columns(table)}


def _insert(db: Session, table: str, values: dict[str, Any]) -> dict[str, Any]:
    columns = _set_columns(db, table)
    values = {key: value for key, value in values.items() if key in columns}
    keys = ", ".join(f"`{key}`" for key in values)
    params = ", ".join(f":{key}" for key in values)
    db.execute(text(f"INSERT INTO `{table}` ({keys}) VALUES ({params})"), values)
    db.commit()
    id_key = "id" if "id" in values else "key"
    return _row(db, f"SELECT * FROM `{table}` WHERE `{id_key}` = :value", {"value": values[id_key]}) or values


def _update(db: Session, table: str, row_id: str, values: dict[str, Any], id_column: str = "id") -> dict[str, Any] | None:
    columns = _set_columns(db, table)
    values = {key: value for key, value in values.items() if key in columns and key != id_column}
    if values:
        values["row_id"] = row_id
        assignments = ", ".join(f"`{key}` = :{key}" for key in values if key != "row_id")
        db.execute(text(f"UPDATE `{table}` SET {assignments} WHERE `{id_column}` = :row_id"), values)
        db.commit()
    return _row(db, f"SELECT * FROM `{table}` WHERE `{id_column}` = :row_id", {"row_id": row_id})


def _update_where(db: Session, table: str, where_sql: str, params: dict[str, Any], values: dict[str, Any]) -> int:
    columns = _set_columns(db, table)
    values = {key: value for key, value in values.items() if key in columns}
    if not values:
        return 0
    assignments = ", ".join(f"`{key}` = :set_{key}" for key in values)
    update_params = {**params, **{f"set_{key}": value for key, value in values.items()}}
    result = db.execute(text(f"UPDATE `{table}` SET {assignments} WHERE {where_sql}"), update_params)
    db.commit()
    return int(result.rowcount or 0)


def _delete(db: Session, table: str, row_id: str, id_column: str = "id") -> bool:
    if not _has_table(db, table):
        return False
    result = db.execute(text(f"DELETE FROM `{table}` WHERE `{id_column}` = :row_id"), {"row_id": row_id})
    db.commit()
    return bool(result.rowcount)


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

    if _has_table(db, "LibraryWork"):
        work = _row(db, "SELECT `coverPath` FROM `LibraryWork` WHERE `id` = :work_id", {"work_id": work_id})
        add((work or {}).get("coverPath"))
    if not _has_table(db, "LibraryEdition"):
        return list(dict.fromkeys(paths))

    editions = _rows(db, "SELECT `id`, `coverPath` FROM `LibraryEdition` WHERE `workId` = :work_id", {"work_id": work_id})
    edition_ids = [edition["id"] for edition in editions]
    for edition in editions:
        add(edition.get("coverPath"))
    if not edition_ids:
        return list(dict.fromkeys(paths))

    for edition_id in edition_ids:
        if _has_table(db, "LibraryVolume"):
            volumes = _rows(db, "SELECT `coverPath` FROM `LibraryVolume` WHERE `editionId` = :edition_id", {"edition_id": edition_id})
            for volume in volumes:
                add(volume.get("coverPath"))
        if _has_table(db, "LibraryFile"):
            files = _rows(db, "SELECT `path` FROM `LibraryFile` WHERE `editionId` = :edition_id", {"edition_id": edition_id})
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
    if _has_table(db, "MonitorFolder"):
        roots.extend(
            Path(str(row["rootPath"])).expanduser()
            for row in _rows(db, "SELECT `rootPath` FROM `MonitorFolder` WHERE `rootPath` IS NOT NULL")
            if str(row.get("rootPath") or "").strip()
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

    if _has_table(db, "ImportTask"):
        for task in _rows(db, "SELECT `sourcePath` FROM `ImportTask` WHERE `workId` = :work_id", {"work_id": work_id}):
            add(task.get("sourcePath"), delete_roots)
    # Older records may not retain an ImportTask link. In that case a library
    # file living in a monitor folder is the best available source-file signal.
    if not paths and _has_table(db, "LibraryEdition") and _has_table(db, "LibraryFile"):
        monitor_roots = _monitor_source_roots(db, settings)
        for file in _rows(
            db,
            "SELECT f.`path` FROM `LibraryFile` f JOIN `LibraryEdition` e ON e.`id` = f.`editionId` WHERE e.`workId` = :work_id",
            {"work_id": work_id},
        ):
            add(file.get("path"), monitor_roots)
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
    if not _has_table(db, "LibraryWork"):
        return {"deleted": False, "deletedDatabaseRecords": 0}

    params = {"work_id": work_id}
    deleted_records = 0

    def delete_where(table: str, where_sql: str) -> None:
        nonlocal deleted_records
        if not _has_table(db, table):
            return
        result = db.execute(text(f"DELETE FROM `{table}` WHERE {where_sql}"), params)
        deleted_records += int(result.rowcount or 0)

    has_editions = _has_table(db, "LibraryEdition")
    edition_ids_sql = "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id"
    volume_ids_sql = f"SELECT `id` FROM `LibraryVolume` WHERE `editionId` IN ({edition_ids_sql})"
    file_ids_sql = f"SELECT `id` FROM `LibraryFile` WHERE `editionId` IN ({edition_ids_sql})"
    linked_scope = "`workId` = :work_id"
    if has_editions:
        linked_scope += f" OR `editionId` IN ({edition_ids_sql}) OR `volumeId` IN ({volume_ids_sql})"

    # Clear nullable references first so deletion remains correct even when SQLite
    # foreign-key enforcement is disabled in an existing installation.
    if _has_table(db, "ImportTask"):
        db.execute(
            text(
                "UPDATE `ImportTask` SET `workId` = NULL, `editionId` = NULL, `volumeId` = NULL "
                f"WHERE {linked_scope}"
            ),
            params,
        )
    if _has_table(db, "KindleSendTask"):
        db.execute(
            text(
                "UPDATE `KindleSendTask` SET `workId` = NULL, `editionId` = NULL, `volumeId` = NULL, `fileId` = NULL "
                f"WHERE {linked_scope}{f' OR `fileId` IN ({file_ids_sql})' if has_editions else ''}"
            ),
            params,
        )
    if _has_table(db, "DownloadTask") and _has_column(db, "DownloadTask", "bookId"):
        db.execute(text("UPDATE `DownloadTask` SET `bookId` = NULL WHERE `bookId` = :work_id"), params)

    if _has_table(db, "OrganizeJob"):
        job_ids_sql = "SELECT `id` FROM `OrganizeJob` WHERE `workId` = :work_id"
        if _has_table(db, "MetadataSuggestion"):
            delete_where("MetadataSuggestion", f"`jobId` IN ({job_ids_sql})")
        if _has_table(db, "DuplicateCandidate"):
            delete_where("DuplicateCandidate", f"`jobId` IN ({job_ids_sql}) OR `targetWorkId` = :work_id")
    elif _has_table(db, "DuplicateCandidate"):
        delete_where("DuplicateCandidate", "`targetWorkId` = :work_id")

    delete_where("MetadataLookupTask", "`workId` = :work_id")
    delete_where("OrganizeJob", "`workId` = :work_id")
    delete_where("ReaderBookPreference", "`workId` = :work_id")
    delete_where("ReaderProgressCursor", "`workId` = :work_id")
    delete_where("WorkDetailPreference", "`workId` = :work_id")
    delete_where("LibraryConsumptionState", "`workId` = :work_id")
    delete_where("ShelfWork", "`workId` = :work_id")
    delete_where("LibraryReadingProgress", "`workId` = :work_id")

    if has_editions:
        delete_where("LibraryReadingUnit", f"`editionId` IN ({edition_ids_sql})")
        delete_where("LibraryMetadata", f"`editionId` IN ({edition_ids_sql})")
        delete_where("LibraryFile", f"`editionId` IN ({edition_ids_sql})")
        delete_where("LibraryVolume", f"`editionId` IN ({edition_ids_sql})")
        delete_where("LibraryEdition", "`workId` = :work_id")

    result = db.execute(text("DELETE FROM `LibraryWork` WHERE `id` = :work_id"), params)
    deleted = bool(result.rowcount)
    deleted_records += int(result.rowcount or 0)
    db.commit()
    return {"deleted": deleted, "deletedDatabaseRecords": deleted_records}


def _delete_work_and_storage(db: Session, work_id: str, settings: Settings, *, delete_source: bool = False) -> dict[str, Any]:
    managed_paths = _collect_work_storage_paths(db, work_id, settings)
    source_paths = _collect_work_source_paths(db, work_id, settings)
    managed_paths = [path for path in managed_paths if path not in source_paths]
    record_cleanup = _delete_work_records(db, work_id)
    deleted = bool(record_cleanup["deleted"])
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

    edition = _row(
        db,
        "SELECT * FROM `LibraryEdition` WHERE `id` = :edition_id AND `workId` = :work_id",
        {"edition_id": edition_id, "work_id": work_id},
    )
    if not edition:
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    managed_paths: list[Path] = []
    deleted_records = 0

    def add_path(value: Any) -> None:
        path = _storage_managed_path(str(value), settings) if value else None
        if path:
            managed_paths.append(path)

    def execute_delete(table: str, where_sql: str, params: dict[str, Any]) -> None:
        nonlocal deleted_records
        if not _has_table(db, table):
            return
        result = db.execute(text(f"DELETE FROM `{table}` WHERE {where_sql}"), params)
        deleted_records += int(result.rowcount or 0)

    def clear_file_references(file_ids: list[str]) -> None:
        if not file_ids:
            return
        placeholders = ", ".join(f":file_{index}" for index in range(len(file_ids)))
        params = {f"file_{index}": file_id for index, file_id in enumerate(file_ids)}
        if _has_table(db, "ImportAsset"):
            db.execute(text(f"UPDATE `ImportAsset` SET `fileId` = NULL WHERE `fileId` IN ({placeholders})"), params)
        if _has_table(db, "KindleSendTask"):
            db.execute(text(f"UPDATE `KindleSendTask` SET `fileId` = NULL WHERE `fileId` IN ({placeholders})"), params)

    def delete_edition_scope(target_edition_id: str) -> None:
        nonlocal deleted_records
        params = {"edition_id": target_edition_id}
        files = _rows(db, "SELECT `id`, `path` FROM `LibraryFile` WHERE `editionId` = :edition_id", params) if _has_table(db, "LibraryFile") else []
        volumes = _rows(db, "SELECT `coverPath` FROM `LibraryVolume` WHERE `editionId` = :edition_id", params) if _has_table(db, "LibraryVolume") else []
        add_path(edition.get("coverPath"))
        for item in files:
            add_path(item.get("path"))
        for item in volumes:
            add_path(item.get("coverPath"))
        clear_file_references([str(item["id"]) for item in files])
        if _has_table(db, "ImportTask"):
            db.execute(text("UPDATE `ImportTask` SET `editionId` = NULL, `volumeId` = NULL WHERE `editionId` = :edition_id"), params)
        if _has_table(db, "KindleSendTask"):
            db.execute(text("UPDATE `KindleSendTask` SET `editionId` = NULL, `volumeId` = NULL WHERE `editionId` = :edition_id"), params)
        if _has_table(db, "LibraryConsumptionState"):
            db.execute(text("UPDATE `LibraryConsumptionState` SET `lastEditionId` = NULL, `lastVolumeId` = NULL, `lastUnitId` = NULL WHERE `lastEditionId` = :edition_id"), params)
        execute_delete("LibraryReadingProgress", "`editionId` = :edition_id", params)
        execute_delete("LibraryReadingUnit", "`editionId` = :edition_id", params)
        execute_delete("LibraryMetadata", "`editionId` = :edition_id", params)
        execute_delete("LibraryFile", "`editionId` = :edition_id", params)
        execute_delete("LibraryVolume", "`editionId` = :edition_id", params)
        execute_delete("LibraryEdition", "`id` = :edition_id", params)

    deleted_scope = False
    if volume_id and _has_table(db, "LibraryVolume"):
        volume = _row(
            db,
            "SELECT * FROM `LibraryVolume` WHERE `id` = :volume_id AND `editionId` = :edition_id",
            {"volume_id": volume_id, "edition_id": edition_id},
        )
        if volume:
            params = {"volume_id": volume_id}
            files = _rows(db, "SELECT `id`, `path` FROM `LibraryFile` WHERE `volumeId` = :volume_id", params) if _has_table(db, "LibraryFile") else []
            add_path(volume.get("coverPath"))
            for item in files:
                add_path(item.get("path"))
            clear_file_references([str(item["id"]) for item in files])
            if _has_table(db, "ImportTask"):
                db.execute(text("UPDATE `ImportTask` SET `volumeId` = NULL WHERE `volumeId` = :volume_id"), params)
            if _has_table(db, "KindleSendTask"):
                db.execute(text("UPDATE `KindleSendTask` SET `volumeId` = NULL WHERE `volumeId` = :volume_id"), params)
            if _has_table(db, "LibraryConsumptionState"):
                db.execute(text("UPDATE `LibraryConsumptionState` SET `lastVolumeId` = NULL, `lastUnitId` = NULL WHERE `lastVolumeId` = :volume_id"), params)
            execute_delete("LibraryReadingProgress", "`volumeId` = :volume_id", params)
            execute_delete("LibraryReadingUnit", "`volumeId` = :volume_id", params)
            execute_delete("LibraryFile", "`volumeId` = :volume_id", params)
            execute_delete("LibraryVolume", "`id` = :volume_id", params)
            deleted_scope = True

            remaining_volumes = _table_count(db, "LibraryVolume", "`editionId` = :edition_id", {"edition_id": edition_id})
            remaining_files = _table_count(db, "LibraryFile", "`editionId` = :edition_id", {"edition_id": edition_id})
            if remaining_volumes == 0 and remaining_files == 0:
                delete_edition_scope(edition_id)
    else:
        delete_edition_scope(edition_id)
        deleted_scope = True

    if not deleted_scope:
        return {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}

    remaining_editions = _table_count(db, "LibraryEdition", "`workId` = :work_id", {"work_id": work_id})
    deleted_work = remaining_editions == 0
    if deleted_work:
        work_cleanup = _delete_work_records(db, work_id)
        deleted_records += int(work_cleanup.get("deletedDatabaseRecords") or 0)
    else:
        primary = _row(
            db,
            "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id ORDER BY COALESCE(`primary`, 0) DESC, `createdAt`, `id` LIMIT 1",
            {"work_id": work_id},
        )
        primary_id = str(primary["id"]) if primary else None
        if primary_id:
            db.execute(text("UPDATE `LibraryEdition` SET `primary` = CASE WHEN `id` = :primary_id THEN 1 ELSE 0 END WHERE `workId` = :work_id"), {"primary_id": primary_id, "work_id": work_id})
        cover_path = _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings)
        _update(db, "LibraryWork", work_id, {
            "primaryEditionId": primary_id,
            "coverPath": cover_path,
            "coverStatus": cover_status(cover_path, settings),
            "updatedAt": _now(),
        })
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
    if not _has_table(db, "MonitorFolder"):
        return None
    params: dict[str, Any] = {"root_path": root_path}
    sql = "SELECT * FROM `MonitorFolder` WHERE `rootPath` = :root_path"
    if exclude_id is not None:
        sql += " AND `id` != :exclude_id"
        params["exclude_id"] = exclude_id
    return _row(db, f"{sql} LIMIT 1", params)


def _optional_shelf_id(db: Session, value: Any) -> tuple[str | None, str | None]:
    shelf_id = str(value or "").strip()
    if not shelf_id:
        return None, None
    if not _has_table(db, "Shelf") or not _row(db, "SELECT `id` FROM `Shelf` WHERE `id` = :id", {"id": shelf_id}):
        return None, "选择的目标书架不存在，请重新选择"
    return shelf_id, None


def _system_setting_value(db: Session, key: str) -> str | None:
    if not _has_table(db, "SystemSetting"):
        return None
    row = _row(db, "SELECT `value` FROM `SystemSetting` WHERE `key` = :key", {"key": key})
    value = (row or {}).get("value")
    parsed = _parse_json(value, value)
    return str(parsed).strip() if parsed is not None and str(parsed).strip() else None


def _enabled_monitor_folder_for_path(db: Session, target: Path) -> dict[str, Any] | None:
    if not _has_table(db, "MonitorFolder"):
        return None
    try:
        real_target = target.expanduser().resolve()
    except OSError:
        return None
    for folder in _rows(db, "SELECT * FROM `MonitorFolder` WHERE `enabled` = 1 ORDER BY `createdAt` DESC"):
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if root == real_target or _is_inside_path(root, real_target):
            return folder
    return None


def _save_system_setting(db: Session, key: str, value: Any) -> None:
    if not _has_table(db, "SystemSetting"):
        return
    now = _now()
    serialized = _json_text(value)
    existing = _row(db, "SELECT `key` FROM `SystemSetting` WHERE `key` = :key", {"key": key})
    if existing:
        db.execute(text("UPDATE `SystemSetting` SET `value` = :value, `updatedAt` = :updated_at WHERE `key` = :key"), {"key": key, "value": serialized, "updated_at": now})
    else:
        db.execute(
            text("INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, :created_at, :updated_at)"),
            {"key": key, "value": serialized, "created_at": now, "updated_at": now},
        )


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
    work_scope, work_params = work_visibility_sql(context, alias="LibraryWork", prefix="dashboard")
    total_books = _table_count(db, "LibraryWork", f"`hidden` = 0 AND {work_scope}", work_params)
    comic_books = _table_count(db, "LibraryWork", f"`hidden` = 0 AND `workType` = 'COMIC' AND {work_scope}", work_params)
    novel_books = _table_count(db, "LibraryWork", f"`hidden` = 0 AND `workType` = 'EPUB' AND {work_scope}", work_params)
    edition_scope, edition_params = edition_visibility_sql(context, alias="LibraryEdition", prefix="dashboard_storage")
    storage = _scalar(
        db,
        f"SELECT COALESCE(SUM(`sizeBytes`), 0) FROM `LibraryEdition` WHERE `hidden` = 0 AND {edition_scope}",
        edition_params,
        default=0,
    ) if _has_table(db, "LibraryEdition") else 0
    import_scope, import_params = monitor_folder_visibility_sql(
        context,
        "`monitorFolderId`",
        prefix="dashboard_import",
    )
    last_import = _row(
        db,
        "SELECT `finishedAt`, `updatedAt` FROM `ImportTask` WHERE `status` = 'COMPLETED' "
        f"AND {import_scope} "
        f"ORDER BY {_timestamp_sql('`finishedAt`')} DESC, `id` DESC LIMIT 1",
        import_params,
    ) if _has_table(db, "ImportTask") else None
    latest_progress = _row(
        db,
        "SELECT `updatedAt` FROM `LibraryReadingProgress` WHERE `userId` = :user_id ORDER BY `updatedAt` DESC LIMIT 1",
        {"user_id": user.id},
    ) if _has_table(db, "LibraryReadingProgress") else None
    return ok(
        {
            "totalBooks": total_books,
            "comicBooks": comic_books,
            "novelBooks": novel_books,
            "storageUsedBytes": int(storage or 0),
            "monitorFolderCount": (
                _table_count(db, "MonitorFolder", "`enabled` = 1")
                if context.is_admin
                else len(context.monitor_folder_ids)
            ),
            "lastImportAt": _dt((last_import or {}).get("finishedAt") or (last_import or {}).get("updatedAt")),
            "latestSyncAt": _dt((latest_progress or {}).get("updatedAt")),
        }
    )


@router.get("/dashboard/recent-books")
def dashboard_recent_books(request: Request, limit: int = 5, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    take = min(24, max(1, limit))
    context = authorization_context(db, user)
    scope, params = work_visibility_sql(context, alias="LibraryWork", prefix="recent")
    params["take"] = take
    works = _rows(
        db,
        f"SELECT * FROM `LibraryWork` WHERE `hidden` = 0 AND {scope} ORDER BY `createdAt` DESC LIMIT :take",
        params,
    ) if _has_table(db, "LibraryWork") else []
    return ok({"books": [_work_view(db, work, user.id) for work in works]})


@router.get("/dashboard/continue-reading")
def dashboard_continue_reading(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    progress = None
    if _has_table(db, "LibraryReadingProgress") and _has_table(db, "LibraryWork"):
        context = authorization_context(db, user)
        scope, scope_params = work_visibility_sql(context, alias="w", prefix="continue")
        progress = _row(
            db,
            "SELECT p.* FROM `LibraryReadingProgress` p "
            "JOIN `LibraryWork` w ON w.`id` = p.`workId` "
            "WHERE p.`userId` = :user_id AND p.`percent` > 0 AND p.`percent` < 100 AND w.`hidden` = 0 "
            f"AND {scope} "
            "ORDER BY p.`updatedAt` DESC LIMIT 1",
            {"user_id": user.id, **scope_params},
        )
    if not progress:
        return ok({"item": None})
    work = _get_work(db, progress["workId"])
    if not work or work.get("hidden"):
        return ok({"item": None})
    book = _work_view(db, work, user.id)
    return ok({"item": {"book": book, "progress": book.get("progress") or 0, "lastReadAt": _dt(progress.get("updatedAt")), "chapter": book.get("chapter") if book.get("chapter") != "未开始" else None, "position": progress.get("position")}})


@router.get("/dashboard/system-status")
def dashboard_system_status(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    health = run_system_health_checks(db, settings)
    checks = {item["name"]: item for item in health["checks"]}
    enabled = _rows(db, "SELECT * FROM `MonitorFolder` WHERE `enabled` = 1 ORDER BY `createdAt` DESC") if _has_table(db, "MonitorFolder") else []
    current_task = _row(
        db,
        "SELECT * FROM `ImportTask` WHERE `status` IN ('PENDING', 'PARSING') "
        f"ORDER BY {_timestamp_sql('`createdAt`')} ASC, `id` ASC LIMIT 1",
    ) if _has_table(db, "ImportTask") else None
    latest_task = _row(
        db,
        f"SELECT * FROM `ImportTask` ORDER BY {_timestamp_sql('`createdAt`')} DESC, `id` DESC LIMIT 1",
    ) if _has_table(db, "ImportTask") else None
    return ok(
        {
            "database": checks.get("database", {"status": "unknown", "message": "待检测"}),
            "worker": {"status": "ok", "message": "正在监听监控文件夹"} if enabled else {"status": "unknown", "message": "未启用监控文件夹"},
            "enabledMonitorFolders": enabled,
            "currentImportTask": current_task,
            "latestImportTask": latest_task,
            "errorFileCount": _table_count(db, "ImportTask", "`status` = 'FAILED'"),
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
    failed_imports = _table_count(db, "ImportTask", "`status` = 'FAILED'")
    failed_downloads = _table_count(db, "DownloadTask", "`status` = 'failed'")
    pending_organize = _table_count(db, "LibraryWork", "`hidden` = 0 AND `organizeStatus` IN ('PENDING', 'REVIEWING')")
    managed_files = _rows(db, "SELECT `path` FROM `LibraryFile`") if _has_table(db, "LibraryFile") else []
    file_paths = {str(item.get("path") or "") for item in managed_files if item.get("path")}
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
    recent_events = _rows(db, "SELECT * FROM `SystemEvent` ORDER BY `createdAt` DESC LIMIT 8") if _has_table(db, "SystemEvent") else []
    storage = _scalar(db, "SELECT COALESCE(SUM(`sizeBytes`), 0) FROM `LibraryFile`", default=0) if _has_table(db, "LibraryFile") else 0
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
    where: list[str] = []
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if level:
        where.append("`level` = :level")
        params["level"] = "warning" if level == "warn" else level
    if source:
        where.append("`source` = :source")
        params["source"] = source
    if targetType:
        where.append("`targetType` = :target_type")
        params["target_type"] = targetType
    if search:
        where.append("(`message` LIKE :term OR `action` LIKE :term OR `targetId` LIKE :term)")
        params["term"] = f"%{search.strip()}%"
    if dateFrom:
        where.append(f"{_timestamp_sql('`createdAt`')} >= :date_from")
        params["date_from"] = to_timestamp_ms(f"{dateFrom}T00:00:00")
    if dateTo:
        where.append(f"{_timestamp_sql('`createdAt`')} < :date_to")
        params["date_to"] = to_timestamp_ms(f"{dateTo}T00:00:00")
    where_sql = " AND ".join(where) if where else "1 = 1"
    total = _table_count(db, "SystemEvent", where_sql, params)
    events = _rows(db, f"SELECT * FROM `SystemEvent` WHERE {where_sql} "
        f"ORDER BY {_timestamp_sql('`createdAt`')} DESC, `id` DESC LIMIT :limit OFFSET :offset", params)
    sources = _rows(db, "SELECT `source`, COUNT(*) AS `count` FROM `SystemEvent` GROUP BY `source` ORDER BY `source` ASC")
    levels = _rows(db, "SELECT `level`, COUNT(*) AS `count` FROM `SystemEvent` GROUP BY `level` ORDER BY `level` ASC")
    return ok({"events": [_serialize_system_event(event) for event in events], "page": page, "pageSize": page_size, "total": total, "totalPages": max(1, (total + page_size - 1) // page_size), "storage": storage, "facets": {"sources": sources, "levels": levels}})


@router.delete("/management/events")
def clear_system_events(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "SystemEvent"):
        return ok({"deleted": 0})
    result = db.execute(text("DELETE FROM `SystemEvent` WHERE `level` IN ('info', 'warning')"))
    db.commit()
    deleted = result.rowcount or 0
    _record_system_event(db, level="info", source="system", action="events.cleared", actor_type="admin", actor_id=user.id, target_type="events", message=f"清理结构化日志 {deleted} 条", metadata={"deleted": deleted})
    return ok({"deleted": deleted, "storage": _prune_system_events(db)})


@router.get("/management/folders")
def management_folders(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    monitor_folders = _rows(db, "SELECT * FROM `MonitorFolder` ORDER BY `createdAt` DESC") if _has_table(db, "MonitorFolder") else []
    source_nodes = [{**folder, **_source_folder_preview(str(folder.get("rootPath") or ""))} for folder in monitor_folders]
    works = _rows(db, "SELECT `id`, `title`, `author`, `seriesName`, `workType`, `monitorFolderId`, `organizeStatus`, `hidden`, `updatedAt` FROM `LibraryWork` WHERE `hidden` = 0 ORDER BY `updatedAt` DESC LIMIT 300") if _has_table(db, "LibraryWork") else []
    editions = _rows(db, "SELECT `workId`, COALESCE(SUM(`sizeBytes`), 0) AS `sizeBytes`, COUNT(*) AS `editionCount` FROM `LibraryEdition` WHERE `hidden` = 0 GROUP BY `workId`") if _has_table(db, "LibraryEdition") else []
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
    file_rows = _rows(db, "SELECT `path`, `sizeBytes` FROM `LibraryFile` ORDER BY `path` ASC LIMIT 2000") if _has_table(db, "LibraryFile") else []
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
    where = ["`seriesName` IS NOT NULL", "TRIM(`seriesName`) != ''"]
    params: dict[str, Any] = {"limit": take, "min_books": min_books}
    scope, scope_params = work_visibility_sql(
        authorization_context(db, user),
        alias="LibraryWork",
        prefix="series",
    )
    where.append(scope)
    params.update(scope_params)
    if visibility == "ignored":
        where.append("`hidden` = 1")
    elif visibility != "all":
        where.append("`hidden` = 0")
    where_sql = " AND ".join(where)
    total = int(
        _scalar(
            db,
            f"SELECT COUNT(*) FROM (SELECT TRIM(`seriesName`) FROM `LibraryWork` WHERE {where_sql} GROUP BY TRIM(`seriesName`) HAVING COUNT(*) >= :min_books) grouped_series",
            params,
            0,
        )
    )
    rows = _rows(
        db,
        f"""
        SELECT
            TRIM(`seriesName`) AS name,
            COUNT(*) AS bookCount,
            MAX(`updatedAt`) AS latestUpdatedAt
        FROM `LibraryWork`
        WHERE {where_sql}
        GROUP BY TRIM(`seriesName`)
        HAVING COUNT(*) >= :min_books
        ORDER BY MAX(`updatedAt`) DESC, TRIM(`seriesName`) ASC
        LIMIT :limit
        """,
        params,
    )
    return ok({"series": [{"name": row.get("name"), "bookCount": row.get("bookCount") or 0, "latestUpdatedAt": _dt(row.get("latestUpdatedAt"))} for row in rows], "total": total})


@router.get("/works")
def list_works(request: Request, page: int = 1, pageSize: int = 24, visibility: str = "active", search: str | None = None, keyword: str | None = None, seriesName: str | None = None, sort: str = "updated", sortDirection: str | None = None, view: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "LibraryWork"):
        return ok({"books": [], "page": page, "pageSize": pageSize, "total": 0, "totalPages": 1})
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    where = []
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    context = authorization_context(db, user)
    scope, scope_params = work_visibility_sql(
        context,
        alias="LibraryWork",
        prefix="works",
    )
    where.append(scope)
    params.update(scope_params)
    if visibility == "ignored":
        where.append("`hidden` = 1")
    elif visibility != "all":
        where.append("`hidden` = 0")
    term = (search or keyword or "").strip()
    if term:
        search_fields = ["`title` LIKE :term", "`author` LIKE :term", "`tags` LIKE :term"]
        if _has_column(db, "LibraryWork", "seriesName"):
            search_fields.append("`seriesName` LIKE :term")
        where.append(f"({' OR '.join(search_fields)})")
        params["term"] = f"%{term}%"
    type_filter = (request.query_params.get("type") or request.query_params.get("format") or "").strip()
    normalized_type = type_filter.upper()
    media_filter_scope, media_filter_params = edition_visibility_sql(
        context,
        alias="media_filter",
        prefix="works_media_filter",
    )
    params.update(media_filter_params)
    if type_filter.lower() == "ebook":
        where.append(
            "EXISTS (SELECT 1 FROM `LibraryEdition` media_filter WHERE media_filter.`workId` = `LibraryWork`.`id` "
            + ("AND media_filter.`mediaKind` = 'EBOOK' " if _has_column(db, "LibraryEdition", "mediaKind") else "AND media_filter.`format` IN ('EPUB', 'PDF', 'MOBI', 'AZW', 'AZW3', 'PRC', 'FB2', 'TXT') ")
            + f"AND COALESCE(media_filter.`hidden`, 0) = 0 AND {media_filter_scope})"
        )
    elif type_filter.lower() in {"audio", "audiobook"}:
        where.append(
            "EXISTS (SELECT 1 FROM `LibraryEdition` media_filter WHERE media_filter.`workId` = `LibraryWork`.`id` "
            + ("AND media_filter.`mediaKind` = 'AUDIOBOOK' " if _has_column(db, "LibraryEdition", "mediaKind") else "AND media_filter.`format` = 'AUDIO' ")
            + f"AND COALESCE(media_filter.`hidden`, 0) = 0 AND {media_filter_scope})"
        )
    elif normalized_type == "COMIC" and _has_table(db, "LibraryEdition"):
        where.append(
            "EXISTS (SELECT 1 FROM `LibraryEdition` media_filter WHERE media_filter.`workId` = `LibraryWork`.`id` "
            + ("AND media_filter.`mediaKind` = 'COMIC' " if _has_column(db, "LibraryEdition", "mediaKind") else "AND media_filter.`format` = 'COMIC' ")
            + f"AND COALESCE(media_filter.`hidden`, 0) = 0 AND {media_filter_scope})"
        )
    elif normalized_type in {"EPUB", "PDF"} and _has_table(db, "LibraryEdition"):
        where.append(
            "EXISTS (SELECT 1 FROM `LibraryEdition` media_filter WHERE media_filter.`workId` = `LibraryWork`.`id` "
            f"AND media_filter.`format` = :edition_format AND COALESCE(media_filter.`hidden`, 0) = 0 AND {media_filter_scope})"
        )
        params["edition_format"] = normalized_type
    elif normalized_type in {"COMIC", "EPUB", "PDF"}:
        where.append("`workType` = :work_type")
        params["work_type"] = normalized_type
    elif normalized_type in {"CBZ", "ZIP"} and _has_table(db, "LibraryFile"):
        file_edition_scope, file_edition_params = edition_visibility_sql(
            context,
            alias="le",
            prefix="works_file_filter",
        )
        params.update(file_edition_params)
        where.append(
            """EXISTS (
                SELECT 1 FROM `LibraryEdition` le
                JOIN `LibraryFile` lf ON lf.`editionId` = le.`id`
                WHERE le.`workId` = `LibraryWork`.`id`
                AND LOWER(lf.`path`) LIKE :file_extension """
            + f"AND {file_edition_scope})"
        )
        params["file_extension"] = f"%.{normalized_type.lower()}"
    raw_media_kinds = (request.query_params.get("mediaKinds") or request.query_params.get("mediaKind") or "").strip()
    if raw_media_kinds and _has_table(db, "LibraryEdition"):
        media_kinds = []
        for raw_kind in raw_media_kinds.split(","):
            kind = raw_kind.strip().upper()
            if kind in {"EBOOK", "COMIC", "AUDIOBOOK"} and kind not in media_kinds:
                media_kinds.append(kind)
        if media_kinds:
            media_params = []
            for index, kind in enumerate(media_kinds):
                key = f"media_kind_{index}"
                params[key] = kind
                media_params.append(f":{key}")
            if _has_column(db, "LibraryEdition", "mediaKind"):
                media_expression = "media_filter.`mediaKind`"
            else:
                media_expression = "CASE WHEN media_filter.`format` = 'COMIC' THEN 'COMIC' WHEN media_filter.`format` = 'AUDIO' THEN 'AUDIOBOOK' ELSE 'EBOOK' END"
            where.append(
                "EXISTS (SELECT 1 FROM `LibraryEdition` media_filter WHERE media_filter.`workId` = `LibraryWork`.`id` "
                f"AND {media_expression} IN ({', '.join(media_params)}) AND COALESCE(media_filter.`hidden`, 0) = 0 "
                f"AND {media_filter_scope})"
            )
    status = (request.query_params.get("status") or "").strip().upper()
    if status == "WANT":
        status = "UNREAD"
    status_clause, status_params = _user_status_filter_sql(db, status, context)
    if status_clause:
        where.append(status_clause)
        params.update(status_params)
        params["status"] = status
        params["current_user_id"] = user.id
    publication_status = (request.query_params.get("publicationStatus") or "").strip().upper()
    if publication_status in {"UNKNOWN", "ONGOING", "COMPLETED", "HIATUS", "CANCELLED"}:
        where.append("`publicationStatus` = :publication_status")
        params["publication_status"] = publication_status
    tracking_status = (request.query_params.get("trackingStatus") or "").strip().upper()
    if tracking_status in {"NOT_TRACKING", "TRACKING", "PAUSED", "IGNORED"}:
        where.append("`trackingStatus` = :tracking_status")
        params["tracking_status"] = tracking_status
    tag = (request.query_params.get("tag") or "").strip()
    if tag:
        where.append("`tags` LIKE :tag")
        params["tag"] = f"%{tag}%"
    if (request.query_params.get("missingCover") or "").lower() == "true" and _has_column(db, "LibraryWork", "coverPath"):
        where.append("(`coverPath` IS NULL OR TRIM(`coverPath`) = '' OR `coverStatus` != 'READY')")
    if (request.query_params.get("newImport") or "").lower() == "true":
        where.append("`organizeStatus` IN ('PENDING', 'REVIEWING')")
    series_name = (seriesName or "").strip()
    if series_name and _has_column(db, "LibraryWork", "seriesName"):
        where.append("TRIM(`seriesName`) = :series_name")
        params["series_name"] = series_name
    raw_filters = (request.query_params.get("filters") or "").strip()
    if raw_filters:
        try:
            filter_rules = json.loads(raw_filters)
        except json.JSONDecodeError:
            return fail("筛选规则格式不正确", status_code=400)
        advanced_edition_scope, advanced_edition_params = edition_visibility_sql(
            context,
            alias="filter_edition",
            prefix="advanced_filter",
        )
        filter_clause, filter_params, filter_error = compile_filter_rules(
            db,
            filter_rules,
            alias="LibraryWork",
            user_id=user.id,
            param_prefix="library_filter",
            edition_scope_sql=advanced_edition_scope,
            edition_scope_params=advanced_edition_params,
            shelf_owner_user_id=user.id if _has_column(db, "Shelf", "ownerUserId") else None,
        )
        if filter_error:
            return fail(filter_error, status_code=400)
        if filter_clause:
            where.append(filter_clause)
            params.update(filter_params)
    where_sql = " AND ".join(where) if where else "1 = 1"
    default_direction = "DESC" if sort in {"updated", "recent_read", "recent_import", "progress"} else "ASC"
    direction = sortDirection.upper() if sortDirection and sortDirection.lower() in {"asc", "desc"} else default_direction
    publisher_expression = """(
        SELECT edition_sort.`publisher`
        FROM `LibraryEdition` edition_sort
        WHERE edition_sort.`workId` = `LibraryWork`.`id`
          AND COALESCE(edition_sort.`hidden`, 0) = 0
        ORDER BY edition_sort.`primary` DESC, edition_sort.`createdAt` ASC
        LIMIT 1
    )"""
    order = (
        f"CASE WHEN `seriesIndex` IS NULL THEN 1 ELSE 0 END ASC, `seriesIndex` {direction}, `title` COLLATE NOCASE ASC"
        if sort == "series_index" and _has_column(db, "LibraryWork", "seriesIndex")
        else f"`title` COLLATE NOCASE {direction}"
        if sort == "title"
        else f"CASE WHEN NULLIF(TRIM(COALESCE(`author`, '')), '') IS NULL THEN 1 ELSE 0 END ASC, `author` COLLATE NOCASE {direction}, `title` COLLATE NOCASE ASC"
        if sort == "author"
        else f"CASE WHEN NULLIF(TRIM(COALESCE({publisher_expression}, '')), '') IS NULL THEN 1 ELSE 0 END ASC, {publisher_expression} COLLATE NOCASE {direction}, `title` COLLATE NOCASE ASC"
        if sort == "publisher" and _has_table(db, "LibraryEdition") and _has_column(db, "LibraryEdition", "publisher")
        else f"CASE WHEN NULLIF(TRIM(COALESCE(`seriesName`, '')), '') IS NULL THEN 1 ELSE 0 END ASC, `seriesName` COLLATE NOCASE {direction}, CASE WHEN `seriesIndex` IS NULL THEN 1 ELSE 0 END ASC, `seriesIndex` ASC, `title` COLLATE NOCASE ASC"
        if sort == "series" and _has_column(db, "LibraryWork", "seriesName")
        else f"{_timestamp_sql('`createdAt`')} {direction}, `id` {direction}"
        if sort == "recent_import"
        else f"`updatedAt` {direction}"
    )
    total = _table_count(db, "LibraryWork", where_sql, params)
    bookshelf_view = view == "bookshelf"
    select_columns = (
        "`LibraryWork`.`id`, `LibraryWork`.`title`, `LibraryWork`.`author`, "
        "`LibraryWork`.`workType`, `LibraryWork`.`coverStatus`, "
        "`LibraryWork`.`coverPath`, `LibraryWork`.`updatedAt`"
        if bookshelf_view
        else "`LibraryWork`.*"
    )
    if sort == "progress" and _has_table(db, "LibraryReadingProgress"):
        # Progress shown on a card follows the reader's continuation semantics: for
        # multi-volume EPUB/comics this can differ from both MAX(percent) and the
        # latest raw row. Serialize the filtered set first so ordering and display
        # use the same value, then paginate the sorted result.
        all_works = _rows(db, f"SELECT * FROM `LibraryWork` WHERE {where_sql}", params)
        work_views = [(work, _work_view(db, work, user.id)) for work in all_works]
        work_views.sort(
            key=lambda item: (
                int(item[1].get("progress") or 0),
                item[1].get("lastReadAt") or "",
                _dt(item[0].get("updatedAt")) or "",
            ),
            reverse=direction == "DESC",
        )
        start = (page - 1) * page_size
        page_items = work_views[start:start + page_size]
        page_views = (
            [_bookshelf_work_view(work) for work, _view in page_items]
            if bookshelf_view
            else [view for _work, view in page_items]
        )
        return ok({"books": page_views, "page": page, "pageSize": page_size, "total": total, "totalPages": max(1, (total + page_size - 1) // page_size)})
    if sort == "recent_read" and _has_table(db, "LibraryReadingProgress"):
        params["recent_user_id"] = user.id
        works = _rows(
            db,
            f"""
            SELECT {select_columns}
            FROM `LibraryWork`
            LEFT JOIN (
                SELECT `workId`, `updatedAt` AS `latestReadAt`, `percent` AS `recentPercent`
                FROM (
                    SELECT `workId`, `updatedAt`, `percent`,
                           ROW_NUMBER() OVER (PARTITION BY `workId` ORDER BY `updatedAt` DESC, `id` DESC) AS `rowNumber`
                    FROM `LibraryReadingProgress`
                    WHERE `userId` = :recent_user_id
                ) ranked_progress
                WHERE ranked_progress.`rowNumber` = 1
            ) recent_progress ON recent_progress.`workId` = `LibraryWork`.`id`
            WHERE {where_sql}
            ORDER BY CASE WHEN recent_progress.`latestReadAt` IS NULL THEN 1 ELSE 0 END ASC,
                     recent_progress.`latestReadAt` {direction}, `LibraryWork`.`updatedAt` {direction}
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
    else:
        works = _rows(db, f"SELECT {select_columns} FROM `LibraryWork` WHERE {where_sql} ORDER BY {order} LIMIT :limit OFFSET :offset", params)
    book_views = (
        [_bookshelf_work_view(work) for work in works]
        if bookshelf_view
        else [_work_view(db, work, user.id) for work in works]
    )
    return ok({"books": book_views, "page": page, "pageSize": page_size, "total": total, "totalPages": max(1, (total + page_size - 1) // page_size)})


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
    existing = (
        _row(
            db,
            "SELECT * FROM `WorkDetailPreference` WHERE `userId` = :user_id AND `workId` = :work_id",
            {"user_id": user.id, "work_id": work_id},
        )
        if _has_table(db, "WorkDetailPreference")
        else None
    )
    if not _has_table(db, "WorkDetailPreference"):
        return fail("详情偏好表尚未初始化", status_code=503)
    if existing:
        db.execute(
            text("UPDATE `WorkDetailPreference` SET `selectedTab` = :selected, `updatedAt` = :now WHERE `id` = :id"),
            {"selected": requested, "now": now, "id": existing["id"]},
        )
    else:
        db.execute(
            text(
                "INSERT INTO `WorkDetailPreference` (`id`, `userId`, `workId`, `selectedTab`, `createdAt`, `updatedAt`) "
                "VALUES (:id, :user_id, :work_id, :selected, :now, :now)"
            ),
            {"id": f"detail_{time_ns()}", "user_id": user.id, "work_id": work_id, "selected": requested, "now": now},
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
    work = _update(db, "LibraryWork", work_id, values)
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
    if not _has_table(db, "LibraryEdition"):
        return None
    return _row(
        db,
        "SELECT edition.* FROM `LibraryEdition` edition "
        "LEFT JOIN `LibraryWork` work ON work.`id` = edition.`workId` "
        "WHERE edition.`workId` = :work_id AND COALESCE(edition.`hidden`, 0) = 0 "
        "ORDER BY CASE WHEN edition.`id` = work.`primaryEditionId` THEN 0 "
        "WHEN COALESCE(edition.`primary`, 0) = 1 THEN 1 ELSE 2 END, edition.`createdAt` ASC LIMIT 1",
        {"work_id": work_id},
    )


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
    edition_scope, edition_scope_params = edition_visibility_sql(
        context,
        alias="LibraryEdition",
        prefix="bulk_reading_status",
    )
    for work_id in work_ids:
        work = _get_work(db, work_id)
        if not work:
            continue
        editions = (
            _rows(
                db,
                "SELECT * FROM `LibraryEdition` WHERE `workId` = :work_id "
                f"AND COALESCE(`hidden`, 0) = 0 AND {edition_scope}",
                {"work_id": work_id, **edition_scope_params},
            )
            if _has_table(db, "LibraryEdition")
            else []
        )
        if not editions:
            continue
        media_editions: dict[str, dict[str, Any]] = {}
        for edition in editions:
            media_editions.setdefault(_edition_media_kind(edition), edition)
        if status == "UNREAD":
            if _has_table(db, "LibraryReadingProgress"):
                for edition in editions:
                    db.execute(
                        text(
                            "DELETE FROM `LibraryReadingProgress` "
                            "WHERE `userId` = :user_id AND `editionId` = :edition_id"
                        ),
                        {"user_id": user.id, "edition_id": edition["id"]},
                    )
            if _has_table(db, "ReaderProgressCursor"):
                db.execute(
                    text(
                        "DELETE FROM `ReaderProgressCursor` "
                        "WHERE `userId` = :user_id AND `workId` = :work_id"
                    ),
                    {"user_id": user.id, "work_id": work_id},
                )
            if _has_table(db, "LibraryConsumptionState"):
                for media_kind in media_editions:
                    db.execute(
                        text(
                            "DELETE FROM `LibraryConsumptionState` "
                            "WHERE `userId` = :user_id AND `workId` = :work_id "
                            "AND `mediaKind` = :media_kind"
                        ),
                        {"user_id": user.id, "work_id": work_id, "media_kind": media_kind},
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
            for edition_index, edition in enumerate(editions):
                if not _has_table(db, "LibraryReadingProgress"):
                    continue
                existing_progress = _row(
                    db,
                    "SELECT `id` FROM `LibraryReadingProgress` WHERE `userId` = :user_id AND `workId` = :work_id AND `editionId` = :edition_id LIMIT 1",
                    {"user_id": user.id, "work_id": work_id, "edition_id": edition["id"]},
                )
                if existing_progress:
                    db.execute(
                        text("UPDATE `LibraryReadingProgress` SET `percent` = 100, `updatedAt` = :now WHERE `userId` = :user_id AND `workId` = :work_id AND `editionId` = :edition_id"),
                        {"now": now, "user_id": user.id, "work_id": work_id, "edition_id": edition["id"]},
                    )
                else:
                    progress_values = {
                        "id": f"bulk_progress_{time_ns()}_{edition_index}",
                        "userId": user.id,
                        "workId": work_id,
                        "editionId": edition["id"],
                        "volumeId": None,
                        "readerType": "comic" if _edition_media_kind(edition) == "COMIC" else "audio" if _edition_media_kind(edition) == "AUDIOBOOK" else "pdf" if str(edition.get("format")).upper() == "PDF" else "epub",
                        "position": "100",
                        "page": edition.get("pageCount") or edition.get("chapterCount"),
                        "percent": 100,
                        "extra": "{}",
                        "schemaVersion": 2,
                        "createdAt": now,
                        "updatedAt": now,
                    }
                    columns = _set_columns(db, "LibraryReadingProgress")
                    filtered = {key: value for key, value in progress_values.items() if key in columns}
                    db.execute(
                        text(
                            "INSERT INTO `LibraryReadingProgress` "
                            f"({', '.join(f'`{key}`' for key in filtered)}) VALUES ({', '.join(f':{key}' for key in filtered)})"
                        ),
                        filtered,
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
            if _update(db, "LibraryWork", str(work_id), values):
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
                    db.execute(
                        text(
                            "UPDATE `LibraryWork` SET `title` = :title, `author` = :author, `normalizedTitle` = :normalized_title, "
                            "`normalizedAuthor` = :normalized_author, `mergeKey` = :merge_key, `updatedAt` = :now WHERE `id` = :work_id"
                        ),
                        {
                            "title": title_value,
                            "author": author_value,
                            "normalized_title": normalize_identity_part(title_value),
                            "normalized_author": normalize_identity_part(author_value),
                            "merge_key": identity_merge_key(title_value, author_value),
                            "now": now,
                            "work_id": replacement["workId"],
                        },
                    )
                else:
                    db.execute(
                        text(f"UPDATE `{replacement['table']}` SET `{replacement['column']}` = :value, `updatedAt` = :now WHERE `id` = :target_id"),
                        {"value": value, "now": now, "target_id": replacement["targetId"]},
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
                _update(db, "LibraryWork", work_id, {"tags": _json_text(next_tags), "updatedAt": _now()})
            elif action in {"add_to_shelf", "remove_from_shelf", "shelf_membership"}:
                if membership == "ADD":
                    db.execute(
                        text("INSERT OR IGNORE INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES (:shelf_id, :work_id, :now)"),
                        {"shelf_id": shelf_id, "work_id": work_id, "now": _now()},
                    )
                else:
                    db.execute(
                        text("DELETE FROM `ShelfWork` WHERE `shelfId` = :shelf_id AND `workId` = :work_id"),
                        {"shelf_id": shelf_id, "work_id": work_id},
                    )
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
                    _update(db, "LibraryWork", work_id, work_values)
                if "publisher" in metadata_fields:
                    edition = _primary_edition(db, work_id)
                    if edition:
                        _update(db, "LibraryEdition", str(edition["id"]), {"publisher": str(metadata_fields.get("publisher") or "").strip() or None, "updatedAt": _now()})
            elif fields:
                _update(db, "LibraryWork", work_id, {**fields, "updatedAt": _now()})
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
            db.execute(
                text("UPDATE `LibraryWork` SET `coverPath` = :cover_path, `coverStatus` = :cover_status, `updatedAt` = :now WHERE `id` = :work_id"),
                {"cover_path": relative, "cover_status": status, "now": now, "work_id": work_id},
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
    folders = _rows(db, "SELECT * FROM `MonitorFolder` ORDER BY `createdAt` DESC") if _has_table(db, "MonitorFolder") else []
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
        folder = _insert(
            db,
            "MonitorFolder",
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
    existing = _row(db, "SELECT * FROM `MonitorFolder` WHERE `id` = :id", {"id": folder_id}) if _has_table(db, "MonitorFolder") else None
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
        folder = _update(db, "MonitorFolder", folder_id, values)
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
    existing = _row(db, "SELECT * FROM `MonitorFolder` WHERE `id` = :id", {"id": folder_id}) if _has_table(db, "MonitorFolder") else None
    affected_user_ids = (
        [
            str(item)
            for item in db.execute(
                text(
                    "SELECT `userId` FROM `UserMonitorFolderAccess` "
                    "WHERE `monitorFolderId` = :folder_id"
                ),
                {"folder_id": folder_id},
            ).scalars()
        ]
        if _has_table(db, "UserMonitorFolderAccess")
        else []
    )
    result = (
        db.execute(text("DELETE FROM `MonitorFolder` WHERE `id` = :id"), {"id": folder_id})
        if _has_table(db, "MonitorFolder")
        else None
    )
    deleted = bool(result and result.rowcount)
    if deleted and affected_user_ids:
        placeholders = ", ".join(f":affected_user_{index}" for index in range(len(affected_user_ids)))
        db.execute(
            text(
                "UPDATE `User` SET `authzVersion` = COALESCE(`authzVersion`, 1) + 1, "
                f"`updatedAt` = :updated_at WHERE `id` IN ({placeholders})"
            ),
            {
                "updated_at": _now(),
                **{
                    f"affected_user_{index}": affected_user_id
                    for index, affected_user_id in enumerate(affected_user_ids)
                },
            },
        )
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
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    rows = _rows(db, "SELECT `key`, `value` FROM `SystemSetting`") if _has_table(db, "SystemSetting") else []
    values = {row["key"]: _parse_json(row.get("value"), row.get("value")) for row in rows}
    return ok({"settings": _public_system_settings(values)})


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
    clear_keys = {str(key) for key in requested_clear_keys if str(key) in _SENSITIVE_SYSTEM_SETTING_KEYS}
    saved = {}
    if not _has_table(db, "SystemSetting"):
        return ok({"settings": _public_system_settings({**values, **{key: "" for key in clear_keys}})})
    keys = [str(key) for key in values.keys()] + list(clear_keys)
    existing: set[str] = set()
    if keys:
        placeholders = ", ".join(f":key_{index}" for index, _ in enumerate(keys))
        params = {f"key_{index}": key for index, key in enumerate(keys)}
        existing = {row["key"] for row in _rows(db, f"SELECT `key` FROM `SystemSetting` WHERE `key` IN ({placeholders})", params)}
    now = _now()
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
        serialized = _json_text(value)
        if key in existing:
            db.execute(text("UPDATE `SystemSetting` SET `value` = :value, `updatedAt` = :updated_at WHERE `key` = :key"), {"key": key, "value": serialized, "updated_at": now})
        else:
            db.execute(
                text("INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, :created_at, :updated_at)"),
                {"key": key, "value": serialized, "created_at": now, "updated_at": now},
            )
        saved[key] = value
    for key in clear_keys:
        db.execute(text("DELETE FROM `SystemSetting` WHERE `key` = :key"), {"key": key})
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
    params: dict[str, Any] = {"edition_id": edition_id}
    where = "`editionId` = :edition_id"
    if volume_id:
        where += " AND `volumeId` = :volume_id"
        params["volume_id"] = volume_id
    total = int(db.execute(text(f"SELECT COUNT(*) FROM `LibraryReadingUnit` WHERE {where}"), params).scalar() or 0)
    total_pages = max(1, (total + resolved_page_size - 1) // resolved_page_size)
    resolved_page = min(requested_page, total_pages)
    units = _rows(
        db,
        f"SELECT * FROM `LibraryReadingUnit` WHERE {where} ORDER BY `sortOrder` ASC LIMIT :limit OFFSET :offset",
        {**params, "limit": resolved_page_size, "offset": (resolved_page - 1) * resolved_page_size},
    ) if total > 0 else []
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
    edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
    if not edition:
        return {"readingUnits": [], "volumeSections": [], "readingUnitsPage": _empty_reading_units_page(resolved_page_size)}
    progresses = _rows(db, "SELECT * FROM `LibraryReadingProgress` WHERE `editionId` = :edition_id AND `userId` = :user_id ORDER BY `updatedAt` DESC", {"edition_id": edition_id, "user_id": user_id}) if user_id and _has_table(db, "LibraryReadingProgress") else []
    if edition.get("format") == "COMIC":
        volumes = _rows(db, "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC", {"edition_id": edition_id}) if _has_table(db, "LibraryVolume") else []
        return {
            "readingUnits": [],
            "volumeSections": [_volume_section_view(volume, "COMIC", progress=_progress_for_volume(progresses, volume["id"])) for volume in volumes],
            "readingUnitsPage": _empty_reading_units_page(resolved_page_size),
        }
    if edition.get("format") == "PDF":
        volumes = _rows(db, "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC", {"edition_id": edition_id}) if _has_table(db, "LibraryVolume") else []
        return {
            "readingUnits": [],
            "volumeSections": [_volume_section_view(volume, "PDF", progress=_progress_for_volume(progresses, volume["id"])) for volume in volumes],
            "readingUnitsPage": _empty_reading_units_page(resolved_page_size),
        }
    volumes = _rows(db, "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC", {"edition_id": edition_id}) if _has_table(db, "LibraryVolume") else []
    if len(volumes) > 1:
        selected_volume = next((item for item in volumes if item["id"] == requested_volume_id), None) if requested_volume_id else None
        selected_volume = selected_volume or _choose_continue_volume(volumes, progresses) or volumes[0]
        units, units_page = _reading_units_page(db, edition_id, chapter_page, resolved_page_size, selected_volume["id"])
        units_by_volume = {
            volume["id"]: _rows(db, "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND `volumeId` = :volume_id ORDER BY `sortOrder` ASC", {"edition_id": edition_id, "volume_id": volume["id"]})
            for volume in volumes
        } if _has_table(db, "LibraryReadingUnit") else {}
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
    file = _row(db, "SELECT * FROM `LibraryFile` WHERE `id` = :id", {"id": file_id}) if _has_table(db, "LibraryFile") else None
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
        file = _row(db, "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id AND `volumeId` = :volume_id ORDER BY `sortOrder` ASC LIMIT 1", {"edition_id": edition_id, "volume_id": volume_id})
    else:
        file = None
    file = file or (_row(db, "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC LIMIT 1", {"edition_id": edition_id}) if _has_table(db, "LibraryFile") else None)
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
        row = _row(db, "SELECT `coverPath` FROM `LibraryWork` WHERE `id` = :id", {"id": work_id})
    elif edition_id and _has_table(db, "LibraryEdition"):
        table, row_id = "LibraryEdition", edition_id
        row = _row(db, "SELECT `coverPath` FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
    elif volume_id and _has_table(db, "LibraryVolume"):
        table, row_id = "LibraryVolume", volume_id
        row = _row(db, "SELECT `coverPath` FROM `LibraryVolume` WHERE `id` = :id", {"id": volume_id})
    cover_id = work_id or edition_id or volume_id or "cover"
    if row is None:
        return fail("条目不存在", status_code=404)
    cover_path = _stored_path(row.get("coverPath"), settings)
    if cover_path is None or not cover_path.is_file() or is_default_cover_path(row.get("coverPath"), settings):
        stored_default = ensure_default_cover(settings)
        if row.get("coverPath") != stored_default:
            values: dict[str, Any] = {"coverPath": stored_default, "updatedAt": _now()}
            if table != "LibraryVolume":
                values["coverStatus"] = cover_status(stored_default, settings)
            _update(db, str(table), str(row_id), values)
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
    work = _row(db, "SELECT `primaryEditionId` FROM `LibraryWork` WHERE `id` = :work_id", {"work_id": work_id}) if _has_table(db, "LibraryWork") else None
    primary_edition_id = (work or {}).get("primaryEditionId")
    if primary_edition_id and _has_table(db, "LibraryVolume"):
        volume = _row(
            db,
            """
            SELECT `coverPath`
            FROM `LibraryVolume`
            WHERE `editionId` = :edition_id AND `coverPath` IS NOT NULL AND `coverPath` != ''
            ORDER BY
                CASE WHEN `volumeIndex` IS NULL THEN 1 ELSE 0 END ASC,
                `volumeIndex` ASC,
                `sortOrder` ASC,
                `createdAt` ASC
            LIMIT 1
            """,
            {"edition_id": primary_edition_id},
        )
        if volume and volume.get("coverPath"):
            return str(volume["coverPath"])
    if primary_edition_id and _has_table(db, "LibraryEdition"):
        edition = _row(db, "SELECT `coverPath` FROM `LibraryEdition` WHERE `id` = :edition_id", {"edition_id": primary_edition_id})
        if edition and edition.get("coverPath"):
            return str(edition["coverPath"])
    edition = _row(
        db,
        """
        SELECT `coverPath`
        FROM `LibraryEdition`
        WHERE `workId` = :work_id AND `hidden` = 0 AND `coverPath` IS NOT NULL AND `coverPath` != ''
        ORDER BY CASE WHEN `primary` = 1 THEN 0 ELSE 1 END ASC, `createdAt` ASC
        LIMIT 1
        """,
        {"work_id": work_id},
    ) if _has_table(db, "LibraryEdition") else None
    return str(edition["coverPath"]) if edition and edition.get("coverPath") else None


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
    _update(db, "LibraryWork", work_id, {"coverPath": relative, "coverStatus": "READY", "updatedAt": _now()})
    return ok({"bookId": work_id, "coverUrl": f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}"})


@router.post("/works/{work_id}/cover/regenerate")
def regenerate_cover(work_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    permission_error = _require_work_manager(db, user, work_id)
    if permission_error is not None:
        return permission_error
    work = _row(db, "SELECT `id` FROM `LibraryWork` WHERE `id` = :id", {"id": work_id}) if _has_table(db, "LibraryWork") else None
    if not work:
        return fail("作品不存在", status_code=404)
    cover_path = _preferred_work_cover_path(db, work_id) or ensure_default_cover(settings)
    if _stored_path(cover_path, settings) is None or not _stored_path(cover_path, settings).is_file():
        cover_path = ensure_default_cover(settings)
    _update(db, "LibraryWork", work_id, {"coverPath": cover_path, "coverStatus": cover_status(cover_path, settings), "updatedAt": _now()})
    return ok({"bookId": work_id, "coverUrl": f"/api/works/{work_id}/cover?size=medium&v={int(_now().timestamp())}"})


@router.get("/volumes/{volume_id}/pages")
def list_volume_pages(volume_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("页面不存在", status_code=404, code="VOLUME_NOT_FOUND")
    units = _rows(db, "SELECT * FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id AND LOWER(`unitType`) = 'page' ORDER BY `sortOrder` ASC", {"volume_id": volume_id}) if _has_table(db, "LibraryReadingUnit") else []
    if not units:
        _ensure_volume_page_index(db, settings, volume_id)
        units = _rows(db, "SELECT * FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id AND LOWER(`unitType`) = 'page' ORDER BY `sortOrder` ASC", {"volume_id": volume_id}) if _has_table(db, "LibraryReadingUnit") else []
    return ok({"pages": units, "total": len(units)})


@router.get("/volumes/{volume_id}/pages/{page_index}")
def get_volume_page(volume_id: str, page_index: int, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not can_access_volume(db, user, volume_id):
        return fail("页面不存在", status_code=404, code="VOLUME_NOT_FOUND")
    unit = _row(db, "SELECT * FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id AND LOWER(`unitType`) = 'page' AND `sortOrder` = :sort_order", {"volume_id": volume_id, "sort_order": page_index}) if _has_table(db, "LibraryReadingUnit") else None
    if not unit:
        _ensure_volume_page_index(db, settings, volume_id)
        unit = _row(db, "SELECT * FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id AND LOWER(`unitType`) = 'page' AND `sortOrder` = :sort_order", {"volume_id": volume_id, "sort_order": page_index}) if _has_table(db, "LibraryReadingUnit") else None
        if not unit:
            return fail("页面不存在", status_code=404)
    file = _row(db, "SELECT * FROM `LibraryFile` WHERE `id` = :id", {"id": unit.get("fileId")}) if _has_table(db, "LibraryFile") and unit.get("fileId") else None
    if file and file.get("kind") == "COMIC":
        metadata = _parse_json(unit.get("metadataJson"), {})
        entry_name = metadata.get("zipEntryName") or unit.get("href")
        return _send_comic_page_zip_entry(_stored_path(file.get("path"), settings), entry_name, request, user.id, settings, unit.get("mediaType"), route="volume-page-zip", file_id=unit.get("id") or f"{volume_id}:{page_index}")
    return _send_comic_page_file(_stored_path(unit.get("href"), settings), request, user.id, settings, media_type=unit.get("mediaType"), route="volume-page", file_id=unit.get("id") or f"{volume_id}:{page_index}")


def _ensure_volume_page_index(db: Session, settings: Settings, volume_id: str) -> int:
    if not all(_has_table(db, table) for table in ["LibraryVolume", "LibraryFile", "LibraryReadingUnit"]):
        return 0
    existing = db.execute(text("SELECT COUNT(*) FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id AND LOWER(`unitType`) = 'page'"), {"volume_id": volume_id}).scalar() or 0
    if existing:
        return int(existing)
    volume = _row(db, "SELECT * FROM `LibraryVolume` WHERE `id` = :id", {"id": volume_id})
    if not volume:
        return 0
    file = _row(db, "SELECT * FROM `LibraryFile` WHERE `volumeId` = :volume_id AND `kind` = 'COMIC' ORDER BY `sortOrder` ASC LIMIT 1", {"volume_id": volume_id})
    if not file:
        file = _row(db, "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id AND `kind` = 'COMIC' ORDER BY `sortOrder` ASC LIMIT 1", {"edition_id": volume.get("editionId")})
    archive_path = _stored_path((file or {}).get("path"), settings)
    if not file or not archive_path:
        return 0
    try:
        parsed = parse_comic_archive(archive_path, Path(file.get("path") or archive_path).name)
    except Exception as exc:
        logger.warning("failed to rebuild comic page index volume=%s file=%s error=%s", volume_id, file.get("id"), exc)
        return 0
    now = _now()
    rows = [
        {
            "id": f"py_{time_ns()}_{page['index']}",
            "editionId": volume.get("editionId"),
            "volumeId": volume_id,
            "fileId": file.get("id"),
            "unitType": "page",
            "title": page["title"],
            "href": page["entryPath"],
            "mediaType": page["mediaType"],
            "sortOrder": page["index"],
            "size": page.get("size"),
            "metadataJson": _json_text(
                {
                    "zipEntryName": page["entryPath"],
                    "originalName": Path(page["entryPath"]).name,
                    "pageInVolume": page["index"],
                    "pageInSection": page["index"],
                    "volumeIndex": volume.get("volumeIndex"),
                    "sourceFileName": Path(file.get("path") or archive_path).name,
                }
            ),
            "createdAt": now,
            "updatedAt": now,
        }
        for page in parsed["pages"]
    ]
    if rows:
        try:
            db.execute(
                text(
                    """
                    INSERT INTO `LibraryReadingUnit`
                    (`id`, `editionId`, `volumeId`, `fileId`, `unitType`, `title`, `href`, `mediaType`, `sortOrder`, `size`, `metadataJson`, `createdAt`, `updatedAt`)
                    VALUES
                    (:id, :editionId, :volumeId, :fileId, :unitType, :title, :href, :mediaType, :sortOrder, :size, :metadataJson, :createdAt, :updatedAt)
                    """
                ),
                rows,
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.execute(text("SELECT COUNT(*) FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id AND LOWER(`unitType`) = 'page'"), {"volume_id": volume_id}).scalar() or 0
            if existing:
                return int(existing)
            raise
    count = len(parsed["pages"])
    _update(db, "LibraryVolume", volume_id, {"pageCount": count, "updatedAt": now})
    if volume.get("editionId") and _has_table(db, "LibraryVolume") and _has_table(db, "LibraryEdition"):
        total = db.execute(text("SELECT COALESCE(SUM(`pageCount`), 0) FROM `LibraryVolume` WHERE `editionId` = :edition_id"), {"edition_id": volume.get("editionId")}).scalar() or count
        _update(db, "LibraryEdition", volume.get("editionId"), {"pageCount": int(total), "updatedAt": now})
    return count


def _list_table_response(db: Session, table: str, key: str, order: str = "`createdAt` DESC") -> Response:
    rows = _rows(db, f"SELECT * FROM `{table}` ORDER BY {order}") if _has_table(db, table) else []
    return ok({key: rows})


def _organize_job_view(db: Session, job: dict[str, Any], user_id: str | None, pending_only: bool = False) -> dict[str, Any] | None:
    work = _get_work(db, str(job.get("workId") or ""))
    if not work:
        return None
    lookup = (
        _row(
            db,
            "SELECT `status`, `resultSource`, `providerOrder`, `errorSummary` FROM `MetadataLookupTask` WHERE `organizeJobId` = :job_id ORDER BY `createdAt` DESC, `id` DESC LIMIT 1",
            {"job_id": job.get("id")},
        )
        if _has_table(db, "MetadataLookupTask")
        else None
    )
    executions = (
        _rows(
            db,
            "SELECT `id`, `providerId`, `status`, `attempts`, `errorSummary`, `startedAt`, `finishedAt` "
            "FROM `MetadataProviderExecution` WHERE `jobId` = :job_id ORDER BY `createdAt` ASC",
            {"job_id": job.get("id")},
        )
        if _has_table(db, "MetadataProviderExecution")
        else []
    )
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
        monitor_folder = _row(db, "SELECT * FROM `MonitorFolder` WHERE `id` = :id", {"id": task.get("monitorFolderId")})
    book = None
    if task.get("workId") and _has_table(db, "LibraryWork"):
        work = _row(db, "SELECT `id`, `title` FROM `LibraryWork` WHERE `id` = :id", {"id": task.get("workId")})
        if work:
            book = {"id": work.get("id"), "title": work.get("title") or "未命名作品"}
    logs = (
        _rows(
            db,
            "SELECT * FROM `ImportLog` WHERE `importTaskId` = :task_id "
            f"ORDER BY {_timestamp_sql('`createdAt`')} DESC, `id` DESC LIMIT :limit",
            {"task_id": task.get("id"), "limit": log_limit},
        )
        if _has_table(db, "ImportLog")
        else []
    )
    conversion = (
        _row(db, "SELECT * FROM `BookConversionTask` WHERE `importTaskId` = :task_id", {"task_id": task.get("id")})
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
    sources = (
        _rows(
            db,
            "SELECT * FROM `Source` WHERE `providerType` = :provider_type ORDER BY `priority` ASC, `createdAt` DESC",
            {"provider_type": ACTIVE_SOURCE_PROVIDER},
        )
        if _has_table(db, "Source")
        else []
    )
    return ok({"sources": [_source_view(source) for source in sources]})


@router.post("/sources")
async def create_source(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("外部资源功能已移除", status_code=410)
    payload = await request.json()
    provider_type = payload.get("providerType") or payload.get("type") or ACTIVE_SOURCE_PROVIDER
    if provider_type != ACTIVE_SOURCE_PROVIDER:
        return fail("外部资源功能已移除", status_code=410)
    existing = _row(
        db,
        "SELECT * FROM `Source` WHERE `providerType` = :provider_type ORDER BY `createdAt` DESC LIMIT 1",
        {"provider_type": provider_type},
    )
    if existing:
        return fail("外部资源功能已移除", status_code=410)
    config = _merge_source_config_for_write(None, provider_type, payload.get("config", {}))
    source = _insert(db, "Source", {"id": f"py_{time_ns()}", "name": payload.get("name") or "外部来源", "kind": payload.get("kind") or "novel", "providerType": provider_type, "enabled": bool(payload.get("enabled", True)), "priority": int(payload.get("priority", 100)), "config": _json_text(config), "credentialsKey": payload.get("credentialsKey"), "capabilities": _json_text(payload.get("capabilities", {})), "rateLimit": _json_text(payload.get("rateLimit", {})), "createdAt": _now(), "updatedAt": _now()})
    return ok({"source": _source_view(source)}, status_code=201)


@router.put("/sources/{source_id}")
@router.patch("/sources/{source_id}")
async def update_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    existing = _active_source(db, source_id)
    if not existing:
        return fail("来源不存在", status_code=404)
    next_provider_type = payload.get("providerType") or existing.get("providerType") or ACTIVE_SOURCE_PROVIDER
    if next_provider_type != ACTIVE_SOURCE_PROVIDER:
        return fail("外部资源功能已移除", status_code=410)
    values = {}
    for key, value in payload.items():
        if key == "config":
            values[key] = _json_text(_merge_source_config_for_write(existing, next_provider_type, value))
        elif key in {"capabilities", "rateLimit"}:
            values[key] = _json_text(value)
        else:
            values[key] = value
    source = _update(db, "Source", source_id, values)
    if not source:
        return fail("来源不存在", status_code=404)
    return ok({"source": _source_view(source)})


@router.get("/sources/{source_id}")
def get_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    source = _active_source(db, source_id)
    if not source:
        return fail("来源不存在", status_code=404)
    return ok({"source": _source_view(source)})


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _active_source(db, source_id):
        return fail("来源不存在", status_code=404)
    return ok({"deleted": _delete(db, "Source", source_id), "id": source_id})


@router.post("/sources/{source_id}/test")
def test_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    source = _active_source(db, source_id)
    if not source:
        return fail("源不存在", status_code=404)
    if not str(source.get("name") or "").strip():
        result = {"status": "failed", "message": "源名称为空"}
    elif source.get("providerType") not in PROVIDER_CAPABILITIES:
        result = {"status": "failed", "message": "这个来源暂不支持搜索或连接测试。"}
    else:
        provider_result = test_source_provider(source)
        result = {"status": "ok" if provider_result.ok else "failed", "message": provider_result.message, "details": provider_result.details}
    updated = _update(
        db,
        "Source",
        source_id,
        {"lastTestAt": _now(), "lastTestStatus": result["status"], "lastError": None if result["status"] == "ok" else result["message"]},
    )
    return ok({"result": result, "source": _source_view(updated) if updated else None})


@router.post("/sources/{source_id}/search")
async def search_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    keyword = str(payload.get("keyword") or payload.get("query") or "").strip()
    if not keyword:
        return fail("请输入搜索关键词", status_code=400)
    source = _active_source(db, source_id)
    if not source:
        return fail("源不存在", status_code=404)
    if source.get("enabled") is False:
        return fail("源已禁用，请启用后再搜索", status_code=400)
    try:
        results, provider = search_source_provider(
            source,
            keyword,
            kind=payload.get("kind"),
            page=_positive_int(payload.get("page"), 1, 9999),
            page_size=_positive_int(payload.get("pageSize"), 20, 100),
        )
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    records = [_upsert_source_record(db, source, result, "saved")[0] for result in results] if payload.get("saveResults") else []
    return ok({"results": results, "records": records, "provider": provider})


def _source_record_values(source: dict[str, Any], result: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "sourceId": source["id"],
        "providerType": source.get("providerType") or ACTIVE_SOURCE_PROVIDER,
        "externalId": result.get("externalId") or f"manual:{time_ns()}",
        "title": (result.get("title") or "未命名结果").strip(),
        "subtitle": result.get("subtitle"),
        "author": result.get("author"),
        "description": result.get("description"),
        "coverUrl": result.get("coverUrl"),
        "externalUrl": result.get("externalUrl"),
        "format": result.get("format"),
        "size": result.get("size"),
        "language": result.get("language"),
        "publishedAt": result.get("publishedAt"),
        "downloadAvailable": bool(result.get("downloadAvailable")),
        "downloadMeta": _json_text(result.get("downloadMeta")) if result.get("downloadMeta") is not None else None,
        "raw": _json_text(result.get("raw")) if result.get("raw") is not None else None,
        "status": status,
        "updatedAt": _now(),
    }


def _upsert_source_record(db: Session, source: dict[str, Any], result: dict[str, Any], status: str) -> tuple[dict[str, Any], bool]:
    if not _has_table(db, "SourceSearchRecord"):
        return result, True
    values = _source_record_values(source, result, status)
    existing = _row(
        db,
        "SELECT * FROM `SourceSearchRecord` WHERE `sourceId` = :source_id AND `externalId` = :external_id",
        {"source_id": source["id"], "external_id": values["externalId"]},
    )
    if existing:
        return _update(db, "SourceSearchRecord", existing["id"], values) or existing, False
    values["id"] = f"py_{time_ns()}"
    values["createdAt"] = _now()
    try:
        return _insert(db, "SourceSearchRecord", values), True
    except IntegrityError:
        db.rollback()
        existing = _row(
            db,
            "SELECT * FROM `SourceSearchRecord` WHERE `sourceId` = :source_id AND `externalId` = :external_id",
            {"source_id": source["id"], "external_id": values["externalId"]},
        )
        if existing:
            return _update(db, "SourceSearchRecord", existing["id"], values) or existing, False
        raise


def _source_from_record_payload(db: Session, payload: dict[str, Any]) -> dict[str, Any] | None:
    source_id = payload.get("sourceId")
    if source_id:
        return _active_source(db, str(source_id))
    return None


def _create_download_task_for_record(db: Session, record: dict[str, Any], save_path: str) -> tuple[dict[str, Any], dict[str, Any], bool, int]:
    existing = find_active_download_task(db, record["id"])
    if existing:
        if record.get("status") != "download_created":
            record = _update(db, "SourceSearchRecord", record["id"], {"status": "download_created", "updatedAt": _now()}) or record
        return existing, record, True, 200
    remote_ref = create_remote_ref_from_search_record(record)
    task_type = infer_download_task_type(record.get("providerType") or "", record.get("downloadMeta"))
    task = (
        _insert(
            db,
            "DownloadTask",
            {
                "id": f"py_{time_ns()}",
                "sourceId": record.get("sourceId"),
                "searchRecordId": record["id"],
                "type": task_type,
                "status": "queued",
                "displayName": record.get("title") or "下载任务",
                "remoteRef": _json_text(remote_ref),
                "savePath": save_path,
                "progress": 0,
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        if _has_table(db, "DownloadTask")
        else {"id": None}
    )
    record = _update(db, "SourceSearchRecord", record["id"], {"status": "download_created", "updatedAt": _now()}) or record
    return task, record, False, 201


def _source_record_view(db: Session, record: dict[str, Any]) -> dict[str, Any]:
    source_name = None
    if record.get("sourceId") and _has_table(db, "Source"):
        source = _row(db, "SELECT `name` FROM `Source` WHERE `id` = :id", {"id": record.get("sourceId")})
        source_name = (source or {}).get("name")
    return {
        **record,
        "downloadMeta": _parse_json(record.get("downloadMeta"), record.get("downloadMeta")),
        "raw": _parse_json(record.get("raw"), record.get("raw")),
        "sourceName": source_name,
    }


@router.get("/source-search-records")
def list_source_records(request: Request, sourceId: str | None = None, status: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not _has_table(db, "SourceSearchRecord"):
        return ok({"records": [], "total": 0})
    where = ["`providerType` = :active_provider_type"]
    params = {"active_provider_type": ACTIVE_SOURCE_PROVIDER}
    if sourceId:
        where.append("`sourceId` = :source_id")
        params["source_id"] = sourceId
    keyword = (request.query_params.get("keyword") or "").strip()
    if status:
        where.append("`status` = :status")
        params["status"] = status
    if keyword:
        where.append("(`title` LIKE :keyword OR `author` LIKE :keyword)")
        params["keyword"] = f"%{keyword}%"
    sql_where = f" WHERE {' AND '.join(where)}" if where else ""
    records = _rows(db, f"SELECT * FROM `SourceSearchRecord`{sql_where} ORDER BY `createdAt` DESC LIMIT 100", params)
    return ok({"records": [_source_record_view(db, record) for record in records], "total": len(records)})


@router.post("/source-search-records")
async def create_source_record(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    source = _source_from_record_payload(db, payload)
    if not source:
        return fail("源不存在", status_code=404)
    record, created = _upsert_source_record(db, source, {**payload, "providerType": ACTIVE_SOURCE_PROVIDER, "raw": payload.get("raw", payload)}, payload.get("status") or "new")
    return ok({"record": record, "created": created}, status_code=201 if created else 200)


@router.post("/source-search-records/create-download-task")
async def create_download_from_search_result(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    source = _source_from_record_payload(db, payload)
    if not source:
        return fail("源不存在", status_code=404)
    if not payload.get("downloadAvailable"):
        return fail("该搜索结果不可下载", status_code=400)
    if not has_usable_download_meta(ACTIVE_SOURCE_PROVIDER, payload.get("downloadMeta")):
        return fail("该搜索结果缺少可用下载信息", status_code=400)
    record, _created = _upsert_source_record(db, source, {**payload, "providerType": ACTIVE_SOURCE_PROVIDER, "raw": payload.get("raw", payload)}, "saved")
    existing = find_active_download_task(db, record["id"])
    if existing:
        if record.get("status") != "download_created":
            record = _update(db, "SourceSearchRecord", record["id"], {"status": "download_created", "updatedAt": _now()}) or record
        return ok({"task": existing, "record": record, "alreadyQueued": True, "autoImport": _enabled_monitor_folder_for_path(db, Path(str(existing.get("savePath") or ""))) is not None})
    try:
        target_dir = _target_directory_from_path(settings, payload.get("targetPath"), "下载")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    save_path = str(target_dir)
    task, record, already_queued, status_code = _create_download_task_for_record(db, record, save_path)
    auto_import = _enabled_monitor_folder_for_path(db, target_dir) is not None
    if not already_queued:
        _save_system_setting(db, "library.lastDownloadTargetPath", save_path)
        db.commit()
    return ok({"task": task, "record": record, "alreadyQueued": already_queued, "autoImport": auto_import}, status_code=status_code)


@router.get("/source-search-records/{record_id}")
def get_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    record = _row(db, "SELECT * FROM `SourceSearchRecord` WHERE `id` = :id", {"id": record_id}) if _has_table(db, "SourceSearchRecord") else None
    if not record or record.get("providerType") != ACTIVE_SOURCE_PROVIDER:
        return fail("搜索记录不存在", status_code=404)
    return ok({"record": record})


@router.delete("/source-search-records/{record_id}")
def delete_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    record = _row(db, "SELECT `id`, `providerType` FROM `SourceSearchRecord` WHERE `id` = :id", {"id": record_id}) if _has_table(db, "SourceSearchRecord") else None
    if not record or record.get("providerType") != ACTIVE_SOURCE_PROVIDER:
        return fail("搜索记录不存在", status_code=404)
    return ok({"deleted": _delete(db, "SourceSearchRecord", record_id), "id": record_id})


@router.put("/source-search-records/{record_id}")
async def update_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    existing = _row(db, "SELECT `providerType` FROM `SourceSearchRecord` WHERE `id` = :id", {"id": record_id}) if _has_table(db, "SourceSearchRecord") else None
    if not existing or existing.get("providerType") != ACTIVE_SOURCE_PROVIDER:
        return fail("搜索记录不存在", status_code=404)
    payload = await request.json()
    allowed = {"status", "title", "subtitle", "author", "description", "externalUrl", "format", "size", "language"}
    record = _update(db, "SourceSearchRecord", record_id, {key: value for key, value in payload.items() if key in allowed})
    if not record:
        return fail("搜索记录不存在", status_code=404)
    return ok({"record": record})


@router.post("/source-search-records/{record_id}/ignore")
@router.post("/source-search-records/{record_id}/save")
def mark_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    existing = _row(db, "SELECT `providerType` FROM `SourceSearchRecord` WHERE `id` = :id", {"id": record_id}) if _has_table(db, "SourceSearchRecord") else None
    if not existing or existing.get("providerType") != ACTIVE_SOURCE_PROVIDER:
        return fail("搜索记录不存在", status_code=404)
    status_value = "ignored" if request.url.path.endswith("/ignore") else "saved"
    record = _update(db, "SourceSearchRecord", record_id, {"status": status_value, "updatedAt": _now()})
    return ok({"record": record, "status": status_value})


@router.post("/source-search-records/{record_id}/create-download-task")
async def create_download_from_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    record = _row(db, "SELECT * FROM `SourceSearchRecord` WHERE `id` = :id", {"id": record_id}) if _has_table(db, "SourceSearchRecord") else None
    if not record or record.get("providerType") != ACTIVE_SOURCE_PROVIDER:
        return fail("搜索记录不存在", status_code=404)
    if not record.get("downloadAvailable"):
        return fail("该搜索结果不可下载", status_code=400)
    if not has_usable_download_meta(record.get("providerType") or "", record.get("downloadMeta")):
        return fail("该搜索结果缺少可用下载信息", status_code=400)
    existing = find_active_download_task(db, record["id"])
    if existing:
        if record.get("status") != "download_created":
            record = _update(db, "SourceSearchRecord", record["id"], {"status": "download_created", "updatedAt": _now()}) or record
        return ok({"task": existing, "record": record, "alreadyQueued": True, "autoImport": _enabled_monitor_folder_for_path(db, Path(str(existing.get("savePath") or ""))) is not None})
    payload = await _request_json_or_empty(request)
    try:
        target_dir = _target_directory_from_path(settings, payload.get("targetPath"), "下载")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    save_path = str(target_dir)
    task, record, already_queued, status_code = _create_download_task_for_record(db, record, save_path)
    auto_import = _enabled_monitor_folder_for_path(db, target_dir) is not None
    if not already_queued:
        _save_system_setting(db, "library.lastDownloadTargetPath", save_path)
        db.commit()
    return ok({"task": task, "record": record, "alreadyQueued": already_queued, "autoImport": auto_import}, status_code=status_code)


@router.get("/download-tasks")
def list_download_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    tasks = _rows(db, "SELECT * FROM `DownloadTask` ORDER BY `createdAt` DESC") if _has_table(db, "DownloadTask") else []
    source_names: dict[str, str] = {}
    if _has_table(db, "Source"):
        for source in _rows(db, "SELECT `id`, `name` FROM `Source`"):
            if source.get("id"):
                source_names[str(source["id"])] = str(source.get("name") or "")
    return ok({
        "tasks": [
            {
                **task,
                "remoteRef": _parse_json(task.get("remoteRef"), task.get("remoteRef")),
                "sourceName": source_names.get(str(task.get("sourceId"))),
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
    task = _insert(db, "DownloadTask", {"id": f"py_{time_ns()}", "sourceId": payload.get("sourceId"), "searchRecordId": payload.get("searchRecordId"), "bookId": payload.get("bookId"), "type": payload.get("type") or "manual", "status": payload.get("status") or "queued", "displayName": payload.get("displayName") or payload.get("name") or "下载任务", "remoteRef": _json_text(payload.get("remoteRef", {})), "savePath": save_path, "filePath": payload.get("filePath"), "errorMessage": payload.get("errorMessage"), "progress": payload.get("progress") if payload.get("progress") is not None else 0, "createdAt": _now(), "updatedAt": _now()}) if _has_table(db, "DownloadTask") else {"id": None}
    _save_system_setting(db, "library.lastDownloadTargetPath", save_path)
    db.commit()
    _record_system_event(db, level="info", source="download", actor_type="admin", actor_id=user.id, action="created", target_type="downloadTask", target_id=task.get("id"), message=f"创建下载任务：{task.get('displayName')}", metadata={"status": task.get("status"), "type": task.get("type")})
    return ok({"task": task, "autoImport": _enabled_monitor_folder_for_path(db, target_dir) is not None}, status_code=201)


@router.get("/download-tasks/{task_id}")
def get_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _row(db, "SELECT * FROM `DownloadTask` WHERE `id` = :id", {"id": task_id}) if _has_table(db, "DownloadTask") else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    return ok({"task": task})


@router.delete("/download-tasks/{task_id}")
def delete_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _row(db, "SELECT * FROM `DownloadTask` WHERE `id` = :id", {"id": task_id}) if _has_table(db, "DownloadTask") else None
    deleted = _delete(db, "DownloadTask", task_id)
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
    task = _update(db, "DownloadTask", task_id, values)
    if not task:
        return fail("下载任务不存在", status_code=404)
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
    task = _row(db, "SELECT * FROM `DownloadTask` WHERE `id` = :id", {"id": task_id}) if _has_table(db, "DownloadTask") else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    if action in {"start", "retry"}:
        if action == "retry":
            if task.get("status") not in {"queued", "failed", "cancelled", "PENDING", "FAILED", "CANCELLED"}:
                return fail("只有等待中、失败或已取消的任务可以重新排队", status_code=400)
            task = _update(db, "DownloadTask", task_id, {"status": "queued", "progress": 0, "errorMessage": None, "updatedAt": _now()})
            _record_system_event(db, level="info", source="download", actor_type="admin", actor_id=user.id, action="retry", target_type="downloadTask", target_id=task_id, message=f"重新排队下载任务：{task.get('displayName')}", metadata={"status": task.get("status")})
            return ok({"task": task, "action": action})
        if task.get("status") not in {"queued", "failed", "PENDING", "FAILED"}:
            return fail("只有等待中或失败的任务可以开始下载", status_code=400)
        result = execute_download_task(db, settings, task_id)
        _record_system_event(db, level="error" if result.task.get("status") == "failed" else "info", source="download", actor_type="admin", actor_id=user.id, action="start", target_type="downloadTask", target_id=task_id, message=f"执行下载任务：{result.task.get('displayName')}", metadata={"status": result.task.get("status"), "errorMessage": result.task.get("errorMessage"), "filePath": result.task.get("filePath")})
        return ok({"task": result.task, "action": action})
    if action == "cancel":
        task = _update(db, "DownloadTask", task_id, {"status": "cancelled", "updatedAt": _now()})
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
    scope_sql, scope_params = monitor_folder_visibility_sql(
        context,
        "`monitorFolderId`",
        prefix="import_tasks",
    )
    filters: list[str] = [scope_sql]
    params: dict[str, Any] = dict(scope_params)
    normalized_status = str(status or "").strip().upper()
    if normalized_status and normalized_status != "ALL":
        if normalized_status not in {"PENDING", "PARSING", "COMPLETED", "FAILED"}:
            return fail("导入状态无效", status_code=400)
        filters.append("`status` = :status")
        params["status"] = normalized_status
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        filters.append(
            "(`originalName` LIKE :keyword OR `sourcePath` LIKE :keyword OR "
            "COALESCE(`message`, '') LIKE :keyword OR COALESCE(`errorSummary`, '') LIKE :keyword OR "
            "EXISTS (SELECT 1 FROM `LibraryWork` WHERE `LibraryWork`.`id` = `ImportTask`.`workId` AND `LibraryWork`.`title` LIKE :keyword))"
        )
        params["keyword"] = f"%{normalized_keyword}%"
    where = " AND ".join(filters)
    total = _table_count(db, "ImportTask", where, params)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    tasks = _rows(
        db,
        f"SELECT * FROM `ImportTask`{' WHERE ' + where if where else ''} "
        f"ORDER BY {_timestamp_sql('`createdAt`')} DESC, `id` DESC LIMIT :limit OFFSET :offset",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ) if total else []
    views = [_import_task_view(db, task, log_limit=20) for task in tasks]
    summary = {
        "completed": _table_count(db, "ImportTask", f"{scope_sql} AND `status` = 'COMPLETED'", scope_params),
        "failed": _table_count(db, "ImportTask", f"{scope_sql} AND `status` = 'FAILED'", scope_params),
    }
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
    folder_rows = _rows(db, "SELECT * FROM `MonitorFolder` WHERE `enabled` = 1") if _has_table(db, "MonitorFolder") else []
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
        scope_sql, scope_params = monitor_folder_visibility_sql(
            context,
            "`monitorFolderId`",
            prefix="clear_import_tasks",
        )
        if _has_table(db, "BookConversionTask"):
            db.execute(
                text(
                    "DELETE FROM `BookConversionTask` WHERE `importTaskId` IN "
                    "(SELECT `id` FROM `ImportTask` WHERE `status` IN ('COMPLETED', 'FAILED') "
                    f"AND {scope_sql})"
                ),
                scope_params,
            )
        result = db.execute(
            text(
                "DELETE FROM `ImportTask` WHERE `status` IN ('COMPLETED', 'FAILED') "
                f"AND {scope_sql}"
            ),
            scope_params,
        )
        db.commit()
        deleted = result.rowcount or 0
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

    conversion = (
        _row(db, "SELECT * FROM `BookConversionTask` WHERE `importTaskId` = :task_id", {"task_id": task_id})
        if _has_table(db, "BookConversionTask")
        else None
    )
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

    if conversion:
        db.execute(text("DELETE FROM `BookConversionTask` WHERE `importTaskId` = :task_id"), {"task_id": task_id})
    result = db.execute(text("DELETE FROM `ImportTask` WHERE `id` = :task_id"), {"task_id": task_id})
    db.commit()
    deleted = bool(result.rowcount)
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
        existing = _row(db, "SELECT `key` FROM `SystemSetting` WHERE `key` = :key", {"key": "monitor.rescanRequestedAt"})
        if existing:
            db.execute(text("UPDATE `SystemSetting` SET `value` = :value, `updatedAt` = :updated_at WHERE `key` = :key"), {"key": "monitor.rescanRequestedAt", "value": requested_value, "updated_at": _now()})
        else:
            db.execute(
                text("INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, :created_at, :updated_at)"),
                {"key": "monitor.rescanRequestedAt", "value": requested_value, "created_at": _now(), "updated_at": _now()},
            )
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
    task = _update(
        db,
        "ImportTask",
        task_id,
        {
            "status": "PENDING",
            "progress": 0,
            "processedAssetCount": 0,
            "message": "已重新加入后台队列",
            "errorCode": None,
            "errorSummary": None,
            "retryable": False,
            "startedAt": None,
            "finishedAt": None,
            "leaseOwner": None,
            "leaseExpiresAt": None,
            "updatedAt": _now(),
        },
    )
    if _has_table(db, "ImportAsset"):
        db.execute(
            text(
                "UPDATE `ImportAsset` SET `status` = 'PENDING', `fileId` = NULL, `errorCode` = NULL, "
                "`errorSummary` = NULL, `updatedAt` = :updated_at WHERE `importTaskId` = :task_id"
            ),
            {"updated_at": _now(), "task_id": task_id},
        )
        db.commit()
    conversion = None
    if _has_table(db, "BookConversionTask"):
        conversion = _row(db, "SELECT * FROM `BookConversionTask` WHERE `importTaskId` = :task_id", {"task_id": task_id})
        if conversion:
            _update(
                db,
                "BookConversionTask",
                conversion["id"],
                {
                    "status": "QUEUED",
                    "progress": 0,
                    "retryable": False,
                    "errorCode": None,
                    "errorSummary": None,
                    "startedAt": None,
                    "finishedAt": None,
                    "updatedAt": _now(),
                },
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
    where = "`importTaskId` = :task_id"
    params: dict[str, Any] = {"task_id": task_id, "limit": page_size, "offset": (page - 1) * page_size}
    if level:
        where += " AND `level` = :level"
        params["level"] = level.lower()
    total = _table_count(db, "ImportLog", where, params)
    logs = (
        _rows(
            db,
            f"SELECT * FROM `ImportLog` WHERE {where} "
            f"ORDER BY {_timestamp_sql('`createdAt`')} DESC, `id` DESC LIMIT :limit OFFSET :offset",
            params,
        )
        if _has_table(db, "ImportLog")
        else []
    )
    return ok({"logs": [_serialize_import_log(log) for log in logs], "page": page, "pageSize": page_size, "total": total, "totalPages": max(1, (total + page_size - 1) // page_size)})


@router.get("/shelves")
def list_shelves(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf_order = "COALESCE(`pinned`, 0) DESC, `updatedAt` DESC" if _has_column(db, "Shelf", "pinned") else "`updatedAt` DESC"
    if not _has_table(db, "Shelf"):
        shelves = []
    elif _has_column(db, "Shelf", "ownerUserId"):
        shelves = _rows(
            db,
            f"SELECT * FROM `Shelf` WHERE `ownerUserId` = :user_id ORDER BY {shelf_order}",
            {"user_id": user.id},
        )
    else:
        shelves = _rows(db, f"SELECT * FROM `Shelf` ORDER BY {shelf_order}")
    return ok({"shelves": [_shelf_summary_view(db, shelf, user) for shelf in shelves]})


def _owned_shelf(db: Session, shelf_id: str, user_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "Shelf"):
        return None
    if _has_column(db, "Shelf", "ownerUserId"):
        return _row(
            db,
            "SELECT * FROM `Shelf` WHERE `id` = :id AND `ownerUserId` = :user_id",
            {"id": shelf_id, "user_id": user_id},
        )
    return _row(db, "SELECT * FROM `Shelf` WHERE `id` = :id", {"id": shelf_id})


def _shelf_work_ids(db: Session, shelf: dict[str, Any], user: User) -> list[str]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    rules = _parse_json(shelf.get("rulesJson"), {})
    work_ids = smart_shelf_work_ids(db, rules, user.id) if kind == "SMART" else (
        [
            row["workId"]
            for row in _rows(
                db,
                "SELECT `workId` FROM `ShelfWork` WHERE `shelfId` = :shelf_id ORDER BY `createdAt` ASC",
                {"shelf_id": shelf["id"]},
            )
        ]
        if _has_table(db, "ShelfWork")
        else []
    )
    if not work_ids or not _has_table(db, "LibraryWork"):
        return []

    context = authorization_context(db, user)
    scope, scope_params = work_visibility_sql(
        context,
        alias="LibraryWork",
        prefix="shelf_books",
    )
    visible: set[str] = set()
    # Keep well below SQLite's bind-variable limit while checking access in bulk.
    for chunk_start in range(0, len(work_ids), 400):
        chunk = work_ids[chunk_start:chunk_start + 400]
        placeholders: list[str] = []
        params = dict(scope_params)
        for index, work_id in enumerate(chunk):
            key = f"shelf_work_{index}"
            placeholders.append(f":{key}")
            params[key] = work_id
        rows = _rows(
            db,
            "SELECT `LibraryWork`.`id` FROM `LibraryWork` "
            f"WHERE `LibraryWork`.`id` IN ({', '.join(placeholders)}) AND {scope}",
            params,
        )
        visible.update(str(row["id"]) for row in rows)
    return [str(work_id) for work_id in work_ids if str(work_id) in visible]


def _shelf_book_views(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    placeholders: list[str] = []
    params: dict[str, Any] = {}
    for index, work_id in enumerate(work_ids):
        key = f"shelf_card_{index}"
        placeholders.append(f":{key}")
        params[key] = work_id
    works = _rows(
        db,
        f"SELECT * FROM `LibraryWork` WHERE `id` IN ({', '.join(placeholders)})",
        params,
    )
    works_by_id = {str(work["id"]): work for work in works}
    labels = _labels()
    result: list[dict[str, Any]] = []
    for work_id in work_ids:
        work = works_by_id.get(str(work_id))
        if not work:
            continue
        format_value = str(work.get("workType") or "EPUB").upper()
        result.append(
            {
                "id": str(work["id"]),
                "title": work.get("title") or "未命名作品",
                "author": work.get("author") or "未知作者",
                "format": labels["format"].get(format_value, format_value),
                "gradient": "from-slate-950 via-blue-800 to-cyan-500",
                "coverStatus": work.get("coverStatus") or "PENDING",
                "coverUrl": _cover_url("works", str(work["id"]), work, size="medium"),
            }
        )
    return result


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
    if not _has_table(db, "ShelfWork"):
        return
    db.execute(text("DELETE FROM `ShelfWork` WHERE `shelfId` = :shelf_id"), {"shelf_id": shelf_id})
    for work_id in work_ids:
        db.execute(
            text("INSERT INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES (:shelf_id, :work_id, :created_at)"),
            {"shelf_id": shelf_id, "work_id": work_id, "created_at": _now()},
        )
    db.commit()


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
    shelf = _insert(db, "Shelf", {"id": f"py_{time_ns()}", "ownerUserId": user.id, "name": name, "description": str(payload.get("description") or "").strip() or None, "kind": kind, "rulesJson": _json_text(rules), "pinned": bool(payload.get("pinned")), "createdAt": _now(), "updatedAt": _now()})
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
    shelf = _update(db, "Shelf", shelf_id, values)
    if not shelf:
        return fail("书架不存在", status_code=404)
    if work_ids is not None and kind == "STATIC":
        _replace_shelf_works(db, shelf_id, work_ids)
    elif kind == "SMART" and str(existing_shelf.get("kind") or "STATIC").upper() != "SMART":
        _replace_shelf_works(db, shelf_id, [])
    return ok({"shelf": _shelf_detail_view(db, shelf, user)})


@router.delete("/shelves/{shelf_id}")
def delete_shelf(shelf_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf = _owned_shelf(db, shelf_id, user.id)
    if not shelf:
        return fail("书架不存在", status_code=404)
    if "shelfId" in _set_columns(db, "MonitorFolder"):
        _update_where(db, "MonitorFolder", "`shelfId` = :shelf_id", {"shelf_id": shelf_id}, {"shelfId": None, "updatedAt": _now()})
    if _has_table(db, "ShelfWork"):
        db.execute(text("DELETE FROM `ShelfWork` WHERE `shelfId` = :shelf_id"), {"shelf_id": shelf_id})
        db.commit()
    return ok({"deleted": _delete(db, "Shelf", shelf_id), "id": shelf_id})


@router.get("/library/facets")
def library_facets(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    facets = {kind.lower(): _visible_categories(db, user, kind) for kind in ("AUTHOR", "TAG", "SERIES", "PUBLISHER")}
    context = authorization_context(db, user)
    work_scope, work_params = work_visibility_sql(context, alias="w", prefix="facet_status")
    visible_works = _rows(
        db,
        f"SELECT w.* FROM `LibraryWork` w WHERE COALESCE(w.`hidden`, 0) = 0 AND {work_scope}",
        work_params,
    )
    status_counts: dict[str, int] = {}
    for work in visible_works:
        status = str(_work_view(db, work, user.id).get("status") or "UNREAD")
        status_counts[status] = status_counts.get(status, 0) + 1
    status_rows = [{"value": value, "count": count} for value, count in sorted(status_counts.items())]
    edition_scope, edition_params = edition_visibility_sql(context, alias="e", prefix="facet_media")
    media_rows = _rows(
        db,
        "SELECT e.`mediaKind` AS `value`, COUNT(DISTINCT e.`workId`) AS `count` "
        "FROM `LibraryEdition` e WHERE COALESCE(e.`hidden`, 0) = 0 "
        f"AND {edition_scope} GROUP BY e.`mediaKind`",
        edition_params,
    )
    return ok({"facets": facets, "statuses": status_rows, "mediaKinds": media_rows})


def _visible_categories(db: Session, user: User, kind: str) -> list[dict[str, Any]]:
    normalized_kind = kind.upper()
    if user.role == "admin":
        return list_categories(db, normalized_kind)
    context = authorization_context(db, user)
    if normalized_kind == "PUBLISHER":
        scope, params = edition_visibility_sql(context, alias="e", prefix="category_publisher")
        rows = _rows(
            db,
            "SELECT f.*, COUNT(DISTINCT e.`workId`) AS `bookCount` FROM `LibraryFacet` f "
            "JOIN `LibraryEditionFacet` ef ON ef.`facetId` = f.`id` "
            "JOIN `LibraryEdition` e ON e.`id` = ef.`editionId` "
            "JOIN `LibraryWork` w ON w.`id` = e.`workId` "
            "WHERE f.`kind` = 'PUBLISHER' AND COALESCE(e.`hidden`, 0) = 0 "
            f"AND COALESCE(w.`hidden`, 0) = 0 AND {scope} "
            "GROUP BY f.`id` ORDER BY `bookCount` DESC, f.`name` COLLATE NOCASE ASC",
            params,
        )
    else:
        scope, params = work_visibility_sql(context, alias="w", prefix=f"category_{normalized_kind.lower()}")
        params["kind"] = normalized_kind
        rows = _rows(
            db,
            "SELECT f.*, COUNT(DISTINCT w.`id`) AS `bookCount` FROM `LibraryFacet` f "
            "JOIN `LibraryWorkFacet` wf ON wf.`facetId` = f.`id` "
            "JOIN `LibraryWork` w ON w.`id` = wf.`workId` "
            "WHERE f.`kind` = :kind AND COALESCE(w.`hidden`, 0) = 0 "
            f"AND {scope} GROUP BY f.`id` "
            "ORDER BY `bookCount` DESC, f.`name` COLLATE NOCASE ASC",
            params,
        )
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
        work_scope, work_params = work_visibility_sql(context, alias="w", prefix="filter_options_work")
        work_rows = _rows(
            db,
            "SELECT w.`author`, w.`tags`, w.`seriesName`, w.`origin` FROM `LibraryWork` w "
            f"WHERE COALESCE(w.`hidden`, 0) = 0 AND {work_scope}",
            work_params,
        )
        edition_scope, edition_params = edition_visibility_sql(context, alias="e", prefix="filter_options_edition")
        edition_rows = _rows(
            db,
            "SELECT e.`publisher`, e.`language`, e.`format`, e.`importStatus`, e.`origin`, e.`mediaKind` "
            "FROM `LibraryEdition` e WHERE COALESCE(e.`hidden`, 0) = 0 "
            f"AND {edition_scope}",
            edition_params,
        )

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
        monitor_rows = _rows(db, "SELECT `id`, `name`, `rootPath` FROM `MonitorFolder` ORDER BY `name` COLLATE NOCASE ASC")
    elif context.monitor_folder_ids:
        placeholders = ", ".join(f":folder_{index}" for index, _folder_id in enumerate(context.monitor_folder_ids))
        monitor_rows = _rows(
            db,
            f"SELECT `id`, `name`, `rootPath` FROM `MonitorFolder` WHERE `id` IN ({placeholders}) ORDER BY `name` COLLATE NOCASE ASC",
            {f"folder_{index}": folder_id for index, folder_id in enumerate(context.monitor_folder_ids)},
        )
    else:
        monitor_rows = []
    options_by_source["monitorFolders"] = [
        {"value": str(row["id"]), "label": str(row["name"]), "rootPath": row.get("rootPath")}
        for row in monitor_rows
    ]
    options_by_source["shelves"] = [
        {"value": str(row["id"]), "label": str(row["name"])}
        for row in _rows(
            db,
            "SELECT `id`, `name` FROM `Shelf` WHERE `ownerUserId` = :user_id "
            "AND COALESCE(`kind`, 'STATIC') = 'STATIC' ORDER BY `name` COLLATE NOCASE ASC",
            {"user_id": user.id},
        )
    ] if _has_column(db, "Shelf", "ownerUserId") else []
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
    operations = _rows(db, "SELECT * FROM `LibraryOperation` WHERE `userId` = :user_id OR `userId` IS NULL ORDER BY `createdAt` DESC LIMIT 100", {"user_id": user.id})
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
        return ok({"policy": update_organize_policy(db, payload)})
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
    if not (_has_table(db, "OrganizeJob") and _has_table(db, "LibraryWork")):
        return ok({"jobs": [], "books": [], "page": 1, "pageSize": page_size, "total": 0, "totalPages": 1, "statusCounts": {"SUCCESS": 0, "FAILED": 0, "RECOGNIZING": 0, "WAITING": 0}})

    lookup_status_sql = (
        "COALESCE((SELECT UPPER(COALESCE(t.`status`, '')) FROM `MetadataLookupTask` t "
        "WHERE t.`organizeJobId` = j.`id` ORDER BY t.`createdAt` DESC, t.`id` DESC LIMIT 1), '')"
        if _has_table(db, "MetadataLookupTask")
        else "''"
    )
    status_category_sql = f"""
        CASE
            WHEN UPPER(COALESCE(j.`status`, '')) IN ('APPLIED', 'COMPLETED') THEN 'SUCCESS'
            WHEN UPPER(COALESCE(j.`status`, '')) IN ('FAILED', 'REVIEWING', 'DISMISSED', 'CANCELLED') THEN 'FAILED'
            WHEN UPPER(COALESCE(j.`status`, '')) = 'RUNNING' OR {lookup_status_sql} = 'RUNNING' THEN 'RECOGNIZING'
            ELSE 'WAITING'
        END
    """
    status_counts = {"SUCCESS": 0, "FAILED": 0, "RECOGNIZING": 0, "WAITING": 0}
    for item in _rows(
        db,
        f"SELECT ({status_category_sql}) AS `category`, COUNT(*) AS `count` "
        "FROM `OrganizeJob` j INNER JOIN `LibraryWork` w ON w.`id` = j.`workId` GROUP BY `category`",
    ):
        category = str(item.get("category") or "")
        if category in status_counts:
            status_counts[category] = int(item.get("count") or 0)
    where: list[str] = []
    params: dict[str, Any] = {}
    if status != "ALL":
        where.append(f"({status_category_sql}) = :status")
        params["status"] = status
    if search:
        search_terms = [
            "LOWER(COALESCE(w.`title`, '')) LIKE :search",
            "LOWER(COALESCE(w.`author`, '')) LIKE :search",
            "LOWER(COALESCE(j.`summary`, '')) LIKE :search",
            "LOWER(COALESCE(j.`issueCodes`, '')) LIKE :search",
        ]
        if _has_column(db, "OrganizeJob", "reasonCodes"):
            search_terms.append("LOWER(COALESCE(j.`reasonCodes`, '')) LIKE :search")
        if _has_column(db, "OrganizeJob", "trigger"):
            search_terms.append("LOWER(COALESCE(j.`trigger`, '')) LIKE :search")
        if _has_table(db, "MetadataProviderExecution"):
            search_terms.append(
                "EXISTS (SELECT 1 FROM `MetadataProviderExecution` e WHERE e.`jobId` = j.`id` AND LOWER(COALESCE(e.`providerId`, '')) LIKE :search)"
            )
        if _has_table(db, "MetadataLookupTask"):
            search_terms.append(
                "EXISTS (SELECT 1 FROM `MetadataLookupTask` t WHERE t.`organizeJobId` = j.`id` "
                "AND (LOWER(COALESCE(t.`resultSource`, '')) LIKE :search OR LOWER(COALESCE(t.`providerOrder`, '')) LIKE :search))"
            )
        reason_aliases = {
            "历史手动加入": "MANUAL_SELECTED",
            "手动重新识别": "MANUAL_RECOGNIZE",
            "尚未识别": "UNRECOGNIZED",
            "缺少元数据": "MISSING_METADATA",
            "元数据质量偏低": "QUALITY_BELOW_THRESHOLD",
            "新增读物": "NEW_IMPORT",
            "导入解析失败": "IMPORT_FAILED",
            "缺少封面": "MISSING_COVER",
            "缺少作者": "MISSING_AUTHOR",
            "标题异常": "ODD_TITLE",
            "新增后自动执行": "NEW",
            "定时识别": "SCHEDULE",
        }
        for index, (label, code) in enumerate(reason_aliases.items()):
            if search not in label.lower():
                continue
            key = f"reason_alias_{index}"
            params[key] = f"%{code.lower()}%"
            search_terms.append(f"LOWER(COALESCE(j.`issueCodes`, '')) LIKE :{key}")
            if _has_column(db, "OrganizeJob", "reasonCodes"):
                search_terms.append(f"LOWER(COALESCE(j.`reasonCodes`, '')) LIKE :{key}")
            if _has_column(db, "OrganizeJob", "trigger"):
                search_terms.append(f"LOWER(COALESCE(j.`trigger`, '')) LIKE :{key}")
        provider_ids = [
            str(provider.get("id") or "")
            for provider in list_metadata_providers(db)
            if search in str(provider.get("name") or "").lower()
        ]
        source_aliases = {
            "embedded": "内嵌元数据",
            "filename": "文件名",
            "aggregation": "自动聚合",
            "external": "外部数据源",
            "rule": "整理规则",
        }
        provider_ids.extend(provider_id for provider_id, label in source_aliases.items() if search in label.lower())
        for index, provider_id in enumerate(provider_ids):
            key = f"provider_id_{index}"
            params[key] = provider_id.lower()
            provider_terms = []
            if _has_table(db, "MetadataProviderExecution"):
                provider_terms.append(
                    f"EXISTS (SELECT 1 FROM `MetadataProviderExecution` e WHERE e.`jobId` = j.`id` AND LOWER(COALESCE(e.`providerId`, '')) = :{key})"
                )
            if _has_table(db, "MetadataLookupTask"):
                provider_terms.append(
                    f"EXISTS (SELECT 1 FROM `MetadataLookupTask` t WHERE t.`organizeJobId` = j.`id` "
                    f"AND (LOWER(COALESCE(t.`resultSource`, '')) = :{key} OR LOWER(COALESCE(t.`providerOrder`, '')) LIKE :{key}_json))"
                )
                params[f"{key}_json"] = f'%"{provider_id.lower()}"%'
            search_terms.extend(provider_terms)
        where.append(f"({' OR '.join(search_terms)})")
        params["search"] = f"%{search}%"

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = int(
        db.execute(
            text(f"SELECT COUNT(*) FROM `OrganizeJob` j INNER JOIN `LibraryWork` w ON w.`id` = j.`workId` {where_sql}"),
            params,
        ).scalar()
        or 0
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(requested_page, total_pages)
    rows = (
        _rows(
            db,
            f"""
            SELECT j.* FROM `OrganizeJob` j
            INNER JOIN `LibraryWork` w ON w.`id` = j.`workId`
            {where_sql}
            ORDER BY j.`createdAt` DESC, j.`updatedAt` DESC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
    )
    jobs = [view for row in rows if (view := _organize_job_view(db, row, getattr(user, "id", None))) is not None]
    return ok({"jobs": jobs, "books": [job["book"] for job in jobs], "page": page, "pageSize": page_size, "total": total, "totalPages": total_pages, "statusCounts": status_counts})


@router.get("/organize/pending")
def list_pending_organize(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page_size = _positive_int(request.query_params.get("pageSize"), 50, 200)
    rows = (
        _rows(
            db,
            """
            SELECT j.* FROM `OrganizeJob` j
            INNER JOIN `LibraryWork` w ON w.`id` = j.`workId`
            WHERE j.`status` = 'REVIEWING' AND COALESCE(w.`hidden`, 0) = 0
            ORDER BY j.`updatedAt` DESC
            LIMIT :limit
            """,
            {"limit": page_size},
        )
        if _has_table(db, "OrganizeJob") and _has_table(db, "LibraryWork")
        else []
    )
    jobs = [view for row in rows if (view := _organize_job_view(db, row, getattr(user, "id", None), pending_only=True)) is not None]
    return ok({"jobs": jobs, "books": [job["book"] for job in jobs], "total": len(jobs)})


@router.get("/organize/jobs/{job_id}")
def get_organize_job(job_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    job = _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) if _has_table(db, "OrganizeJob") else None
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
        job = _row(db, "SELECT * FROM `OrganizeJob` WHERE `id` = :id", {"id": job_id}) or {}
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
    jobs = _rows(
        db,
        "SELECT `id` FROM `OrganizeJob` WHERE `workId` = :work_id AND `status` IN ('PENDING', 'REVIEWING', 'FAILED')",
        {"work_id": work_id},
    )
    job_ids = [str(job["id"]) for job in jobs if job.get("id")]
    if not job_ids:
        return []
    for job_id in job_ids:
        _update(db, "OrganizeJob", job_id, {"status": "APPLIED", "summary": "元数据已应用，整理完成", "errorSummary": None, "updatedAt": _now()})
    db.commit()
    return job_ids


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
    edition = _row(
        db,
        "SELECT * FROM `LibraryEdition` WHERE `id` = :edition_id AND `workId` = :work_id AND COALESCE(`hidden`, 0) = 0",
        {"edition_id": edition_id, "work_id": work_id},
    ) if _has_table(db, "LibraryEdition") else None
    if not edition:
        return fail("版本不存在或不属于该作品", status_code=404)
    payload = await request.json()
    allowed = {"versionName", "description", "publisher", "publishedAt", "language", "identifier", "isbn", "narrator", "abridged"}
    values = {key: payload.get(key) for key in allowed if key in payload}
    for key in ("versionName", "publisher", "language", "identifier", "isbn", "narrator"):
        if key in values:
            values[key] = str(values[key] or "").strip() or None
    values["updatedAt"] = _now()
    updated = _update(db, "LibraryEdition", edition_id, values)
    sync_work_facets(db, work_id)
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
    edition = (
        _row(
            db,
            "SELECT * FROM `LibraryEdition` WHERE `id` = :edition_id AND `workId` = :work_id AND COALESCE(`hidden`, 0) = 0",
            {"edition_id": edition_id, "work_id": work_id},
        )
        if _has_table(db, "LibraryEdition")
        else None
    )
    if not work or not edition:
        return fail("版本不存在或不属于该作品", status_code=404)
    source_format = str(edition.get("format") or "").strip().lower()
    if f".{source_format}" not in CONVERTIBLE_TEXT_EXTS:
        return fail("该版本不支持转换为 EPUB", status_code=400)
    source_file = _row(
        db,
        "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `createdAt` LIMIT 1",
        {"edition_id": edition_id},
    ) if _has_table(db, "LibraryFile") else None
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
        work = _update(db, "LibraryWork", work_id, patch)
        if not work:
            return fail("作品不存在", status_code=404)
        if publisher and _has_table(db, "LibraryEdition"):
            primary_edition_id = str(work.get("primaryEditionId") or "")
            if not primary_edition_id:
                first_edition = _row(
                    db,
                    "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC LIMIT 1",
                    {"work_id": work_id},
                )
                primary_edition_id = str((first_edition or {}).get("id") or "")
            if primary_edition_id:
                _update(db, "LibraryEdition", primary_edition_id, {"publisher": publisher, "updatedAt": _now()})
        sync_work_facets(db, work_id)
        finished_job_ids = _finish_metadata_organize_work(db, work_id)
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
        edition = _row(
            db,
            "SELECT * FROM `LibraryEdition` WHERE `id` = :edition_id AND `workId` = :work_id AND COALESCE(`hidden`, 0) = 0",
            {"edition_id": edition_id, "work_id": work_id},
        ) if _has_table(db, "LibraryEdition") else None
        if not edition:
            return fail("版本不存在或不属于该作品", status_code=404)
        if not _get_work(db, work_id):
            return fail("作品不存在", status_code=404)
        now = _now()
        media_kind = _edition_media_kind(edition)
        if _has_column(db, "LibraryEdition", "mediaKind"):
            db.execute(
                text("UPDATE `LibraryEdition` SET `primary` = 0, `updatedAt` = :updated_at WHERE `workId` = :work_id AND `mediaKind` = :media_kind"),
                {"work_id": work_id, "media_kind": media_kind, "updated_at": now},
            )
        else:
            compatible_formats = ("EPUB", "PDF") if media_kind == "EBOOK" else (edition.get("format"),)
            placeholders = ", ".join(f":format_{index}" for index in range(len(compatible_formats)))
            db.execute(
                text(f"UPDATE `LibraryEdition` SET `primary` = 0, `updatedAt` = :updated_at WHERE `workId` = :work_id AND `format` IN ({placeholders})"),
                {"work_id": work_id, "updated_at": now, **{f"format_{index}": value for index, value in enumerate(compatible_formats)}},
            )
        db.execute(text("UPDATE `LibraryEdition` SET `primary` = 1, `updatedAt` = :updated_at WHERE `id` = :edition_id AND `workId` = :work_id"), {"edition_id": edition_id, "work_id": work_id, "updated_at": now})
        db.execute(text("UPDATE `LibraryWork` SET `primaryEditionId` = :edition_id, `workType` = :work_type, `updatedAt` = :updated_at WHERE `id` = :work_id"), {"edition_id": edition_id, "work_type": edition.get("format") or "EPUB", "work_id": work_id, "updated_at": now})
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
        source = _row(
            db,
            """
            SELECT v.*, e.`workId` AS sourceWorkId, e.`format` AS sourceFormat
            FROM `LibraryVolume` v
            JOIN `LibraryEdition` e ON e.`id` = v.`editionId`
            WHERE v.`id` = :volume_id AND e.`workId` = :work_id AND COALESCE(e.`hidden`, 0) = 0
            """,
            {"volume_id": volume_id, "work_id": work_id},
        ) if _has_table(db, "LibraryVolume") and _has_table(db, "LibraryEdition") else None
        if not source:
            return fail("卷册不存在或不属于该作品", status_code=404)
        target = _row(
            db,
            """
            SELECT e.*, w.`title` AS targetWorkTitle
            FROM `LibraryEdition` e
            JOIN `LibraryWork` w ON w.`id` = e.`workId`
            WHERE e.`id` = :edition_id AND COALESCE(e.`hidden`, 0) = 0
            """,
            {"edition_id": target_edition_id},
        ) if _has_table(db, "LibraryEdition") and _has_table(db, "LibraryWork") else None
        if not target:
            return fail("目标版本不存在", status_code=404)
        target_work_id = target.get("workId")
        if target_work_id == work_id:
            return fail("请选择另一部目标图书", status_code=400)
        now = _now()
        source_edition_id = str(source.get("editionId") or "")
        source_edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": source_edition_id}) or {}
        source_format = str(source.get("sourceFormat") or "").upper()
        source_media_kind = _edition_media_kind(source_edition)
        matching_primary = _row(
            db,
            """
            SELECT * FROM `LibraryEdition`
            WHERE `workId` = :work_id
              AND UPPER(`format`) = :format
              AND COALESCE(`hidden`, 0) = 0
            ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC, `id` ASC
            LIMIT 1
            """,
            {"work_id": target_work_id, "format": source_format},
        )
        source_volume_count = int((_row(
            db,
            "SELECT COUNT(*) AS count FROM `LibraryVolume` WHERE `editionId` = :edition_id",
            {"edition_id": source_edition_id},
        ) or {}).get("count") or 0)
        matching_volume_count = int((_row(
            db,
            "SELECT COUNT(*) AS count FROM `LibraryVolume` WHERE `editionId` = :edition_id",
            {"edition_id": (matching_primary or {}).get("id")},
        ) or {}).get("count") or 0) if matching_primary else 0
        merge_volumes = bool(matching_primary and source_volume_count > 0 and matching_volume_count > 0)

        if merge_volumes:
            resolved_target_edition_id = str(matching_primary["id"])
            transfer_mode = "MERGED_VOLUME"
            _update(db, "LibraryVolume", volume_id, {"editionId": resolved_target_edition_id, "updatedAt": now})
            _update_where(db, "LibraryFile", "`volumeId` = :volume_id", {"volume_id": volume_id}, {"editionId": resolved_target_edition_id, "updatedAt": now})
            _update_where(db, "LibraryReadingUnit", "`volumeId` = :volume_id", {"volume_id": volume_id}, {"editionId": resolved_target_edition_id, "updatedAt": now})
            _update_where(db, "LibraryReadingProgress", "`volumeId` = :volume_id", {"volume_id": volume_id}, {"workId": target_work_id, "editionId": resolved_target_edition_id, "updatedAt": now})
            _update_where(db, "ImportTask", "`volumeId` = :volume_id", {"volume_id": volume_id}, {"workId": target_work_id, "editionId": resolved_target_edition_id, "updatedAt": now})
            if _has_table(db, "KindleSendTask"):
                _update_where(db, "KindleSendTask", "`volumeId` = :volume_id", {"volume_id": volume_id}, {"workId": target_work_id, "editionId": resolved_target_edition_id, "updatedAt": now})
            previous_counts = _row(
                db,
                "SELECT COUNT(*) AS volumes, COALESCE(SUM(`pageCount`), 0) AS pages, COALESCE(SUM(`chapterCount`), 0) AS chapters FROM `LibraryVolume` WHERE `editionId` = :edition_id",
                {"edition_id": source_edition_id},
            ) or {}
            _update(db, "LibraryEdition", source_edition_id, {"pageCount": int(previous_counts.get("pages") or 0), "chapterCount": int(previous_counts.get("chapters") or 0), "updatedAt": now})
            direct_file_count = int((_row(
                db,
                "SELECT COUNT(*) AS count FROM `LibraryFile` WHERE `editionId` = :edition_id AND `volumeId` IS NULL",
                {"edition_id": source_edition_id},
            ) or {}).get("count") or 0)
            if int(previous_counts.get("volumes") or 0) == 0 and direct_file_count == 0:
                source_was_primary = bool(source_edition.get("primary"))
                _update(db, "LibraryEdition", source_edition_id, {"primary": False, "hidden": True, "updatedAt": now})
                remaining_same_media = _row(
                    db,
                    """
                    SELECT `id`, `primary` FROM `LibraryEdition`
                    WHERE `workId` = :work_id AND `mediaKind` = :media_kind AND COALESCE(`hidden`, 0) = 0
                    ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC, `id` ASC LIMIT 1
                    """,
                    {"work_id": work_id, "media_kind": source_media_kind},
                )
                if source_was_primary and remaining_same_media and not remaining_same_media.get("primary"):
                    _update(db, "LibraryEdition", str(remaining_same_media["id"]), {"primary": True, "updatedAt": now})
                remaining_edition = _row(
                    db,
                    "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC LIMIT 1",
                    {"work_id": work_id},
                )
                _update(
                    db,
                    "LibraryWork",
                    work_id,
                    {
                        "primaryEditionId": (remaining_edition or {}).get("id"),
                        "hidden": not bool(remaining_edition),
                        "updatedAt": now,
                    },
                )
            target_volumes = _rows(
                db,
                """
                SELECT * FROM `LibraryVolume`
                WHERE `editionId` = :edition_id
                ORDER BY
                    CASE WHEN `volumeIndex` IS NULL THEN 1 ELSE 0 END ASC,
                    `volumeIndex` ASC,
                    `sortOrder` ASC,
                    `createdAt` ASC,
                    `id` ASC
                """,
                {"edition_id": resolved_target_edition_id},
            )
            for index, volume in enumerate(target_volumes):
                _update(db, "LibraryVolume", volume["id"], {"sortOrder": (index + 1) * 1000, "updatedAt": now})
            target_counts = _row(
                db,
                "SELECT COALESCE(SUM(`pageCount`), 0) AS pages, COALESCE(SUM(`chapterCount`), 0) AS chapters FROM `LibraryVolume` WHERE `editionId` = :edition_id",
                {"edition_id": resolved_target_edition_id},
            ) or {}
            _update(db, "LibraryEdition", resolved_target_edition_id, {"pageCount": int(target_counts.get("pages") or 0), "chapterCount": int(target_counts.get("chapters") or 0), "updatedAt": now})
        else:
            resolved_target_edition_id = source_edition_id
            existing_media = _row(
                db,
                "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND `mediaKind` = :media_kind AND COALESCE(`hidden`, 0) = 0 LIMIT 1",
                {"work_id": target_work_id, "media_kind": source_media_kind},
            )
            transfer_mode = "ADDED_MEDIA" if not existing_media else "ADDED_BACKUP_EDITION"
            desired_version_key = str(source_edition.get("versionKey") or source_edition_id)
            version_key = desired_version_key
            suffix = 1
            while _row(
                db,
                "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND `versionKey` = :version_key AND `id` != :edition_id LIMIT 1",
                {"work_id": target_work_id, "version_key": version_key, "edition_id": source_edition_id},
            ):
                suffix += 1
                version_key = f"{desired_version_key}:backup-{suffix}"
            _update(
                db,
                "LibraryEdition",
                source_edition_id,
                {
                    "workId": target_work_id,
                    "versionKey": version_key,
                    "primary": not bool(existing_media),
                    "updatedAt": now,
                },
            )
            _update_where(db, "LibraryReadingProgress", "`editionId` = :edition_id", {"edition_id": source_edition_id}, {"workId": target_work_id, "updatedAt": now})
            _update_where(db, "ImportTask", "`editionId` = :edition_id", {"edition_id": source_edition_id}, {"workId": target_work_id, "updatedAt": now})
            if _has_table(db, "KindleSendTask"):
                _update_where(db, "KindleSendTask", "`editionId` = :edition_id", {"edition_id": source_edition_id}, {"workId": target_work_id, "updatedAt": now})
            remaining_edition = _row(
                db,
                "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 ORDER BY COALESCE(`primary`, 0) DESC, `createdAt` ASC LIMIT 1",
                {"work_id": work_id},
            )
            _update(
                db,
                "LibraryWork",
                work_id,
                {
                    "primaryEditionId": (remaining_edition or {}).get("id"),
                    "hidden": not bool(remaining_edition),
                    "updatedAt": now,
                },
            )
        _update(db, "LibraryWork", work_id, {"updatedAt": now})
        if target_work_id:
            _update(db, "LibraryWork", target_work_id, {"updatedAt": now})
        _record_system_event(
            db,
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="volume.moved" if merge_volumes else "edition.moved",
            target_type="volume" if merge_volumes else "edition",
            target_id=volume_id if merge_volumes else source_edition_id,
            message=("合并卷册" if merge_volumes else "转移版本") + f"到《{target.get('targetWorkTitle') or target_work_id}》",
            metadata={"sourceWorkId": work_id, "targetWorkId": target_work_id, "sourceEditionId": source_edition_id, "targetEditionId": resolved_target_edition_id, "transferMode": transfer_mode},
        )
        source_work = _get_work(db, work_id)
        target_work = _get_work(db, target_work_id) if target_work_id else None
        return ok({
            "book": _work_view(db, source_work, user.id) if source_work else None,
            "targetBook": _work_view(db, target_work, user.id) if target_work else None,
            "workId": work_id,
            "targetWorkId": target_work_id,
            "volumeId": volume_id,
            "targetEditionId": resolved_target_edition_id,
            "transferMode": transfer_mode,
        })
    if request.url.path.endswith("/move") and volume_id:
        payload = await request.json()
        direction = str(payload.get("direction") or "").lower()
        if direction not in {"up", "down"}:
            return fail("请选择上移或下移", status_code=400)
        volume = _row(
            db,
            """
            SELECT v.* FROM `LibraryVolume` v
            JOIN `LibraryEdition` e ON e.`id` = v.`editionId`
            WHERE v.`id` = :volume_id AND e.`workId` = :work_id
            """,
            {"volume_id": volume_id, "work_id": work_id},
        ) if _has_table(db, "LibraryVolume") and _has_table(db, "LibraryEdition") else None
        if not volume:
            return fail("卷册不存在或不属于该作品", status_code=404)
        volumes = _rows(db, "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder` ASC, `id` ASC", {"edition_id": volume["editionId"]})
        index = next((item_index for item_index, item in enumerate(volumes) if item["id"] == volume_id), -1)
        target_index = index - 1 if direction == "up" else index + 1
        if index < 0 or target_index < 0 or target_index >= len(volumes):
            work = _get_work(db, work_id)
            return ok({"book": _work_view(db, work, user.id) if work else None, "workId": work_id, "volumeId": volume_id})
        target = volumes[target_index]
        _update(db, "LibraryVolume", volume_id, {"sortOrder": target.get("sortOrder") or 0, "updatedAt": _now()})
        _update(db, "LibraryVolume", target["id"], {"sortOrder": volume.get("sortOrder") or 0, "updatedAt": _now()})
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
