from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.book_identity import BookIdentity, UNKNOWN_AUTHOR, identity_merge_key, logical_import_path, normalize_identity_part, parse_bracketed_series_identity, recognize_book_identity
from app.services.audio_metadata import (
    AudioChapterMetadata,
    AudioFileMetadata,
    DISC_DIRECTORY_PATTERN,
    MAX_AUDIO_CHAPTERS,
    SUPPORTED_AUDIO_EXTS,
    collect_audio_bundle_files,
    is_supported_audio_file,
    parse_audio_metadata,
)
from app.services.system_events import record_system_event
from app.services.import_preferences import extension_is_allowed, load_import_preferences, matches_ignore_patterns
from app.services.library_management import sync_work_facets
from app.services.text_conversion import CONVERTIBLE_TEXT_EXTS, ConversionArtifact, convert_to_epub
from app.services.default_cover import cover_status, ensure_default_cover, is_default_cover_path
from app.core.time import now_timestamp_ms

SUPPORTED_EXTS = {".epub", ".cbz", ".zip", ".pdf", *CONVERTIBLE_TEXT_EXTS, *SUPPORTED_AUDIO_EXTS}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_EPUB_SIZE_BYTES = 512 * 1024 * 1024
MAX_TEXT_EBOOK_SIZE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_SIZE_BYTES = 2 * 1024 * 1024 * 1024
MAX_COMIC_INFO_BYTES = 1024 * 1024
MAX_AUDIO_COVER_BYTES = 20 * 1024 * 1024
MAX_AUDIO_COVER_PIXELS = 40_000_000
AUDIO_COVER_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


@dataclass(frozen=True)
class ImportOptions:
    source_file_path: Path
    origin: str
    original_name: str | None = None
    requested_title: str | None = None
    requested_author: str | None = None
    monitor_folder_id: str | None = None
    import_task_id: str | None = None
    original_source_file_path: Path | None = None
    requested_work_id: str | None = None


@dataclass(frozen=True)
class ImportResult:
    book_id: str
    work_id: str
    edition_id: str
    volume_id: str | None
    title: str
    type: str
    format: str
    total_units: int
    import_status: str
    duplicate: bool
    merged: bool
    merge_reason: str


@dataclass(frozen=True)
class SeriesVolumeInfo:
    series_name: str
    series_index: float
    title: str
    author: str | None = None


def is_supported_import_file(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.is_dir() and bool(collect_audio_bundle_files(candidate)) or candidate.suffix.lower() in SUPPORTED_EXTS


def import_file_size_limit_bytes_for_ext(ext: str) -> int | None:
    normalized = ext if ext.startswith(".") else f".{ext}"
    normalized = normalized.lower()
    if normalized == ".epub":
        return MAX_EPUB_SIZE_BYTES
    if normalized in CONVERTIBLE_TEXT_EXTS:
        return MAX_TEXT_EBOOK_SIZE_BYTES
    if normalized in {".cbz", ".zip"}:
        return MAX_ARCHIVE_SIZE_BYTES
    return None


def import_managed_book(db: Session, settings: Settings, options: ImportOptions) -> ImportResult:
    original_source = (options.original_source_file_path or options.source_file_path).resolve()
    source = options.source_file_path.resolve()
    audio_sources = collect_audio_bundle_files(source)
    source_ext = source.suffix.lower() if source.is_file() else ".audio-bundle" if audio_sources else ""
    ext = source_ext
    if ext not in SUPPORTED_EXTS and ext != ".audio-bundle":
        raise ValueError("当前版本仅支持 EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT、CBZ、ZIP、PDF、M4B、M4A、MP3 格式。")
    task_id = options.import_task_id or _ensure_import_task(db, options)
    started = time.time()
    _update(db, "ImportTask", task_id, {"status": "PARSING", "progress": 5, "startedAt": _now(), "message": "正在校验文件"})
    _log_import(db, task_id, "info", f"import started: {source}")
    record_system_event(
        db,
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
    db.commit()
    try:
        import_preferences = load_import_preferences(db)
        preference_sources = audio_sources if audio_sources else [original_source]
        disallowed_sources = [item for item in preference_sources if not extension_is_allowed(item, import_preferences)]
        if disallowed_sources:
            raise ValueError(f"文件后缀已在导入偏好中关闭：{disallowed_sources[0].suffix.lower() or disallowed_sources[0].name}")
        ignored_sources = [item for item in preference_sources if matches_ignore_patterns(item, import_preferences.ignore_patterns)]
        if ignored_sources:
            raise ValueError(f"文件命中全局导入忽略规则：{ignored_sources[0].name}")
        original_stat = original_source.stat()
        if not original_source.is_file() and not audio_sources:
            raise ValueError("导入源不是受支持的文件或有声书目录")
        limit = import_file_size_limit_bytes_for_ext(source_ext)
        if original_source.is_file() and limit and original_stat.st_size > limit:
            raise ValueError(f"文件过大：当前限制 {limit} bytes")
        if audio_sources:
            oversized = [item.name for item in audio_sources if item.stat().st_size > settings.audiobook_max_file_bytes]
            if oversized:
                raise ValueError(f"音频文件超过单文件上限 {settings.audiobook_max_file_bytes} bytes：{oversized[0]}")
            bundle_size = sum(item.stat().st_size for item in audio_sources)
            if bundle_size > settings.audiobook_max_bundle_bytes:
                raise ValueError(f"有声书文件总量超过上限 {settings.audiobook_max_bundle_bytes} bytes")
        converted: ConversionArtifact | None = None
        effective_options = options
        should_convert_text = source_ext in CONVERTIBLE_TEXT_EXTS and (
            import_preferences.auto_convert_to_epub or options.origin == "DEFERRED_CONVERSION"
        )
        if should_convert_text:
            converted = convert_to_epub(db, settings, task_id, original_source)
            source = converted.output_path.resolve()
            ext = ".epub"
            effective_options = replace(options, source_file_path=source, original_source_file_path=original_source)
        stat = source.stat()
        existing_file = _existing_file_result(db, source) if source.is_file() else _existing_audio_bundle_result(db, audio_sources)
        if existing_file:
            _update(
                db,
                "ImportTask",
                task_id,
                {
                    "workId": existing_file.work_id,
                    "editionId": existing_file.edition_id,
                    "volumeId": existing_file.volume_id,
                    "status": "COMPLETED",
                    "progress": 100,
                    "duplicate": True,
                    "message": "文件路径已入库，跳过重复处理",
                    "errorCode": None,
                    "errorSummary": None,
                    "retryable": False,
                    "leaseOwner": None,
                    "leaseExpiresAt": None,
                    "duration": int((time.time() - started) * 1000),
                    "finishedAt": _now(),
                },
            )
            _log_import(db, task_id, "info", f"import skipped existing path: {source}")
            record_system_event(
                db,
                source="import",
                action="import.skipped",
                target_type="importTask",
                target_id=task_id,
                message=f"跳过已导入文件：{options.original_name or source.name}",
                metadata={
                    "sourcePath": str(original_source),
                    "reason": "existing_path",
                    "workId": existing_file.work_id,
                    "editionId": existing_file.edition_id,
                    "volumeId": existing_file.volume_id,
                },
                prune=True,
            )
            db.commit()
            return existing_file

        audio_metadata: list[AudioFileMetadata] = []
        if audio_sources:
            _update(
                db,
                "ImportTask",
                task_id,
                {
                    "taskKind": "AUDIO_BUNDLE" if original_source.is_dir() or len(audio_sources) > 1 else "FILE",
                    "bundleKey": _hash_text(str(original_source)),
                    "assetCount": len(audio_sources),
                    "processedAssetCount": 0,
                    "message": f"正在读取 {len(audio_sources)} 个音频文件",
                },
            )
            audio_metadata = [parse_audio_metadata(path) for path in audio_sources]
            identity = _audio_identity(db, settings, original_source, options, audio_metadata)
        else:
            identity = _existing_series_volume_identity(db, settings, effective_options) or recognize_book_identity(db, settings, original_source, options.original_name)
        if options.requested_work_id:
            identity = replace(identity, reused_work_id=options.requested_work_id)
        if identity.fallback_reason:
            _log_import(db, task_id, "warning", identity.fallback_reason)
        _record_identity_system_events(db, task_id, identity, original_source)
        identity_method = (
            "现有作品卷册关系"
            if identity.source == "existing_work"
            else "识别缓存"
            if identity.cache_hit
            else "AI"
            if identity.source == "ai"
            else "正则规则"
        )
        _update(db, "ImportTask", task_id, {"progress": 88 if converted else 20, "message": f"已通过{identity_method}获取书名与作者"})
        db.commit()
        content_hash = converted.source_hash if converted else None if ext in {".cbz", ".zip", ".audio-bundle", *SUPPORTED_AUDIO_EXTS} else _content_hash(source)
        task_update = {"progress": 92 if converted else 30, "message": "正在读取元数据"}
        if content_hash:
            task_update["contentHash"] = content_hash
        _update(db, "ImportTask", task_id, task_update)
        if ext == ".epub":
            result = _import_epub(db, settings, effective_options, task_id, stat.st_size, ext, identity)
        elif ext in CONVERTIBLE_TEXT_EXTS:
            result = _import_unconverted_text(db, settings, effective_options, task_id, stat.st_size, ext, identity)
        elif ext == ".pdf":
            result = _import_pdf(db, settings, effective_options, task_id, stat.st_size, ext, identity)
        elif audio_metadata:
            result = _import_audio(db, settings, effective_options, task_id, identity, audio_metadata)
        else:
            result = _import_comic(db, settings, effective_options, task_id, stat.st_size, ext, identity)
        sync_work_facets(db, result.work_id, commit=False)
        if converted and _has_table(db, "LibraryMetadata"):
            conversion_row = _row(db, "SELECT * FROM `BookConversionTask` WHERE `importTaskId` = :task_id", {"task_id": task_id}) if _has_table(db, "BookConversionTask") else None
            _insert(
                db,
                "LibraryMetadata",
                {
                    "id": _id(),
                    "editionId": result.edition_id,
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
                            "options": json.loads((conversion_row or {}).get("optionsJson") or "{}"),
                        },
                        ensure_ascii=False,
                    ),
                    "createdAt": _now(),
                    "updatedAt": _now(),
                },
            )
            if options.origin == "DEFERRED_CONVERSION":
                _complete_deferred_source_conversion(db, original_source, result)
        _update(
            db,
            "ImportTask",
            task_id,
            {
                "workId": result.work_id,
                "editionId": result.edition_id,
                "volumeId": result.volume_id,
                "status": "COMPLETED",
                "progress": 100,
                "duplicate": result.duplicate,
                "message": "读物已存在，跳过重复导入" if result.duplicate else f"导入完成：{result.merge_reason}",
                "errorCode": None,
                "errorSummary": None,
                "retryable": False,
                "leaseOwner": None,
                "leaseExpiresAt": None,
                "duration": int((time.time() - started) * 1000),
                "finishedAt": _now(),
            },
        )
        _log_import(db, task_id, "info", f"import completed: {result.book_id}")
        duration_ms = int((time.time() - started) * 1000)
        record_system_event(
            db,
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
                "editionId": result.edition_id,
                "volumeId": result.volume_id,
                "title": result.title,
                "format": result.format,
                "sourceFormat": converted.source_format if converted else ext.removeprefix(".").upper(),
                "totalUnits": result.total_units,
                "duplicate": result.duplicate,
                "merged": result.merged,
                "mergeReason": result.merge_reason,
                "durationMs": duration_ms,
            },
            prune=True,
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        message = str(exc)
        current_task = _row(db, "SELECT * FROM `ImportTask` WHERE `id` = :id", {"id": task_id}) or {}
        audio_retryable = bool(audio_sources and original_source.exists())
        _update(db, "ImportTask", task_id, {"status": "FAILED", "progress": 100, "errorCode": current_task.get("errorCode") or ("AUDIO_IMPORT_FAILED" if audio_retryable else "IMPORT_FAILED"), "retryable": audio_retryable or bool(current_task.get("retryable")), "errorSummary": message, "message": "导入失败，详情见错误信息", "leaseOwner": None, "leaseExpiresAt": None, "duration": int((time.time() - started) * 1000), "finishedAt": _now()})
        if _has_table(db, "ImportAsset"):
            db.execute(
                text(
                    "UPDATE `ImportAsset` SET `status` = 'FAILED', `errorCode` = :error_code, "
                    "`errorSummary` = :error_summary, `updatedAt` = :updated_at "
                    "WHERE `importTaskId` = :task_id AND `status` != 'COMPLETED'"
                ),
                {"error_code": "IMPORT_FAILED", "error_summary": message, "updated_at": _now(), "task_id": task_id},
            )
        _log_import(db, task_id, "error", message)
        record_system_event(
            db,
            source="import",
            action="import.failed",
            level="error",
            target_type="importTask",
            target_id=task_id,
            message=f"导入失败：{options.original_name or source.name}",
            metadata={
                "sourcePath": str(original_source),
                "originalName": options.original_name or source.name,
                "origin": options.origin,
                "monitorFolderId": options.monitor_folder_id,
                "error": message,
                "durationMs": int((time.time() - started) * 1000),
            },
            prune=True,
        )
        db.commit()
        raise


def _import_epub(db: Session, settings: Settings, options: ImportOptions, task_id: str, file_size: int, ext: str, identity: BookIdentity) -> ImportResult:
    metadata = parse_epub_metadata(options.source_file_path)
    volume_info = (
        SeriesVolumeInfo(identity.title, identity.volume_index, f"第 {identity.volume_index:g} 卷", identity.author)
        if identity.volume_index is not None
        else None
    )
    if volume_info:
        metadata = dict(metadata)
        raw_metadata = dict(metadata.get("rawMetadata") or {})
        raw_metadata["sourceSeriesTitle"] = volume_info.series_name
        raw_metadata["sourceVolumeIndex"] = volume_info.series_index
        raw_metadata["sourceVolumeTitle"] = volume_info.title
        if volume_info.author:
            raw_metadata["sourceSeriesAuthor"] = volume_info.author
        metadata["rawMetadata"] = raw_metadata
        metadata["title"] = volume_info.series_name
        if volume_info.author:
            metadata["author"] = volume_info.author
    merge_key = _work_merge_key("epub", identity.title, identity.author, metadata.get("identifier"), metadata.get("isbn"))
    work, created = _ensure_work(db, {"workId": identity.reused_work_id, "title": identity.title, "author": identity.author, "description": None, "workType": "EPUB", "tags": ["epub"], "mergeKey": merge_key, "origin": options.origin, "monitorFolderId": options.monitor_folder_id})
    if volume_info:
        source_key = _source_group_key(options, metadata["title"])
        edition = _select_volume_edition(db, work["id"], "EPUB", source_key, volume_info.series_index, volume_info.title)
        created_edition = False
        if not edition:
            created_edition = True
            edition = _insert(
                db,
                "LibraryEdition",
                {
                    "id": _id(),
                    "workId": work["id"],
                    "monitorFolderId": options.monitor_folder_id,
                    "origin": options.origin,
                    "mediaKind": "EBOOK",
                    "format": "EPUB",
                    "versionName": _next_edition_name(db, work["id"], "EPUB", "EBOOK"),
                    "versionKey": f"epub:{source_key}",
                    "sourceGroupKey": source_key,
                    "description": metadata.get("description"),
                    "language": metadata.get("language"),
                    "publisher": metadata.get("publisher"),
                    "publishedAt": metadata.get("publishedAt"),
                    "identifier": metadata.get("identifier"),
                    "isbn": metadata.get("isbn"),
                    "sizeBytes": 0,
                    "chapterCount": 0,
                    "coverStatus": "PENDING",
                    "importStatus": "PARSING",
                    "primary": _should_be_media_primary(db, work["id"], "EBOOK"),
                    "hidden": False,
                    "createdAt": _now(),
                    "updatedAt": _now(),
                },
            )
        cover_path = None
        try:
            sort_order = int(volume_info.series_index * 1000)
            volume = _insert(db, "LibraryVolume", {"id": _id(), "editionId": edition["id"], "title": volume_info.title, "volumeIndex": volume_info.series_index, "sortOrder": sort_order, "chapterCount": metadata["chapterCount"], "coverPath": None, "createdAt": _now(), "updatedAt": _now()})
            source_path = options.source_file_path.resolve()
            _update(db, "ImportTask", task_id, {"message": "正在建立 EPUB 卷册记录"})
            if metadata.get("coverPath"):
                cover_path = _extract_epub_cover(settings, source_path, work["id"], edition["id"], metadata, volume["id"])
            source_stat = source_path.stat()
            file = _insert(db, "LibraryFile", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "path": str(source_path), "filePathHash": _hash_text(str(source_path)), "hashStatus": "PARTIAL_PENDING", "kind": "EPUB", "mimeType": "application/epub+zip", "sizeBytes": file_size, "mtimeMs": int(source_stat.st_mtime * 1000), "sortOrder": sort_order, "createdAt": _now(), "updatedAt": _now()})
            for chapter in metadata["chapters"]:
                _insert(db, "LibraryReadingUnit", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "fileId": file["id"], "unitType": "chapter", "title": chapter["title"], "href": chapter["href"], "mediaType": chapter.get("mediaType"), "sortOrder": chapter["sortOrder"], "metadataJson": json.dumps({"idref": chapter.get("idref"), "volumeIndex": volume_info.series_index}, ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
            _insert(db, "LibraryMetadata", {"id": _id(), "editionId": edition["id"], "source": "epub_opf", "rawJson": json.dumps(metadata["rawMetadata"], ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
            _insert_identity_metadata(db, edition["id"], identity)
            stored_cover_path = cover_path or ensure_default_cover(settings)
            edition_cover_path = cover_path or edition.get("coverPath") or stored_cover_path
            _update(db, "LibraryVolume", volume["id"], {"coverPath": stored_cover_path, "chapterCount": metadata["chapterCount"], "updatedAt": _now()})
            size_total = _scalar(db, "SELECT COALESCE(SUM(`sizeBytes`), 0) FROM `LibraryFile` WHERE `editionId` = :edition_id", {"edition_id": edition["id"]}, 0)
            chapter_total = _scalar(db, "SELECT COALESCE(SUM(`chapterCount`), 0) FROM `LibraryVolume` WHERE `editionId` = :edition_id", {"edition_id": edition["id"]}, 0)
            _update(db, "LibraryEdition", edition["id"], {"sizeBytes": int(size_total), "chapterCount": int(chapter_total), "coverPath": edition_cover_path, "coverStatus": cover_status(edition_cover_path, settings), "importStatus": "COMPLETED", "updatedAt": _now()})
            _finalize_work_primary(db, settings, work["id"], edition["id"], edition_cover_path)
            return ImportResult(work["id"], work["id"], edition["id"], volume["id"], work["title"], "ebook", "epub", metadata["chapterCount"], "completed", False, (not created) or (not created_edition), "new-epub-work" if created else "new-epub-version" if created_edition else "same-epub-series")
        except Exception:
            if cover_path:
                Path(cover_path).unlink(missing_ok=True)
            raise
    cover_path = None
    try:
        source_path = options.source_file_path.resolve()
        _update(db, "ImportTask", task_id, {"message": "正在建立 EPUB 记录"})
        edition = _insert(
            db,
            "LibraryEdition",
            {
                "id": _id(),
                "workId": work["id"],
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "mediaKind": "EBOOK",
                "format": "EPUB",
                "versionName": _next_edition_name(db, work["id"], "EPUB", "EBOOK"),
                "versionKey": _file_version_key("epub", source_path),
                "description": metadata.get("description"),
                "language": metadata.get("language"),
                "publisher": metadata.get("publisher"),
                "publishedAt": metadata.get("publishedAt"),
                "identifier": metadata.get("identifier"),
                "isbn": metadata.get("isbn"),
                "sizeBytes": file_size,
                "chapterCount": metadata["chapterCount"],
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                "primary": _should_be_media_primary(db, work["id"], "EBOOK"),
                "hidden": False,
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        if metadata.get("coverPath"):
            cover_path = _extract_epub_cover(settings, source_path, work["id"], edition["id"], metadata)
        stored_cover_path = cover_path or ensure_default_cover(settings)
        volume = _insert(db, "LibraryVolume", {"id": _id(), "editionId": edition["id"], "title": "正文", "sortOrder": 0, "chapterCount": metadata["chapterCount"], "coverPath": stored_cover_path, "createdAt": _now(), "updatedAt": _now()})
        source_stat = source_path.stat()
        file = _insert(db, "LibraryFile", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "path": str(source_path), "filePathHash": _hash_text(str(source_path)), "hashStatus": "PARTIAL_PENDING", "kind": "EPUB", "mimeType": "application/epub+zip", "sizeBytes": file_size, "mtimeMs": int(source_stat.st_mtime * 1000), "sortOrder": 0, "createdAt": _now(), "updatedAt": _now()})
        for chapter in metadata["chapters"]:
            _insert(db, "LibraryReadingUnit", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "fileId": file["id"], "unitType": "chapter", "title": chapter["title"], "href": chapter["href"], "mediaType": chapter.get("mediaType"), "sortOrder": chapter["sortOrder"], "metadataJson": json.dumps({"idref": chapter.get("idref")}, ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
        _insert(db, "LibraryMetadata", {"id": _id(), "editionId": edition["id"], "source": "epub_opf", "rawJson": json.dumps(metadata["rawMetadata"], ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
        _insert_identity_metadata(db, edition["id"], identity)
        _update(db, "LibraryEdition", edition["id"], {"coverPath": stored_cover_path, "coverStatus": cover_status(stored_cover_path, settings), "importStatus": "COMPLETED", "updatedAt": _now()})
        _finalize_work_primary(db, settings, work["id"], edition["id"], stored_cover_path)
        return ImportResult(work["id"], work["id"], edition["id"], volume["id"], work["title"], "ebook", "epub", metadata["chapterCount"], "completed", False, not created, "new-work" if created else "same-epub-work")
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


def _import_unconverted_text(
    db: Session,
    settings: Settings,
    options: ImportOptions,
    task_id: str,
    file_size: int,
    ext: str,
    identity: BookIdentity,
) -> ImportResult:
    """Register a supported text source without fabricating readable content.

    The original file becomes a normal library edition and remains downloadable,
    but has no reading units until the user requests the existing EPUB conversion
    pipeline from the work detail page.
    """

    source_path = options.source_file_path.resolve()
    source_format = ext.removeprefix(".").upper()
    merge_key = _work_merge_key("epub", identity.title, identity.author)
    work, created = _ensure_work(
        db,
        {
            "workId": identity.reused_work_id,
            "title": identity.title,
            "author": identity.author,
            "description": None,
            "workType": source_format,
            "tags": ["ebook", source_format.lower()],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )
    _update(db, "ImportTask", task_id, {"message": f"正在建立 {source_format} 原始文件版本"})
    edition = _insert(
        db,
        "LibraryEdition",
        {
            "id": _id(),
            "workId": work["id"],
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "mediaKind": "EBOOK",
            "format": source_format,
            "versionName": _next_edition_name(db, work["id"], f"{source_format} 原始文件", "EBOOK"),
            "versionKey": _file_version_key(source_format.lower(), source_path),
            "sizeBytes": file_size,
            "chapterCount": 0,
            "coverStatus": "PENDING",
            "importStatus": "COMPLETED",
            "primary": _should_be_media_primary(db, work["id"], "EBOOK"),
            "hidden": False,
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    _insert(
        db,
        "LibraryFile",
        {
            "id": _id(),
            "editionId": edition["id"],
            "volumeId": None,
            "path": str(source_path),
            "filePathHash": _hash_text(str(source_path)),
            "hashStatus": "PARTIAL_PENDING",
            "kind": "TEXT_SOURCE",
            "mimeType": mime_type,
            "sizeBytes": file_size,
            "mtimeMs": int(source_path.stat().st_mtime * 1000),
            "sortOrder": 0,
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    if _has_table(db, "LibraryMetadata"):
        _insert(
            db,
            "LibraryMetadata",
            {
                "id": _id(),
                "editionId": edition["id"],
                "source": "unconverted_text",
                "rawJson": json.dumps(
                    {
                        "sourceFormat": source_format,
                        "sourcePath": str(source_path),
                        "readable": False,
                        "conversionAvailable": True,
                    },
                    ensure_ascii=False,
                ),
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        _insert_identity_metadata(db, edition["id"], identity)
    stored_cover_path = ensure_default_cover(settings)
    _update(
        db,
        "LibraryEdition",
        edition["id"],
        {
            "coverPath": stored_cover_path,
            "coverStatus": cover_status(stored_cover_path, settings),
            "updatedAt": _now(),
        },
    )
    _finalize_work_primary(db, settings, work["id"], edition["id"], stored_cover_path)
    return ImportResult(
        work["id"],
        work["id"],
        edition["id"],
        None,
        work["title"],
        "ebook",
        source_format.lower(),
        0,
        "completed",
        False,
        not created,
        "unconverted-text-source",
    )


def _complete_deferred_source_conversion(db: Session, source_path: Path, result: ImportResult) -> None:
    source_edition = _row(
        db,
        """
        SELECT e.`id`
        FROM `LibraryFile` f
        JOIN `LibraryEdition` e ON e.`id` = f.`editionId`
        WHERE f.`path` = :source_path
          AND e.`workId` = :work_id
          AND e.`id` != :result_edition_id
          AND UPPER(e.`format`) IN ('MOBI', 'AZW', 'AZW3', 'PRC', 'FB2', 'TXT')
          AND COALESCE(e.`hidden`, 0) = 0
        ORDER BY e.`createdAt` ASC
        LIMIT 1
        """,
        {
            "source_path": str(source_path.resolve()),
            "work_id": result.work_id,
            "result_edition_id": result.edition_id,
        },
    )
    if not source_edition:
        return
    _update(db, "LibraryEdition", str(source_edition["id"]), {"primary": False, "hidden": True, "updatedAt": _now()})
    _update(db, "LibraryEdition", result.edition_id, {"primary": True, "hidden": False, "updatedAt": _now()})
    _update(
        db,
        "LibraryWork",
        result.work_id,
        {"primaryEditionId": result.edition_id, "workType": "EPUB", "updatedAt": _now()},
    )


def _import_pdf(db: Session, settings: Settings, options: ImportOptions, task_id: str, file_size: int, ext: str, identity: BookIdentity) -> ImportResult:
    metadata = parse_pdf_metadata(options.source_file_path, options.original_name)
    merge_key = _work_merge_key("pdf", identity.title, identity.author)
    work, created = _ensure_work(
        db,
        {
            "workId": identity.reused_work_id,
            "title": identity.title,
            "author": identity.author,
            "description": None,
            "workType": "PDF",
            "tags": ["pdf"],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )
    cover_path = None
    try:
        source_path = options.source_file_path.resolve()
        _update(db, "ImportTask", task_id, {"message": "正在建立 PDF 记录"})
        edition = _insert(
            db,
            "LibraryEdition",
            {
                "id": _id(),
                "workId": work["id"],
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "mediaKind": "EBOOK",
                "format": "PDF",
                "versionName": _next_edition_name(db, work["id"], "PDF", "EBOOK"),
                "versionKey": _file_version_key("pdf", source_path),
                "description": metadata.get("description"),
                "sizeBytes": file_size,
                "pageCount": metadata["pageCount"],
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                "primary": _should_be_media_primary(db, work["id"], "EBOOK"),
                "hidden": False,
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        cover_path = _extract_pdf_cover(settings, source_path, work["id"], edition["id"], metadata)
        stored_cover_path = cover_path or ensure_default_cover(settings)
        volume = _insert(db, "LibraryVolume", {"id": _id(), "editionId": edition["id"], "title": "PDF", "sortOrder": 0, "pageCount": metadata["pageCount"], "coverPath": stored_cover_path, "createdAt": _now(), "updatedAt": _now()})
        file = _insert(db, "LibraryFile", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "path": str(source_path), "filePathHash": _hash_text(str(source_path)), "hashStatus": "PARTIAL_PENDING", "kind": "PDF", "mimeType": "application/pdf", "sizeBytes": file_size, "mtimeMs": int(source_path.stat().st_mtime * 1000), "sortOrder": 0, "createdAt": _now(), "updatedAt": _now()})
        for index in range(1, max(1, metadata["pageCount"]) + 1):
            _insert(db, "LibraryReadingUnit", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "fileId": file["id"], "unitType": "page", "title": f"第 {index} 页", "href": str(source_path), "mediaType": "application/pdf", "sortOrder": index, "metadataJson": json.dumps({"pageNumber": index, "sourceFileName": options.original_name or options.source_file_path.name}, ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
        _insert(db, "LibraryMetadata", {"id": _id(), "editionId": edition["id"], "source": "pdf", "rawJson": json.dumps(metadata["rawMetadata"], ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
        _insert_identity_metadata(db, edition["id"], identity)
        _update(db, "LibraryEdition", edition["id"], {"coverPath": stored_cover_path, "coverStatus": cover_status(stored_cover_path, settings), "importStatus": "COMPLETED", "updatedAt": _now()})
        _finalize_work_primary(db, settings, work["id"], edition["id"], stored_cover_path)
        return ImportResult(work["id"], work["id"], edition["id"], volume["id"], work["title"], "ebook", "pdf", metadata["pageCount"], "completed", False, not created, "new-pdf-work" if created else "same-pdf-work")
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


def _import_comic(db: Session, settings: Settings, options: ImportOptions, task_id: str, file_size: int, ext: str, identity: BookIdentity) -> ImportResult:
    parsed = parse_comic_archive(options.source_file_path, options.original_name)
    volume_info = {"seriesName": identity.title, "seriesIndex": identity.volume_index, "author": identity.author} if identity.volume_index is not None else None
    title = identity.title
    author = identity.author
    merge_key = _work_merge_key("cbz", title, author)
    source_key = _source_group_key(options, title)
    volume_index = (volume_info or {}).get("seriesIndex")
    volume_title = f"第 {volume_index:g} 卷" if volume_index is not None else ((parsed.get("comicInfo") or {}).get("title") or parsed["title"])
    work, created = _ensure_work(db, {"workId": identity.reused_work_id, "title": title, "author": author, "description": None, "workType": "COMIC", "tags": ["comic", parsed["format"]], "mergeKey": merge_key, "origin": options.origin, "monitorFolderId": options.monitor_folder_id})
    edition = _select_volume_edition(db, work["id"], "COMIC", source_key, volume_index, volume_title) if volume_index is not None else None
    created_edition = False
    if not edition:
        created_edition = True
        edition = _insert(db, "LibraryEdition", {"id": _id(), "workId": work["id"], "monitorFolderId": options.monitor_folder_id, "origin": options.origin, "mediaKind": "COMIC", "format": "COMIC", "versionName": _next_edition_name(db, work["id"], "漫画版本", "COMIC"), "versionKey": f"comic:{source_key}" if volume_index is not None else _file_version_key("comic", options.source_file_path.resolve()), "sourceGroupKey": source_key, "description": parsed.get("description"), "publisher": (parsed.get("comicInfo") or {}).get("publisher"), "coverStatus": "PENDING", "importStatus": "PARSING", "primary": _should_be_media_primary(db, work["id"], "COMIC"), "hidden": False, "createdAt": _now(), "updatedAt": _now()})
    cover_path = None
    try:
        sort_order = int(volume_index * 1000) if volume_index is not None else _table_count(db, "LibraryVolume", "`editionId` = :edition_id", {"edition_id": edition["id"]})
        volume = _insert(db, "LibraryVolume", {"id": _id(), "editionId": edition["id"], "title": volume_title, "volumeIndex": volume_index, "sortOrder": sort_order, "pageCount": parsed["pageCount"], "coverPath": None, "createdAt": _now(), "updatedAt": _now()})
        source_path = options.source_file_path.resolve()
        _update(db, "ImportTask", task_id, {"message": "正在建立漫画记录"})
        file = _insert(db, "LibraryFile", {"id": _id(), "editionId": edition["id"], "volumeId": volume["id"], "path": str(source_path), "filePathHash": _hash_text(str(source_path)), "hashStatus": "PARTIAL_PENDING", "kind": "COMIC", "mimeType": "application/vnd.comicbook+zip" if parsed["format"] == "cbz" else "application/zip", "sizeBytes": file_size, "mtimeMs": int(source_path.stat().st_mtime * 1000), "sortOrder": sort_order, "createdAt": _now(), "updatedAt": _now()})
        try:
            cover_path = _extract_comic_cover(settings, source_path, work["id"], edition["id"], volume["id"], parsed["coverEntryPath"])
        except Exception as exc:
            cover_path = None
            _log_import(db, task_id, "warning", f"comic cover extraction skipped: {exc}")
        _insert(db, "LibraryMetadata", {"id": _id(), "editionId": edition["id"], "source": "comic_info" if parsed.get("comicInfo") else "system", "rawJson": json.dumps({**parsed["rawMetadata"], "volumeIndex": volume_index, "sourceFileName": options.original_name or options.source_file_path.name}, ensure_ascii=False), "createdAt": _now(), "updatedAt": _now()})
        _insert_identity_metadata(db, edition["id"], identity)
        stored_cover_path = cover_path or ensure_default_cover(settings)
        edition_cover_path = cover_path or edition.get("coverPath") or stored_cover_path
        _update(db, "LibraryVolume", volume["id"], {"coverPath": stored_cover_path, "pageCount": parsed["pageCount"], "updatedAt": _now()})
        size_total = _scalar(db, "SELECT COALESCE(SUM(`sizeBytes`), 0) FROM `LibraryFile` WHERE `editionId` = :edition_id", {"edition_id": edition["id"]}, 0)
        page_total = _scalar(db, "SELECT COALESCE(SUM(`pageCount`), 0) FROM `LibraryVolume` WHERE `editionId` = :edition_id", {"edition_id": edition["id"]}, 0)
        _update(db, "LibraryEdition", edition["id"], {"sizeBytes": int(size_total), "pageCount": int(page_total), "coverPath": edition_cover_path, "coverStatus": cover_status(edition_cover_path, settings), "importStatus": "COMPLETED", "updatedAt": _now()})
        _finalize_work_primary(db, settings, work["id"], edition["id"], edition_cover_path)
        return ImportResult(work["id"], work["id"], edition["id"], volume["id"], work["title"], "comic", parsed["format"], parsed["pageCount"], "completed", False, (not created) or (not created_edition), "new-comic-work" if created else "new-comic-version" if created_edition else "same-comic-series")
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


def _import_audio(
    db: Session,
    settings: Settings,
    options: ImportOptions,
    task_id: str,
    identity: BookIdentity,
    metadata_items: list[AudioFileMetadata],
) -> ImportResult:
    if not metadata_items:
        raise ValueError("有声书目录中没有可导入的音频文件")
    chapter_total = sum(max(1, len(item.chapters)) for item in metadata_items)
    if chapter_total > MAX_AUDIO_CHAPTERS:
        raise ValueError(f"有声书章节总数超过 {MAX_AUDIO_CHAPTERS} 个，请拆分后导入")
    effective_track_numbers = _effective_audio_track_numbers(metadata_items)
    metadata_items = sorted(
        metadata_items,
        key=lambda item: _audio_metadata_sort_key(item, effective_track_numbers.get(item.path)),
    )
    source_root = options.source_file_path.resolve()
    directory_bundle = source_root.is_dir()
    flat_title = _flat_audio_filename_title(source_root) if source_root.is_file() else None
    flat_bundle_key = _flat_audio_bundle_key(source_root, flat_title) if flat_title else None
    display_titles = _audio_track_titles(metadata_items)
    content_info = [
        {
            "item": item,
            "size": item.path.stat().st_size,
            "fingerprint": _sample_fingerprint(item.path),
            "fullHash": None,
        }
        for item in metadata_items
    ]
    _reject_duplicate_audio_tracks(content_info)
    existing_by_path = _audio_files_by_path(db, [item.path for item in metadata_items])
    if existing_by_path and not directory_bundle:
        raise ValueError("音频文件已入库，请使用原目录重新扫描")

    narrator_values = _consistent_audio_values(
        metadata_items,
        "narrator",
        "朗读者",
        strict=not directory_bundle,
    )
    narrator = narrator_values[0] if narrator_values else None
    merge_key = _work_merge_key("audio", identity.title, identity.author)
    # A directory identifies one split-track bundle. An explicitly structured
    # Emby flat filename joins its sibling chapters; every other single file
    # remains keyed by the file itself so independent M4Bs cannot collide.
    bundle_key = flat_bundle_key or _hash_text(str(source_root))[:24]
    version_key = (
        f"audio-flat:{bundle_key}"
        if flat_bundle_key
        else f"audio:{bundle_key}:{_normalize_key(narrator or 'default')}"
    )
    base_name = f"有声书 · {narrator}" if narrator else "有声书"
    total_duration = sum(item.duration_ms for item in metadata_items)
    reconciled = False
    created = False
    if existing_by_path:
        work, created = _ensure_audio_work(db, options, identity, merge_key)
        edition, volume = _prepare_existing_audio_bundle(
            db,
            work,
            existing_by_path,
            options,
            bundle_key,
            base_name,
            narrator,
        )
        reconciled = True
    else:
        duplicate_result, duplicate_files = _audio_content_duplicate_result(db, content_info)
        if duplicate_result:
            for index, (item_info, duplicate_file) in enumerate(zip(content_info, duplicate_files, strict=True)):
                item = item_info["item"]
                asset = _row(
                    db,
                    "SELECT * FROM `ImportAsset` WHERE `importTaskId` = :task_id AND `sourcePath` = :source_path",
                    {"task_id": task_id, "source_path": str(item.path)},
                ) if _has_table(db, "ImportAsset") else None
                if asset:
                    _update(
                        db,
                        "ImportAsset",
                        str(asset["id"]),
                        {
                            "status": "COMPLETED",
                            "sortOrder": index,
                            "fileId": duplicate_file["id"],
                            "errorCode": None,
                            "errorSummary": None,
                            "updatedAt": _now(),
                        },
                    )
            _update(
                db,
                "ImportTask",
                task_id,
                {"processedAssetCount": len(metadata_items), "message": "音频内容已存在，复用现有有声书版本"},
            )
            return replace(duplicate_result, merge_reason="duplicate-audio-content")
        flat_edition = _audio_flat_edition(db, version_key) if flat_bundle_key else None
        if flat_edition:
            identity = replace(identity, reused_work_id=str(flat_edition["workId"]))
            merge_key = _work_merge_key("audio", identity.title, identity.author)
            work, _unused_created = _ensure_audio_work(db, options, identity, merge_key)
            created = False
            edition, volume = _prepare_flat_audio_bundle(
                db,
                work,
                flat_edition,
                options,
                version_key,
                bundle_key,
                narrator,
            )
            reconciled = True
        else:
            work, created = _ensure_audio_work(db, options, identity, merge_key)
            edition = _insert(
                db,
                "LibraryEdition",
                {
                    "id": _id(),
                    "workId": work["id"],
                    "monitorFolderId": options.monitor_folder_id,
                    "origin": options.origin,
                    "mediaKind": "AUDIOBOOK",
                    "format": "AUDIO",
                    "versionName": _next_edition_name(db, work["id"], base_name, "AUDIOBOOK"),
                    "versionKey": version_key,
                    "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
                    "description": None,
                    "sizeBytes": sum(item.path.stat().st_size for item in metadata_items),
                    "chapterCount": 0,
                    "durationMs": total_duration,
                    "trackCount": len(metadata_items),
                    "narrator": narrator,
                    "coverStatus": "PENDING",
                    "importStatus": "PARSING",
                    "primary": _should_be_media_primary(db, work["id"], "AUDIOBOOK"),
                    "hidden": False,
                    "createdAt": _now(),
                    "updatedAt": _now(),
                },
            )
            volume = _insert(
                db,
                "LibraryVolume",
                {
                    "id": _id(),
                    "editionId": edition["id"],
                    "title": "正文",
                    "sortOrder": 0,
                    "chapterCount": 0,
                    "durationMs": total_duration,
                    "createdAt": _now(),
                    "updatedAt": _now(),
                },
            )
    cover_path = edition.get("coverPath") or _extract_audio_cover(
        settings,
        work["id"],
        edition["id"],
        metadata_items,
        bundle_root=source_root if directory_bundle else None,
    )
    cover_path = cover_path or ensure_default_cover(settings)
    manifest_tracks: list[dict[str, Any]] = []
    manifest_chapters: list[dict[str, Any]] = []
    chapter_sort_order = 0
    for index, item in enumerate(metadata_items):
        item_content = content_info[index]
        stat = item.path.stat()
        sort_order = index
        file_values = {
            "editionId": edition["id"],
            "volumeId": volume["id"],
            "path": str(item.path),
            "filePathHash": _hash_text(str(item.path)),
            "fingerprint": item_content["fingerprint"],
            "fullHash": item_content["fullHash"] or (existing_by_path.get(str(item.path)) or {}).get("fullHash"),
            "hashStatus": "COMPLETED" if item_content["fullHash"] or (existing_by_path.get(str(item.path)) or {}).get("fullHash") else "PARTIAL_PENDING",
            "mtimeMs": int(stat.st_mtime * 1000),
            "kind": "AUDIO",
            "mimeType": "audio/mpeg" if item.path.suffix.lower() == ".mp3" else "audio/mp4",
            "sizeBytes": stat.st_size,
            "durationMs": item.duration_ms,
            "codec": item.codec,
            "bitrate": item.bitrate,
            "sampleRate": item.sample_rate,
            "channels": item.channels,
            "discNumber": item.disc_number if item.disc_number is not None else _audio_disc_number(item.path),
            "trackNumber": effective_track_numbers.get(item.path),
            "sortOrder": sort_order,
            "updatedAt": _now(),
        }
        existing_file = existing_by_path.get(str(item.path))
        if existing_file:
            _update(db, "LibraryFile", str(existing_file["id"]), file_values)
            file_row = _row(db, "SELECT * FROM `LibraryFile` WHERE `id` = :id", {"id": existing_file["id"]}) or {**existing_file, **file_values}
        else:
            file_row = _insert(db, "LibraryFile", {"id": _id(), "createdAt": _now(), **file_values})
        asset = _row(
            db,
            "SELECT * FROM `ImportAsset` WHERE `importTaskId` = :task_id AND `sourcePath` = :source_path",
            {"task_id": task_id, "source_path": str(item.path)},
        ) if _has_table(db, "ImportAsset") else None
        asset_values = {
            "status": "COMPLETED",
            "sortOrder": sort_order,
            "fileId": file_row["id"],
            "errorCode": None,
            "errorSummary": None,
            "updatedAt": _now(),
        }
        if asset:
            _update(db, "ImportAsset", str(asset["id"]), asset_values)
        elif _has_table(db, "ImportAsset"):
            _insert(
                db,
                "ImportAsset",
                {
                    "id": _id(),
                    "importTaskId": task_id,
                    "sourcePath": str(item.path),
                    "createdAt": _now(),
                    **asset_values,
                },
            )
        source_chapters = list(item.chapters) or [
            AudioChapterMetadata(title=display_titles[item.path], start_ms=0, end_ms=item.duration_ms)
        ]
        existing_units = _rows(
            db,
            "SELECT * FROM `LibraryReadingUnit` WHERE `fileId` = :file_id AND `unitType` = 'audio_chapter' ORDER BY `sortOrder`, `createdAt`, `id`",
            {"file_id": file_row["id"]},
        )
        kept_unit_ids: set[str] = set()
        for chapter_index, chapter in enumerate(source_chapters):
            chapter_sort_order += 1
            start_ms = max(0, int(chapter.start_ms))
            end_ms = min(item.duration_ms, int(chapter.end_ms)) if item.duration_ms else int(chapter.end_ms)
            if end_ms <= start_ms:
                continue
            unit_values = {
                "editionId": edition["id"],
                "volumeId": volume["id"],
                "fileId": file_row["id"],
                "unitType": "audio_chapter",
                "title": chapter.title or display_titles[item.path] or f"第 {chapter_sort_order} 章",
                "href": f"audio:{file_row['id']}#t={start_ms / 1000:g},{end_ms / 1000:g}",
                "mediaType": "audio/mpeg" if item.path.suffix.lower() == ".mp3" else "audio/mp4",
                "sortOrder": chapter_sort_order,
                "startMs": start_ms,
                "endMs": end_ms,
                "durationMs": end_ms - start_ms,
                "metadataJson": json.dumps({"trackIndex": index, "sourceFileName": item.path.name}, ensure_ascii=False),
                "updatedAt": _now(),
            }
            if chapter_index < len(existing_units):
                existing_unit = existing_units[chapter_index]
                _update(db, "LibraryReadingUnit", str(existing_unit["id"]), unit_values)
                unit = _row(db, "SELECT * FROM `LibraryReadingUnit` WHERE `id` = :id", {"id": existing_unit["id"]}) or {**existing_unit, **unit_values}
            else:
                unit = _insert(db, "LibraryReadingUnit", {"id": _id(), "createdAt": _now(), **unit_values})
            kept_unit_ids.add(str(unit["id"]))
            manifest_chapters.append(
                {
                    "id": unit["id"],
                    "title": unit["title"],
                    "fileId": file_row["id"],
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "sortOrder": chapter_sort_order,
                }
            )
        for stale_unit in existing_units:
            if str(stale_unit["id"]) not in kept_unit_ids:
                db.execute(text("DELETE FROM `LibraryReadingUnit` WHERE `id` = :id"), {"id": stale_unit["id"]})
        manifest_tracks.append(
            {
                "fileId": file_row["id"],
                "title": display_titles[item.path],
                "sourceFileName": item.path.name,
                "mimeType": file_row["mimeType"],
                "durationMs": item.duration_ms,
                "discNumber": file_row.get("discNumber"),
                "trackNumber": file_row.get("trackNumber"),
                "sortOrder": sort_order,
            }
        )
        _update(
            db,
            "ImportTask",
            task_id,
            {
                "processedAssetCount": index + 1,
                "progress": 30 + round(((index + 1) / len(metadata_items)) * 55),
                "message": f"已建立音轨 {index + 1}/{len(metadata_items)}",
            },
        )
    raw_tags = [
        {"sourcePath": str(item.path), "tags": item.raw_tags}
        for item in metadata_items
    ]
    _restore_unassigned_audio_units(db, str(edition["id"]), str(volume["id"]), chapter_sort_order)
    if reconciled:
        _resort_audio_edition(db, str(edition["id"]), str(volume["id"]))
    raw_tags = _merge_audio_raw_tags(db, str(edition["id"]), raw_tags)
    manifest_tracks, manifest_chapters = _audio_manifest_from_db(db, str(edition["id"]))
    total_duration = sum(int(item.get("durationMs") or 0) for item in manifest_tracks)
    db.execute(
        text("DELETE FROM `LibraryMetadata` WHERE `editionId` = :edition_id AND `source` IN ('audio_tags', 'audiobook_manifest')"),
        {"edition_id": edition["id"]},
    )
    _insert(
        db,
        "LibraryMetadata",
        {
            "id": _id(),
            "editionId": edition["id"],
            "source": "audio_tags",
            "rawJson": json.dumps(raw_tags, ensure_ascii=False),
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    _insert(
        db,
        "LibraryMetadata",
        {
            "id": _id(),
            "editionId": edition["id"],
            "source": "audiobook_manifest",
            "rawJson": json.dumps(
                {"durationMs": total_duration, "narrator": narrator, "tracks": manifest_tracks, "chapters": manifest_chapters},
                ensure_ascii=False,
            ),
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    _insert_identity_metadata(db, edition["id"], identity)
    actual_size = int(_scalar(db, "SELECT COALESCE(SUM(`sizeBytes`), 0) FROM `LibraryFile` WHERE `editionId` = :edition_id AND UPPER(`kind`) = 'AUDIO'", {"edition_id": edition["id"]}, 0))
    actual_duration = int(_scalar(db, "SELECT COALESCE(SUM(`durationMs`), 0) FROM `LibraryFile` WHERE `editionId` = :edition_id AND UPPER(`kind`) = 'AUDIO'", {"edition_id": edition["id"]}, 0))
    actual_tracks = int(_scalar(db, "SELECT COUNT(*) FROM `LibraryFile` WHERE `editionId` = :edition_id AND UPPER(`kind`) = 'AUDIO'", {"edition_id": edition["id"]}, 0))
    actual_chapters = int(_scalar(db, "SELECT COUNT(*) FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND `unitType` = 'audio_chapter'", {"edition_id": edition["id"]}, 0))
    if reconciled:
        _refresh_audio_progress_after_bundle_sync(db, str(edition["id"]), str(volume["id"]))
    _update(
        db,
        "LibraryVolume",
        volume["id"],
        {"coverPath": cover_path, "chapterCount": actual_chapters, "durationMs": actual_duration, "updatedAt": _now()},
    )
    _update(
        db,
        "LibraryEdition",
        edition["id"],
        {
            "coverPath": cover_path,
            "coverStatus": cover_status(cover_path, settings),
            "sizeBytes": actual_size,
            "chapterCount": actual_chapters,
            "trackCount": actual_tracks,
            "durationMs": actual_duration,
            "narrator": narrator,
            "importStatus": "COMPLETED",
            "updatedAt": _now(),
        },
    )
    _finalize_work_primary(db, settings, work["id"], edition["id"], cover_path)
    return ImportResult(
        work["id"],
        work["id"],
        edition["id"],
        volume["id"],
        work["title"],
        "audiobook",
        "audio",
        actual_chapters,
        "completed",
        False,
        reconciled or not created,
        "reconciled-audio-directory" if reconciled else "new-audio-work" if created else "new-audio-edition",
    )


def _audio_files_by_path(db: Session, paths: list[Path]) -> dict[str, dict[str, Any]]:
    if not paths or not _has_table(db, "LibraryFile"):
        return {}
    found: dict[str, dict[str, Any]] = {}
    resolved = [str(path.resolve()) for path in paths]
    for offset in range(0, len(resolved), 400):
        chunk = resolved[offset:offset + 400]
        params = {f"path_{index}": path for index, path in enumerate(chunk)}
        placeholders = ", ".join(f":path_{index}" for index in range(len(chunk)))
        rows = _rows(db, f"SELECT * FROM `LibraryFile` WHERE `path` IN ({placeholders})", params)
        found.update({str(row["path"]): row for row in rows})
    return found


def _reject_duplicate_audio_tracks(content_info: list[dict[str, Any]]) -> None:
    pending_by_sample: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for info in content_info:
        signature = (int(info["size"]), str(info["fingerprint"]))
        pending_by_sample.setdefault(signature, []).append(info)
    for group in pending_by_sample.values():
        if len(group) < 2:
            continue
        full_hashes = [_audio_info_full_hash(info) for info in group]
        if len(set(full_hashes)) != len(full_hashes):
            raise ValueError("有声书目录中包含字节完全相同的重复音轨，请移除后重试")


def _ensure_audio_work(
    db: Session,
    options: ImportOptions,
    identity: BookIdentity,
    merge_key: str,
) -> tuple[dict[str, Any], bool]:
    return _ensure_work(
        db,
        {
            "workId": identity.reused_work_id,
            "title": identity.title,
            "author": identity.author,
            "description": None,
            "workType": "AUDIO",
            "tags": ["audiobook", "audio"],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )


def _audio_flat_edition(db: Session, version_key: str) -> dict[str, Any] | None:
    return _row(
        db,
        "SELECT * FROM `LibraryEdition` WHERE `versionKey` = :version_key "
        "AND UPPER(`mediaKind`) = 'AUDIOBOOK' AND COALESCE(`hidden`, 0) = 0 "
        "ORDER BY `createdAt`, `id` LIMIT 1",
        {"version_key": version_key},
    )


def _prepare_flat_audio_bundle(
    db: Session,
    work: dict[str, Any],
    edition: dict[str, Any],
    options: ImportOptions,
    version_key: str,
    bundle_key: str,
    narrator: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append one strict Emby flat-layout chapter to its existing edition."""

    edition_id = str(edition["id"])
    volume = _row(
        db,
        "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id "
        "ORDER BY `sortOrder`, `createdAt`, `id` LIMIT 1",
        {"edition_id": edition_id},
    )
    if not volume:
        volume = _insert(
            db,
            "LibraryVolume",
            {
                "id": _id(),
                "editionId": edition_id,
                "title": "正文",
                "sortOrder": 0,
                "chapterCount": 0,
                "durationMs": 0,
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
    # The schema has a unique (volume, unit type, sort order) index. Detach
    # the existing units while the new file is inserted, then globally sort
    # all tracks and chapters after the append.
    db.execute(
        text(
            "UPDATE `LibraryReadingUnit` SET `volumeId` = NULL, `updatedAt` = CURRENT_TIMESTAMP "
            "WHERE `editionId` = :edition_id AND `unitType` = 'audio_chapter'"
        ),
        {"edition_id": edition_id},
    )
    _update(
        db,
        "LibraryEdition",
        edition_id,
        {
            "workId": work["id"],
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "versionKey": version_key,
            "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
            "narrator": narrator or edition.get("narrator"),
            "hidden": False,
            "importStatus": "PARSING",
            "updatedAt": _now(),
        },
    )
    _update(db, "LibraryWork", str(work["id"]), {"hidden": False, "updatedAt": _now()})
    refreshed = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id}) or edition
    return refreshed, volume


def _prepare_existing_audio_bundle(
    db: Session,
    work: dict[str, Any],
    existing_by_path: dict[str, dict[str, Any]],
    options: ImportOptions,
    bundle_key: str,
    base_name: str,
    narrator: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Collapse files previously imported one-by-one into one visible edition.

    The old editions and empty works are hidden rather than deleted so import
    history and user data remain recoverable. File, chapter, shelf, and latest
    audio progress pointers are retargeted to the canonical bundle.
    """

    edition_ids = sorted({str(row["editionId"]) for row in existing_by_path.values() if row.get("editionId")})
    if not edition_ids:
        raise ValueError("已入库音频缺少版本信息，无法按目录合并")
    params = {f"edition_{index}": edition_id for index, edition_id in enumerate(edition_ids)}
    placeholders = ", ".join(f":edition_{index}" for index in range(len(edition_ids)))
    editions = _rows(
        db,
        f"SELECT * FROM `LibraryEdition` WHERE `id` IN ({placeholders})",
        params,
    )
    if not editions:
        raise ValueError("已入库音频的版本记录不完整")
    target_work_id = str(work["id"])
    editions.sort(
        key=lambda row: (
            0 if str(row.get("workId")) == target_work_id else 1,
            0 if bool(row.get("primary")) else 1,
            str(row.get("createdAt") or ""),
            str(row.get("id") or ""),
        )
    )
    canonical = editions[0]
    canonical_id = str(canonical["id"])
    redundant_ids = [edition_id for edition_id in edition_ids if edition_id != canonical_id]
    source_work_ids = sorted({str(row.get("workId")) for row in editions if row.get("workId")})

    for edition_id in redundant_ids:
        _update(db, "LibraryEdition", edition_id, {"primary": False, "hidden": True, "updatedAt": _now()})

    other_primary = int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM `LibraryEdition` WHERE `workId` = :work_id AND `mediaKind` = 'AUDIOBOOK' "
            "AND `id` != :edition_id AND COALESCE(`hidden`, 0) = 0 AND `primary` = 1",
            {"work_id": target_work_id, "edition_id": canonical_id},
            0,
        )
    )
    version_key = f"audio:{bundle_key}:{_normalize_key(narrator or 'default')}"
    version_conflict = _row(
        db,
        "SELECT `id` FROM `LibraryEdition` WHERE `workId` = :work_id AND `versionKey` = :version_key AND `id` != :edition_id LIMIT 1",
        {"work_id": target_work_id, "version_key": version_key, "edition_id": canonical_id},
    )
    _update(
        db,
        "LibraryEdition",
        canonical_id,
        {
            "workId": target_work_id,
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "mediaKind": "AUDIOBOOK",
            "format": "AUDIO",
            "versionName": base_name,
            "versionKey": canonical.get("versionKey") if version_conflict else version_key,
            "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
            "narrator": narrator,
            "primary": other_primary == 0,
            "hidden": False,
            "importStatus": "PARSING",
            "updatedAt": _now(),
        },
    )
    canonical = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": canonical_id}) or canonical
    volume = _row(
        db,
        "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `createdAt`, `id` LIMIT 1",
        {"edition_id": canonical_id},
    )
    if not volume:
        volume = _insert(
            db,
            "LibraryVolume",
            {
                "id": _id(),
                "editionId": canonical_id,
                "title": "正文",
                "sortOrder": 0,
                "chapterCount": 0,
                "durationMs": 0,
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )

    file_ids = sorted({str(row["id"]) for row in existing_by_path.values() if row.get("id")})
    unit_params: dict[str, Any] = {"canonical_id": canonical_id}
    file_placeholders: list[str] = []
    for index, file_id in enumerate(file_ids):
        key = f"file_{index}"
        unit_params[key] = file_id
        file_placeholders.append(f":{key}")
    if _has_table(db, "LibraryReadingUnit"):
        where = "`editionId` = :canonical_id"
        if file_placeholders:
            where += f" OR `fileId` IN ({', '.join(file_placeholders)})"
        db.execute(
            text(f"UPDATE `LibraryReadingUnit` SET `volumeId` = NULL, `updatedAt` = CURRENT_TIMESTAMP WHERE {where}"),
            unit_params,
        )

    _retarget_audio_progress(db, source_work_ids, edition_ids, target_work_id, canonical_id, str(volume["id"]))
    if _has_table(db, "ShelfWork") and source_work_ids:
        shelf_params = {"target_work_id": target_work_id, **{f"work_{index}": value for index, value in enumerate(source_work_ids)}}
        shelf_placeholders = ", ".join(f":work_{index}" for index in range(len(source_work_ids)))
        db.execute(
            text(
                "INSERT OR IGNORE INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) "
                f"SELECT `shelfId`, :target_work_id, CURRENT_TIMESTAMP FROM `ShelfWork` WHERE `workId` IN ({shelf_placeholders})"
            ),
            shelf_params,
        )

    _update(db, "LibraryWork", target_work_id, {"hidden": False, "primaryEditionId": canonical_id, "updatedAt": _now()})
    for source_work_id in source_work_ids:
        if source_work_id == target_work_id:
            continue
        visible_editions = int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0",
                {"work_id": source_work_id},
                0,
            )
        )
        if visible_editions == 0:
            _update(db, "LibraryWork", source_work_id, {"hidden": True, "primaryEditionId": None, "updatedAt": _now()})
    return canonical, volume


def _retarget_audio_progress(
    db: Session,
    source_work_ids: list[str],
    source_edition_ids: list[str],
    target_work_id: str,
    target_edition_id: str,
    target_volume_id: str,
) -> None:
    if _has_table(db, "LibraryReadingProgress") and source_edition_ids:
        params = {f"edition_{index}": value for index, value in enumerate(source_edition_ids)}
        placeholders = ", ".join(f":edition_{index}" for index in range(len(source_edition_ids)))
        rows = _rows(
            db,
            f"SELECT * FROM `LibraryReadingProgress` WHERE `editionId` IN ({placeholders}) ORDER BY `updatedAt`, `createdAt`, `id`",
            params,
        )
        for user_id in {str(row.get("userId")) for row in rows if row.get("userId")}:
            user_rows = [row for row in rows if str(row.get("userId")) == user_id]
            latest = user_rows[-1]
            canonical = next((row for row in user_rows if str(row.get("editionId")) == target_edition_id), None)
            target = canonical or latest
            copied = {
                key: value
                for key, value in latest.items()
                if key not in {"id", "userId", "createdAt", "workId", "editionId", "volumeId"}
            }
            _update(
                db,
                "LibraryReadingProgress",
                str(target["id"]),
                {**copied, "workId": target_work_id, "editionId": target_edition_id, "volumeId": target_volume_id, "updatedAt": _now()},
            )

    if _has_table(db, "LibraryConsumptionState") and source_work_ids:
        params = {f"work_{index}": value for index, value in enumerate(source_work_ids)}
        placeholders = ", ".join(f":work_{index}" for index in range(len(source_work_ids)))
        rows = _rows(
            db,
            f"SELECT * FROM `LibraryConsumptionState` WHERE `workId` IN ({placeholders}) AND UPPER(`mediaKind`) = 'AUDIOBOOK' "
            "ORDER BY `updatedAt`, `createdAt`, `id`",
            params,
        )
        for user_id in {str(row.get("userId")) for row in rows if row.get("userId")}:
            user_rows = [row for row in rows if str(row.get("userId")) == user_id]
            latest = user_rows[-1]
            canonical = next((row for row in user_rows if str(row.get("workId")) == target_work_id), None)
            target = canonical or latest
            _update(
                db,
                "LibraryConsumptionState",
                str(target["id"]),
                {
                    "workId": target_work_id,
                    "mediaKind": "AUDIOBOOK",
                    "status": latest.get("status") or "UNREAD",
                    "lastEditionId": target_edition_id,
                    "lastVolumeId": target_volume_id,
                    "lastUnitId": latest.get("lastUnitId"),
                    "updatedAt": _now(),
                },
            )


def _restore_unassigned_audio_units(db: Session, edition_id: str, volume_id: str, after_sort_order: int) -> None:
    rows = _rows(
        db,
        "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND `volumeId` IS NULL "
        "ORDER BY `sortOrder`, `createdAt`, `id`",
        {"edition_id": edition_id},
    )
    sort_order = after_sort_order
    for row in rows:
        sort_order += 1
        _update(
            db,
            "LibraryReadingUnit",
            str(row["id"]),
            {"volumeId": volume_id, "sortOrder": sort_order, "updatedAt": _now()},
        )


def _resort_audio_edition(db: Session, edition_id: str, volume_id: str) -> None:
    files = _rows(
        db,
        "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id AND UPPER(`kind`) = 'AUDIO'",
        {"edition_id": edition_id},
    )
    files.sort(key=_audio_file_row_sort_key)
    db.execute(
        text(
            "UPDATE `LibraryReadingUnit` SET `volumeId` = NULL, `updatedAt` = CURRENT_TIMESTAMP "
            "WHERE `editionId` = :edition_id AND `unitType` = 'audio_chapter'"
        ),
        {"edition_id": edition_id},
    )
    chapter_sort_order = 0
    for file_sort_order, file in enumerate(files):
        _update(
            db,
            "LibraryFile",
            str(file["id"]),
            {"volumeId": volume_id, "sortOrder": file_sort_order, "updatedAt": _now()},
        )
        units = _rows(
            db,
            "SELECT * FROM `LibraryReadingUnit` WHERE `fileId` = :file_id AND `unitType` = 'audio_chapter' "
            "ORDER BY COALESCE(`startMs`, 0), `sortOrder`, `createdAt`, `id`",
            {"file_id": file["id"]},
        )
        for unit in units:
            chapter_sort_order += 1
            _update(
                db,
                "LibraryReadingUnit",
                str(unit["id"]),
                {
                    "editionId": edition_id,
                    "volumeId": volume_id,
                    "sortOrder": chapter_sort_order,
                    "updatedAt": _now(),
                },
            )


def _audio_file_row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    path = Path(str(row.get("path") or ""))
    disc_number = row.get("discNumber")
    track_number = row.get("trackNumber")
    natural = tuple(
        int(part) if part.isdigit() else part.casefold()
        for segment in path.parts[-2:]
        for part in re.split(r"(\d+)", segment)
    )
    return (
        int(disc_number) if disc_number is not None else _audio_disc_number(path) or 1,
        int(track_number) if track_number is not None else _audio_episode_number(path) or 10**9,
        natural,
    )


def _merge_audio_raw_tags(
    db: Session,
    edition_id: str,
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = _row(
        db,
        "SELECT `rawJson` FROM `LibraryMetadata` WHERE `editionId` = :edition_id "
        "AND `source` = 'audio_tags' ORDER BY `updatedAt` DESC, `id` DESC LIMIT 1",
        {"edition_id": edition_id},
    )
    merged: dict[str, dict[str, Any]] = {}
    if existing:
        try:
            decoded = json.loads(str(existing.get("rawJson") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = []
        if isinstance(decoded, list):
            for item in decoded:
                if isinstance(item, dict) and item.get("sourcePath"):
                    merged[str(item["sourcePath"])] = item
    for item in incoming:
        if item.get("sourcePath"):
            merged[str(item["sourcePath"])] = item
    return [merged[key] for key in sorted(merged, key=str.casefold)]


def _audio_manifest_from_db(
    db: Session,
    edition_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = _rows(
        db,
        "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id AND UPPER(`kind`) = 'AUDIO' "
        "ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id},
    )
    chapters = _rows(
        db,
        "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND `unitType` = 'audio_chapter' "
        "ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id},
    )
    first_title_by_file: dict[str, str] = {}
    for chapter in chapters:
        file_id = str(chapter.get("fileId") or "")
        if file_id and file_id not in first_title_by_file:
            first_title_by_file[file_id] = str(chapter.get("title") or "")
    tracks = [
        {
            "fileId": file["id"],
            "title": first_title_by_file.get(str(file["id"])) or _title_from_file(Path(str(file["path"]))),
            "sourceFileName": Path(str(file["path"])).name,
            "mimeType": file.get("mimeType"),
            "durationMs": int(file.get("durationMs") or 0),
            "discNumber": file.get("discNumber"),
            "trackNumber": file.get("trackNumber"),
            "sortOrder": int(file.get("sortOrder") or 0),
        }
        for file in files
    ]
    manifest_chapters = [
        {
            "id": chapter["id"],
            "title": chapter.get("title"),
            "fileId": chapter.get("fileId"),
            "startMs": int(chapter.get("startMs") or 0),
            "endMs": int(chapter.get("endMs") or 0),
            "sortOrder": int(chapter.get("sortOrder") or 0),
        }
        for chapter in chapters
    ]
    return tracks, manifest_chapters


def _refresh_audio_progress_after_bundle_sync(db: Session, edition_id: str, volume_id: str) -> None:
    if not _has_table(db, "LibraryReadingProgress"):
        return
    files = _rows(
        db,
        "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id AND `volumeId` = :volume_id "
        "AND UPPER(`kind`) = 'AUDIO' ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id, "volume_id": volume_id},
    )
    if not files:
        return
    fingerprint_tokens = [
        {
            "id": file.get("id"),
            "hash": file.get("fingerprint") or file.get("fullHash"),
            "size": file.get("sizeBytes"),
            "mtime": file.get("mtimeMs"),
        }
        for file in files
    ]
    content_fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(fingerprint_tokens, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    offsets: dict[str, int] = {}
    elapsed = 0
    for file in files:
        offsets[str(file["id"])] = elapsed
        elapsed += max(0, int(file.get("durationMs") or 0))
    total_duration = elapsed

    progresses = _rows(
        db,
        "SELECT * FROM `LibraryReadingProgress` WHERE `editionId` = :edition_id",
        {"edition_id": edition_id},
    )
    for progress in progresses:
        try:
            location = json.loads(str(progress.get("locationJson") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            location = {}
        try:
            extra = json.loads(str(progress.get("extra") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            extra = {}
        location = location if isinstance(location, dict) else {}
        extra = extra if isinstance(extra, dict) else {}
        file_id = str(location.get("fileId") or extra.get("fileId") or "")
        try:
            position_ms = max(0, int(location.get("positionMs") or extra.get("positionMs") or progress.get("position") or 0))
        except (TypeError, ValueError):
            position_ms = 0
        values: dict[str, Any] = {
            "volumeId": volume_id,
            "contentFingerprint": content_fingerprint,
            "updatedAt": _now(),
        }
        if file_id in offsets:
            file_duration = max(0, int(next(file.get("durationMs") or 0 for file in files if str(file["id"]) == file_id)))
            absolute_position = offsets[file_id] + min(position_ms, file_duration)
            if total_duration > 0:
                calculated_percent = absolute_position / total_duration * 100
                values["percent"] = 100.0 if float(progress.get("percent") or 0) >= 100 else min(calculated_percent, 99.9999)
            location = {**location, "type": "audio", "volumeId": volume_id, "fileId": file_id, "positionMs": position_ms}
            extra = {**extra, "volumeId": volume_id, "fileId": file_id, "positionMs": position_ms}
            values["locationType"] = "audio"
            values["locationJson"] = json.dumps(location, ensure_ascii=False, separators=(",", ":"))
            values["extra"] = json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
        _update(db, "LibraryReadingProgress", str(progress["id"]), values)


def parse_epub_metadata(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        container = archive.read("META-INF/container.xml").decode("utf-8", "replace")
        match = re.search(r'full-path=["\']([^"\']+)["\']', container)
        if not match:
            raise ValueError("container.xml 缺少 rootfile full-path")
        opf_path = match.group(1)
        opf_xml = archive.read(opf_path).decode("utf-8", "replace")
        title = _first_text(opf_xml, "title") or _title_from_file(path)
        author = _first_text(opf_xml, "creator") or "未知作者"
        identifiers = _texts(opf_xml, "identifier")
        manifest = _opf_items(opf_xml)
        spine = _opf_itemrefs(opf_xml)
        chapters = _epub_chapters(archive, opf_path, opf_xml, manifest, spine)
        cover = _epub_cover(manifest, opf_xml)
        raw_metadata = {
            "opfPath": opf_path,
            "dc:title": _texts(opf_xml, "title"),
            "dc:creator": _texts(opf_xml, "creator"),
            "dc:identifier": identifiers,
            "dc:language": _texts(opf_xml, "language"),
            "dc:publisher": _texts(opf_xml, "publisher"),
            "dc:date": _texts(opf_xml, "date"),
            "dc:description": _texts(opf_xml, "description"),
            "dc:subject": _texts(opf_xml, "subject"),
            "meta": _attrs(opf_xml, "meta"),
        }
        return {
            "title": title,
            "author": author,
            "language": _first_text(opf_xml, "language"),
            "identifier": _preferred_identifier(identifiers),
            "isbn": _extract_isbn(identifiers),
            "publisher": _first_text(opf_xml, "publisher"),
            "publishedAt": _first_text(opf_xml, "date"),
            "description": _sanitize_description(_first_text(opf_xml, "description")),
            "subjects": _texts(opf_xml, "subject"),
            "coverPath": cover.get("href") if cover else None,
            "coverMediaType": cover.get("mediaType") if cover else None,
            "chapterCount": len(chapters),
            "chapters": chapters,
            "opfPath": opf_path,
            "rawMetadata": raw_metadata,
        }


def parse_comic_archive(path: Path, original_name: str | None = None) -> dict[str, Any]:
    fmt = "cbz" if path.suffix.lower() == ".cbz" else "zip"
    with zipfile.ZipFile(path) as archive:
        entries = [info for info in archive.infolist() if not info.is_dir() and _safe_entry_name(info.filename)]
        images = [info for info in entries if Path(info.filename).suffix.lower() in IMAGE_EXTS and not _ignored_entry(info.filename)]
        if not images:
            raise ValueError("漫画压缩包内没有可导入的图片")
        images.sort(key=lambda item: _natural_key(item.filename))
        comic_info_entry = next((info for info in entries if info.filename.lower().endswith("comicinfo.xml") and info.file_size <= MAX_COMIC_INFO_BYTES), None)
        comic_info = _parse_comic_info(archive.read(comic_info_entry).decode("utf-8", "replace")) if comic_info_entry else None
        pages = [{"index": index + 1, "title": f"第 {index + 1} 页", "entryPath": info.filename, "mediaType": mimetypes.guess_type(info.filename)[0] or "application/octet-stream", "size": info.file_size} for index, info in enumerate(images)]
        cover_index = (comic_info or {}).get("coverImageIndex")
        cover = pages[cover_index] if isinstance(cover_index, int) and 0 <= cover_index < len(pages) else next((page for page in pages if re.search(r"(cover|folder|front|封面)", Path(page["entryPath"]).name, re.I)), pages[0])
        image_formats = sorted({Path(page["entryPath"]).suffix.lower().lstrip(".") for page in pages})
        raw_metadata = {"hasComicInfo": comic_info is not None, "pageCount": len(pages), "imageFormats": image_formats, "coverEntryPath": cover["entryPath"]}
        if comic_info:
            raw_metadata["comicInfo"] = comic_info.get("raw") or {}
        return {"title": (comic_info or {}).get("title") or _title_from_file(Path(original_name or path.name)), "author": (comic_info or {}).get("writer") or (comic_info or {}).get("penciller") or "未知作者", "description": (comic_info or {}).get("summary"), "format": fmt, "pageCount": len(pages), "coverEntryPath": cover["entryPath"], "pages": pages, "comicInfo": comic_info, "rawMetadata": raw_metadata}


def parse_pdf_metadata(path: Path, original_name: str | None = None) -> dict[str, Any]:
    title = _title_from_file(Path(original_name or path.name))
    author = "未知作者"
    page_count = 1
    raw_metadata: dict[str, Any] = {"sourceFileName": original_name or path.name}
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page_count = max(1, len(pdf))
            doc_info = pdf.get_metadata_dict()
            raw_metadata.update(doc_info or {})
            title = str(doc_info.get("Title") or title).strip() or title
            author = str(doc_info.get("Author") or author).strip() or author
        finally:
            pdf.close()
    except Exception as exc:
        raw_metadata["parseWarning"] = str(exc)
        page_count = max(1, _fallback_pdf_page_count(path))
    raw_metadata.update(_pdf_inline_metadata(path))
    title = str(raw_metadata.get("Title") or title).strip() or title
    author = str(raw_metadata.get("Author") or author).strip() or author
    description = _sanitize_description(str(raw_metadata.get("Subject") or "").strip())
    tags = _split_tags(str(raw_metadata.get("Keywords") or ""))
    return {"title": title, "author": author, "description": description, "tags": tags, "pageCount": page_count, "rawMetadata": raw_metadata}


def _pdf_inline_metadata(path: Path) -> dict[str, str]:
    try:
        content = path.read_bytes()
    except OSError:
        return {}
    metadata: dict[str, str] = {}
    for key in ["Title", "Author", "Subject", "Keywords"]:
        match = re.search(rb"/" + key.encode("ascii") + rb"\s*\(([^()]*)\)", content, re.S)
        if not match:
            continue
        value = _decode_pdf_literal(match.group(1))
        if value:
            metadata[key] = value
    return metadata


def _decode_pdf_literal(value: bytes) -> str:
    text = value.decode("utf-8", "replace")
    replacements = {
        r"\(": "(",
        r"\)": ")",
        r"\\": "\\",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
        r"\b": "\b",
        r"\f": "\f",
    }
    for escaped, replacement in replacements.items():
        text = text.replace(escaped, replacement)
    return text.strip()


def _fallback_pdf_page_count(path: Path) -> int:
    try:
        content = path.read_bytes()
    except OSError:
        return 1
    matches = re.findall(rb"/Type\s*/Page\b", content)
    return len(matches) or 1


def parse_comic_volume_from_name(path: Path, original_name: str | None = None) -> dict[str, Any] | None:
    source = original_name or path.name
    base = Path(source).stem
    parent = _comic_parent_title(path, "WATCH")
    for pattern in [r"^(?:vol\.?|volume)\s*(\d+(?:\.\d+)?)$", r"^v\s*(\d+(?:\.\d+)?)$", r"^(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$"]:
        match = re.match(pattern, base.strip(), re.I)
        if match and parent:
            index = float(match.group(1))
            author = _comic_parent_author(path)
            result = {"seriesName": parent, "seriesIndex": index, "title": f"{parent} ({index:g})"}
            if author:
                result["author"] = author
            return result
    for pattern in [r"^(.+?)\s*[\(（［\[]\s*(\d+(?:\.\d+)?)\s*[\)）］\]]\s*$", r"^(.+?)\s*(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)\s*$", r"^(.+?)\s*(?:vol\.?|volume)\s*(\d+(?:\.\d+)?)\s*$", r"^(.+?)\s+v(\d+(?:\.\d+)?)\s*$"]:
        match = re.match(pattern, base, re.I)
        if match:
            series = _clean_title_part(match.group(1))
            index = float(match.group(2))
            if series:
                return {"seriesName": series, "seriesIndex": index, "title": f"{series} ({index:g})"}
    return None


def parse_series_volume_info(path: Path, original_name: str | None = None, origin: str = "WATCH") -> SeriesVolumeInfo | None:
    source = original_name or path.name
    base = _clean_title_part(Path(source).stem)
    folder = _series_folder_metadata(path.parent.name, source) if origin == "WATCH" else None
    folder_title = (folder or {}).get("title")
    author = (folder or {}).get("author")
    if folder_title:
        suffix = base
        title_key = _normalize_key(folder_title)
        base_key = _normalize_key(base)
        if base_key.startswith(title_key):
            suffix = base[len(folder_title) :].strip()
        volume_index = _volume_index_from_suffix(suffix)
        if volume_index is not None:
            return SeriesVolumeInfo(series_name=folder_title, series_index=volume_index, title=f"第 {volume_index:g} 卷", author=author)
    for pattern in [
        r"^(.+?)\s*(?:vol\.?|volume)\s*(\d+(?:\.\d+)?)$",
        r"^(.+?)\s*(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"^(.+?)\s+(\d+(?:\.\d+)?)$",
    ]:
        match = re.match(pattern, base, re.I)
        if match:
            series = _clean_title_part(match.group(1))
            index = float(match.group(2))
            if series:
                return SeriesVolumeInfo(series_name=series, series_index=index, title=f"第 {index:g} 卷", author=author)
    return None


def parse_comic_volume_info(parsed: dict[str, Any], path: Path, original_name: str | None = None) -> dict[str, Any] | None:
    comic_info = parsed.get("comicInfo") if isinstance(parsed.get("comicInfo"), dict) else {}
    if comic_info.get("series") and comic_info.get("volume") is not None:
        return {
            "seriesName": comic_info["series"],
            "seriesIndex": comic_info["volume"],
            "title": f"{comic_info['series']} ({comic_info['volume']:g})",
        }
    return parse_comic_volume_from_name(path, original_name)


def _ensure_import_task(db: Session, options: ImportOptions) -> str:
    existing = _row(
        db,
        "SELECT `id` FROM `ImportTask` WHERE `sourcePath` = :source_path AND `status` = 'PENDING' "
        "ORDER BY CAST(`createdAt` AS INTEGER) ASC, `id` ASC LIMIT 1",
        {"source_path": str(options.source_file_path)},
    )
    if existing:
        return existing["id"]
    row = _insert(
        db,
        "ImportTask",
        {
            "id": _id(),
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "status": "PENDING",
            "originalName": options.original_name or options.source_file_path.name,
            "requestedTitle": options.requested_title,
            "requestedAuthor": options.requested_author,
            "sourcePath": str(options.source_file_path),
            "progress": 0,
            "duplicate": False,
            "duration": 0,
            "message": "等待导入",
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    return row["id"]


def _existing_series_volume_identity(db: Session, settings: Settings, options: ImportOptions) -> BookIdentity | None:
    if not all(_has_table(db, table) for table in ["LibraryWork", "LibraryEdition", "LibraryFile"]):
        return None
    source_path = (options.original_source_file_path or options.source_file_path).resolve()
    folder_metadata = _series_folder_metadata(source_path.parent.name, options.original_name or source_path.name)
    volume_info = parse_series_volume_info(source_path, options.original_name, "WATCH")
    if volume_info is None or volume_info.series_index is None:
        return None
    folder_title_matches = bool(
        folder_metadata and _normalize_key(volume_info.series_name) == _normalize_key(folder_metadata.get("title"))
    )
    filename_series_fallback = bool(
        not folder_metadata
        and len(re.findall(r"\[([^\]]+)\]", source_path.parent.name)) >= 2
        and _is_exact_bracket_sequence(source_path.parent.name)
    )
    if not folder_title_matches and not filename_series_fallback:
        return None

    source_group_suffix = f":{_hash_text(str(source_path.parent))[:24]}"
    works = _rows(
        db,
        """
        SELECT DISTINCT w.`id`, w.`title`, w.`author`
        FROM `LibraryEdition` e
        JOIN `LibraryWork` w ON w.`id` = e.`workId`
        WHERE e.`sourceGroupKey` LIKE :source_group_suffix
          AND e.`hidden` = 0
          AND w.`hidden` = 0
        ORDER BY w.`createdAt` ASC, w.`id` ASC
        """,
        {"source_group_suffix": f"%{source_group_suffix}"},
    )
    if folder_title_matches:
        candidates = works
    else:
        candidates = [
            work
            for work in works
            if _work_has_matching_source_series(db, str(work["id"]), source_group_suffix, volume_info.series_name)
        ]
    if len(candidates) != 1:
        return None
    work = candidates[0]
    logical_path = logical_import_path(db, settings, source_path, options.original_name)
    return BookIdentity(
        title=str(work.get("title") or (folder_metadata or {}).get("title") or volume_info.series_name),
        author=str(work.get("author") or UNKNOWN_AUTHOR),
        volume_index=volume_info.series_index,
        source="existing_work",
        confidence=1.0,
        logical_path=logical_path,
        reused_work_id=str(work["id"]),
    )


def _work_has_matching_source_series(db: Session, work_id: str, source_group_suffix: str, series_name: str) -> bool:
    files = _rows(
        db,
        """
        SELECT f.`path`
        FROM `LibraryFile` f
        JOIN `LibraryEdition` e ON e.`id` = f.`editionId`
        WHERE e.`workId` = :work_id
          AND e.`sourceGroupKey` LIKE :source_group_suffix
        ORDER BY f.`createdAt` ASC
        """,
        {"work_id": work_id, "source_group_suffix": f"%{source_group_suffix}"},
    )
    expected = _normalize_key(series_name)
    for file in files:
        existing_path = Path(str(file.get("path") or ""))
        existing = parse_series_volume_info(existing_path, existing_path.name, "WATCH")
        if existing is not None and _normalize_key(existing.series_name) == expected:
            return True
    return False


def _existing_file_result(db: Session, path: Path) -> ImportResult | None:
    if not all(_has_table(db, table) for table in ["LibraryFile", "LibraryEdition", "LibraryWork"]):
        return None
    existing = _row(
        db,
        """
        SELECT
            f.`volumeId`, e.`id` AS `editionId`, e.`format`, e.`pageCount`, e.`chapterCount`,
            w.`id` AS `workId`, w.`title`, w.`workType`
        FROM `LibraryFile` f
        JOIN `LibraryEdition` e ON e.`id` = f.`editionId`
        JOIN `LibraryWork` w ON w.`id` = e.`workId`
        WHERE f.`path` = :path
        LIMIT 1
        """,
        {"path": str(path.resolve())},
    )
    if not existing:
        return None
    file_format = str(existing.get("format") or "").lower()
    total_units = int(existing.get("pageCount") or existing.get("chapterCount") or 0)
    result_type = "comic" if file_format == "comic" else "audiobook" if file_format == "audio" else "ebook"
    return ImportResult(
        str(existing["workId"]),
        str(existing["workId"]),
        str(existing["editionId"]),
        str(existing["volumeId"]) if existing.get("volumeId") else None,
        str(existing.get("title") or "未命名作品"),
        result_type,
        file_format,
        total_units,
        "completed",
        True,
        True,
        "duplicate-file-path",
    )


def _existing_audio_bundle_result(db: Session, paths: list[Path]) -> ImportResult | None:
    if not paths or not all(_has_table(db, table) for table in ["LibraryFile", "LibraryEdition", "LibraryWork"]):
        return None
    params = {f"path_{index}": str(path.resolve()) for index, path in enumerate(paths)}
    placeholders = ", ".join(f":path_{index}" for index in range(len(paths)))
    rows = _rows(
        db,
        f"SELECT `path`, `editionId` FROM `LibraryFile` WHERE `path` IN ({placeholders})",
        params,
    )
    if len(rows) != len(paths) or len({row.get("editionId") for row in rows}) != 1:
        return None
    return _existing_file_result(db, paths[0])


def _audio_content_duplicate_result(
    db: Session,
    content_info: list[dict[str, Any]],
) -> tuple[ImportResult | None, list[dict[str, Any]]]:
    """Resolve byte-identical audio moved to a new path without full scans of unrelated files."""

    if not content_info or not _has_table(db, "LibraryFile"):
        return None, []

    # Sample collisions inside the pending bundle are the only reason to hash
    # brand-new tracks eagerly. Exact duplicates are rejected; different full
    # hashes are valid tracks that happened to share the bounded sample.
    pending_by_sample: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for info in content_info:
        signature = (int(info["size"]), str(info["fingerprint"]))
        pending_by_sample.setdefault(signature, []).append(info)
    for group in pending_by_sample.values():
        if len(group) < 2:
            continue
        full_hashes = [_audio_info_full_hash(info) for info in group]
        if len(set(full_hashes)) != len(full_hashes):
            raise ValueError("有声书目录中包含字节完全相同的重复音轨，请移除后重试")

    matches: list[dict[str, Any] | None] = []
    for info in content_info:
        candidates = _rows(
            db,
            "SELECT * FROM `LibraryFile` WHERE `sizeBytes` = :size AND `fingerprint` = :fingerprint "
            "AND UPPER(`kind`) = 'AUDIO' ORDER BY `createdAt`, `id`",
            {"size": info["size"], "fingerprint": info["fingerprint"]},
        )
        if not candidates:
            matches.append(None)
            continue
        current_hash = _audio_info_full_hash(info)
        matched = None
        for candidate in candidates:
            candidate_hash = str(candidate.get("fullHash") or "")
            if not candidate_hash:
                candidate_path = Path(str(candidate.get("path") or ""))
                if not candidate_path.is_file():
                    continue
                try:
                    candidate_hash = _content_hash(candidate_path)
                except OSError:
                    continue
                _update(
                    db,
                    "LibraryFile",
                    str(candidate["id"]),
                    {"fullHash": candidate_hash, "hashStatus": "COMPLETED", "updatedAt": _now()},
                )
            if candidate_hash == current_hash:
                matched = candidate
                break
        matches.append(matched)

    matched_files = [item for item in matches if item is not None]
    if not matched_files:
        return None, []
    if len(matched_files) != len(content_info):
        raise ValueError("有声书目录中部分音轨与书库内容重复，请移除重复音轨后重试")
    edition_ids = {str(item.get("editionId")) for item in matched_files}
    if len(edition_ids) != 1:
        raise ValueError("有声书目录中的音轨已分散存在于多个版本，请拆分目录后重试")
    edition_id = next(iter(edition_ids))
    existing_count = int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM `LibraryFile` WHERE `editionId` = :edition_id AND UPPER(`kind`) = 'AUDIO'",
            {"edition_id": edition_id},
            0,
        )
    )
    if existing_count != len(matched_files):
        raise ValueError("有声书目录只匹配现有版本的部分音轨，请确认目录内容后重试")
    result = _existing_file_result(db, Path(str(matched_files[0]["path"])))
    return result, matched_files if result else []


def _audio_info_full_hash(info: dict[str, Any]) -> str:
    existing = str(info.get("fullHash") or "")
    if existing:
        return existing
    item = info.get("item")
    if not isinstance(item, AudioFileMetadata):
        raise ValueError("有声书音轨缺少可计算哈希的文件信息")
    calculated = _content_hash(item.path)
    info["fullHash"] = calculated
    return calculated


def _audio_identity(
    db: Session,
    settings: Settings,
    source: Path,
    options: ImportOptions,
    metadata_items: list[AudioFileMetadata],
) -> BookIdentity:
    requested_title = re.sub(r"\s+", " ", str(options.requested_title or "")).strip()
    requested_author = re.sub(r"\s+", " ", str(options.requested_author or "")).strip()
    fallback = recognize_book_identity(db, settings, source, options.original_name)
    fallback_title = _clean_audio_work_title(fallback.title)
    directory_bundle = source.is_dir()
    flat_title = _flat_audio_filename_title(source) if source.is_file() else None
    directory_author = _emby_audio_directory_author(db, settings, source, options) if directory_bundle else None
    albums = [] if requested_title or directory_bundle else _consistent_audio_values(metadata_items, "album", "专辑/书名")
    authors = [] if requested_author else _consistent_audio_values(
        metadata_items,
        "author",
        "作者",
        strict=not directory_bundle,
    )
    if requested_title:
        title = requested_title
    elif directory_bundle:
        title = fallback_title
    elif albums:
        title = albums[0]
    elif flat_title:
        title = flat_title
    elif len(metadata_items) == 1 and metadata_items[0].title:
        title = _clean_audio_work_title(metadata_items[0].title)
    else:
        title = fallback_title
    if requested_author:
        author = requested_author
    elif directory_bundle and fallback.author != UNKNOWN_AUTHOR:
        author = fallback.author
    elif authors:
        author = authors[0]
    elif directory_author:
        author = directory_author
    elif flat_title:
        # The documented flat layout encodes book title and chapter, not an
        # author. Do not let the generic filename parser reinterpret the
        # trailing chapter label as an author.
        author = UNKNOWN_AUTHOR
    else:
        author = fallback.author
    return replace(
        fallback,
        title=str(title).strip() or fallback.title,
        author=str(author).strip() or UNKNOWN_AUTHOR,
        confidence=max(fallback.confidence, 0.95 if albums or authors else fallback.confidence),
        cache_hit=False,
    )


def _clean_audio_work_title(value: Any) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = re.sub(r"(?:[ ._-]*有声书)$", "", title, flags=re.I).strip()
    title = re.sub(r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:track\s*)?\d+[ ._-]*", "", title, flags=re.I).strip()
    return title or "未命名有声书"


_FLAT_AUDIO_FILENAME_PATTERN = re.compile(
    r"^\s*0*\d{1,6}\s*[-–—_.]+\s*(?P<title>.+?)\s*[-–—_]+\s*"
    r"(?:(?:chapter|chap|ch|track|part|episode|ep)\s*0*\d{1,6}\b|\u7b2c?\s*0*\d{1,6}\s*[章回集节]).*$",
    re.I,
)


def _flat_audio_filename_title(path: Path) -> str | None:
    if not path.is_file() or not is_supported_audio_file(path):
        return None
    match = _FLAT_AUDIO_FILENAME_PATTERN.match(path.stem)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group("title")).strip(" ._-–—")
    return _clean_audio_work_title(title) if title else None


def _flat_audio_bundle_key(path: Path, title: str) -> str:
    source_group = f"{path.parent.resolve()}\0{_normalize_key(title)}"
    return _hash_text(source_group)[:24]


def _emby_audio_directory_author(
    db: Session,
    settings: Settings,
    source: Path,
    options: ImportOptions,
) -> str | None:
    """Infer Author from the documented ``Author/Book`` directory layout.

    Inference only happens relative to a configured monitor root and only for
    exactly two path components. This prevents arbitrary parent directories
    (for example ``media`` or a download destination) from becoming authors.
    """

    roots: list[Path] = []
    if _has_table(db, "MonitorFolder"):
        if options.monitor_folder_id:
            row = _row(
                db,
                "SELECT `rootPath` FROM `MonitorFolder` WHERE `id` = :id LIMIT 1",
                {"id": options.monitor_folder_id},
            )
            if row and row.get("rootPath"):
                roots.append(Path(str(row["rootPath"])).expanduser().resolve())
        else:
            for value in db.execute(
                text("SELECT `rootPath` FROM `MonitorFolder` WHERE `enabled` = 1 AND `rootPath` IS NOT NULL")
            ).scalars():
                try:
                    roots.append(Path(str(value)).expanduser().resolve())
                except OSError:
                    continue
    if settings.resolved_monitor_root is not None:
        roots.append(settings.resolved_monitor_root.resolve())
    matching = [root for root in roots if source == root or root in source.parents]
    if not matching:
        return None
    root = max(matching, key=lambda item: len(item.parts))
    try:
        relative = source.relative_to(root)
    except ValueError:
        return None
    if len(relative.parts) != 2:
        return None
    author = re.sub(r"\s+", " ", relative.parts[0]).strip()
    generic = {
        _normalize_key(value)
        for value in ["audiobook", "audiobooks", "audio books", "books", "library", "media", "有声书", "听书"]
    }
    return author if author and _normalize_key(author) not in generic else None


def _consistent_audio_values(
    metadata_items: list[AudioFileMetadata],
    field: str,
    label: str,
    *,
    strict: bool = True,
) -> list[str]:
    values: list[str] = []
    normalized: dict[str, str] = {}
    for item in metadata_items:
        value = getattr(item, field, None)
        if not value:
            continue
        key = _normalize_key(value)
        if key and key not in normalized:
            normalized[key] = str(value).strip()
            values.append(str(value).strip())
    if len(values) > 1:
        if not strict:
            return []
        preview = "、".join(values[:3])
        raise ValueError(f"有声书目录中的{label}不一致（{preview}），请拆分目录或修正音频标签后重试")
    return values


def _effective_audio_track_numbers(metadata_items: list[AudioFileMetadata]) -> dict[Path, int | None]:
    by_disc: dict[int, list[AudioFileMetadata]] = {}
    for item in metadata_items:
        disc_number = item.disc_number if item.disc_number is not None else _audio_disc_number(item.path) or 1
        by_disc.setdefault(disc_number, []).append(item)
    result: dict[Path, int | None] = {}
    for items in by_disc.values():
        embedded = [item.track_number for item in items]
        tags_are_complete_and_unique = (
            all(value is not None for value in embedded)
            and len(set(embedded)) == len(embedded)
        )
        for item in items:
            result[item.path] = (
                item.track_number
                if tags_are_complete_and_unique
                else _audio_episode_number(item.path) or item.track_number
            )
    return result


def _audio_metadata_sort_key(
    item: AudioFileMetadata,
    effective_track_number: int | None = None,
) -> tuple[Any, ...]:
    natural = tuple(
        int(part) if part.isdigit() else part.casefold()
        for segment in item.path.parts[-2:]
        for part in re.split(r"(\d+)", segment)
    )
    return (
        item.disc_number if item.disc_number is not None else _audio_disc_number(item.path) or 1,
        effective_track_number if effective_track_number is not None else 10**9,
        natural,
    )


def _audio_episode_number(path: Path) -> int | None:
    stem = path.stem
    explicit = re.search(r"第\s*0*(\d{1,6})\s*[集章回节]", stem, re.I)
    if explicit:
        return int(explicit.group(1))
    prefixed = re.match(
        r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:(?:track|chapter|chap|ch)\s*)?[\[(]?0*(\d{1,6})[\])]?(?:\s*[集章回节])?(?:[ ._-]+|$)",
        stem,
        re.I,
    )
    return int(prefixed.group(1)) if prefixed else None


def _audio_disc_number(path: Path) -> int | None:
    parent_name = path.parent.name.strip()
    if not DISC_DIRECTORY_PATTERN.match(parent_name):
        return None
    matched = re.search(r"\d{1,6}", parent_name)
    return int(matched.group()) if matched else None


def _audio_track_titles(metadata_items: list[AudioFileMetadata]) -> dict[Path, str]:
    embedded_counts: dict[str, int] = {}
    for item in metadata_items:
        embedded = re.sub(r"\s+", " ", str(item.title or "")).strip()
        if embedded:
            key = _normalize_key(embedded)
            embedded_counts[key] = embedded_counts.get(key, 0) + 1
    generic = {_normalize_key(value) for value in ["正文", "audio", "track", "chapter", "音频", "未命名"]}
    titles: dict[Path, str] = {}
    for item in metadata_items:
        embedded = re.sub(r"\s+", " ", str(item.title or "")).strip()
        key = _normalize_key(embedded)
        titles[item.path] = (
            _title_from_file(item.path)
            if not embedded or key in generic or embedded_counts.get(key, 0) > 1
            else embedded
        )
    return titles


def _sample_fingerprint(path: Path, sample_bytes: int = 1024 * 1024) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(sample_bytes))
        if stat.st_size > sample_bytes:
            handle.seek(max(0, stat.st_size - sample_bytes))
            digest.update(handle.read(sample_bytes))
    return f"sample-sha256:{digest.hexdigest()}"


def _extract_audio_cover(
    settings: Settings,
    work_id: str,
    edition_id: str,
    metadata_items: list[AudioFileMetadata],
    *,
    bundle_root: Path | None = None,
) -> str | None:
    selected = next((item for item in metadata_items if item.cover_data), None)
    if selected and selected.cover_data:
        validated = _validated_audio_cover(selected.cover_data)
        if validated:
            cover_data, extension = validated
            target = settings.resolved_storage_root / "books" / work_id / edition_id / f"cover{extension}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(cover_data)
            return str(target)
    source_root = bundle_root or metadata_items[0].path.parent
    cover_names = ["folder", "poster", "cover", "default", "front", "封面"]
    cover_priorities = {name: index for index, name in enumerate(cover_names)}
    candidates = [
        item
        for item in source_root.iterdir()
        if item.is_file()
        and item.suffix.lower() in {*IMAGE_EXTS, ".tbn"}
        and (
            item.stem.casefold() in cover_priorities
            or re.search(r"^(?:cover|folder|front|封面)", item.stem, re.I)
        )
    ]
    for source in sorted(
        candidates,
        key=lambda item: (cover_priorities.get(item.stem.casefold(), len(cover_names)), item.name.casefold()),
    ):
        try:
            if source.stat().st_size > MAX_AUDIO_COVER_BYTES:
                continue
            validated = _validated_audio_cover(source.read_bytes())
        except OSError:
            continue
        if not validated:
            continue
        cover_data, extension = validated
        target = settings.resolved_storage_root / "books" / work_id / edition_id / f"cover{extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cover_data)
        return str(target)
    return None


def _validated_audio_cover(data: bytes) -> tuple[bytes, str] | None:
    if not data or len(data) > MAX_AUDIO_COVER_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            if image_format not in AUDIO_COVER_FORMATS or width <= 0 or height <= 0:
                return None
            if width * height > MAX_AUDIO_COVER_PIXELS:
                return None
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    return data, AUDIO_COVER_FORMATS[image_format]


def _insert_identity_metadata(db: Session, edition_id: str, identity: BookIdentity) -> None:
    _insert(
        db,
        "LibraryMetadata",
        {
            "id": _id(),
            "editionId": edition_id,
            "source": f"identity_{identity.source}",
            "rawJson": json.dumps(identity.raw_metadata(), ensure_ascii=False),
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )


def _enqueue_metadata_lookup(
    db: Session,
    work_id: str,
    edition_id: str,
    import_task_id: str,
    organize_job_id: str,
    file_format: str,
) -> None:
    if not _has_table(db, "MetadataLookupTask"):
        return
    provider_order = ["bangumi", "douban"] if file_format.lower() in {"comic", "cbz", "zip"} else ["douban", "bangumi"]
    existing = _row(db, "SELECT `id` FROM `MetadataLookupTask` WHERE `importTaskId` = :task_id", {"task_id": import_task_id})
    values = {
        "workId": work_id,
        "editionId": edition_id,
        "organizeJobId": organize_job_id,
        "status": "PENDING",
        "providerOrder": json.dumps(provider_order, ensure_ascii=False),
        "attempts": 0,
        "nextAttemptAt": _now(),
        "resultSource": None,
        "candidateRawJson": None,
        "appliedFields": None,
        "errorSummary": None,
        "startedAt": None,
        "finishedAt": None,
        "updatedAt": _now(),
    }
    if existing:
        _update(db, "MetadataLookupTask", str(existing["id"]), values)
        return
    _insert(
        db,
        "MetadataLookupTask",
        {
            "id": _id(),
            "importTaskId": import_task_id,
            "createdAt": _now(),
            **values,
        },
    )


def _ensure_work(db: Session, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if data.get("workId"):
        existing_by_id = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": data["workId"]})
        if existing_by_id:
            _update(db, "LibraryWork", existing_by_id["id"], {"hidden": False, "updatedAt": _now()})
            return _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": existing_by_id["id"]}) or existing_by_id, False
    existing = _row(db, "SELECT * FROM `LibraryWork` WHERE `mergeKey` = :merge_key", {"merge_key": data["mergeKey"]})
    if existing:
        _update(db, "LibraryWork", existing["id"], {"hidden": False, "updatedAt": _now()})
        return _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": existing["id"]}) or existing, False
    row = _insert(db, "LibraryWork", {"id": _id(), "monitorFolderId": data.get("monitorFolderId"), "origin": data["origin"], "title": data["title"], "normalizedTitle": _normalize_key(data["title"]), "author": data["author"], "normalizedAuthor": _normalize_key(data["author"]), "description": data.get("description"), "workType": data["workType"], "status": "UNREAD", "publicationStatus": "UNKNOWN", "trackingStatus": "NOT_TRACKING", "tags": json.dumps(data["tags"], ensure_ascii=False), "metadataQuality": 0, "organizeStatus": "UNASSESSED", "coverStatus": "PENDING", "hidden": False, "organized": False, "mergeKey": data["mergeKey"], "createdAt": _now(), "updatedAt": _now()})
    return row, True


def _create_or_refresh_organize_job(db: Session, work_id: str, edition_id: str, task_id: str) -> str:
    existing = _row(db, "SELECT * FROM `OrganizeJob` WHERE `workId` = :work_id AND `editionId` = :edition_id", {"work_id": work_id, "edition_id": edition_id})
    if existing:
        _update(db, "OrganizeJob", existing["id"], {"status": "LOOKUP_PENDING", "summary": "等待豆瓣/Bangumi 元数据匹配", "errorSummary": None, "updatedAt": _now()})
        return str(existing["id"])
    job = _insert(db, "OrganizeJob", {"id": _id(), "workId": work_id, "editionId": edition_id, "importTaskId": task_id, "status": "LOOKUP_PENDING", "issueCodes": "[]", "summary": "等待豆瓣/Bangumi 元数据匹配", "createdAt": _now(), "updatedAt": _now()})
    return str(job["id"])


def _insert(db: Session, table: str, values: dict[str, Any]) -> dict[str, Any]:
    columns = _columns(db, table)
    filtered = {key: value for key, value in values.items() if key in columns}
    keys = ", ".join(f"`{key}`" for key in filtered)
    params = ", ".join(f":{key}" for key in filtered)
    db.execute(text(f"INSERT INTO `{table}` ({keys}) VALUES ({params})"), filtered)
    return _row(db, f"SELECT * FROM `{table}` WHERE `id` = :id", {"id": filtered["id"]}) or filtered


def _update(db: Session, table: str, row_id: str, values: dict[str, Any]) -> None:
    columns = _columns(db, table)
    filtered = {key: value for key, value in values.items() if key in columns}
    if not filtered:
        return
    filtered["row_id"] = row_id
    assignments = ", ".join(f"`{key}` = :{key}" for key in filtered if key != "row_id")
    db.execute(text(f"UPDATE `{table}` SET {assignments} WHERE `id` = :row_id"), filtered)


def _row(db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = db.execute(text(sql), params or {}).mappings().first()
    return dict(result) if result else None


def _scalar(db: Session, sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    value = db.execute(text(sql), params or {}).scalar()
    return default if value is None else value


def _table_count(db: Session, table: str, where: str = "", params: dict[str, Any] | None = None) -> int:
    suffix = f" WHERE {where}" if where else ""
    return int(_scalar(db, f"SELECT COUNT(*) FROM `{table}`{suffix}", params, 0))


def _columns(db: Session, table: str) -> set[str]:
    # Keep schema introspection on the Session connection.  With SQLite an
    # Inspector created from the Engine can check the same pooled DB-API
    # connection back in and roll back the import transaction underneath us.
    return {column["name"] for column in inspect(db.connection()).get_columns(table)}


def _has_table(db: Session, table: str) -> bool:
    return table in inspect(db.connection()).get_table_names()


def _id() -> str:
    return f"py_{time.time_ns()}"


def _now() -> int:
    return now_timestamp_ms()


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _log_import(db: Session, task_id: str | None, level: str, message: str) -> None:
    if task_id and "ImportLog" in inspect(db.connection()).get_table_names():
        _insert(db, "ImportLog", {"id": _id(), "importTaskId": task_id, "level": level, "message": message, "createdAt": _now()})


def _record_identity_system_events(db: Session, task_id: str, identity: BookIdentity, source_path: Path) -> None:
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
        record_system_event(
            db,
            source="import",
            action="identity.existing_work.reused",
            target_type="importTask",
            target_id=task_id,
            message=f"识别为现有作品的新卷册：{source_path.name} → 《{identity.title}》第 {identity.volume_index:g} 卷",
            metadata=metadata,
        )
        return
    if identity.cache_hit:
        record_system_event(
            db,
            source="import",
            action="identity.cache.hit",
            target_type="importTask",
            target_id=task_id,
            message=f"应用路径识别缓存：{source_path.name} → 《{identity.title}》 / {identity.author}",
            metadata=metadata,
        )
        return
    if identity.fallback_reason:
        ai_failed = identity.fallback_reason.startswith("AI identity recognition failed:")
        record_system_event(
            db,
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
        )
    method_label = "AI" if identity.source == "ai" else "正则匹配"
    record_system_event(
        db,
        source="import",
        action=f"identity.{identity.source}.completed",
        target_type="importTask",
        target_id=task_id,
        message=f"{method_label}识别文件信息：{source_path.name} → 《{identity.title}》 / {identity.author}",
        metadata=metadata,
    )


def _normalize_key(value: Any) -> str:
    return normalize_identity_part(value)


def _work_merge_key(fmt: str, title: str, author: str | None = None, identifier: str | None = None, isbn: str | None = None) -> str:
    return identity_merge_key(title, author)


def _usable_merge_identifier(identifier: str | None) -> bool:
    if not identifier:
        return False
    value = str(identifier).strip().lower()
    return not (value.startswith("urn:uuid:") or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value))


def _source_group_key(options: ImportOptions, _fallback_title: str) -> str:
    source_directory = str((options.original_source_file_path or options.source_file_path).resolve().parent)
    return f"{options.origin.lower()}:{_hash_text(source_directory)[:24]}"


def _file_version_key(fmt: str, path: Path) -> str:
    return f"{fmt}:{_hash_text(str(path.resolve()))[:24]}"


def _next_edition_name(db: Session, work_id: str, base: str, media_kind: str | None = None) -> str:
    where = "`workId` = :work_id"
    params = {"work_id": work_id}
    if media_kind and "mediaKind" in _columns(db, "LibraryEdition"):
        where += " AND `mediaKind` = :media_kind"
        params["media_kind"] = media_kind
    count = _table_count(db, "LibraryEdition", where, params)
    return base if count == 0 else f"{base} {count + 1}"


def _should_be_media_primary(db: Session, work_id: str, media_kind: str) -> bool:
    edition_columns = _columns(db, "LibraryEdition")
    if "mediaKind" not in edition_columns:
        return _table_count(db, "LibraryEdition", "`workId` = :work_id", {"work_id": work_id}) == 0
    existing = _scalar(
        db,
        "SELECT COUNT(*) FROM `LibraryEdition` WHERE `workId` = :work_id AND `mediaKind` = :media_kind AND COALESCE(`hidden`, 0) = 0",
        {"work_id": work_id, "media_kind": media_kind},
        0,
    )
    return int(existing or 0) == 0


def _finalize_work_primary(db: Session, settings: Settings, work_id: str, edition_id: str, cover_path: str | None) -> None:
    work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": work_id})
    if not work:
        return
    primary_edition_id = work.get("primaryEditionId") or edition_id
    primary_edition = _row(db, "SELECT `format` FROM `LibraryEdition` WHERE `id` = :id", {"id": primary_edition_id})
    preferred_cover_path = _preferred_work_cover_path(db, work_id, primary_edition_id, settings) or cover_path or ensure_default_cover(settings)
    current_cover_path = work.get("coverPath")
    should_update_cover = not current_cover_path or _is_generated_work_cover_path(db, work_id, str(current_cover_path))
    _update(
        db,
        "LibraryWork",
        work_id,
        {
            "primaryEditionId": primary_edition_id,
            "workType": (primary_edition or {}).get("format") or work.get("workType"),
            "coverPath": preferred_cover_path if should_update_cover else current_cover_path,
            "coverStatus": cover_status(preferred_cover_path if should_update_cover else current_cover_path, settings),
            "updatedAt": _now(),
        },
    )


def _preferred_work_cover_path(db: Session, work_id: str, primary_edition_id: str | None, settings: Settings) -> str | None:
    if primary_edition_id:
        volumes = _rows(
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
            """,
            {"edition_id": primary_edition_id},
        )
        volume = next((item for item in volumes if not is_default_cover_path(item.get("coverPath"), settings)), volumes[0] if volumes else None)
        if volume and volume.get("coverPath"):
            return str(volume["coverPath"])
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
    )
    return str(edition["coverPath"]) if edition and edition.get("coverPath") else None


def _is_generated_work_cover_path(db: Session, work_id: str, cover_path: str) -> bool:
    generated = _row(
        db,
        """
        SELECT `coverPath` FROM `LibraryEdition` WHERE `workId` = :work_id AND `coverPath` = :cover_path
        UNION
        SELECT v.`coverPath`
        FROM `LibraryVolume` v
        JOIN `LibraryEdition` e ON e.`id` = v.`editionId`
        WHERE e.`workId` = :work_id AND v.`coverPath` = :cover_path
        LIMIT 1
        """,
        {"work_id": work_id, "cover_path": cover_path},
    )
    return generated is not None


def _select_volume_edition(db: Session, work_id: str, fmt: str, source_key: str, volume_index: float | None, volume_title: str) -> dict[str, Any] | None:
    editions = _rows(db, "SELECT * FROM `LibraryEdition` WHERE `workId` = :work_id AND `format` = :fmt AND `hidden` = 0 ORDER BY `createdAt` ASC", {"work_id": work_id, "fmt": fmt})
    for edition in editions:
        conflict = _row(
            db,
            """
            SELECT * FROM `LibraryVolume`
            WHERE `editionId` = :edition_id
              AND ((:volume_index IS NOT NULL AND `volumeIndex` = :volume_index)
                   OR (:volume_index IS NULL AND `title` = :volume_title))
            LIMIT 1
            """,
            {"edition_id": edition["id"], "volume_index": volume_index, "volume_title": volume_title},
        )
        if not conflict and edition.get("sourceGroupKey") == source_key:
            return edition
    return None


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(text(sql), params or {}).mappings().all()]


def _first_text(xml: str, tag: str) -> str | None:
    values = _texts(xml, tag)
    return values[0] if values else None


def _texts(xml: str, tag: str) -> list[str]:
    values = []
    for match in re.finditer(rf"<(?:[\w]+:)?{re.escape(tag)}\b[^>]*>([\s\S]*?)</(?:[\w]+:)?{re.escape(tag)}>", xml, re.I):
        text_value = _decode_xml_text(match.group(1))
        if text_value:
            values.append(text_value)
    return values


def _decode_xml_text(value: str) -> str:
    value = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    try:
        value = ElementTree.fromstring(f"<x>{value}</x>").text or value
    except ElementTree.ParseError:
        pass
    return re.sub(r"\s+", " ", value).strip()


def _attrs(xml: str, name: str) -> list[dict[str, str]]:
    output = []
    for match in re.finditer(rf"<{name}\b([^>]*)/?>(?:</{name}>)?", xml, re.I):
        output.append({item.group(1): item.group(2) or item.group(3) or "" for item in re.finditer(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", match.group(1))})
    return output


def _opf_items(opf_xml: str) -> list[dict[str, str]]:
    return [{"id": attrs.get("id"), "href": attrs.get("href"), "mediaType": attrs.get("media-type"), "properties": attrs.get("properties")} for attrs in _attrs(opf_xml, "item")]


def _opf_itemrefs(opf_xml: str) -> list[dict[str, str]]:
    return [{"idref": attrs.get("idref")} for attrs in _attrs(opf_xml, "itemref")]


def _epub_chapters(archive: zipfile.ZipFile, opf_path: str, opf_xml: str, manifest: list[dict[str, str]], spine: list[dict[str, str]]) -> list[dict[str, Any]]:
    href_items = {_normalize_epub_path(item.get("href") or ""): item for item in manifest if item.get("href")}
    spine_attrs = _attrs(opf_xml, "spine")
    ncx_id = (spine_attrs[0] if spine_attrs else {}).get("toc")
    ncx = next((item for item in manifest if item.get("id") == ncx_id), None) or next((item for item in manifest if "ncx" in str(item.get("mediaType") or "").lower()), None)
    if ncx and ncx.get("href"):
        chapters = _parse_ncx(_read_zip_text_optional(archive, _epub_zip_path(opf_path, ncx["href"])), opf_path, _epub_zip_path(opf_path, ncx["href"]), href_items)
        if chapters:
            return chapters
    nav = next((item for item in manifest if "nav" in str(item.get("properties") or "").split()), None)
    if nav and nav.get("href"):
        chapters = _parse_nav(_read_zip_text_optional(archive, _epub_zip_path(opf_path, nav["href"])), opf_path, _epub_zip_path(opf_path, nav["href"]), href_items)
        if chapters:
            return chapters
    chapters = []
    by_id = {item.get("id"): item for item in manifest}
    for index, ref in enumerate(spine, start=1):
        item = by_id.get(ref.get("idref"))
        if item and item.get("href"):
            title = _chapter_heading(archive, opf_path, item["href"]) or f"第 {index} 章"
            chapters.append({"title": title, "href": item["href"], "idref": ref.get("idref"), "mediaType": item.get("mediaType"), "sortOrder": index})
    return chapters


def _parse_ncx(xml: str | None, opf_path: str, ncx_path: str, href_items: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    if not xml:
        return []
    entries = []
    for index, block in enumerate(re.findall(r"<navPoint\b[\s\S]*?</navPoint>", xml, re.I), start=1):
        title = _first_text(block, "text") or ""
        src = (_attrs(block, "content")[0] if _attrs(block, "content") else {}).get("src", "")
        chapter = _chapter_from_toc(title, src, index, opf_path, ncx_path, href_items)
        if chapter:
            entries.append(chapter)
    return entries


def _parse_nav(xml: str | None, opf_path: str, nav_path: str, href_items: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    if not xml:
        return []
    entries = []
    nav_blocks = list(re.finditer(r"<nav\b([^>]*)>([\s\S]*?)</nav>", xml, re.I))
    toc_block = next(
        (
            match.group(2)
            for match in nav_blocks
            if re.search(r"\b(?:epub:)?type\s*=\s*['\"][^'\"]*\btoc\b", match.group(1), re.I) or re.search(r"\brole\s*=\s*['\"]doc-toc['\"]", match.group(1), re.I)
        ),
        nav_blocks[0].group(2) if nav_blocks else xml,
    )
    for index, match in enumerate(re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", toc_block, re.I), start=1):
        title = _decode_xml_text(match.group(2))
        href = (_attrs(f"<a{match.group(1)}>", "a")[0] if _attrs(f"<a{match.group(1)}>", "a") else {}).get("href", "")
        chapter = _chapter_from_toc(title, href, index, opf_path, nav_path, href_items)
        if chapter:
            entries.append(chapter)
    return entries


def _chapter_from_toc(title: str, href: str, index: int, opf_path: str, toc_path: str, href_items: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    if not title or not href:
        return None
    path_part, _, fragment = href.partition("#")
    absolute = _normalize_epub_path(str(PurePosixPath(toc_path).parent / path_part))
    relative = _normalize_epub_path(os.path.relpath(absolute, str(PurePosixPath(opf_path).parent)).replace("\\", "/"))
    full_href = f"{relative}#{fragment}" if fragment else relative
    item = href_items.get(_normalize_epub_path(relative))
    return {"title": title, "href": full_href, "idref": item.get("id") if item else None, "mediaType": item.get("mediaType") if item else None, "sortOrder": index}


def _chapter_heading(archive: zipfile.ZipFile, opf_path: str, href: str) -> str | None:
    markup = _read_zip_text_optional(archive, _epub_zip_path(opf_path, href))
    if not markup:
        return None
    for tag in ["h1", "h2", "h3", "title"]:
        value = _first_text(markup, tag)
        if value:
            return value
    return None


def _epub_cover(manifest: list[dict[str, str]], opf_xml: str) -> dict[str, str] | None:
    meta_cover = next((attrs.get("content") for attrs in _attrs(opf_xml, "meta") if attrs.get("name") == "cover"), None)
    return next((item for item in manifest if item.get("id") == meta_cover), None) or next((item for item in manifest if "cover-image" in str(item.get("properties") or "")), None) or next((item for item in manifest if "image" in str(item.get("mediaType") or "") and re.search(r"(cover|front|folder|封面)", str(item.get("href") or ""), re.I)), None)


def _epub_zip_path(opf_path: str, href: str) -> str:
    path = href.split("#", 1)[0]
    return _normalize_epub_path(str(PurePosixPath(opf_path).parent / path))


def _normalize_epub_path(value: str) -> str:
    return str(PurePosixPath(value.replace("\\", "/"))).lstrip("./")


def _read_zip_text_optional(archive: zipfile.ZipFile, entry: str) -> str | None:
    try:
        return archive.read(entry).decode("utf-8", "replace")
    except KeyError:
        return None


def _resolve_epub_archive_entry(archive: zipfile.ZipFile, entry: str) -> str | None:
    """Resolve an EPUB href without making optional resources fatal.

    EPUB hrefs are URL paths, while real-world ZIPs sometimes contain decoded
    names or use different path casing. Prefer an exact normalized match, then
    accept a unique case-insensitive match. Ambiguous or missing entries remain
    unresolved instead of selecting an arbitrary file.
    """
    wanted = _normalize_epub_path(unquote(entry))
    exact_matches: list[str] = []
    folded_matches: list[str] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        normalized = _normalize_epub_path(unquote(info.filename))
        if normalized == wanted:
            exact_matches.append(info.filename)
        if normalized.casefold() == wanted.casefold():
            folded_matches.append(info.filename)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(folded_matches) == 1:
        return folded_matches[0]
    return None


def _extract_epub_cover(settings: Settings, staged: Path, work_id: str, edition_id: str, metadata: dict[str, Any], volume_id: str | None = None) -> str | None:
    if not metadata.get("coverPath"):
        return None
    rel = _epub_zip_path(metadata["opfPath"], metadata["coverPath"])
    with zipfile.ZipFile(staged) as archive:
        resolved = _resolve_epub_archive_entry(archive, rel)
        if not resolved:
            return None
        cover = archive.read(resolved)
    ext = Path(unquote(metadata["coverPath"])).suffix or ".jpg"
    target = settings.resolved_storage_root / "books" / work_id / edition_id / (volume_id or "") / f"cover{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(cover)
    return str(target)


def _extract_comic_cover(settings: Settings, staged: Path, work_id: str, edition_id: str, volume_id: str, entry: str) -> str:
    ext = Path(entry).suffix.lower() or ".jpg"
    target = settings.resolved_storage_root / "books" / work_id / edition_id / volume_id / f"cover{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(staged) as archive:
        with archive.open(entry, "r") as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
    return str(target)


def _extract_pdf_cover(settings: Settings, staged: Path, work_id: str, edition_id: str, metadata: dict[str, Any]) -> str | None:
    target = settings.resolved_storage_root / "books" / work_id / edition_id / "cover.jpg"
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(staged))
        try:
            if len(pdf) < 1:
                return None
            page = pdf[0]
            bitmap = page.render(scale=2)
            image = bitmap.to_pil()
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.thumbnail((900, 1200))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="JPEG", quality=88, optimize=True)
            metadata["rawMetadata"]["coverRenderedFromPage"] = 1
            return str(target)
        finally:
            pdf.close()
    except Exception as exc:
        metadata["rawMetadata"]["coverWarning"] = str(exc)
        target.unlink(missing_ok=True)
        return None


def _extract_isbn(ids: list[str]) -> str | None:
    for value in ids:
        if "isbn" not in str(value).lower():
            continue
        candidates = re.findall(r"(?:97[89][-\s]?)?[0-9][0-9Xx\-\s]{8,16}[0-9Xx]", value)
        for candidate in candidates:
            normalized = re.sub(r"[^0-9Xx]", "", candidate).upper()
            if _valid_isbn(normalized):
                return normalized
    return None


def _preferred_identifier(ids: list[str]) -> str | None:
    for value in ids:
        if "isbn" in str(value).lower():
            continue
        cleaned = str(value or "").strip()
        if cleaned and _usable_merge_identifier(cleaned):
            return cleaned
    return None


def _valid_isbn(value: str) -> bool:
    if len(value) == 13 and value.isdigit():
        total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(value[:12]))
        return (10 - total % 10) % 10 == int(value[-1])
    if len(value) == 10 and re.fullmatch(r"[0-9]{9}[0-9X]", value):
        total = sum((10 - index) * (10 if char == "X" else int(char)) for index, char in enumerate(value))
        return total % 11 == 0
    return False


def _sanitize_description(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip() if value else None


def _title_from_file(path: Path) -> str:
    return re.sub(r"[_-]+", " ", Path(path).stem).strip() or Path(path).name


def _safe_entry_name(name: str) -> bool:
    normalized = str(PurePosixPath(name.replace("\\", "/")))
    return bool(name and not name.startswith("/") and not re.match(r"^[a-zA-Z]:", name) and not normalized.startswith("../") and "/../" not in normalized)


def _ignored_entry(name: str) -> bool:
    parts = name.split("/")
    last = parts[-1]
    return "__MACOSX" in parts or last in {".DS_Store", "Thumbs.db"} or last.startswith("._") or any(part.startswith(".") for part in parts)


def _natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _parse_comic_info(xml: str) -> dict[str, Any]:
    raw = {}
    for tag in ["Title", "Series", "Volume", "Summary", "Writer", "Penciller", "Publisher", "Genre", "Tags"]:
        value = _first_text(xml, tag)
        if value:
            raw[tag] = value
    volume = float(raw["Volume"]) if str(raw.get("Volume", "")).replace(".", "", 1).isdigit() else None
    cover_match = re.search(r"<Page\b[^>]*(?:Type|type)=['\"](?:FrontCover|Cover)['\"][^>]*(?:Image|image)=['\"](\d+)['\"]", xml, re.I)
    return {"title": raw.get("Title"), "series": raw.get("Series"), "volume": volume, "summary": raw.get("Summary"), "writer": raw.get("Writer"), "penciller": raw.get("Penciller"), "publisher": raw.get("Publisher"), "tags": _split_tags(raw.get("Tags") or raw.get("Genre")), "coverImageIndex": int(cover_match.group(1)) if cover_match else None, "raw": raw}


def _split_tags(value: str | None) -> list[str]:
    return [tag.strip() for tag in re.split(r"[,，;]", value or "") if tag.strip()]


def _clean_title_part(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()


def _bracketed_folder_metadata(value: str) -> dict[str, str] | None:
    parts = [_clean_title_part(match.group(1)) for match in re.finditer(r"\[([^\]]+)\]", value)]
    if len(parts) == 2 and "".join(parts) and _is_exact_bracket_sequence(value, 2):
        return {"title": parts[0], "author": parts[1]}
    return None


def _series_folder_metadata(value: str, filename: str | None = None) -> dict[str, str] | None:
    inferred = parse_bracketed_series_identity(value, filename)
    if inferred:
        return {"title": inferred[0], "author": inferred[1]}
    raw_parts = [match.group(1) for match in re.finditer(r"\[([^\]]+)\]", value)]
    parts = [_clean_title_part(part) for part in raw_parts]
    if len(parts) >= 3 and parts[0] and parts[1] and _volume_range_part(raw_parts[2]) and _is_exact_bracket_sequence(value):
        return {"title": parts[0], "author": parts[1]}
    if len(parts) == 2 and "".join(parts) and _is_exact_bracket_sequence(value, 2):
        return {"title": parts[0], "author": parts[1]}
    return None


def _is_exact_bracket_sequence(value: str, count: int | None = None) -> bool:
    repeat = f"{{{count}}}" if count is not None else "+"
    return bool(re.fullmatch(rf"\s*(?:\[[^\]]+\]\s*){repeat}", value))


def _volume_range_part(value: str) -> bool:
    return bool(re.search(r"(?:vol\.?|volume|v|第)?\s*\d+(?:\.\d+)?\s*[-~至到]\s*(?:vol\.?|volume|v|第)?\s*\d+(?:\.\d+)?", value, re.I))


def _volume_index_from_suffix(value: str) -> float | None:
    suffix = _clean_title_part(value).strip()
    suffix = re.sub(r"^[\s._\-~～]+", "", suffix)
    if not suffix:
        return None
    for pattern in [
        r"(?:^|\s)(?:vol\.?|volume|v)\s*(\d+(?:\.\d+)?)$",
        r"(?:^|\s)(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"(?:^|\s)(\d+(?:\.\d+)?)$",
    ]:
        match = re.search(pattern, suffix, re.I)
        if match:
            return float(match.group(1))
    return None


def _comic_parent_title(path: Path, origin: str) -> str | None:
    if origin != "WATCH":
        return None
    parent = _clean_title_part(path.parent.name)
    if not parent or parent.lower() in {".", "/", "books", "library", "comics", "comic", "manga", "漫画"}:
        return None
    return (_bracketed_folder_metadata(parent) or {}).get("title") or parent


def _comic_parent_author(path: Path) -> str | None:
    parent = _clean_title_part(path.parent.name)
    return (_bracketed_folder_metadata(parent) or {}).get("author")
