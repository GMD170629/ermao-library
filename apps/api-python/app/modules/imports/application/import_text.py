"""Unconverted-text media import and deferred-conversion completion."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
)
from app.modules.imports.application.import_support import (
    _file_version_key,
    _finalize_work_primary,
    _hash_text,
    _id,
    _insert_identity_metadata,
    _next_edition_name,
    _now,
    _should_be_media_primary,
    _ensure_work,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)


def _import_unconverted_text(
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
    """Register a supported text source without fabricating readable content.

    The original file becomes a normal library edition and remains downloadable,
    but has no reading units until the user requests the existing EPUB conversion
    pipeline from the work detail page.
    """

    source_path = options.source_file_path.resolve()
    source_format = ext.removeprefix(".").upper()
    merge_key = _work_merge_key("epub", identity.title, identity.author)
    work, created = _ensure_work(
        store,
        queries,
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
    store.update_import_task(
        task_id, columns={"message": f"正在建立 {source_format} 原始文件版本"}
    )
    edition = store.insert_library_edition(
        columns={
            "id": _id(),
            "workId": work["id"],
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "mediaKind": "EBOOK",
            "format": source_format,
            "versionName": _next_edition_name(
                queries, work["id"], f"{source_format} 原始文件", "EBOOK"
            ),
            "versionKey": _file_version_key(source_format.lower(), source_path),
            "sizeBytes": file_size,
            "chapterCount": 0,
            "coverStatus": "PENDING",
            "importStatus": "COMPLETED",
            "primary": _should_be_media_primary(queries, work["id"], "EBOOK"),
            "hidden": False,
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    store.insert_library_file(
        columns={
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
        }
    )
    store.insert_library_metadata(
        columns={
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
        }
    )
    _insert_identity_metadata(store, edition["id"], identity)
    stored_cover_path = services.ensure_default_cover()
    store.update_library_edition(
        edition["id"],
        columns={
            "coverPath": stored_cover_path,
            "coverStatus": services.cover_status(stored_cover_path),
            "updatedAt": _now(),
        },
    )
    _finalize_work_primary(
        store,
        queries,
        services,
        work["id"],
        edition["id"],
        stored_cover_path,
    )
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


def _complete_deferred_source_conversion(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    source_path: Path,
    result: ImportResult,
) -> None:
    source_edition = queries.find_deferred_source_edition(
        source_path=str(source_path.resolve()),
        work_id=result.work_id,
        result_edition_id=result.edition_id,
    )
    if not source_edition:
        return
    store.update_library_edition(
        str(source_edition["id"]),
        columns={"primary": False, "hidden": True, "updatedAt": _now()},
    )
    store.update_library_edition(
        result.edition_id,
        columns={"primary": True, "hidden": False, "updatedAt": _now()},
    )
    store.update_library_work(
        result.work_id,
        columns={
            "primaryEditionId": result.edition_id,
            "workType": "EPUB",
            "updatedAt": _now(),
        },
    )
