"""Audiobook media import command and audio-specific helpers."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.modules.imports.application.audio_types import (
    DISC_DIRECTORY_PATTERN,
    MAX_AUDIO_CHAPTERS,
    AudioBundleStructure,
    AudioChapterMetadata,
    AudioFileMetadata,
    audio_episode_number,
    audio_mime_type,
    is_supported_audio_file,
    strict_flat_audio_title,
)
from app.modules.imports.application.commands import release_import_transaction
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
)
from app.modules.imports.application.identity_policy import UNKNOWN_AUTHOR
from app.modules.imports.application.import_support import (
    BoundTopologyTarget,
    _bound_topology_target,
    _classification_columns,
    _finalize_work_cover,
    _hash_text,
    _id,
    _normalize_key,
    _now,
    _persist_import_volume,
    _prepared_default_cover,
    _title_from_file,
)
from app.modules.imports.application.local_metadata import ResolvedLocalMetadata
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    ImportUnitOfWork,
    LibraryImportStore,
)
from app.modules.imports.domain.content_classification import (
    ContentClassification,
    ContentEvidence,
    classify_content,
    normalize_media_kind_policy,
)

_FLAT_AUDIO_FILENAME_PATTERN = re.compile(
    r"^\s*0*\d{1,6}\s*[-–—_.]+\s*(?P<title>.+?)\s*[-–—_]+\s*"
    r"(?:(?:chapter|chap|ch|track|part|episode|ep)\s*0*\d{1,6}\b|\u7b2c?\s*0*\d{1,6}\s*[章回集节]).*$",
    re.IGNORECASE,
)


def _import_audio(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    options: ImportOptions,
    task_id: str,
    identity: BookIdentityDTO,
    metadata_items: list[AudioFileMetadata],
    structure: AudioBundleStructure | None = None,
    resolved_local: ResolvedLocalMetadata | None = None,
    unit_of_work: ImportUnitOfWork | None = None,
) -> ImportResult:
    if not metadata_items:
        raise ValueError("有声书目录中没有可导入的音频文件")
    if unit_of_work is None:
        raise RuntimeError("有声书导入缺少事务协调器")
    classification = classify_content(
        normalize_media_kind_policy(options.media_kind_policy),
        ContentEvidence(volume_format="AUDIO"),
    )
    chapter_total = sum(max(1, len(item.chapters)) for item in metadata_items)
    if chapter_total > MAX_AUDIO_CHAPTERS:
        raise ValueError(f"有声书章节总数超过 {MAX_AUDIO_CHAPTERS} 个，请拆分后导入")

    volume_groups = list(structure.volumes) if structure is not None else []
    source_volume_order = {
        path.resolve(): volume_index
        for volume_index, group in enumerate(volume_groups)
        for path in group.files
    }
    effective_track_numbers = _effective_audio_track_numbers(metadata_items)
    metadata_items = sorted(
        metadata_items,
        key=lambda item: (
            source_volume_order.get(item.path.resolve(), 0),
            _audio_metadata_sort_key(item, effective_track_numbers.get(item.path)),
        ),
    )
    display_titles = _audio_track_titles(metadata_items)
    narrator_values = _consistent_audio_values(
        metadata_items,
        "narrator",
        "朗读者",
        strict=False,
    )
    narrator = narrator_values[0] if narrator_values else None
    target = _bound_topology_target(queries, options)
    return _import_bound_audio(
        store,
        queries,
        services,
        settings,
        options,
        task_id,
        identity,
        metadata_items,
        effective_track_numbers,
        display_titles,
        narrator,
        classification,
        target,
        resolved_local,
        unit_of_work,
    )


def _import_bound_audio(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    options: ImportOptions,
    task_id: str,
    identity: BookIdentityDTO,
    metadata_items: list[AudioFileMetadata],
    effective_track_numbers: dict[Path, int | None],
    display_titles: dict[Path, str],
    narrator: str | None,
    classification: ContentClassification,
    target: BoundTopologyTarget,
    resolved_local: ResolvedLocalMetadata | None,
    unit_of_work: ImportUnitOfWork,
) -> ImportResult:
    """Enrich one scanner-owned audiobook Volume without structural inference."""

    volume = _persist_import_volume(
        store,
        {
            "id": target.volume["id"],
            "versionId": target.version_id,
            "title": target.volume["title"],
            "format": "AUDIO",
            "resourceKey": target.volume["resourceKey"],
            "origin": options.origin,
            "importStatus": "PARSING",
            "narrator": narrator,
            **_classification_columns(classification),
            "updatedAt": _now(),
        },
        target,
    )
    release_import_transaction(unit_of_work)
    cover_path = services.publish_audio_cover(
        settings.resolved_storage_root,
        str(target.work["id"]),
        target.version_id,
        tuple(metadata_items),
        bundle_root=(
            options.source_file_path.resolve()
            if options.source_file_path.is_dir()
            else None
        ),
    ) or _prepared_default_cover(options)
    manifest_tracks: list[dict[str, object]] = []
    manifest_chapters: list[dict[str, object]] = []
    chapter_sort_order = 0
    total_size = 0
    total_duration = 0
    for index, item in enumerate(metadata_items):
        stat = item.path.stat()
        total_size += stat.st_size
        total_duration += item.duration_ms
        file_row = store.insert_library_file(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "path": str(item.path),
                "filePathHash": _hash_text(str(item.path)),
                "mtimeMs": int(stat.st_mtime * 1000),
                "kind": "AUDIO",
                "mimeType": audio_mime_type(item.path),
                "sizeBytes": stat.st_size,
                "durationMs": item.duration_ms,
                "codec": item.codec,
                "bitrate": item.bitrate,
                "sampleRate": item.sample_rate,
                "channels": item.channels,
                "discNumber": (
                    item.disc_number
                    if item.disc_number is not None
                    else _audio_disc_number(item.path)
                ),
                "trackNumber": effective_track_numbers.get(item.path),
                "sortOrder": index,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        asset = queries.get_import_asset_by_task_and_path(task_id, str(item.path))
        asset_values: dict[str, object] = {
            "status": "COMPLETED",
            "sortOrder": index,
            "fileId": file_row["id"],
            "errorCode": None,
            "errorSummary": None,
            "updatedAt": _now(),
        }
        if asset is not None:
            store.update_import_asset(str(asset["id"]), columns=asset_values)
        else:
            store.insert_import_asset(
                columns={
                    "id": _id(),
                    "importTaskId": task_id,
                    "sourcePath": str(item.path),
                    "createdAt": _now(),
                    **asset_values,
                }
            )
        source_chapters = list(item.chapters) or [
            AudioChapterMetadata(
                title=display_titles[item.path],
                start_ms=0,
                end_ms=item.duration_ms,
            )
        ]
        for chapter in source_chapters:
            start_ms = max(0, int(chapter.start_ms))
            end_ms = min(item.duration_ms, int(chapter.end_ms))
            if end_ms <= start_ms:
                continue
            chapter_sort_order += 1
            unit = store.insert_library_reading_unit(
                columns={
                    "id": _id(),
                    "volumeId": volume["id"],
                    "fileId": file_row["id"],
                    "unitType": "audio_chapter",
                    "title": chapter.title
                    or display_titles[item.path]
                    or f"第 {chapter_sort_order} 章",
                    "href": (
                        f"audio:{file_row['id']}#t="
                        f"{start_ms / 1000:g},{end_ms / 1000:g}"
                    ),
                    "mediaType": audio_mime_type(item.path),
                    "sortOrder": chapter_sort_order,
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "durationMs": end_ms - start_ms,
                    "metadataJson": json.dumps(
                        {"trackIndex": index, "sourceFileName": item.path.name},
                        ensure_ascii=False,
                    ),
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
            manifest_chapters.append(
                {
                    "id": unit["id"],
                    "volumeId": volume["id"],
                    "title": unit["title"],
                    "fileId": file_row["id"],
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "sortOrder": chapter_sort_order,
                }
            )
        manifest_tracks.append(
            {
                "fileId": file_row["id"],
                "title": display_titles[item.path],
                "sourceFileName": item.path.name,
                "mimeType": file_row["mimeType"],
                "durationMs": item.duration_ms,
                "discNumber": file_row.get("discNumber"),
                "trackNumber": file_row.get("trackNumber"),
                "sortOrder": index,
            }
        )
        store.update_import_task(
            task_id,
            columns={
                "processedAssetCount": index + 1,
                "progress": 30 + round(((index + 1) / len(metadata_items)) * 55),
                "message": f"已建立音轨 {index + 1}/{len(metadata_items)}",
            },
        )
    raw_tags = [
        {"sourcePath": str(item.path), "tags": item.raw_tags} for item in metadata_items
    ]
    for source, payload in (
        ("audio_tags", raw_tags),
        (
            "audiobook_manifest",
            {
                "durationMs": total_duration,
                "narrator": narrator,
                "tracks": manifest_tracks,
                "chapters": manifest_chapters,
            },
        ),
        (f"identity_{identity.source}", identity.raw_metadata()),
    ):
        store.insert_library_metadata(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "source": source,
                "rawJson": json.dumps(payload, ensure_ascii=False),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
    actual_chapters = max(chapter_sort_order, len(metadata_items))
    store.update_library_volume(
        str(volume["id"]),
        columns={
            "coverPath": cover_path,
            "coverStatus": services.cover_status(cover_path),
            "sizeBytes": total_size,
            "chapterCount": actual_chapters,
            "trackCount": len(metadata_items),
            "durationMs": total_duration,
            "narrator": narrator,
            "importStatus": "COMPLETED",
            "updatedAt": _now(),
        },
    )
    _finalize_work_cover(
        store,
        queries,
        services,
        str(target.work["id"]),
        target.version_id,
        cover_path,
        _prepared_default_cover(options),
    )
    return ImportResult(
        str(target.work["id"]),
        str(target.work["id"]),
        target.version_id,
        str(volume["id"]),
        str(target.work["title"]),
        classification.media_kind.lower(),
        "audio",
        actual_chapters,
        "completed",
        False,
        False,
        "topology-bound",
        resolved_metadata=resolved_local.metadata if resolved_local else None,
        metadata_field_sources=resolved_local.field_sources if resolved_local else (),
        metadata_source_order=resolved_local.source_order if resolved_local else (),
    )


def audio_embedded_metadata(
    identity: BookIdentityDTO,
    metadata_items: list[AudioFileMetadata],
) -> PublicationMetadata:
    """Map consistent album-level audio tags to the common metadata contract."""

    albums = _consistent_audio_values(
        metadata_items, "album", "专辑/书名", strict=False
    )
    authors = _consistent_audio_values(metadata_items, "author", "作者", strict=False)
    series_names = _consistent_audio_values(
        metadata_items, "series_name", "系列", strict=False
    )
    volume_indexes = _consistent_audio_values(
        metadata_items, "volume_index", "卷号", strict=False
    )
    series_name = series_names[0] if series_names else None
    volume_index = float(volume_indexes[0]) if volume_indexes else None
    publication_titles = titles_from_local_source(
        albums[0] if albums else identity.title,
        series_name=series_name,
        volume_index=volume_index,
    )
    single_file_title = (
        metadata_items[0].title
        if len(metadata_items) == 1 and metadata_items[0].title
        else None
    )
    return PublicationMetadata(
        title=publication_titles.work_title,
        volume_title=single_file_title or publication_titles.volume_title,
        authors=(authors[0],)
        if authors
        else ((identity.author,) if identity.author else ()),
        series_name=series_name,
        series_index=volume_index,
        volume_index=publication_titles.volume_index,
    )


def _audio_identity(
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    source: Path,
    options: ImportOptions,
    metadata_items: list[AudioFileMetadata],
    structure: AudioBundleStructure | None = None,
) -> BookIdentityDTO:
    """Determine title and author for one audio import."""

    requested_title = re.sub(r"\s+", " ", str(options.requested_title or "")).strip()
    requested_author = re.sub(r"\s+", " ", str(options.requested_author or "")).strip()
    fallback = services.recognize_identity(
        source,
        options.original_name if source.is_file() else None,
    )
    fallback_title = _clean_audio_work_title(fallback.title)
    directory_bundle = source.is_dir()
    flat_title = _flat_audio_filename_title(source) if source.is_file() else None
    directory_flat_titles = {
        _normalize_key(item_title): item_title
        for item in metadata_items
        if (item_title := _flat_audio_filename_title(item.path))
    }
    directory_flat_title = (
        next(iter(directory_flat_titles.values()))
        if len(directory_flat_titles) == 1
        else None
    )
    directory_author = structure.author if directory_bundle and structure else None
    volume_authors = {
        _normalize_key(volume.author): volume.author
        for volume in (structure.volumes if directory_bundle and structure else ())
        if volume.author
    }
    volume_author = (
        next(iter(volume_authors.values())) if len(volume_authors) == 1 else None
    )
    author_diagnostic = None
    if len(volume_authors) > 1:
        author_diagnostic = "有声书各卷目录中的内嵌作者不一致，已忽略卷目录作者"
    elif (
        directory_author
        and volume_author
        and _normalize_key(directory_author) != _normalize_key(volume_author)
    ):
        author_diagnostic = (
            "有声书书名目录与卷目录中的内嵌作者不一致，已采用书名目录作者"
        )
    albums = (
        []
        if requested_title or directory_bundle
        else _consistent_audio_values(metadata_items, "album", "专辑/书名")
    )
    authors = (
        []
        if requested_author
        else _consistent_audio_values(
            metadata_items,
            "author",
            "作者",
            strict=not directory_bundle,
        )
    )
    if requested_title:
        title = requested_title
    elif directory_bundle and directory_flat_title:
        title = directory_flat_title
    elif directory_bundle and structure:
        title = structure.title
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
    elif directory_author:
        author = directory_author
    elif volume_author:
        author = volume_author
    elif flat_title:
        # The documented flat layout encodes book title and chapter, not an
        # author. Do not let the generic filename parser reinterpret the
        # trailing chapter label as an author.
        author = UNKNOWN_AUTHOR
    elif authors:
        author = authors[0]
    else:
        author = fallback.author
    return replace(
        fallback,
        title=str(title).strip() or fallback.title,
        author=str(author).strip() or UNKNOWN_AUTHOR,
        confidence=max(
            fallback.confidence, 0.95 if albums or authors else fallback.confidence
        ),
        cache_hit=False,
        fallback_reason=author_diagnostic or fallback.fallback_reason,
    )


def _clean_audio_work_title(value: Any) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = re.sub(r"(?:[ ._-]*有声书)$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(
        r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:track\s*)?\d+[ ._-]*",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    return title or "未命名有声书"


def _flat_audio_filename_title(path: Path) -> str | None:
    if not path.is_file() or not is_supported_audio_file(path):
        return None
    title = strict_flat_audio_title(path)
    return _clean_audio_work_title(title) if title else None


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
        raise ValueError(
            f"有声书目录中的{label}不一致（{preview}），请拆分目录或修正音频标签后重试"
        )
    return values


def _effective_audio_track_numbers(
    metadata_items: list[AudioFileMetadata],
) -> dict[Path, int | None]:
    by_disc: dict[int, list[AudioFileMetadata]] = {}
    for item in metadata_items:
        disc_number = (
            item.disc_number
            if item.disc_number is not None
            else _audio_disc_number(item.path) or 1
        )
        by_disc.setdefault(disc_number, []).append(item)
    result: dict[Path, int | None] = {}
    for items in by_disc.values():
        embedded = [item.track_number for item in items]
        tags_are_complete_and_unique = all(
            value is not None for value in embedded
        ) and len(set(embedded)) == len(embedded)
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
        item.disc_number
        if item.disc_number is not None
        else _audio_disc_number(item.path) or 1,
        effective_track_number if effective_track_number is not None else 10**9,
        natural,
    )


def _audio_episode_number(path: Path) -> int | None:
    return audio_episode_number(path)


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
    generic = {
        _normalize_key(value)
        for value in ["正文", "audio", "track", "chapter", "音频", "未命名"]
    }
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
