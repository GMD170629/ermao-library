"""Comic (CBZ/ZIP/CBR/RAR) media import command."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.modules.imports.application.comic_types import ComicArchiveInspection
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
)
from app.modules.imports.application.errors import ComicArchiveError
from app.modules.imports.application.identity_resolution import (
    resolve_import_metadata,
)
from app.modules.imports.application.import_support import (
    _bracketed_folder_metadata,
    _classification_columns,
    _classification_result_type,
    _clean_title_part,
    _ensure_work,
    _file_resource_key,
    _finalize_work_cover,
    _hash_text,
    _id,
    _insert_identity_metadata,
    _log_import,
    _now,
    _select_volume_media_version,
    _source_group_key,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)
from app.modules.imports.domain.content_classification import (
    ContentEvidence,
    classify_content,
    normalize_media_kind_policy,
)


def _import_comic(
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
    parsed = services.inspect_comic_archive(
        options.source_file_path, options.original_name
    )
    comic_info = (
        parsed.get("comicInfo") if isinstance(parsed.get("comicInfo"), dict) else None
    )
    archive_format = str(
        parsed.get("format") or ext.removeprefix(".") or "COMIC"
    ).upper()
    classification = classify_content(
        normalize_media_kind_policy(options.media_kind_policy),
        ContentEvidence(
            volume_format=archive_format,
            has_comic_info=comic_info is not None,
        ),
    )
    comic_titles = (
        titles_from_local_source(
            str(comic_info.get("title") or "").strip() or None,
            series_name=str(comic_info.get("series") or "").strip() or None,
            volume_index=comic_info.get("volume"),
        )
        if comic_info is not None
        else None
    )
    embedded_metadata = (
        PublicationMetadata(
            title=comic_titles.work_title,
            volume_title=comic_titles.volume_title,
            authors=(str(parsed.get("author") or "").strip(),)
            if str(parsed.get("author") or "").strip()
            else (),
            description=str(parsed.get("description") or "").strip() or None,
            subjects=tuple(comic_info.get("tags") or ()),
            series_name=str(comic_info.get("series") or "").strip() or None,
            series_index=comic_info.get("volume"),
            volume_index=comic_titles.volume_index,
            publisher=str(comic_info.get("publisher") or "").strip() or None,
        )
        if comic_info is not None
        else None
    )
    identity, resolved_local = resolve_import_metadata(
        identity,
        embedded=embedded_metadata,
        sidecar=options.sidecar_metadata,
        source_order=options.local_metadata_priority,
        path_metadata=options.path_metadata,
        requested_title=options.requested_title,
        requested_author=options.requested_author,
    )
    volume_info = (
        {
            "seriesName": identity.title,
            "seriesIndex": identity.volume_index,
            "author": identity.author,
        }
        if identity.volume_index is not None
        else None
    )
    title = identity.title
    author = identity.author
    merge_key = _work_merge_key(title)
    source_key = _source_group_key(options, title)
    volume_index = (volume_info or {}).get("seriesIndex")
    volume_title = resolved_local.metadata.volume_title or identity.title
    work, created = _ensure_work(
        store,
        queries,
        {
            "title": title,
            "author": author,
            "description": None,
            "tags": ["comic", parsed["format"]],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )
    media_version = (
        _select_volume_media_version(
            queries,
            work["id"],
            archive_format,
            source_key,
        )
        if volume_index is not None
        else None
    )
    if media_version and media_version.get("mediaKind") != classification.media_kind:
        media_version = None
    created_media_version = False
    if not media_version:
        created_media_version = True
        media_version = store.ensure_library_media_version(
            columns={
                "id": _id(),
                "workId": work["id"],
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "mediaKind": classification.media_kind,
                "format": archive_format,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
    cover_path = None
    try:
        sort_order = (
            int(volume_index * 1000)
            if volume_index is not None
            else queries.count_volumes_for_media_version(str(media_version["id"]))
        )
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "mediaVersionId": media_version["id"],
                "title": volume_title,
                "volumeIndex": volume_index,
                "sortOrder": sort_order,
                "format": archive_format,
                "resourceKey": _file_resource_key(
                    "comic", options.source_file_path.resolve()
                ),
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "sourceGroupKey": source_key,
                "description": parsed.get("description"),
                "sizeBytes": file_size,
                "pageCount": parsed["pageCount"],
                "coverPath": None,
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                **_classification_columns(classification),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        source_path = options.source_file_path.resolve()
        store.update_import_task(task_id, columns={"message": "正在建立漫画记录"})
        store.insert_library_file(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "path": str(source_path),
                "filePathHash": _hash_text(str(source_path)),
                "hashStatus": "PARTIAL_PENDING",
                "kind": "COMIC",
                "mimeType": _comic_archive_media_type(parsed["format"]),
                "sizeBytes": file_size,
                "mtimeMs": int(source_path.stat().st_mtime * 1000),
                "sortOrder": sort_order,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        try:
            cover_path = services.publish_comic_cover(
                settings.resolved_storage_root,
                source_path,
                work["id"],
                media_version["id"],
                volume["id"],
                parsed["coverEntryPath"],
            )
        except ComicArchiveError:
            raise
        # Optional cover publication is a containment boundary for heterogeneous
        # archive/image adapter failures; the imported comic remains readable.
        except Exception as exc:  # noqa: BLE001
            cover_path = None
            _log_import(
                store, task_id, "warning", f"comic cover extraction skipped: {exc}"
            )
        store.insert_library_metadata(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "source": "comic_info" if parsed.get("comicInfo") else "system",
                "rawJson": json.dumps(
                    {
                        **parsed["rawMetadata"],
                        "volumeIndex": volume_index,
                        "sourceFileName": options.original_name
                        or options.source_file_path.name,
                    },
                    ensure_ascii=False,
                ),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        _insert_identity_metadata(store, volume["id"], identity)
        stored_cover_path = cover_path or services.ensure_default_cover()
        media_version_cover_path = (
            cover_path or media_version.get("coverPath") or stored_cover_path
        )
        store.update_library_volume(
            volume["id"],
            columns={
                "coverPath": stored_cover_path,
                "pageCount": parsed["pageCount"],
                "updatedAt": _now(),
            },
        )
        store.update_library_volume(
            volume["id"],
            columns={
                "sizeBytes": file_size,
                "pageCount": parsed["pageCount"],
                "coverPath": media_version_cover_path,
                "coverStatus": services.cover_status(media_version_cover_path),
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
            media_version_cover_path,
        )
        return ImportResult(
            work["id"],
            work["id"],
            media_version["id"],
            volume["id"],
            work["title"],
            _classification_result_type(classification),
            parsed["format"],
            parsed["pageCount"],
            "completed",
            False,
            (not created) or (not created_media_version),
            "new-comic-work"
            if created
            else "new-comic-version"
            if created_media_version
            else "same-comic-series",
            resolved_metadata=resolved_local.metadata,
            metadata_field_sources=resolved_local.field_sources,
            metadata_source_order=resolved_local.source_order,
        )
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


def parse_comic_volume_from_name(
    path: Path, original_name: str | None = None
) -> dict[str, object] | None:
    source = original_name or path.name
    base = Path(source).stem
    parent = _comic_parent_title(path, "WATCH")
    for pattern in [
        r"^(?:vol\.?|volume)\s*(\d+(?:\.\d+)?)$",
        r"^v\s*(\d+(?:\.\d+)?)$",
        r"^(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
    ]:
        match = re.match(pattern, base.strip(), re.IGNORECASE)
        if match and parent:
            index = float(match.group(1))
            author = _comic_parent_author(path)
            result = {
                "seriesName": parent,
                "seriesIndex": index,
                "title": f"{parent} ({index:g})",
            }
            if author:
                result["author"] = author
            return result
    for pattern in [
        r"^(.+?)\s*[\(（［\[]\s*(\d+(?:\.\d+)?)\s*[\)）］\]]\s*$",
        r"^(.+?)\s*(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)\s*$",
        r"^(.+?)\s*(?:vol\.?|volume)\s*(\d+(?:\.\d+)?)\s*$",
        r"^(.+?)\s+v(\d+(?:\.\d+)?)\s*$",
    ]:
        match = re.match(pattern, base, re.IGNORECASE)
        if match:
            series = _clean_title_part(match.group(1))
            index = float(match.group(2))
            if series:
                return {
                    "seriesName": series,
                    "seriesIndex": index,
                    "title": f"{series} ({index:g})",
                }
    return None


def parse_comic_volume_info(
    parsed: ComicArchiveInspection, path: Path, original_name: str | None = None
) -> dict[str, object] | None:
    comic_info = (
        parsed.get("comicInfo") if isinstance(parsed.get("comicInfo"), dict) else {}
    )
    if comic_info.get("series") and comic_info.get("volume") is not None:
        return {
            "seriesName": comic_info["series"],
            "seriesIndex": comic_info["volume"],
            "title": f"{comic_info['series']} ({comic_info['volume']:g})",
        }
    return parse_comic_volume_from_name(path, original_name)


def _comic_archive_media_type(fmt: str) -> str:
    return {
        "cbr": "application/vnd.comicbook-rar",
        "cbz": "application/vnd.comicbook+zip",
        "rar": "application/vnd.rar",
        "zip": "application/zip",
    }[fmt]


def _comic_parent_title(path: Path, origin: str) -> str | None:
    if origin != "WATCH":
        return None
    parent = _clean_title_part(path.parent.name)
    if not parent or parent.lower() in {
        ".",
        "/",
        "books",
        "library",
        "comics",
        "comic",
        "manga",
        "漫画",
    }:
        return None
    return (_bracketed_folder_metadata(parent) or {}).get("title") or parent


def _comic_parent_author(path: Path) -> str | None:
    parent = _clean_title_part(path.parent.name)
    return (_bracketed_folder_metadata(parent) or {}).get("author")
