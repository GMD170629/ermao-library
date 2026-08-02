"""Media import orchestrator: eligibility checks and per-format dispatch."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from app.modules.imports.application.audio_types import (
    SUPPORTED_AUDIO_EXTS,
    AudioBundleStructure,
    AudioFileMetadata,
    audio_bundle_membership_is_proven,
)
from app.modules.imports.application.commands import (
    commit_import_checkpoint,
    reset_failed_import_checkpoint,
)
from app.modules.imports.application.dto import (
    ConversionArtifactDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportSystemEvent,
)
from app.modules.imports.application.identity import _record_identity_system_events
from app.modules.imports.application.identity_resolution import (
    resolve_import_identity,
)
from app.modules.imports.application.import_audio import _audio_identity, _import_audio
from app.modules.imports.application.import_comic import _import_comic
from app.modules.imports.application.import_epub import _import_epub
from app.modules.imports.application.import_pdf import _import_pdf
from app.modules.imports.application.import_policy import (
    REFLOWABLE_SOURCE_EXTS,
    extension_is_allowed,
    matches_ignore_patterns,
)
from app.modules.imports.application.import_support import (
    SUPPORTED_EXTS,
    _content_hash,
    _ensure_import_task,
    _existing_audio_bundle_result,
    _existing_file_result,
    _hash_text,
    _id,
    _log_import,
    _now,
    import_file_size_limit_bytes_for_ext,
)
from app.modules.imports.application.import_text import (
    _complete_deferred_source_conversion,
    _import_reflowable_source,
    refresh_existing_reflowable_source,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    ImportUnitOfWork,
    LibraryImportStore,
)
from app.modules.imports.application.work_grouping import (
    resolve_non_audio_work_identity,
)
from app.modules.imports.application.volume_ordering import (
    normalize_media_version_volume_order,
)


def _resolve_audio_import_source(
    services: ImportOrchestrationServices,
    source: Path,
) -> tuple[Path, AudioBundleStructure | None]:
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
        return source, None
    parent = source.parent.resolve()
    structure = services.inspect_audio_bundle(parent)
    if structure is None or len(structure.files) < 2:
        return source, None
    if not _audio_bundle_is_proven(parent, structure):
        return source, None
    resolved_source = source.resolve()
    if resolved_source not in {path.resolve() for path in structure.files}:
        return source, None
    return parent, structure


def _audio_bundle_is_proven(
    directory: Path,
    structure: AudioBundleStructure,
) -> bool:
    bundled_paths = {path.resolve() for path in structure.files}
    try:
        has_sibling_book = any(
            child.is_file()
            and child.resolve() not in bundled_paths
            and child.suffix.lower() in SUPPORTED_EXTS
            for child in directory.iterdir()
        )
    except OSError:
        return False
    return audio_bundle_membership_is_proven(
        list(structure.files),
        has_sibling_book=has_sibling_book,
    )


def import_managed_book(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    unit_of_work: ImportUnitOfWork,
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    options: ImportOptions,
) -> ImportResult:
    """Import one media source using explicit collaborator ports."""

    requested_source = options.source_file_path.resolve()
    original_source = (options.original_source_file_path or requested_source).resolve()
    source, audio_structure = _resolve_audio_import_source(services, requested_source)
    effective_options = (
        replace(options, source_file_path=source, original_name=source.name)
        if source != requested_source
        else options
    )
    task_id = options.import_task_id or _ensure_import_task(
        store, queries, effective_options
    )
    started = time.time()
    audio_sources: list = []
    source_ext = source.suffix.lower()
    ext = source_ext
    store.update_import_task(
        task_id,
        columns={
            "status": "PARSING",
            "progress": 5,
            "startedAt": _now(),
            "message": "正在校验文件",
        },
    )
    commit_import_checkpoint(unit_of_work)
    try:
        if not original_source.exists():
            raise FileNotFoundError(f"导入源已不存在：{original_source}")
        audio_structure = audio_structure or services.inspect_audio_bundle(source)
        if (
            source.is_dir()
            and audio_structure is not None
            and not _audio_bundle_is_proven(source, audio_structure)
        ):
            raise ValueError(
                "Audiobook directory mixes independent resources; rescan it as individual files"
            )
        audio_sources = list(audio_structure.files) if audio_structure else []
        source_ext = (
            source.suffix.lower()
            if source.is_file()
            else ".audio-bundle"
            if audio_sources
            else ""
        )
        ext = source_ext
        if (
            ext not in SUPPORTED_EXTS
            and ext not in SUPPORTED_AUDIO_EXTS
            and ext != ".audio-bundle"
        ):
            raise ValueError(
                "当前版本仅支持 EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT、CBZ、ZIP、PDF、M4B、M4A、MP3 格式。"
            )
        _log_import(store, task_id, "info", f"import started: {source}")
        services.stage_system_event(
            ImportSystemEvent(
                source="import",
                action="import.started",
                target_type="importTask",
                target_id=task_id,
                message=f"开始导入文件：{options.original_name or source.name}",
                metadata={
                    "sourcePath": str(original_source),
                    "originalName": options.original_name or source.name,
                    "origin": options.origin,
                    "monitorFolderId": options.monitor_folder_id,
                    "format": source_ext.removeprefix("."),
                },
            )
        )
        commit_import_checkpoint(unit_of_work)
        import_preferences = services.load_preferences()
        preference_sources = audio_sources if audio_sources else [original_source]
        disallowed_sources = [
            item
            for item in preference_sources
            if not extension_is_allowed(item, import_preferences)
        ]
        if disallowed_sources:
            raise ValueError(
                f"文件后缀已在导入偏好中关闭：{disallowed_sources[0].suffix.lower() or disallowed_sources[0].name}"
            )
        ignored_sources = [
            item
            for item in preference_sources
            if matches_ignore_patterns(item, import_preferences.ignore_patterns)
        ]
        if ignored_sources:
            raise ValueError(f"文件命中全局导入忽略规则：{ignored_sources[0].name}")
        original_stat = original_source.stat()
        if not original_source.is_file() and not audio_sources:
            raise ValueError("导入源不是受支持的文件或有声书目录")
        limit = import_file_size_limit_bytes_for_ext(source_ext)
        if original_source.is_file() and limit and original_stat.st_size > limit:
            raise ValueError(f"文件过大：当前限制 {limit} bytes")
        if audio_sources:
            oversized = [
                item.name
                for item in audio_sources
                if item.stat().st_size > settings.audiobook_max_file_bytes
            ]
            if oversized:
                raise ValueError(
                    f"音频文件超过单文件上限 {settings.audiobook_max_file_bytes} bytes：{oversized[0]}"
                )
        converted: ConversionArtifactDTO | None = None
        should_convert_text = (
            source_ext in REFLOWABLE_SOURCE_EXTS
            and options.origin == "DEFERRED_CONVERSION"
        )
        if should_convert_text:
            converted = services.convert_text(task_id, original_source)
            source = converted.output_path.resolve()
            ext = ".epub"
            effective_options = replace(
                effective_options,
                source_file_path=source,
                original_source_file_path=original_source,
            )
        stat = source.stat()
        existing_file = (
            _existing_file_result(queries, source)
            if source.is_file()
            else _existing_audio_bundle_result(queries, audio_sources)
        )
        if existing_file:
            if source_ext in REFLOWABLE_SOURCE_EXTS:
                existing_file = refresh_existing_reflowable_source(
                    store,
                    queries,
                    services,
                    settings,
                    source,
                    existing_file,
                )
            if converted is not None:
                services.bind_conversion_result(
                    converted.idempotency_key, existing_file.volume_id
                )
            metadata_refreshed = (
                existing_file.merge_reason == "refreshed-native-metadata"
            )
            store.update_import_task(
                task_id,
                columns={
                    "workId": existing_file.work_id,
                    "volumeId": existing_file.volume_id,
                    "status": "COMPLETED",
                    "progress": 100,
                    "duplicate": True,
                    "message": "已补充原文件章节与元数据"
                    if metadata_refreshed
                    else "文件路径已入库，跳过重复处理",
                    "errorCode": None,
                    "errorSummary": None,
                    "retryable": False,
                    "leaseOwner": None,
                    "leaseExpiresAt": None,
                    "duration": int((time.time() - started) * 1000),
                    "finishedAt": _now(),
                },
            )
            _log_import(
                store,
                task_id,
                "info",
                f"native metadata refreshed: {source}"
                if metadata_refreshed
                else f"import skipped existing path: {source}",
            )
            services.stage_system_event(
                ImportSystemEvent(
                    source="import",
                    action=(
                        "import.metadata_refreshed"
                        if metadata_refreshed
                        else "import.skipped"
                    ),
                    target_type="importTask",
                    target_id=task_id,
                    message=(
                        f"已补充原文件章节与元数据：{options.original_name or source.name}"
                        if metadata_refreshed
                        else f"跳过已导入文件：{options.original_name or source.name}"
                    ),
                    metadata={
                        "sourcePath": str(original_source),
                        "reason": "native_metadata_refreshed"
                        if metadata_refreshed
                        else "existing_path",
                        "workId": existing_file.work_id,
                        "mediaVersionId": existing_file.media_version_id,
                        "volumeId": existing_file.volume_id,
                    },
                )
            )
            return existing_file

        audio_metadata: list[AudioFileMetadata] = []
        if audio_sources:
            store.update_import_task(
                task_id,
                columns={
                    "taskKind": "AUDIO_BUNDLE"
                    if source.is_dir() or len(audio_sources) > 1
                    else "FILE",
                    "bundleKey": _hash_text(str(source)),
                    "assetCount": len(audio_sources),
                    "processedAssetCount": 0,
                    "message": f"正在读取 {len(audio_sources)} 个音频文件",
                },
            )
            audio_metadata = [
                services.parse_audio_metadata(path) for path in audio_sources
            ]
            identity = _audio_identity(
                services,
                settings,
                source,
                effective_options,
                audio_metadata,
                audio_structure,
            )
        else:
            identity = resolve_non_audio_work_identity(
                services,
                effective_options,
                import_preferences,
            )
            identity = resolve_import_identity(
                identity,
                requested_title=options.requested_title,
                requested_author=options.requested_author,
            )
        if options.requested_work_id:
            identity = replace(identity, reused_work_id=options.requested_work_id)
        if identity.fallback_reason:
            _log_import(store, task_id, "warning", identity.fallback_reason)
        _record_identity_system_events(services, task_id, identity, original_source)
        identity_method = (
            "现有作品卷册关系"
            if identity.source == "existing_work"
            else "识别缓存"
            if identity.cache_hit
            else {
                "ai": "AI",
                "regex": "正则规则",
                "requested": "用户输入",
                "epub_opf": "EPUB 元数据",
                "pdf_metadata": "PDF 元数据",
                "comic_info": "ComicInfo 元数据",
                "reflowable_metadata": "原文件元数据",
            }.get(identity.source, "多来源裁决")
        )
        store.update_import_task(
            task_id,
            columns={
                "progress": 88 if converted else 20,
                "message": f"已通过{identity_method}获取书名与作者",
            },
        )
        commit_import_checkpoint(unit_of_work)
        current_claim = queries.get_import_task_by_id(task_id)
        if current_claim is None or str(current_claim.get("status") or "") != "PARSING":
            raise RuntimeError("导入任务已不再处于可应用状态")
        if (
            options.expected_lease_owner is not None
            and str(current_claim.get("leaseOwner") or "")
            != options.expected_lease_owner
        ):
            raise RuntimeError("导入任务租约已失效")
        content_hash = (
            converted.source_hash
            if converted
            else None
            if ext in {".cbz", ".zip", ".audio-bundle", *SUPPORTED_AUDIO_EXTS}
            else _content_hash(source)
        )
        task_update: dict[str, object] = {
            "progress": 92 if converted else 30,
            "message": "正在读取元数据",
        }
        if content_hash:
            task_update["contentHash"] = content_hash
        store.update_import_task(task_id, columns=task_update)
        if ext == ".epub":
            result = _import_epub(
                store,
                queries,
                services,
                settings,
                effective_options,
                task_id,
                stat.st_size,
                ext,
                identity,
            )
        elif ext in REFLOWABLE_SOURCE_EXTS:
            result = _import_reflowable_source(
                store,
                queries,
                services,
                settings,
                effective_options,
                task_id,
                stat.st_size,
                ext,
                identity,
            )
        elif ext == ".pdf":
            result = _import_pdf(
                store,
                queries,
                services,
                settings,
                effective_options,
                task_id,
                stat.st_size,
                ext,
                identity,
            )
        elif audio_metadata:
            result = _import_audio(
                store,
                queries,
                services,
                settings,
                effective_options,
                task_id,
                identity,
                audio_metadata,
                audio_structure,
            )
        else:
            result = _import_comic(
                store,
                queries,
                services,
                settings,
                effective_options,
                task_id,
                stat.st_size,
                ext,
                identity,
            )
        if not audio_metadata:
            normalize_media_version_volume_order(
                store,
                queries,
                result.media_version_id,
            )
        services.sync_work_facets(result.work_id)
        if converted:
            conversion_row = queries.get_conversion_by_import_task_id(task_id)
            store.insert_library_metadata(
                columns={
                    "id": _id(),
                    "volumeId": result.volume_id,
                    "source": "conversion",
                    "rawJson": json.dumps(
                        {
                            "sourceFormat": converted.source_format,
                            "targetFormat": "EPUB",
                            "sourcePath": str(original_source),
                            "sourceHash": converted.source_hash,
                            "converter": converted.converter,
                            "converterVersion": converted.converter_version,
                            "cached": converted.cached,
                            "options": json.loads(
                                (conversion_row or {}).get("optionsJson") or "{}"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    "createdAt": _now(),
                    "updatedAt": _now(),
                },
            )
            if options.origin == "DEFERRED_CONVERSION":
                _complete_deferred_source_conversion(
                    store, queries, original_source, result
                )
            services.bind_conversion_result(converted.idempotency_key, result.volume_id)
        store.update_import_task(
            task_id,
            columns={
                "workId": result.work_id,
                "volumeId": result.volume_id,
                "status": "COMPLETED",
                "progress": 100,
                "duplicate": result.duplicate,
                "message": "读物已存在，跳过重复导入"
                if result.duplicate
                else f"导入完成：{result.merge_reason}",
                "errorCode": None,
                "errorSummary": None,
                "retryable": False,
                "leaseOwner": None,
                "leaseExpiresAt": None,
                "duration": int((time.time() - started) * 1000),
                "finishedAt": _now(),
            },
        )
        _log_import(store, task_id, "info", f"import completed: {result.book_id}")
        duration_ms = int((time.time() - started) * 1000)
        services.stage_system_event(
            ImportSystemEvent(
                source="import",
                action="import.skipped" if result.duplicate else "import.completed",
                target_type="importTask",
                target_id=task_id,
                message=(
                    f"读物已存在，跳过重复导入：{result.title}"
                    if result.duplicate
                    else f"导入完成：{result.title}"
                ),
                metadata={
                    "sourcePath": str(original_source),
                    "workId": result.work_id,
                    "mediaVersionId": result.media_version_id,
                    "volumeId": result.volume_id,
                    "title": result.title,
                    "format": result.format,
                    "sourceFormat": converted.source_format
                    if converted
                    else ext.removeprefix(".").upper(),
                    "totalUnits": result.total_units,
                    "duplicate": result.duplicate,
                    "merged": result.merged,
                    "mergeReason": result.merge_reason,
                    "durationMs": duration_ms,
                },
            )
        )
        return result
    except Exception:
        reset_failed_import_checkpoint(unit_of_work)
        raise
