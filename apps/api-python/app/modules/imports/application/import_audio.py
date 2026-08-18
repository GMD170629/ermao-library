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
    _classification_columns,
    _ensure_implicit_version,
    _ensure_work,
    _finalize_work_cover,
    _hash_text,
    _id,
    _normalize_key,
    _now,
    _prepared_default_cover,
    _title_from_file,
    _work_merge_key,
)
from app.modules.imports.application.local_metadata import ResolvedLocalMetadata
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    ImportUnitOfWork,
    LibraryImportStore,
)
from app.modules.imports.domain.content_classification import (
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
    classification = classify_content(
        normalize_media_kind_policy(options.media_kind_policy),
        ContentEvidence(volume_format="AUDIO"),
    )
    chapter_total = sum(max(1, len(item.chapters)) for item in metadata_items)
    if chapter_total > MAX_AUDIO_CHAPTERS:
        raise ValueError(f"有声书章节总数超过 {MAX_AUDIO_CHAPTERS} 个，请拆分后导入")
    source_root = options.source_file_path.resolve()
    directory_bundle = source_root.is_dir()
    volume_groups = list(structure.volumes) if directory_bundle and structure else []
    source_volume_order = {
        path.resolve(): volume_index
        for volume_index, group in enumerate(volume_groups)
        for path in group.files
    }
    flat_title = (
        _flat_audio_filename_title(source_root) if source_root.is_file() else None
    )
    effective_track_numbers = (
        {item.path: _audio_episode_number(item.path) for item in metadata_items}
        if flat_title
        else _effective_audio_track_numbers(metadata_items)
    )
    metadata_items = sorted(
        metadata_items,
        key=lambda item: (
            source_volume_order.get(item.path.resolve(), 0),
            _audio_metadata_sort_key(item, effective_track_numbers.get(item.path)),
        ),
    )
    flat_bundle_key = (
        _flat_audio_bundle_key(source_root, flat_title) if flat_title else None
    )
    display_titles = _audio_track_titles(metadata_items)
    source_stats = {item.path.resolve(): item.path.stat() for item in metadata_items}
    existing_by_path = _audio_files_by_path(
        queries, [item.path for item in metadata_items]
    )
    if existing_by_path and not directory_bundle:
        raise ValueError("音频文件已入库，请使用原目录重新扫描")
    if existing_by_path and structure and structure.is_multi_volume:
        raise ValueError(
            "多卷有声书中已有音轨入库；为保护已有作品和进度，本次不会自动重组，请使用未入库的完整目录"
        )

    narrator_values = _consistent_audio_values(
        metadata_items,
        "narrator",
        "朗读者",
        strict=not directory_bundle,
    )
    narrator = narrator_values[0] if narrator_values else None
    merge_key = _work_merge_key(identity.title)
    # A directory identifies one split-track bundle. An explicitly structured
    # Emby flat filename joins its sibling chapters; every other single file
    # remains keyed by the file itself so independent M4Bs cannot collide.
    bundle_key = flat_bundle_key or _hash_text(str(source_root))[:24]
    resource_key = (
        f"audio-flat:{bundle_key}"
        if flat_bundle_key
        else f"audio:{bundle_key}:{_normalize_key(narrator or 'default')}"
    )
    base_name = f"有声书 · {narrator}" if narrator else "有声书"
    total_duration = sum(item.duration_ms for item in metadata_items)
    reconciled = False
    created = False
    volumes: list[dict[str, Any]] = []
    if existing_by_path:
        work, created = _ensure_audio_work(store, queries, options, identity, merge_key)
        media_version, volume = _prepare_existing_audio_bundle(
            store,
            queries,
            work,
            existing_by_path,
            options,
            bundle_key,
            base_name,
            narrator,
        )
        volumes = [volume]
        reconciled = True
    else:
        flat_media_version = (
            _audio_flat_media_version(queries, resource_key)
            if flat_bundle_key
            else None
        )
        if flat_media_version:
            work = _reuse_existing_audio_work(
                store, queries, str(flat_media_version["workId"])
            )
            created = False
            media_version, volume = _prepare_flat_audio_bundle(
                store,
                queries,
                work,
                flat_media_version,
                options,
                resource_key,
                bundle_key,
                narrator,
            )
            volumes = [volume]
            reconciled = True
        else:
            work, created = _ensure_audio_work(
                store, queries, options, identity, merge_key
            )
            version = _ensure_implicit_version(store, work["id"])
            media_version = store.ensure_library_media_version(
                columns={
                    "id": _id(),
                    "workId": work["id"],
                    "libraryId": options.library_id,
                    "origin": options.origin,
                    "mediaKind": classification.media_kind,
                    "format": "AUDIO",
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
            volume_specs = volume_groups or [None]
            volumes = []
            for volume_index, group in enumerate(volume_specs):
                group_duration = (
                    sum(
                        item.duration_ms
                        for item in metadata_items
                        if item.path.resolve() in set(group.files)
                    )
                    if group is not None
                    else total_duration
                )
                volumes.append(
                    store.insert_library_volume(
                        columns={
                            "id": _id(),
                            "versionId": version["id"],
                            "title": group.title if group is not None else "正文",
                            "volumeIndex": group.volume_index
                            if group is not None
                            else None,
                            "sortOrder": volume_index,
                            "format": "AUDIO",
                            "resourceKey": (
                                resource_key
                                if flat_bundle_key and group is None
                                else f"{resource_key}:{volume_index}"
                            ),
                            "libraryId": options.library_id,
                            "origin": options.origin,
                            "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
                            "sizeBytes": sum(
                                source_stats[item.path.resolve()].st_size
                                for item in metadata_items
                                if group is None
                                or item.path.resolve() in set(group.files)
                            ),
                            "chapterCount": 0,
                            "durationMs": group_duration,
                            "narrator": narrator,
                            "coverStatus": "PENDING",
                            "importStatus": "PARSING",
                            **_classification_columns(classification),
                            "createdAt": _now(),
                            "updatedAt": _now(),
                        }
                    )
                )
            volume = volumes[0]
    if not volumes:
        volumes = [volume]
    volume_by_source_path = {
        path.resolve(): volumes[index]
        for index, group in enumerate(volume_groups)
        if index < len(volumes)
        for path in group.files
    }
    if unit_of_work is None:
        raise RuntimeError("有声书导入缺少事务协调器")
    release_import_transaction(unit_of_work)
    cover_path = media_version.get("coverPath") or services.publish_audio_cover(
        settings.resolved_storage_root,
        str(work["id"]),
        str(media_version["id"]),
        tuple(metadata_items),
        bundle_root=source_root if directory_bundle else None,
    )
    cover_path = cover_path or _prepared_default_cover(options)
    manifest_tracks: list[dict[str, Any]] = []
    manifest_chapters: list[dict[str, Any]] = []
    chapter_sort_order = 0
    # Make the unique (volume, unit type, sort order) slots available before
    # inserting a newly discovered track between existing tracks. The same
    # unit rows are updated back into their final order below, preserving IDs.
    for offset, existing_unit in enumerate(
        queries.list_audio_chapters_for_media_version(str(media_version["id"]))
    ):
        store.update_library_reading_unit(
            str(existing_unit["id"]),
            columns={"sortOrder": -1_000_000 - offset, "updatedAt": _now()},
        )
    for index, item in enumerate(metadata_items):
        item_volume = volume_by_source_path.get(item.path.resolve(), volume)
        stat = source_stats[item.path.resolve()]
        sort_order = index
        existing_file = existing_by_path.get(str(item.path))
        file_values = {
            "volumeId": item_volume["id"],
            "path": str(item.path),
            "filePathHash": _hash_text(str(item.path)),
            "fingerprint": existing_file.get("fingerprint") if existing_file else None,
            "mtimeMs": int(stat.st_mtime * 1000),
            "kind": "AUDIO",
            "mimeType": audio_mime_type(item.path),
            "sizeBytes": stat.st_size,
            "durationMs": item.duration_ms,
            "codec": item.codec,
            "bitrate": item.bitrate,
            "sampleRate": item.sample_rate,
            "channels": item.channels,
            "discNumber": item.disc_number
            if item.disc_number is not None
            else _audio_disc_number(item.path),
            "trackNumber": effective_track_numbers.get(item.path),
            "sortOrder": sort_order,
            "updatedAt": _now(),
        }
        if existing_file:
            store.update_library_file(str(existing_file["id"]), columns=file_values)
            file_row = store.get_library_file(str(existing_file["id"])) or {
                **existing_file,
                **file_values,
            }
        else:
            file_row = store.insert_library_file(
                columns={"id": _id(), "createdAt": _now(), **file_values}
            )
        asset = queries.get_import_asset_by_task_and_path(task_id, str(item.path))
        asset_values = {
            "status": "COMPLETED",
            "sortOrder": sort_order,
            "fileId": file_row["id"],
            "errorCode": None,
            "errorSummary": None,
            "updatedAt": _now(),
        }
        if asset:
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
                title=display_titles[item.path], start_ms=0, end_ms=item.duration_ms
            )
        ]
        existing_units = queries.list_audio_chapters_for_file(str(file_row["id"]))
        kept_unit_ids: set[str] = set()
        for chapter_index, chapter in enumerate(source_chapters):
            chapter_sort_order += 1
            start_ms = max(0, int(chapter.start_ms))
            end_ms = (
                min(item.duration_ms, int(chapter.end_ms))
                if item.duration_ms
                else int(chapter.end_ms)
            )
            if end_ms <= start_ms:
                continue
            unit_values = {
                "volumeId": item_volume["id"],
                "fileId": file_row["id"],
                "unitType": "audio_chapter",
                "title": chapter.title
                or display_titles[item.path]
                or f"第 {chapter_sort_order} 章",
                "href": f"audio:{file_row['id']}#t={start_ms / 1000:g},{end_ms / 1000:g}",
                "mediaType": audio_mime_type(item.path),
                "sortOrder": chapter_sort_order,
                "startMs": start_ms,
                "endMs": end_ms,
                "durationMs": end_ms - start_ms,
                "metadataJson": json.dumps(
                    {"trackIndex": index, "sourceFileName": item.path.name},
                    ensure_ascii=False,
                ),
                "updatedAt": _now(),
            }
            if chapter_index < len(existing_units):
                existing_unit = existing_units[chapter_index]
                store.update_library_reading_unit(
                    str(existing_unit["id"]), columns=unit_values
                )
                unit = store.get_library_reading_unit(str(existing_unit["id"])) or {
                    **existing_unit,
                    **unit_values,
                }
            else:
                unit = store.insert_library_reading_unit(
                    columns={"id": _id(), "createdAt": _now(), **unit_values}
                )
            kept_unit_ids.add(str(unit["id"]))
            manifest_chapters.append(
                {
                    "id": unit["id"],
                    "volumeId": item_volume["id"],
                    "title": unit["title"],
                    "fileId": file_row["id"],
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "sortOrder": chapter_sort_order,
                }
            )
        for stale_unit in existing_units:
            if str(stale_unit["id"]) not in kept_unit_ids:
                store.delete_library_reading_unit(str(stale_unit["id"]))
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
    _restore_unassigned_audio_units(
        store, queries, str(media_version["id"]), str(volume["id"]), chapter_sort_order
    )
    if reconciled:
        _resort_audio_media_version(
            store, queries, str(media_version["id"]), str(volume["id"])
        )
    raw_tags = _merge_audio_raw_tags(queries, str(media_version["id"]), raw_tags)
    manifest_tracks, manifest_chapters = _audio_manifest_from_db(
        queries, str(media_version["id"])
    )
    total_duration = sum(int(item.get("durationMs") or 0) for item in manifest_tracks)
    queries.delete_audio_metadata_sources(str(media_version["id"]))
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume["id"],
            "source": "audio_tags",
            "rawJson": json.dumps(raw_tags, ensure_ascii=False),
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume["id"],
            "source": "audiobook_manifest",
            "rawJson": json.dumps(
                {
                    "durationMs": total_duration,
                    "narrator": narrator,
                    "tracks": manifest_tracks,
                    "chapters": manifest_chapters,
                },
                ensure_ascii=False,
            ),
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume["id"],
            "source": f"identity_{identity.source}",
            "rawJson": json.dumps(identity.raw_metadata(), ensure_ascii=False),
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    if reconciled:
        _refresh_audio_progress_after_bundle_sync(
            store, queries, str(media_version["id"]), str(volume["id"])
        )
    actual_chapters = 0
    for item_volume in volumes:
        volume_chapters = sum(
            1
            for chapter in manifest_chapters
            if str(chapter.get("volumeId")) == str(item_volume["id"])
        )
        volume_duration = queries.sum_audio_duration_for_volume(str(item_volume["id"]))
        volume_files = queries.list_audio_files_for_volume(
            str(media_version["id"]), str(item_volume["id"])
        )
        volume_chapters = max(volume_chapters, len(volume_files))
        actual_chapters += volume_chapters
        store.update_library_volume(
            item_volume["id"],
            columns={
                "coverPath": cover_path,
                "coverStatus": services.cover_status(cover_path),
                "sizeBytes": sum(
                    int(file.get("sizeBytes") or 0) for file in volume_files
                ),
                "chapterCount": volume_chapters,
                "trackCount": len(volume_files),
                "durationMs": volume_duration,
                "narrator": narrator,
                "importStatus": "COMPLETED",
                "updatedAt": _now(),
            },
        )
    _finalize_work_cover(
        store,
        queries,
        services,
        work["id"],
        media_version["id"],
        cover_path,
        _prepared_default_cover(options),
    )
    return ImportResult(
        work["id"],
        work["id"],
        media_version["id"],
        volume["id"],
        work["title"],
        str(media_version.get("mediaKind") or classification.media_kind).lower(),
        "audio",
        actual_chapters,
        "completed",
        False,
        reconciled or not created,
        "reconciled-audio-directory"
        if reconciled
        else "new-audio-work"
        if created
        else "new-audio-volume",
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


def _audio_files_by_path(
    queries: ImportLibraryQueries, paths: list[Path]
) -> dict[str, dict[str, Any]]:
    if not paths:
        return {}
    candidates: list[str] = []
    for path in paths:
        candidates.append(str(path))
        try:
            candidates.append(str(path.resolve()))
        except OSError:
            pass
    found = queries.list_library_files_by_paths(list(dict.fromkeys(candidates)))
    by_path: dict[str, dict[str, Any]] = {}
    for row in found:
        if str(row.get("volumeImportStatus") or "") not in {
            "COMPLETED",
            "IMPORTED",
            "READY",
        }:
            continue
        stored = str(row["path"])
        by_path[stored] = row
        try:
            by_path[str(Path(stored).resolve())] = row
        except OSError:
            pass
    return by_path


def _ensure_audio_work(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    options: ImportOptions,
    identity: BookIdentityDTO,
    merge_key: str,
) -> tuple[dict[str, Any], bool]:
    return _ensure_work(
        store,
        queries,
        {
            "title": identity.title,
            "author": identity.author,
            "description": None,
            "tags": ["audiobook", "audio"],
            "mergeKey": merge_key,
            "origin": options.origin,
            "libraryId": options.library_id,
        },
    )


def _reuse_existing_audio_work(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    work_id: str,
) -> dict[str, Any]:
    """Reuse a work proven by existing stored audio structure, not recognition."""

    existing = queries.get_work_by_id(work_id)
    if existing is None:
        raise ValueError("有声书关联的作品不存在")
    store.update_library_work(
        work_id,
        columns={"hidden": False, "updatedAt": _now()},
    )
    return queries.get_work_by_id(work_id) or existing


def _audio_flat_media_version(
    queries: ImportLibraryQueries, resource_key: str
) -> dict[str, Any] | None:
    return queries.find_audio_media_version_by_resource_key(resource_key)


def _prepare_flat_audio_bundle(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    work: dict[str, Any],
    media_version: dict[str, Any],
    options: ImportOptions,
    resource_key: str,
    bundle_key: str,
    narrator: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append one strict Emby flat-layout chapter to its existing media_version."""

    media_version_id = str(media_version["id"])
    version = _ensure_implicit_version(store, work["id"])
    volume = queries.get_first_volume_for_media_version(media_version_id)
    if not volume:
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "versionId": version["id"],
                "title": "正文",
                "sortOrder": 0,
                "format": "AUDIO",
                "resourceKey": resource_key,
                "libraryId": options.library_id,
                "origin": options.origin,
                "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
                "chapterCount": 0,
                "durationMs": 0,
                "narrator": narrator,
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )

    # The schema has a unique (volume, unit type, sort order) index. Detach
    # the existing units while the new file is inserted, then globally sort
    # all tracks and chapters after the append.
    store.update_library_volume(
        str(volume["id"]),
        columns={
            "libraryId": options.library_id,
            "origin": options.origin,
            "resourceKey": resource_key,
            "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
            "narrator": narrator or media_version.get("narrator"),
            "hidden": False,
            "importStatus": "PARSING",
            "updatedAt": _now(),
        },
    )
    store.update_library_work(
        str(work["id"]), columns={"hidden": False, "updatedAt": _now()}
    )
    refreshed = queries.get_media_version_by_id(media_version_id) or media_version
    return refreshed, volume


def _prepare_existing_audio_bundle(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    work: dict[str, Any],
    existing_by_path: dict[str, dict[str, Any]],
    options: ImportOptions,
    bundle_key: str,
    base_name: str,
    narrator: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Collapse files previously imported one-by-one into one visible media_version.

    The old media_versions and empty works are hidden rather than deleted so import
    history and user data remain recoverable. File, chapter, shelf, and latest
    audio progress pointers are retargeted to the canonical bundle.
    """

    volume_contexts = [
        context
        for row in existing_by_path.values()
        if row.get("volumeId")
        if (context := queries.get_volume_context_by_id(str(row["volumeId"])))
    ]
    media_version_ids = sorted(
        {
            str(row["mediaVersionId"])
            for row in volume_contexts
            if row.get("mediaVersionId")
        }
    )
    if not media_version_ids:
        raise ValueError("已入库音频缺少媒介版本信息，无法按目录合并")
    media_versions = queries.list_media_versions_by_ids(media_version_ids)
    if not media_versions:
        raise ValueError("已入库音频的卷册资源记录不完整")
    target_work_id = str(work["id"])
    source_work_ids = sorted(
        {str(row.get("workId")) for row in media_versions if row.get("workId")}
    )
    canonical = store.ensure_library_media_version(
        columns={
            "id": _id(),
            "workId": target_work_id,
            "mediaKind": "AUDIOBOOK",
            "createdAt": _now(),
            "updatedAt": _now(),
        },
    )
    canonical_id = str(canonical["id"])
    version = _ensure_implicit_version(store, target_work_id)
    volume = volume_contexts[0] if volume_contexts else None
    if not volume:
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "versionId": version["id"],
                "title": "正文",
                "sortOrder": 0,
                "format": "AUDIO",
                "resourceKey": f"audio:{bundle_key}",
                "libraryId": options.library_id,
                "origin": options.origin,
                "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
                "chapterCount": 0,
                "durationMs": 0,
                "narrator": narrator,
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
    else:
        store.update_library_volume(
            str(volume["id"]),
            columns={
                "versionId": version["id"],
                "title": base_name,
                "format": "AUDIO",
                "resourceKey": f"audio:{bundle_key}",
                "sourceGroupKey": f"{options.origin.lower()}:{bundle_key}",
                "libraryId": options.library_id,
                "origin": options.origin,
                "narrator": narrator,
                "hidden": False,
                "importStatus": "PARSING",
                "updatedAt": _now(),
            },
        )
        volume = {
            **volume,
            "versionId": version["id"],
            "mediaVersionId": canonical_id,
            "hidden": False,
        }

    for source_volume in volume_contexts:
        source_volume_id = str(source_volume.get("id") or "")
        if source_volume_id and source_volume_id != str(volume["id"]):
            store.update_library_volume(
                source_volume_id,
                columns={"hidden": True, "updatedAt": _now()},
            )

    _retarget_audio_progress(
        store,
        queries,
        source_work_ids,
        media_version_ids,
        target_work_id,
        canonical_id,
        str(volume["id"]),
    )
    if source_work_ids:
        queries.copy_shelf_links_to_work(source_work_ids, target_work_id)

    store.update_library_work(
        target_work_id,
        columns={
            "hidden": False,
            "updatedAt": _now(),
        },
    )
    for source_work_id in source_work_ids:
        if source_work_id == target_work_id:
            continue
        visible_volumes = queries.count_visible_volumes_for_work(source_work_id)
        if visible_volumes == 0:
            store.update_library_work(
                source_work_id,
                columns={"hidden": True, "updatedAt": _now()},
            )
    return canonical, volume


def _retarget_audio_progress(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    source_work_ids: list[str],
    source_media_version_ids: list[str],
    target_work_id: str,
    target_media_version_id: str,
    target_volume_id: str,
) -> None:
    del source_work_ids, target_work_id, target_media_version_id
    if source_media_version_ids:
        rows = queries.list_reading_progress_for_media_versions(
            source_media_version_ids
        )
        for user_id in {str(row.get("userId")) for row in rows if row.get("userId")}:
            user_rows = [row for row in rows if str(row.get("userId")) == user_id]
            latest = user_rows[-1]
            target_progress = next(
                (
                    row
                    for row in user_rows
                    if str(row.get("volumeId")) == target_volume_id
                ),
                None,
            )
            target = target_progress or latest
            copied = {
                key: value
                for key, value in latest.items()
                if key not in {"id", "userId", "createdAt", "volumeId"}
            }
            store.update_library_reading_progress(
                str(target["id"]),
                columns={
                    **copied,
                    "volumeId": target_volume_id,
                    "updatedAt": _now(),
                },
            )


def _restore_unassigned_audio_units(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    media_version_id: str,
    volume_id: str,
    after_sort_order: int,
) -> None:
    rows = queries.list_unassigned_audio_chapters_for_media_version(media_version_id)
    sort_order = after_sort_order
    for row in rows:
        sort_order += 1
        store.update_library_reading_unit(
            str(row["id"]),
            columns={
                "volumeId": volume_id,
                "sortOrder": sort_order,
                "updatedAt": _now(),
            },
        )


def _resort_audio_media_version(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    media_version_id: str,
    volume_id: str,
) -> None:
    files = queries.list_audio_files_for_media_version(media_version_id)
    files.sort(key=_audio_file_row_sort_key)
    units_by_file = {
        str(file["id"]): queries.list_audio_chapter_units_for_file_ordered(
            str(file["id"])
        )
        for file in files
    }
    temporary_order = -1
    for units in units_by_file.values():
        for unit in units:
            store.update_library_reading_unit(
                str(unit["id"]),
                columns={"sortOrder": temporary_order, "updatedAt": _now()},
            )
            temporary_order -= 1
    chapter_sort_order = 0
    for file_sort_order, file in enumerate(files):
        store.update_library_file(
            str(file["id"]),
            columns={
                "volumeId": volume_id,
                "sortOrder": file_sort_order,
                "updatedAt": _now(),
            },
        )
        units = units_by_file[str(file["id"])]
        for unit in units:
            chapter_sort_order += 1
            store.update_library_reading_unit(
                str(unit["id"]),
                columns={
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
        int(track_number)
        if track_number is not None
        else _audio_episode_number(path) or 10**9,
        natural,
    )


def _merge_audio_raw_tags(
    queries: ImportLibraryQueries,
    media_version_id: str,
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = queries.get_latest_audio_tags_metadata(media_version_id)
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
    queries: ImportLibraryQueries,
    media_version_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = queries.list_audio_files_for_media_version(media_version_id)
    chapters = queries.list_audio_chapters_for_media_version(media_version_id)
    first_title_by_file: dict[str, str] = {}
    for chapter in chapters:
        file_id = str(chapter.get("fileId") or "")
        if file_id and file_id not in first_title_by_file:
            first_title_by_file[file_id] = str(chapter.get("title") or "")
    tracks = [
        {
            "fileId": file["id"],
            "title": first_title_by_file.get(str(file["id"]))
            or _title_from_file(Path(str(file["path"]))),
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


def _refresh_audio_progress_after_bundle_sync(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    media_version_id: str,
    volume_id: str,
) -> None:
    files = queries.list_audio_files_for_volume(media_version_id, volume_id)
    if not files:
        return
    offsets: dict[str, int] = {}
    elapsed = 0
    for file in files:
        offsets[str(file["id"])] = elapsed
        elapsed += max(0, int(file.get("durationMs") or 0))
    total_duration = elapsed

    progresses = queries.list_reading_progress_for_media_version(media_version_id)
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
            position_ms = max(
                0,
                int(
                    location.get("positionMs")
                    or extra.get("positionMs")
                    or progress.get("position")
                    or 0
                ),
            )
        except (TypeError, ValueError):
            position_ms = 0
        values: dict[str, Any] = {
            "volumeId": volume_id,
            "updatedAt": _now(),
        }
        if file_id in offsets:
            file_duration = max(
                0,
                int(
                    next(
                        file.get("durationMs") or 0
                        for file in files
                        if str(file["id"]) == file_id
                    )
                ),
            )
            absolute_position = offsets[file_id] + min(position_ms, file_duration)
            if total_duration > 0:
                calculated_percent = absolute_position / total_duration * 100
                values["percent"] = (
                    100.0
                    if float(progress.get("percent") or 0) >= 100
                    else min(calculated_percent, 99.9999)
                )
            location = {
                **location,
                "type": "audio",
                "volumeId": volume_id,
                "fileId": file_id,
                "positionMs": position_ms,
            }
            extra = {
                **extra,
                "volumeId": volume_id,
                "fileId": file_id,
                "positionMs": position_ms,
            }
            values["locationType"] = "audio"
            values["locationJson"] = json.dumps(
                location, ensure_ascii=False, separators=(",", ":")
            )
            values["extra"] = json.dumps(
                extra, ensure_ascii=False, separators=(",", ":")
            )
        store.update_library_reading_progress(str(progress["id"]), columns=values)


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


def _flat_audio_bundle_key(path: Path, title: str) -> str:
    source_group = f"{path.parent.resolve()}\0{_normalize_key(title)}"
    return _hash_text(source_group)[:24]


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
