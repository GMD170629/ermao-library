"""Original reflowable-source import and deferred-conversion completion."""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.modules.imports.application.commands import release_import_transaction
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
)
from app.modules.imports.application.identity_resolution import (
    resolve_import_metadata,
)
from app.modules.imports.application.import_support import (
    _classification_columns,
    _classification_result_type,
    _bound_topology_target,
    _ensure_implicit_version,
    _finalize_work_cover,
    _hash_text,
    _id,
    _import_media_context,
    _import_version,
    _import_work,
    _now,
    _persist_import_volume,
    _prepared_default_cover,
    _source_group_key,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    ImportUnitOfWork,
    LibraryImportStore,
)
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata
from app.modules.imports.domain.content_classification import (
    ContentEvidence,
    classify_content,
    normalize_media_kind_policy,
)

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
    unit_of_work: ImportUnitOfWork,
) -> ImportResult:
    """Refresh source metadata and invalidate navigation when content changes."""

    source_format = source_path.suffix.removeprefix(".").upper()
    if source_format not in REFLOWABLE_MIME_TYPES:
        return existing
    metadata = services.inspect_reflowable_book(source_path, source_format)
    file_rows = queries.list_library_files_by_paths([str(source_path.resolve())])
    if not file_rows:
        return existing
    file_row = file_rows[0]
    volume_id = str(file_row.get("volumeId") or existing.volume_id or "")
    volume = queries.get_volume_context_by_id(volume_id) if volume_id else None
    if volume is None:
        version = _ensure_implicit_version(store, existing.work_id)
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "versionId": version["id"],
                "title": source_path.stem,
                "format": source_format,
                "resourceKey": _hash_text(str(source_path)),
                "sortOrder": queries.count_volumes_for_media_version(
                    existing.media_version_id
                )
                * 1000,
                "chapterCount": None,
                "coverPath": None,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
    volume_id = str(volume["id"])
    file_id = str(file_row["id"])
    source_stat = source_path.stat()
    content_changed = int(
        file_row.get("sizeBytes") or -1
    ) != source_stat.st_size or int(file_row.get("mtimeMs") or -1) != int(
        source_stat.st_mtime * 1000
    )
    if not file_row.get("volumeId"):
        store.update_library_file(
            file_id,
            columns={"volumeId": volume_id, "updatedAt": _now()},
        )
    if content_changed:
        store.update_library_file(
            file_id,
            columns={
                "sizeBytes": source_stat.st_size,
                "mtimeMs": int(source_stat.st_mtime * 1000),
                "updatedAt": _now(),
            },
        )
    for unit in queries.list_reflowable_chapters_for_volume(volume_id):
        unit_id = unit.get("id")
        if unit_id:
            store.delete_library_reading_unit(str(unit_id))
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
    release_import_transaction(unit_of_work)
    cover_path = services.publish_reflowable_cover(
        settings.resolved_storage_root,
        existing.work_id,
        existing.media_version_id,
        volume_id,
        metadata,
    )
    volume_values: dict[str, object] = {
        "description": metadata.description,
        "language": metadata.language,
        "publishedAt": metadata.published_at,
        "identifier": metadata.identifier,
        "isbn": metadata.isbn,
        "chapterCount": None,
        "updatedAt": _now(),
    }
    if cover_path:
        volume_values.update(
            coverPath=cover_path,
            coverStatus=services.cover_status(cover_path),
        )
    store.update_library_volume(
        volume_id,
        columns=volume_values,
    )
    work = queries.get_work_by_id(existing.work_id) or {}
    current_title = str(work.get("title") or existing.title)
    current_author = str(work.get("author") or "")
    topology_owned = bool(work.get("sourceKey"))
    selected_title = (
        metadata.title
        if metadata.title and current_title == source_path.stem and not topology_owned
        else current_title
    )
    selected_author = (
        metadata.author
        if metadata.author and current_author in {"", "未知作者", "Unknown author"}
        else current_author
    )
    work_values: dict[str, object] = {"updatedAt": _now()}
    if selected_title != current_title or selected_author != current_author:
        merge_key = _work_merge_key(selected_title)
        work = queries.get_work_by_id(existing.work_id)
        library_id = str((work or {}).get("libraryId") or "")
        merge_conflict = (
            queries.get_work_by_merge_key(library_id, merge_key) if library_id else None
        )
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
        0,
        existing.import_status,
        True,
        existing.merged,
        "refreshed-native-metadata",
    )


def _reflowable_metadata_json(
    metadata: ReflowableBookMetadata,
    source_path: Path,
    source_format: str,
) -> str:
    return json.dumps(
        {
            **{
                key: value
                for key, value in metadata.raw_metadata.items()
                if key
                not in {"chapterSource", "navigationCount", "navigationFingerprint"}
            },
            "sourceFormat": source_format,
            "sourcePath": str(source_path),
            "readable": True,
            "title": metadata.title,
            "authors": metadata.authors,
            "language": metadata.language,
            "publishedAt": metadata.published_at,
            "identifier": metadata.identifier,
            "isbn": metadata.isbn,
            "description": metadata.description,
            "subjects": metadata.subjects,
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
    unit_of_work: ImportUnitOfWork,
) -> ImportResult:
    """Inspect and register an original source for the native reader."""

    source_path = options.source_file_path.resolve()
    source_stat = source_path.stat()
    source_format = ext.removeprefix(".").upper()
    metadata = services.inspect_reflowable_book(source_path, source_format)
    embedded_title = (
        None if metadata.raw_metadata.get("inspectionWarning") else metadata.title
    )
    embedded_titles = titles_from_local_source(
        embedded_title,
        series_name=metadata.series_name,
        volume_index=metadata.series_index,
    )
    identity, resolved_local = resolve_import_metadata(
        identity,
        embedded=PublicationMetadata(
            title=embedded_titles.work_title,
            volume_title=embedded_titles.volume_title,
            authors=metadata.authors,
            description=metadata.description,
            subjects=metadata.subjects,
            series_name=metadata.series_name,
            series_index=metadata.series_index,
            volume_index=embedded_titles.volume_index,
            language=metadata.language,
            publisher=metadata.publisher,
            published_at=metadata.published_at,
            identifier=metadata.identifier,
            isbn=metadata.isbn,
        ),
        sidecar=options.sidecar_metadata,
        source_order=options.local_metadata_priority,
        path_metadata=options.path_metadata,
        requested_title=options.requested_title,
        requested_author=options.requested_author,
    )
    classification = classify_content(
        normalize_media_kind_policy(options.media_kind_policy),
        ContentEvidence(
            volume_format=source_format,
            subjects=tuple(metadata.subjects),
            title=identity.title,
        ),
    )
    topology_target = _bound_topology_target(queries, options)
    merge_key = _work_merge_key(identity.title)
    work, created = _import_work(
        store,
        queries,
        options,
        {
            "title": identity.title,
            "author": identity.author,
            "description": metadata.description,
            "tags": ["ebook", source_format.lower(), *metadata.subjects],
            "mergeKey": merge_key,
            "origin": options.origin,
            "libraryId": options.library_id,
        },
        topology_target,
    )
    version = _import_version(store, work["id"], topology_target)
    volume_title = resolved_local.metadata.volume_title or identity.title
    volume_index = identity.volume_index
    source_group_key = _source_group_key(options, identity.title)
    store.update_import_task(
        task_id, columns={"message": f"正在建立 {source_format} 原始文件卷册"}
    )
    media_version = _import_media_context(
        store,
        work_id=work["id"],
        media_kind=classification.media_kind,
        format_name=source_format,
        library_id=options.library_id,
        origin=options.origin,
        target=topology_target,
    )
    mime_type = REFLOWABLE_MIME_TYPES[source_format]
    volume = _persist_import_volume(
        store,
        {
            "id": (
                str(topology_target.volume["id"])
                if topology_target is not None
                else _id()
            ),
            "versionId": version["id"],
            "title": volume_title,
            "volumeIndex": volume_index,
            "sortOrder": (
                int(volume_index * 1000)
                if volume_index is not None
                else queries.count_volumes_for_media_version(str(media_version["id"]))
                * 1000
            ),
            "format": source_format,
            "resourceKey": _hash_text(str(source_path)),
            "sourceGroupKey": source_group_key,
            "libraryId": options.library_id,
            "origin": options.origin,
            "description": metadata.description,
            "language": metadata.language,
            "publishedAt": metadata.published_at,
            "identifier": metadata.identifier,
            "isbn": metadata.isbn,
            "sizeBytes": file_size,
            "chapterCount": None,
            "coverPath": None,
            "coverStatus": "PENDING",
            "importStatus": "COMPLETED",
            **_classification_columns(classification),
            "createdAt": _now(),
            "updatedAt": _now(),
        },
        topology_target,
    )
    store.insert_library_file(
        columns={
            "id": _id(),
            "volumeId": volume["id"],
            "path": str(source_path),
            "filePathHash": _hash_text(str(source_path)),
            "kind": source_format,
            "mimeType": mime_type,
            "sizeBytes": file_size,
            "mtimeMs": int(source_stat.st_mtime * 1000),
            "sortOrder": 0,
            "createdAt": _now(),
            "updatedAt": _now(),
        }
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
    release_import_transaction(unit_of_work)
    cover_path = services.publish_reflowable_cover(
        settings.resolved_storage_root,
        str(work["id"]),
        str(media_version["id"]),
        str(volume["id"]),
        metadata,
    )
    stored_cover_path = cover_path or _prepared_default_cover(options)
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
        _prepared_default_cover(options),
    )
    return ImportResult(
        str(work["id"]),
        str(work["id"]),
        str(media_version["id"]),
        str(volume["id"]),
        str(work["title"]),
        _classification_result_type(classification),
        source_format.lower(),
        0,
        "completed",
        False,
        topology_target is None and not created,
        "topology-bound"
        if topology_target is not None
        else "native-reflowable-metadata",
        resolved_metadata=resolved_local.metadata,
        metadata_field_sources=resolved_local.field_sources,
        metadata_source_order=resolved_local.source_order,
    )
