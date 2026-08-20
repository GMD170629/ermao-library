"""Import HTTP projections."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.bootstrap.imports import import_http_store
from app.contracts.imports import ImportTaskContract
from app.core.time import timestamp_ms_to_iso
from app.models.library import LibraryWork
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.monitor_paths import (
    LibraryPathError,
    is_inside_path,
    library_directory_tree_node,
    resolve_library_root_path,
)

logger = logging.getLogger(__name__)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except SQLAlchemyError:
        return False


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return timestamp_ms_to_iso(value) or str(value)


def _recognized_metadata_view(value: object) -> dict[str, object] | None:
    parsed_value: object = value
    if isinstance(value, str):
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed_value, dict):
        return None
    title = parsed_value.get("title")
    source = parsed_value.get("source")
    if not isinstance(title, str) or source not in {
        "REQUESTED",
        "SIDECAR_OPF",
        "EMBEDDED",
        "PATH",
    }:
        return None
    author = parsed_value.get("author")
    fields = parsed_value.get("fields")
    field_sources = parsed_value.get("fieldSources")
    source_order = parsed_value.get("sourceOrder")
    allowed_sources = {"REQUESTED", "SIDECAR_OPF", "EMBEDDED", "PATH"}
    return {
        "title": title,
        "volumeTitle": (
            parsed_value.get("volumeTitle")
            if isinstance(parsed_value.get("volumeTitle"), str)
            else title
        ),
        "author": author if isinstance(author, str) else None,
        "volumeIndex": parsed_value.get("volumeIndex")
        if isinstance(parsed_value.get("volumeIndex"), (int, float))
        else None,
        "fields": [field for field in fields if isinstance(field, str)]
        if isinstance(fields, list)
        else [],
        "fieldSources": {
            str(field): item_source
            for field, item_source in field_sources.items()
            if isinstance(field, str) and item_source in allowed_sources
        }
        if isinstance(field_sources, dict)
        else {},
        "sourceOrder": [
            item_source
            for item_source in source_order
            if item_source in {"SIDECAR_OPF", "EMBEDDED", "PATH"}
        ]
        if isinstance(source_order, list)
        else [],
        "source": source,
    }


def friendly_import_error(
    message: str | None, error_code: str | None = None
) -> str | None:
    text_value = message or ""
    code = (error_code or "").upper()
    if code == "LIBRARY_NOT_FOUND":
        return "书库已被删除，本次导入任务已结束。"
    if code == "SOURCE_NOT_FOUND":
        return "文件不存在：可能已被移动、删除，或监控目录配置已变化。"
    if code == "IMPORT_WORKER_FAILED":
        return "导入工作进程意外中断，本次任务已经结束，可以稍后重试。"
    if code == "AUDIO_TRACK_LIMIT_EXCEEDED":
        return "有声书音轨超过 10000 条，请按卷或子目录拆分后重新导入。"
    if code == "DRM_PROTECTED":
        return "文件可能受 DRM 保护，无法打开。原文件已保留。"
    if code == "TEXT_ENCODING_UNCERTAIN":
        return "无法可靠识别 TXT 编码。原文件已保留，可在后续高级模式中手动指定。"
    if re.search(r"EACCES|permission|权限", text_value, re.IGNORECASE):
        return "权限不足：请确认容器用户可以读取该目录和文件。"
    if re.search(r"ENOENT|not found|不存在", text_value, re.IGNORECASE):
        return "文件不存在：可能已被移动、删除，或监控目录配置已变化。"
    if re.search(r"unsupported|format|格式", text_value, re.IGNORECASE):
        return "格式暂不支持：请确认文件属于当前支持的图书格式。"
    if re.search(r"zip|archive|corrupt|invalid|损坏", text_value, re.IGNORECASE):
        return "压缩包可能损坏：请重新复制文件或用本地工具测试压缩包。"
    return "导入失败：请检查文件完整性和格式。" if text_value else None


def display_path_name(value: Any) -> str:
    text_value = str(value or "")
    parts = [part for part in re.split(r"[\\/]+", text_value) if part]
    return parts[-1] if parts else text_value


def serialize_import_log(log: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": log.get("id"),
        "level": log.get("level") or "info",
        "message": log.get("message") or "",
        "createdAt": _dt(log.get("createdAt")),
    }


def import_task_view(
    db: Session, task: dict[str, Any], log_limit: int = 20
) -> dict[str, Any]:
    page_hydrated = "_pageLogs" in task
    library = task.get("_pageLibrary") if page_hydrated else None
    if not page_hydrated and task.get("libraryId") and _has_table(db, "Library"):
        library = import_http_store.get_library(db, str(task.get("libraryId")))
    book = None
    if page_hydrated:
        work = task.get("_pageWork")
        if isinstance(work, dict):
            book = {"id": work.get("id"), "title": work.get("title") or "未命名作品"}
    elif task.get("workId") and _has_table(db, "LibraryWork"):
        work_row = db.get(LibraryWork, str(task.get("workId")))
        work = (
            {"id": work_row.id, "title": work_row.title}
            if work_row is not None
            else None
        )
        if work:
            book = {"id": work.get("id"), "title": work.get("title") or "未命名作品"}
    logs = (
        list(task.get("_pageLogs") or [])
        if page_hydrated
        else import_http_store.list_import_logs(
            db, str(task.get("id") or ""), limit=log_limit
        )[0]
    )
    file_state_started_at = perf_counter()
    source_file_exists = Path(str(task.get("sourcePath") or "")).is_file()
    file_state_elapsed_ms = (perf_counter() - file_state_started_at) * 1000
    if file_state_elapsed_ms >= 100:
        logger.warning(
            "import_task.file_state.slow",
            extra={
                "event": "import_task.file_state.slow",
                "taskId": str(task.get("id") or ""),
                "elapsedMs": round(file_state_elapsed_ms, 2),
            },
        )
    view = dict(task)
    view.update(
        {
            "sourcePath": display_path_name(task.get("sourcePath")),
            "sourceFileExists": source_file_exists,
            "progress": task.get("progress") or 0,
            "friendlyError": friendly_import_error(
                task.get("errorSummary"), task.get("errorCode")
            ),
            "retryable": bool(task.get("retryable")),
            "createdAt": _dt(task.get("createdAt")),
            "finishedAt": _dt(task.get("finishedAt")),
            "library": library,
            "book": book,
            "logs": [serialize_import_log(log) for log in logs],
            "recognizedMetadata": _recognized_metadata_view(
                task.get("recognizedMetadata")
            ),
        }
    )
    view.pop("duplicate", None)
    view.pop("sourceKey", None)
    view.pop("_pageLibrary", None)
    view.pop("_pageWork", None)
    view.pop("_pageLogs", None)
    return view


__all__ = [
    "LibraryPathError",
    "display_path_name",
    "friendly_import_error",
    "import_task_view",
    "is_inside_path",
    "library_directory_tree_node",
    "resolve_library_root_path",
    "serialize_import_log",
]


def import_task_dto_view(task: ImportTaskDTO) -> dict[str, object]:
    return ImportTaskContract.from_dto(task).to_wire()
