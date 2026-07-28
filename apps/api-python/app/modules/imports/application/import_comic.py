"""Comic (CBZ/ZIP) media import command."""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

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
    IMAGE_EXTS,
    _bracketed_folder_metadata,
    _clean_title_part,
    _ensure_work,
    _file_version_key,
    _finalize_work_primary,
    _first_text,
    _hash_text,
    _id,
    _ignored_entry,
    _insert_identity_metadata,
    _log_import,
    _natural_key,
    _next_edition_name,
    _now,
    _safe_entry_name,
    _select_volume_edition,
    _should_be_media_primary,
    _source_group_key,
    _split_tags,
    _title_from_file,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)

MAX_COMIC_INFO_BYTES = 1024 * 1024


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
    parsed = parse_comic_archive(options.source_file_path, options.original_name)
    comic_info = (
        parsed.get("comicInfo") if isinstance(parsed.get("comicInfo"), dict) else None
    )
    identity = resolve_import_identity(
        identity,
        embedded=(
            EmbeddedIdentityMetadata(
                title=str(parsed.get("title") or "").strip() or None,
                author=str(parsed.get("author") or "").strip() or None,
                source="comic_info",
                confidence=0.9,
            )
            if comic_info is not None
            else None
        ),
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
    merge_key = _work_merge_key("cbz", title, author)
    source_key = _source_group_key(options, title)
    volume_index = (volume_info or {}).get("seriesIndex")
    volume_title = (
        f"第 {volume_index:g} 卷"
        if volume_index is not None
        else ((parsed.get("comicInfo") or {}).get("title") or parsed["title"])
    )
    work, created = _ensure_work(
        store,
        queries,
        {
            "workId": identity.reused_work_id,
            "title": title,
            "author": author,
            "description": None,
            "workType": "COMIC",
            "tags": ["comic", parsed["format"]],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )
    edition = (
        _select_volume_edition(
            queries, work["id"], "COMIC", source_key, volume_index, volume_title
        )
        if volume_index is not None
        else None
    )
    created_edition = False
    if not edition:
        created_edition = True
        edition = store.insert_library_edition(
            columns={
                "id": _id(),
                "workId": work["id"],
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "mediaKind": "COMIC",
                "format": "COMIC",
                "versionName": _next_edition_name(
                    queries, work["id"], "漫画版本", "COMIC"
                ),
                "versionKey": f"comic:{source_key}"
                if volume_index is not None
                else _file_version_key("comic", options.source_file_path.resolve()),
                "sourceGroupKey": source_key,
                "description": parsed.get("description"),
                "publisher": (parsed.get("comicInfo") or {}).get("publisher"),
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                "primary": _should_be_media_primary(queries, work["id"], "COMIC"),
                "hidden": False,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
    cover_path = None
    try:
        sort_order = (
            int(volume_index * 1000)
            if volume_index is not None
            else queries.count_volumes_for_edition(str(edition["id"]))
        )
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "editionId": edition["id"],
                "title": volume_title,
                "volumeIndex": volume_index,
                "sortOrder": sort_order,
                "pageCount": parsed["pageCount"],
                "coverPath": None,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        source_path = options.source_file_path.resolve()
        store.update_import_task(task_id, columns={"message": "正在建立漫画记录"})
        file = store.insert_library_file(
            columns={
                "id": _id(),
                "editionId": edition["id"],
                "volumeId": volume["id"],
                "path": str(source_path),
                "filePathHash": _hash_text(str(source_path)),
                "hashStatus": "PARTIAL_PENDING",
                "kind": "COMIC",
                "mimeType": "application/vnd.comicbook+zip"
                if parsed["format"] == "cbz"
                else "application/zip",
                "sizeBytes": file_size,
                "mtimeMs": int(source_path.stat().st_mtime * 1000),
                "sortOrder": sort_order,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        try:
            cover_path = _extract_comic_cover(
                settings,
                source_path,
                work["id"],
                edition["id"],
                volume["id"],
                parsed["coverEntryPath"],
            )
        except Exception as exc:
            cover_path = None
            _log_import(
                store, task_id, "warning", f"comic cover extraction skipped: {exc}"
            )
        store.insert_library_metadata(
            columns={
                "id": _id(),
                "editionId": edition["id"],
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
        _insert_identity_metadata(store, edition["id"], identity)
        stored_cover_path = cover_path or services.ensure_default_cover()
        edition_cover_path = cover_path or edition.get("coverPath") or stored_cover_path
        store.update_library_volume(
            volume["id"],
            columns={
                "coverPath": stored_cover_path,
                "pageCount": parsed["pageCount"],
                "updatedAt": _now(),
            },
        )
        size_total = queries.sum_file_size_bytes_for_edition(str(edition["id"]))
        page_total = queries.sum_volume_page_count_for_edition(str(edition["id"]))
        store.update_library_edition(
            edition["id"],
            columns={
                "sizeBytes": int(size_total),
                "pageCount": int(page_total),
                "coverPath": edition_cover_path,
                "coverStatus": services.cover_status(edition_cover_path),
                "importStatus": "COMPLETED",
                "updatedAt": _now(),
            },
        )
        _finalize_work_primary(
            store,
            queries,
            services,
            work["id"],
            edition["id"],
            edition_cover_path,
        )
        return ImportResult(
            work["id"],
            work["id"],
            edition["id"],
            volume["id"],
            work["title"],
            "comic",
            parsed["format"],
            parsed["pageCount"],
            "completed",
            False,
            (not created) or (not created_edition),
            "new-comic-work"
            if created
            else "new-comic-version"
            if created_edition
            else "same-comic-series",
        )
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


def parse_comic_archive(path: Path, original_name: str | None = None) -> dict[str, Any]:
    fmt = "cbz" if path.suffix.lower() == ".cbz" else "zip"
    with zipfile.ZipFile(path) as archive:
        entries = [
            info
            for info in archive.infolist()
            if not info.is_dir() and _safe_entry_name(info.filename)
        ]
        images = [
            info
            for info in entries
            if Path(info.filename).suffix.lower() in IMAGE_EXTS
            and not _ignored_entry(info.filename)
        ]
        if not images:
            raise ValueError("漫画压缩包内没有可导入的图片")
        images.sort(key=lambda item: _natural_key(item.filename))
        comic_info_entry = next(
            (
                info
                for info in entries
                if info.filename.lower().endswith("comicinfo.xml")
                and info.file_size <= MAX_COMIC_INFO_BYTES
            ),
            None,
        )
        comic_info = (
            _parse_comic_info(archive.read(comic_info_entry).decode("utf-8", "replace"))
            if comic_info_entry
            else None
        )
        pages = [
            {
                "index": index + 1,
                "title": f"第 {index + 1} 页",
                "entryPath": info.filename,
                "mediaType": mimetypes.guess_type(info.filename)[0]
                or "application/octet-stream",
                "size": info.file_size,
            }
            for index, info in enumerate(images)
        ]
        cover_index = (comic_info or {}).get("coverImageIndex")
        cover = (
            pages[cover_index]
            if isinstance(cover_index, int) and 0 <= cover_index < len(pages)
            else next(
                (
                    page
                    for page in pages
                    if re.search(
                        r"(cover|folder|front|封面)", Path(page["entryPath"]).name, re.IGNORECASE
                    )
                ),
                pages[0],
            )
        )
        image_formats = sorted(
            {Path(page["entryPath"]).suffix.lower().lstrip(".") for page in pages}
        )
        raw_metadata = {
            "hasComicInfo": comic_info is not None,
            "pageCount": len(pages),
            "imageFormats": image_formats,
            "coverEntryPath": cover["entryPath"],
        }
        if comic_info:
            raw_metadata["comicInfo"] = comic_info.get("raw") or {}
        return {
            "title": (comic_info or {}).get("title")
            or _title_from_file(Path(original_name or path.name)),
            "author": (comic_info or {}).get("writer")
            or (comic_info or {}).get("penciller")
            or "未知作者",
            "description": (comic_info or {}).get("summary"),
            "format": fmt,
            "pageCount": len(pages),
            "coverEntryPath": cover["entryPath"],
            "pages": pages,
            "comicInfo": comic_info,
            "rawMetadata": raw_metadata,
        }


def parse_comic_volume_from_name(
    path: Path, original_name: str | None = None
) -> dict[str, Any] | None:
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
    parsed: dict[str, Any], path: Path, original_name: str | None = None
) -> dict[str, Any] | None:
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


def _parse_comic_info(xml: str) -> dict[str, Any]:
    raw = {}
    for tag in [
        "Title",
        "Series",
        "Volume",
        "Summary",
        "Writer",
        "Penciller",
        "Publisher",
        "Genre",
        "Tags",
    ]:
        value = _first_text(xml, tag)
        if value:
            raw[tag] = value
    volume = (
        float(raw["Volume"])
        if str(raw.get("Volume", "")).replace(".", "", 1).isdigit()
        else None
    )
    cover_match = re.search(
        r"<Page\b[^>]*(?:Type|type)=['\"](?:FrontCover|Cover)['\"][^>]*(?:Image|image)=['\"](\d+)['\"]",
        xml,
        re.IGNORECASE,
    )
    return {
        "title": raw.get("Title"),
        "series": raw.get("Series"),
        "volume": volume,
        "summary": raw.get("Summary"),
        "writer": raw.get("Writer"),
        "penciller": raw.get("Penciller"),
        "publisher": raw.get("Publisher"),
        "tags": _split_tags(raw.get("Tags") or raw.get("Genre")),
        "coverImageIndex": int(cover_match.group(1)) if cover_match else None,
        "raw": raw,
    }


def _extract_comic_cover(
    settings: ImportRuntimeConfig,
    staged: Path,
    work_id: str,
    edition_id: str,
    volume_id: str,
    entry: str,
) -> str:
    ext = Path(entry).suffix.lower() or ".jpg"
    target = (
        settings.resolved_storage_root
        / "books"
        / work_id
        / edition_id
        / volume_id
        / f"cover{ext}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(staged) as archive:
        with archive.open(entry, "r") as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
    return str(target)


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
