"""PDF media import command."""

from __future__ import annotations

import json
import logging

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
    _file_resource_key,
    _finalize_work_cover,
    _hash_text,
    _id,
    _insert_identity_metadata,
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
from app.modules.imports.domain.content_classification import (
    ContentEvidence,
    classify_content,
    normalize_media_kind_policy,
)
from app.modules.imports.domain.pdf_content import PdfContentKind

logger = logging.getLogger(__name__)


def _import_pdf(
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
    inspection = services.inspect_pdf(
        options.source_file_path,
        options.original_name,
    )
    source_path = options.source_file_path.resolve()
    source_stat = source_path.stat()
    embedded_series_name = str(inspection.raw_metadata.get("Series") or "").strip()
    embedded_volume_raw = inspection.raw_metadata.get("Volume")
    try:
        embedded_volume_index = (
            float(str(embedded_volume_raw))
            if embedded_volume_raw not in (None, "")
            else None
        )
    except ValueError:
        embedded_volume_index = None
    embedded_titles = titles_from_local_source(
        inspection.embedded_title,
        series_name=embedded_series_name or None,
        volume_index=embedded_volume_index,
    )
    identity, resolved_local = resolve_import_metadata(
        identity,
        embedded=PublicationMetadata(
            title=embedded_titles.work_title,
            volume_title=embedded_titles.volume_title,
            authors=(inspection.embedded_author,) if inspection.embedded_author else (),
            description=inspection.description,
            subjects=inspection.tags,
            series_name=embedded_series_name or None,
            series_index=embedded_volume_index,
            volume_index=embedded_titles.volume_index,
        ),
        sidecar=options.sidecar_metadata,
        source_order=options.local_metadata_priority,
        path_metadata=options.path_metadata,
        requested_title=options.requested_title,
        requested_author=options.requested_author,
    )
    is_image_only = inspection.content_kind is PdfContentKind.IMAGE_ONLY
    classification = classify_content(
        normalize_media_kind_policy(options.media_kind_policy),
        ContentEvidence(volume_format="PDF", image_only=is_image_only),
    )
    media_kind = classification.media_kind
    result_type = _classification_result_type(classification)
    topology_target = _bound_topology_target(queries, options)
    tags = ["pdf"]
    merge_key = _work_merge_key(identity.title)
    source_group_key = _source_group_key(options, identity.title)
    work, _created = _import_work(
        store,
        queries,
        options,
        {
            "title": identity.title,
            "author": identity.author,
            "description": None,
            "tags": tags,
            "mergeKey": merge_key,
            "origin": options.origin,
            "libraryId": options.library_id,
        },
        topology_target,
    )
    version = _import_version(store, work["id"], topology_target)
    cover_path = None
    try:
        store.update_import_task(task_id, columns={"message": "正在建立 PDF 记录"})
        media_version = _import_media_context(
            store,
            work_id=work["id"],
            media_kind=media_kind,
            format_name="PDF",
            library_id=options.library_id,
            origin=options.origin,
            target=topology_target,
        )
        volume_id = str(topology_target.volume["id"])
        release_import_transaction(unit_of_work)
        cover = services.publish_pdf_cover(
            settings.resolved_storage_root,
            source_path,
            str(work["id"]),
            str(media_version["id"]),
            volume_id,
        )
        cover_path = cover.path
        raw_metadata = dict(inspection.raw_metadata)
        if cover.rendered_page is not None:
            raw_metadata["coverRenderedFromPage"] = cover.rendered_page
        if cover.warning:
            raw_metadata["coverWarning"] = cover.warning
        stored_cover_path = cover_path or _prepared_default_cover(options)
        volume = _persist_import_volume(
            store,
            {
                "id": volume_id,
                "versionId": version["id"],
                "title": resolved_local.metadata.volume_title or identity.title,
                "volumeIndex": identity.volume_index,
                "sortOrder": (
                    int(identity.volume_index * 1000)
                    if identity.volume_index is not None
                    else 0
                ),
                "format": "PDF",
                "resourceKey": _file_resource_key("pdf", source_path),
                "sourceGroupKey": source_group_key,
                "libraryId": options.library_id,
                "origin": options.origin,
                "description": inspection.description,
                "sizeBytes": file_size,
                "pageCount": inspection.page_count,
                "chapterCount": len(inspection.chapters),
                "coverPath": stored_cover_path,
                "coverStatus": services.cover_status(stored_cover_path),
                "importStatus": "PARSING",
                **_classification_columns(classification),
                "createdAt": _now(),
                "updatedAt": _now(),
            },
            topology_target,
        )
        file = store.insert_library_file(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "path": str(source_path),
                "filePathHash": _hash_text(str(source_path)),
                "kind": "PDF",
                "mimeType": "application/pdf",
                "sizeBytes": file_size,
                "mtimeMs": int(source_stat.st_mtime * 1000),
                "sortOrder": 0,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        for index in range(1, max(1, inspection.page_count) + 1):
            store.insert_library_reading_unit(
                columns={
                    "id": _id(),
                    "volumeId": volume["id"],
                    "fileId": file["id"],
                    "unitType": "page",
                    "title": f"第 {index} 页",
                    "href": str(source_path),
                    "mediaType": "application/pdf",
                    "sortOrder": index,
                    "metadataJson": json.dumps(
                        {
                            "pageNumber": index,
                            "sourceFileName": options.original_name
                            or options.source_file_path.name,
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
                "source": "pdf",
                "rawJson": json.dumps(raw_metadata, ensure_ascii=False),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        _insert_identity_metadata(store, volume["id"], identity)
        store.update_library_volume(
            volume["id"],
            columns={
                "coverPath": stored_cover_path,
                "coverStatus": services.cover_status(stored_cover_path),
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
            stored_cover_path,
            _prepared_default_cover(options),
        )
        return ImportResult(
            str(work["id"]),
            str(work["id"]),
            str(media_version["id"]),
            str(volume["id"]),
            str(work["title"]),
            result_type,
            "pdf",
            inspection.page_count,
            "completed",
            False,
            False,
            "topology-bound",
            resolved_metadata=resolved_local.metadata,
            metadata_field_sources=resolved_local.field_sources,
            metadata_source_order=resolved_local.source_order,
        )
    except Exception:
        logger.debug("PDF import persistence failed", exc_info=True)
        raise
