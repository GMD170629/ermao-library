"""Media import orchestrator: eligibility checks and per-format dispatch."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.modules.imports.application.audio_types import (
    SUPPORTED_AUDIO_EXTS,
    AudioFileMetadata,
)
from app.modules.imports.application.commands import (
    commit_import_checkpoint,
    release_import_transaction,
    reset_failed_import_checkpoint,
)
from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportSystemEvent,
)
from app.modules.imports.application.errors import ImportExecutionError
from app.modules.imports.application.identity import _record_identity_system_events
from app.modules.imports.application.identity_resolution import (
    apply_requested_identity,
    resolve_import_metadata,
)
from app.modules.imports.application.import_audio import (
    _audio_identity,
    _import_audio,
    audio_embedded_metadata,
)
from app.modules.imports.application.import_comic import _import_comic
from app.modules.imports.application.import_epub import _import_epub
from app.modules.imports.application.import_pdf import _import_pdf
from app.modules.imports.application.import_policy import (
    extension_is_allowed,
    matches_ignore_patterns,
)
from app.modules.imports.application.import_support import (
    SUPPORTED_EXTS,
    _existing_audio_bundle_result,
    _existing_file_result,
    _hash_text,
    _id,
    _log_import,
    _now,
    import_file_size_limit_bytes_for_ext,
)
from app.modules.imports.application.import_text import _import_reflowable_source
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    ImportUnitOfWork,
    LibraryImportStore,
)
from app.modules.imports.application.work_grouping import (
    resolve_non_audio_work_identity,
)
from app.modules.imports.domain.reflowable_formats import (
    REFLOWABLE_SOURCE_EXTENSIONS,
)


def _publication_date(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = (
        f"{value}-01-01"
        if len(value) == 4
        else f"{value}-01"
        if len(value) == 7
        else value
    )
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


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
    if (
        options.topology_work_id is None
        or options.topology_volume_id is None
        or options.import_task_id is None
    ):
        raise ImportExecutionError(
            "TOPOLOGY_TARGET_REQUIRED",
            "导入任务必须由书库根目录扫描器绑定 Work 与 Volume",
            retryable=False,
        )
    source = requested_source
    audio_structure = None
    effective_options = options
    task_id = options.import_task_id
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
    release_import_transaction(unit_of_work)
    try:
        if not original_source.exists():
            raise FileNotFoundError(f"导入源已不存在：{original_source}")
        audio_structure = audio_structure or services.inspect_audio_bundle(source)
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
            raise ValueError(f"当前版本不支持此文件后缀：{ext or source.name}")
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
                    "libraryId": options.library_id,
                    "format": source_ext.removeprefix("."),
                },
            )
        )
        commit_import_checkpoint(unit_of_work)
        import_preferences = services.load_preferences()
        effective_options = replace(
            effective_options,
            local_metadata_priority=services.load_local_metadata_priority(),
        )
        release_import_transaction(unit_of_work)
        effective_options = replace(
            effective_options,
            default_cover_path=services.ensure_default_cover(),
        )
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
        release_import_transaction(unit_of_work)
        stat = source.stat()
        existing_file = (
            _existing_file_result(queries, source)
            if source.is_file()
            else _existing_audio_bundle_result(queries, audio_sources)
        )
        if existing_file:
            release_import_transaction(unit_of_work)
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
                        "versionId": existing_file.version_id,
                        "volumeId": existing_file.volume_id,
                    },
                )
            )
            return existing_file

        release_import_transaction(unit_of_work)
        audio_metadata: list[AudioFileMetadata] = []
        sidecar = services.read_sidecar_metadata(
            original_source,
            directory_fallback=bool(audio_sources or original_source.is_dir()),
        )
        if sidecar is not None:
            effective_options = replace(
                effective_options,
                sidecar_metadata=sidecar.metadata,
                sidecar_cover_path=sidecar.cover_path,
                sidecar_source_kind=sidecar.source_kind,
            )
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
            release_import_transaction(unit_of_work)
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
            identity, audio_resolved_local = resolve_import_metadata(
                identity,
                embedded=audio_embedded_metadata(identity, audio_metadata),
                sidecar=sidecar.metadata if sidecar is not None else None,
                source_order=effective_options.local_metadata_priority,
                path_publication_title=Path(options.original_name or source.name).stem,
                requested_title=options.requested_title,
                requested_author=options.requested_author,
            )
        else:
            audio_resolved_local = None
            path_resolution = resolve_non_audio_work_identity(
                services,
                effective_options,
                import_preferences,
            )
            identity = path_resolution.identity
            effective_options = replace(
                effective_options,
                path_metadata=path_resolution.metadata,
            )
            identity = apply_requested_identity(
                identity,
                requested_title=options.requested_title,
                requested_author=options.requested_author,
            )
        if identity.fallback_reason:
            _log_import(store, task_id, "warning", identity.fallback_reason)
        _record_identity_system_events(services, task_id, identity, original_source)
        identity_method = (
            "识别缓存"
            if identity.cache_hit
            else {
                "ai": "AI",
                "regex": "正则规则",
                "requested": "用户输入",
                "epub_opf": "EPUB 元数据",
                "pdf_metadata": "PDF 元数据",
                "comic_info": "ComicInfo 元数据",
                "reflowable_metadata": "原文件元数据",
                "sidecar_opf": "OPF 元数据",
            }.get(identity.source, "多来源裁决")
        )
        store.update_import_task(
            task_id,
            columns={
                "progress": 20,
                "message": f"已通过{identity_method}获取书名与作者",
                "recognizedMetadata": {
                    "title": identity.title,
                    "volumeTitle": (
                        effective_options.path_metadata.volume_title
                        if effective_options.path_metadata is not None
                        else identity.title
                    ),
                    "volumeIndex": (
                        effective_options.path_metadata.volume_index
                        if effective_options.path_metadata is not None
                        else identity.volume_index
                    ),
                    "author": identity.author,
                    "fields": list(sidecar.metadata.populated_fields)
                    if sidecar is not None
                    else [
                        field
                        for field, value in (
                            ("title", identity.title),
                            ("author", identity.author),
                        )
                        if value
                    ],
                    "source": "REQUESTED"
                    if identity.source == "requested"
                    else "SIDECAR_OPF"
                    if identity.source == "sidecar_opf"
                    else "PATH"
                    if identity.source in {"regex", "path"}
                    else "EMBEDDED",
                },
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
        release_import_transaction(unit_of_work)
        task_update: dict[str, object] = {
            "progress": 30,
            "message": "正在读取元数据",
        }
        store.update_import_task(task_id, columns=task_update)
        release_import_transaction(unit_of_work)
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
                unit_of_work,
            )
        elif ext in REFLOWABLE_SOURCE_EXTENSIONS:
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
                unit_of_work,
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
                unit_of_work,
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
                audio_resolved_local,
                unit_of_work,
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
                unit_of_work,
            )
        if result.resolved_metadata is not None:
            publication = result.resolved_metadata
            field_sources = dict(result.metadata_field_sources)
            work_values: dict[str, object] = {"updatedAt": _now()}
            volume_values: dict[str, object] = {"updatedAt": _now()}
            if publication.description:
                work_values["description"] = publication.description
                volume_values["description"] = publication.description
            if publication.subjects:
                kind_tag = (
                    "audiobook"
                    if audio_metadata
                    else "comic"
                    if ext in {".cbz", ".cbr", ".zip", ".rar"}
                    else ext.removeprefix(".") or "ebook"
                )
                work_values["tags"] = json.dumps(
                    list(dict.fromkeys((kind_tag, *publication.subjects))),
                    ensure_ascii=False,
                )
            if publication.series_name:
                work_values["seriesName"] = publication.series_name
            if publication.series_index is not None:
                work_values["seriesIndex"] = publication.series_index
            for column, value in (
                ("language", publication.language),
                ("publisher", publication.publisher),
                ("publishedAt", _publication_date(publication.published_at)),
                ("identifier", publication.identifier),
                ("isbn", publication.isbn),
            ):
                if value not in (None, ""):
                    volume_values[column] = value
            if (
                sidecar is not None
                and sidecar.cover_path is not None
                and field_sources.get("cover") == "SIDECAR_OPF"
                and result.volume_id
            ):
                release_import_transaction(unit_of_work)
                cover_path = services.publish_sidecar_cover(
                    settings.resolved_storage_root,
                    sidecar.cover_path,
                    result.work_id,
                    result.version_id,
                    result.volume_id,
                )
                work_values.update({"coverPath": cover_path, "coverStatus": "READY"})
                volume_values.update({"coverPath": cover_path, "coverStatus": "READY"})
            store.update_library_work(result.work_id, columns=work_values)
            if result.volume_id:
                store.update_library_volume(result.volume_id, columns=volume_values)
        services.sync_work_facets(result.work_id)
        if sidecar is not None and result.volume_id:
            store.insert_library_metadata(
                columns={
                    "id": _id(),
                    "volumeId": result.volume_id,
                    "source": "sidecar_opf",
                    "rawJson": json.dumps(
                        {
                            "sourceKind": sidecar.source_kind,
                            "fieldSources": dict(sidecar.field_sources),
                            "fields": list(sidecar.metadata.populated_fields),
                            "title": sidecar.metadata.title,
                            "volumeTitle": sidecar.metadata.volume_title,
                            "authors": list(sidecar.metadata.authors),
                            "description": sidecar.metadata.description,
                            "subjects": list(sidecar.metadata.subjects),
                            "seriesName": sidecar.metadata.series_name,
                            "seriesIndex": sidecar.metadata.series_index,
                            "language": sidecar.metadata.language,
                            "publisher": sidecar.metadata.publisher,
                            "publishedAt": sidecar.metadata.published_at,
                            "identifier": sidecar.metadata.identifier,
                            "isbn": sidecar.metadata.isbn,
                            "cover": sidecar.cover_path is not None,
                            "unparsed": dict(sidecar.metadata.unparsed_values),
                        },
                        ensure_ascii=False,
                    ),
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
        if result.resolved_metadata is not None and result.volume_id:
            publication = result.resolved_metadata
            store.insert_library_metadata(
                columns={
                    "id": _id(),
                    "volumeId": result.volume_id,
                    "source": "local_resolution",
                    "rawJson": json.dumps(
                        {
                            "sourceOrder": list(result.metadata_source_order),
                            "fieldSources": dict(result.metadata_field_sources),
                            "fields": list(publication.populated_fields),
                            "title": publication.title,
                            "authors": list(publication.authors),
                            "description": publication.description,
                            "subjects": list(publication.subjects),
                            "seriesName": publication.series_name,
                            "seriesIndex": publication.series_index,
                            "volumeTitle": publication.volume_title,
                            "volumeIndex": publication.volume_index,
                            "language": publication.language,
                            "publisher": publication.publisher,
                            "publishedAt": publication.published_at,
                            "identifier": publication.identifier,
                            "isbn": publication.isbn,
                            "cover": bool(publication.cover_href),
                            "unparsed": dict(publication.unparsed_values),
                        },
                        ensure_ascii=False,
                    ),
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
            store.update_import_task(
                task_id,
                columns={
                    "recognizedMetadata": {
                        "title": publication.title or result.title,
                        "volumeTitle": publication.volume_title
                        or publication.title
                        or result.title,
                        "author": publication.author,
                        "volumeIndex": publication.volume_index,
                        "fields": list(publication.populated_fields),
                        "fieldSources": dict(result.metadata_field_sources),
                        "sourceOrder": list(result.metadata_source_order),
                        "source": field_sources.get("title")
                        or field_sources.get("author")
                        or next(iter(field_sources.values()), "PATH"),
                    }
                },
            )
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
                    "versionId": result.version_id,
                    "volumeId": result.volume_id,
                    "title": result.title,
                    "format": result.format,
                    "sourceFormat": ext.removeprefix(".").upper(),
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
