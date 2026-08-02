"""Original reflowable-source import and deferred-conversion completion."""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
)
from app.modules.imports.application.identity_resolution import (
    EmbeddedIdentityMetadata,
    resolve_import_identity,
)
from app.modules.imports.application.import_support import (
    _ensure_work,
    _finalize_work_cover,
    _hash_text,
    _id,
    _now,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata

REFLOWABLE_MIME_TYPES = {
    "MOBI": "application/x-mobipocket-ebook",
    "AZW": "application/vnd.amazon.ebook",
    "AZW3": "application/vnd.amazon.ebook",
    "PRC": "application/x-mobipocket-ebook",
    "FB2": "application/x-fictionbook+xml",
    "TXT": "text/plain",
}


def refresh_existing_reflowable_source(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    source_path: Path,
    existing: ImportResult,
) -> ImportResult:
    """Reinspect a source and deterministically replace its exact navigation."""

    source_format = source_path.suffix.removeprefix(".").upper()
    if source_format not in REFLOWABLE_MIME_TYPES:
        return existing
    metadata = services.inspect_reflowable_book(source_path, source_format)
    if not metadata.chapters and metadata.cover is None and metadata.title is None:
        return existing
    file_rows = queries.list_library_files_by_paths([str(source_path.resolve())])
    if not file_rows:
        return existing
    file_row = file_rows[0]
    volume_id = str(file_row.get("volumeId") or existing.volume_id or "")
    volume = queries.get_volume_context_by_id(volume_id) if volume_id else None
    if volume is None:
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "mediaVersionId": existing.media_version_id,
                "title": metadata.title or existing.title,
                "format": source_format,
                "resourceKey": _hash_text(str(source_path)),
                "sortOrder": queries.count_volumes_for_media_version(
                    existing.media_version_id
                )
                * 1000,
                "chapterCount": len(metadata.chapters),
                "coverPath": None,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
    volume_id = str(volume["id"])
    file_id = str(file_row["id"])
    if not file_row.get("volumeId"):
        store.update_library_file(
            file_id,
            columns={"volumeId": volume_id, "updatedAt": _now()},
        )
    for unit in queries.list_reflowable_chapters_for_volume(volume_id):
        unit_id = unit.get("id")
        if unit_id:
            store.delete_library_reading_unit(str(unit_id))
    _insert_reflowable_chapters(
        store,
        volume_id,
        file_id,
        source_format,
        metadata,
    )
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume_id,
            "source": "reflowable_source",
            "rawJson": _reflowable_metadata_json(metadata, source_path, source_format),
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    cover_path = services.publish_reflowable_cover(
        settings.resolved_storage_root,
        existing.work_id,
        existing.media_version_id,
        metadata,
    )
    volume_values: dict[str, object] = {
        "description": metadata.description,
        "language": metadata.language,
        "publisher": metadata.publisher,
        "publishedAt": metadata.published_at,
        "identifier": metadata.identifier,
        "isbn": metadata.isbn,
        "chapterCount": len(metadata.chapters),
        "updatedAt": _now(),
    }
    if cover_path:
        volume_values.update(
            coverPath=cover_path,
            coverStatus=services.cover_status(cover_path),
        )
    store.update_library_volume(
        volume_id,
        columns={
            **volume_values,
            "chapterCount": len(metadata.chapters),
            "updatedAt": _now(),
        },
    )
    work = queries.get_work_by_id(existing.work_id) or {}
    current_title = str(work.get("title") or existing.title)
    current_author = str(work.get("author") or "")
    selected_title = (
        metadata.title
        if metadata.title and current_title == source_path.stem
        else current_title
    )
    selected_author = (
        metadata.author
        if metadata.author and current_author in {"", "未知作者", "Unknown author"}
        else current_author
    )
    work_values: dict[str, object] = {"updatedAt": _now()}
    if selected_title != current_title or selected_author != current_author:
        merge_key = _work_merge_key("epub", selected_title, selected_author)
        merge_conflict = queries.get_work_by_merge_key(merge_key)
        work_values.update(
            title=selected_title,
            author=selected_author,
        )
        if merge_conflict is None or str(merge_conflict["id"]) == existing.work_id:
            work_values["mergeKey"] = merge_key
    if cover_path:
        work_values.update(
            coverPath=cover_path,
            coverStatus=services.cover_status(cover_path),
        )
    store.update_library_work(existing.work_id, columns=work_values)
    return ImportResult(
        existing.book_id,
        existing.work_id,
        existing.media_version_id,
        volume_id,
        selected_title,
        existing.type,
        existing.format,
        len(metadata.chapters),
        existing.import_status,
        True,
        existing.merged,
        "refreshed-native-metadata",
    )


def _insert_reflowable_chapters(
    store: LibraryImportStore,
    volume_id: str,
    file_id: str,
    source_format: str,
    metadata: ReflowableBookMetadata,
) -> None:
    mime_type = REFLOWABLE_MIME_TYPES[source_format]
    for index, chapter in enumerate(metadata.chapters):
        store.insert_library_reading_unit(
            columns={
                "id": _id(),
                "volumeId": volume_id,
                "fileId": file_id,
                "unitType": "chapter",
                "title": chapter.title,
                "href": chapter.href,
                "mediaType": mime_type,
                "sortOrder": index,
                "metadataJson": json.dumps(
                    {
                        "exactNavigation": True,
                        "level": chapter.level,
                        "navigationKey": chapter.navigation_key,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )


def _reflowable_metadata_json(
    metadata: ReflowableBookMetadata,
    source_path: Path,
    source_format: str,
) -> str:
    return json.dumps(
        {
            **metadata.raw_metadata,
            "sourceFormat": source_format,
            "sourcePath": str(source_path),
            "readable": True,
            "title": metadata.title,
            "authors": metadata.authors,
            "language": metadata.language,
            "publisher": metadata.publisher,
            "publishedAt": metadata.published_at,
            "identifier": metadata.identifier,
            "isbn": metadata.isbn,
            "description": metadata.description,
            "subjects": metadata.subjects,
            "chapters": [
                {
                    "title": chapter.title,
                    "href": chapter.href,
                    "level": chapter.level,
                    "navigationKey": chapter.navigation_key,
                }
                for chapter in metadata.chapters
            ],
            "coverEmbedded": metadata.cover is not None,
        },
        ensure_ascii=False,
    )


def _import_reflowable_source(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    settings: ImportRuntimeConfig,
    options: ImportOptions,
    task_id: str,
    file_size: int,
    ext: str,
    identity: BookIdentityDTO,
) -> ImportResult:
    """Inspect and register an original source for the native reader."""

    source_path = options.source_file_path.resolve()
    source_format = ext.removeprefix(".").upper()
    metadata = services.inspect_reflowable_book(source_path, source_format)
    identity = resolve_import_identity(
        identity,
        embedded=EmbeddedIdentityMetadata(
            title=metadata.title,
            author=metadata.author,
            source="reflowable_metadata",
            confidence=0.95,
        ),
        requested_title=options.requested_title,
        requested_author=options.requested_author,
    )
    merge_key = _work_merge_key("epub", identity.title, identity.author)
    work, created = _ensure_work(
        store,
        queries,
        {
            "workId": identity.reused_work_id,
            "title": identity.title,
            "author": identity.author,
            "description": metadata.description,
            "workType": source_format,
            "tags": ["ebook", source_format.lower(), *metadata.subjects],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )
    store.update_import_task(
        task_id, columns={"message": f"正在建立 {source_format} 原始文件卷册"}
    )
    media_version = store.ensure_library_media_version(
        columns={
            "id": _id(),
            "workId": work["id"],
            "mediaKind": "EBOOK",
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    mime_type = REFLOWABLE_MIME_TYPES[source_format]
    volume = store.insert_library_volume(
        columns={
            "id": _id(),
            "mediaVersionId": media_version["id"],
            "title": identity.title,
            "sortOrder": queries.count_volumes_for_media_version(
                str(media_version["id"])
            )
            * 1000,
            "format": source_format,
            "resourceKey": _hash_text(str(source_path)),
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "description": metadata.description,
            "language": metadata.language,
            "publisher": metadata.publisher,
            "publishedAt": metadata.published_at,
            "identifier": metadata.identifier,
            "isbn": metadata.isbn,
            "sizeBytes": file_size,
            "chapterCount": len(metadata.chapters),
            "coverPath": None,
            "coverStatus": "PENDING",
            "importStatus": "COMPLETED",
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    file = store.insert_library_file(
        columns={
            "id": _id(),
            "volumeId": volume["id"],
            "path": str(source_path),
            "filePathHash": _hash_text(str(source_path)),
            "hashStatus": "PARTIAL_PENDING",
            "kind": source_format,
            "mimeType": mime_type,
            "sizeBytes": file_size,
            "mtimeMs": int(source_path.stat().st_mtime * 1000),
            "sortOrder": 0,
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    _insert_reflowable_chapters(
        store,
        str(volume["id"]),
        str(file["id"]),
        source_format,
        metadata,
    )
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume["id"],
            "source": "reflowable_source",
            "rawJson": _reflowable_metadata_json(metadata, source_path, source_format),
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
    cover_path = services.publish_reflowable_cover(
        settings.resolved_storage_root,
        str(work["id"]),
        str(volume["id"]),
        metadata,
    )
    stored_cover_path = cover_path or services.ensure_default_cover()
    store.update_library_volume(
        str(volume["id"]),
        columns={"coverPath": stored_cover_path, "updatedAt": _now()},
    )
    _finalize_work_cover(
        store,
        queries,
        services,
        str(work["id"]),
        str(media_version["id"]),
        stored_cover_path,
    )
    return ImportResult(
        str(work["id"]),
        str(work["id"]),
        str(media_version["id"]),
        str(volume["id"]),
        str(work["title"]),
        "ebook",
        source_format.lower(),
        len(metadata.chapters),
        "completed",
        False,
        not created,
        "native-reflowable-metadata",
    )


def _complete_deferred_source_conversion(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    source_path: Path,
    result: ImportResult,
) -> None:
    source_volume = queries.find_deferred_source_volume(
        source_path=str(source_path.resolve()),
        work_id=result.work_id,
        result_volume_id=result.volume_id,
    )
    if not source_volume or not result.volume_id:
        return
    store.update_library_volume(
        result.volume_id,
        columns={
            "derivedFromVolumeId": source_volume["id"],
            "updatedAt": _now(),
        },
    )
