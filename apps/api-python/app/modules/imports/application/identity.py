"""Identity resolution helpers used before dispatching to a media importer.

These helpers still take a raw database handle because ``logical_import_path``
and ``record_system_event`` have not been ported behind an application port
yet. ``managed_book.import_managed_book`` passes its ``unit_of_work`` through
here (the concrete object is the SQLAlchemy ``Session`` at runtime).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportRuntimeConfig,
    ImportSystemEvent,
)
from app.modules.imports.application.import_support import (
    _hash_text,
    _normalize_key,
    _series_folder_metadata,
    parse_series_volume_info,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
)

UNKNOWN_AUTHOR = "未知作者"


def _existing_series_volume_identity(
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    options: ImportOptions,
) -> BookIdentityDTO | None:
    source_path = (
        options.original_source_file_path or options.source_file_path
    ).resolve()
    folder_metadata = _series_folder_metadata(
        source_path.parent.name, options.original_name or source_path.name
    )
    volume_info = parse_series_volume_info(source_path, options.original_name, "WATCH")
    if volume_info is None or volume_info.series_index is None:
        return None
    folder_title_matches = bool(
        folder_metadata
        and _normalize_key(volume_info.series_name)
        == _normalize_key(folder_metadata.get("title"))
    )
    filename_series_fallback = bool(
        not folder_metadata
        and len(re.findall(r"\[([^\]]+)\]", source_path.parent.name)) >= 2
        and _is_exact_bracket_sequence(source_path.parent.name)
    )
    if not folder_title_matches and not filename_series_fallback:
        return None

    source_group_suffix = f":{_hash_text(str(source_path.parent))[:24]}"
    works = queries.list_works_by_source_group_suffix(source_group_suffix)
    if folder_title_matches:
        candidates = works
    else:
        candidates = [
            work
            for work in works
            if _work_has_matching_source_series(
                queries, str(work["id"]), source_group_suffix, volume_info.series_name
            )
        ]
    if len(candidates) != 1:
        return None
    work = candidates[0]
    logical_path = services.logical_import_path(source_path, options.original_name)
    return BookIdentityDTO(
        title=str(
            work.get("title")
            or (folder_metadata or {}).get("title")
            or volume_info.series_name
        ),
        author=str(work.get("author") or UNKNOWN_AUTHOR),
        volume_index=volume_info.series_index,
        source="existing_work",
        confidence=1.0,
        logical_path=logical_path,
        reused_work_id=str(work["id"]),
    )


def _work_has_matching_source_series(
    queries: ImportLibraryQueries,
    work_id: str,
    source_group_suffix: str,
    series_name: str,
) -> bool:
    files = queries.list_edition_file_paths_for_work(work_id, source_group_suffix)
    expected = _normalize_key(series_name)
    for file in files:
        existing_path = Path(str(file.get("path") or ""))
        existing = parse_series_volume_info(existing_path, existing_path.name, "WATCH")
        if existing is not None and _normalize_key(existing.series_name) == expected:
            return True
    return False


def _is_exact_bracket_sequence(value: str, count: int | None = None) -> bool:
    repeat = f"{{{count}}}" if count is not None else "+"
    return bool(re.fullmatch(rf"\s*(?:\[[^\]]+\]\s*){repeat}", value))


def _record_identity_system_events(
    services: ImportOrchestrationServices,
    task_id: str,
    identity: BookIdentityDTO,
    source_path: Path,
) -> None:
    metadata = {
        "sourcePath": str(source_path),
        "logicalPath": identity.logical_path,
        "recognitionMethod": identity.source,
        "title": identity.title,
        "author": identity.author,
        "volumeIndex": identity.volume_index,
        "confidence": identity.confidence,
        "fallbackReason": identity.fallback_reason,
        "cacheHit": identity.cache_hit,
        "reusedWorkId": identity.reused_work_id,
    }
    if identity.source == "existing_work":
        services.stage_system_event(ImportSystemEvent(
            source="import",
            action="identity.existing_work.reused",
            target_type="importTask",
            target_id=task_id,
            message=f"识别为现有作品的新卷册：{source_path.name} → 《{identity.title}》第 {identity.volume_index:g} 卷",
            metadata=metadata,
        ))
        return
    if identity.cache_hit:
        services.stage_system_event(ImportSystemEvent(
            source="import",
            action="identity.cache.hit",
            target_type="importTask",
            target_id=task_id,
            message=f"应用路径识别缓存：{source_path.name} → 《{identity.title}》 / {identity.author}",
            metadata=metadata,
        ))
        return
    if identity.fallback_reason:
        ai_failed = identity.fallback_reason.startswith(
            "AI identity recognition failed:"
        )
        services.stage_system_event(ImportSystemEvent(
            source="import",
            action="identity.ai.failed" if ai_failed else "identity.ai.unavailable",
            level="warning",
            target_type="importTask",
            target_id=task_id,
            message=(
                f"正则结果不完整，AI 兜底识别失败，已保留正则结果：{source_path.name}"
                if ai_failed
                else f"正则结果不完整，AI 识别配置不可用，已保留正则结果：{source_path.name}"
            ),
            metadata=metadata,
        ))
    method_label = "AI" if identity.source == "ai" else "正则匹配"
    services.stage_system_event(ImportSystemEvent(
        source="import",
        action=f"identity.{identity.source}.completed",
        target_type="importTask",
        target_id=task_id,
        message=f"{method_label}识别文件信息：{source_path.name} → 《{identity.title}》 / {identity.author}",
        metadata=metadata,
    ))
