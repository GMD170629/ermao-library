"""EPUB media import command."""

from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    SeriesVolumeInfo,
)
from app.modules.imports.application.identity_resolution import (
    EmbeddedIdentityMetadata,
    resolve_import_identity,
)
from app.modules.imports.application.import_support import (
    _attrs,
    _decode_xml_text,
    _ensure_work,
    _extract_isbn,
    _file_resource_key,
    _finalize_work_cover,
    _first_text,
    _hash_text,
    _id,
    _insert_identity_metadata,
    _now,
    _preferred_identifier,
    _sanitize_description,
    _select_volume_media_version,
    _source_group_key,
    _texts,
    _title_from_file,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)


def _import_epub(
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
    metadata = parse_epub_metadata(options.source_file_path)
    raw_metadata = metadata.get("rawMetadata")
    opf_title = (
        next(iter(raw_metadata.get("dc:title") or []), None)
        if isinstance(raw_metadata, dict)
        else None
    )
    opf_author = (
        next(iter(raw_metadata.get("dc:creator") or []), None)
        if isinstance(raw_metadata, dict)
        else None
    )
    identity = resolve_import_identity(
        identity,
        embedded=EmbeddedIdentityMetadata(
            title=str(opf_title or "").strip() or None,
            author=str(opf_author or "").strip() or None,
            source="epub_opf",
            confidence=0.95,
        ),
        requested_title=options.requested_title,
        requested_author=options.requested_author,
    )
    volume_info = (
        SeriesVolumeInfo(
            identity.title,
            identity.volume_index,
            f"第 {identity.volume_index:g} 卷",
            identity.author,
        )
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
    merge_key = _work_merge_key(
        "epub",
        identity.title,
        identity.author,
        metadata.get("identifier"),
        metadata.get("isbn"),
    )
    work, created = _ensure_work(
        store,
        queries,
        {
            "workId": identity.reused_work_id,
            "title": identity.title,
            "author": identity.author,
            "description": None,
            "workType": "EPUB",
            "tags": ["epub"],
            "mergeKey": merge_key,
            "origin": options.origin,
            "monitorFolderId": options.monitor_folder_id,
        },
    )
    if volume_info:
        source_key = _source_group_key(options, metadata["title"])
        source_path = options.source_file_path.resolve()
        media_version = _select_volume_media_version(
            queries,
            work["id"],
            "EPUB",
            source_key,
            volume_info.series_index,
            volume_info.title,
        )
        created_media_version = False
        if not media_version:
            created_media_version = True
            media_version = store.ensure_library_media_version(
                columns={
                    "id": _id(),
                    "workId": work["id"],
                    "mediaKind": "EBOOK",
                    "createdAt": _now(),
                    "updatedAt": _now(),
                },
            )
        cover_path = None
        try:
            sort_order = int(volume_info.series_index * 1000)
            volume = store.insert_library_volume(
                columns={
                    "id": _id(),
                    "mediaVersionId": media_version["id"],
                    "title": volume_info.title,
                    "volumeIndex": volume_info.series_index,
                    "sortOrder": sort_order,
                    "format": "EPUB",
                    "resourceKey": _file_resource_key("epub", source_path),
                    "monitorFolderId": options.monitor_folder_id,
                    "origin": options.origin,
                    "sourceGroupKey": source_key,
                    "description": metadata.get("description"),
                    "language": metadata.get("language"),
                    "publisher": metadata.get("publisher"),
                    "publishedAt": metadata.get("publishedAt"),
                    "identifier": metadata.get("identifier"),
                    "isbn": metadata.get("isbn"),
                    "sizeBytes": file_size,
                    "chapterCount": metadata["chapterCount"],
                    "coverPath": None,
                    "coverStatus": "PENDING",
                    "importStatus": "PARSING",
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
            store.update_import_task(
                task_id, columns={"message": "正在建立 EPUB 卷册记录"}
            )
            if metadata.get("coverPath"):
                cover_path = _extract_epub_cover(
                    settings,
                    source_path,
                    work["id"],
                    media_version["id"],
                    metadata,
                    volume["id"],
                )
            source_stat = source_path.stat()
            file = store.insert_library_file(
                columns={
                    "id": _id(),
                    "volumeId": volume["id"],
                    "path": str(source_path),
                    "filePathHash": _hash_text(str(source_path)),
                    "hashStatus": "PARTIAL_PENDING",
                    "kind": "EPUB",
                    "mimeType": "application/epub+zip",
                    "sizeBytes": file_size,
                    "mtimeMs": int(source_stat.st_mtime * 1000),
                    "sortOrder": sort_order,
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
            for chapter in metadata["chapters"]:
                store.insert_library_reading_unit(
                    columns={
                        "id": _id(),
                        "volumeId": volume["id"],
                        "fileId": file["id"],
                        "unitType": "chapter",
                        "title": chapter["title"],
                        "href": chapter["href"],
                        "mediaType": chapter.get("mediaType"),
                        "sortOrder": chapter["sortOrder"],
                        "metadataJson": json.dumps(
                            {
                                "idref": chapter.get("idref"),
                                "volumeIndex": volume_info.series_index,
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
                    "source": "epub_opf",
                    "rawJson": json.dumps(metadata["rawMetadata"], ensure_ascii=False),
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
                    "chapterCount": metadata["chapterCount"],
                    "updatedAt": _now(),
                },
            )
            store.update_library_volume(
                volume["id"],
                columns={
                    "sizeBytes": file_size,
                    "chapterCount": metadata["chapterCount"],
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
                "ebook",
                "epub",
                metadata["chapterCount"],
                "completed",
                False,
                (not created) or (not created_media_version),
                "new-epub-work"
                if created
                else "new-epub-version"
                if created_media_version
                else "same-epub-series",
            )
        except Exception:
            if cover_path:
                Path(cover_path).unlink(missing_ok=True)
            raise
    cover_path = None
    try:
        source_path = options.source_file_path.resolve()
        store.update_import_task(task_id, columns={"message": "正在建立 EPUB 记录"})
        media_version = store.ensure_library_media_version(
            columns={
                "id": _id(),
                "workId": work["id"],
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "mediaKind": "EBOOK",
                "format": "EPUB",
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        if metadata.get("coverPath"):
            cover_path = _extract_epub_cover(
                settings, source_path, work["id"], media_version["id"], metadata
            )
        stored_cover_path = cover_path or services.ensure_default_cover()
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "mediaVersionId": media_version["id"],
                "title": str(
                    metadata.get("title") or identity.title or source_path.stem
                ),
                "sortOrder": 0,
                "format": "EPUB",
                "resourceKey": _file_resource_key("epub", source_path),
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "description": metadata.get("description"),
                "language": metadata.get("language"),
                "publisher": metadata.get("publisher"),
                "publishedAt": metadata.get("publishedAt"),
                "identifier": metadata.get("identifier"),
                "isbn": metadata.get("isbn"),
                "sizeBytes": file_size,
                "chapterCount": metadata["chapterCount"],
                "coverPath": stored_cover_path,
                "coverStatus": services.cover_status(stored_cover_path),
                "importStatus": "PARSING",
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        source_stat = source_path.stat()
        file = store.insert_library_file(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "path": str(source_path),
                "filePathHash": _hash_text(str(source_path)),
                "hashStatus": "PARTIAL_PENDING",
                "kind": "EPUB",
                "mimeType": "application/epub+zip",
                "sizeBytes": file_size,
                "mtimeMs": int(source_stat.st_mtime * 1000),
                "sortOrder": 0,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        for chapter in metadata["chapters"]:
            store.insert_library_reading_unit(
                columns={
                    "id": _id(),
                    "volumeId": volume["id"],
                    "fileId": file["id"],
                    "unitType": "chapter",
                    "title": chapter["title"],
                    "href": chapter["href"],
                    "mediaType": chapter.get("mediaType"),
                    "sortOrder": chapter["sortOrder"],
                    "metadataJson": json.dumps(
                        {"idref": chapter.get("idref")}, ensure_ascii=False
                    ),
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
            )
        store.insert_library_metadata(
            columns={
                "id": _id(),
                "volumeId": volume["id"],
                "source": "epub_opf",
                "rawJson": json.dumps(metadata["rawMetadata"], ensure_ascii=False),
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
        )
        return ImportResult(
            work["id"],
            work["id"],
            media_version["id"],
            volume["id"],
            work["title"],
            "ebook",
            "epub",
            metadata["chapterCount"],
            "completed",
            False,
            not created,
            "new-work" if created else "same-epub-work",
        )
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


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


def _opf_items(opf_xml: str) -> list[dict[str, str]]:
    return [
        {
            "id": attrs.get("id"),
            "href": attrs.get("href"),
            "mediaType": attrs.get("media-type"),
            "properties": attrs.get("properties"),
        }
        for attrs in _attrs(opf_xml, "item")
    ]


def _opf_itemrefs(opf_xml: str) -> list[dict[str, str]]:
    return [{"idref": attrs.get("idref")} for attrs in _attrs(opf_xml, "itemref")]


def _epub_chapters(
    archive: zipfile.ZipFile,
    opf_path: str,
    opf_xml: str,
    manifest: list[dict[str, str]],
    spine: list[dict[str, str]],
) -> list[dict[str, Any]]:
    href_items = {
        _normalize_epub_path(item.get("href") or ""): item
        for item in manifest
        if item.get("href")
    }
    spine_attrs = _attrs(opf_xml, "spine")
    ncx_id = (spine_attrs[0] if spine_attrs else {}).get("toc")
    ncx = next((item for item in manifest if item.get("id") == ncx_id), None) or next(
        (
            item
            for item in manifest
            if "ncx" in str(item.get("mediaType") or "").lower()
        ),
        None,
    )
    if ncx and ncx.get("href"):
        chapters = _parse_ncx(
            _read_zip_text_optional(archive, _epub_zip_path(opf_path, ncx["href"])),
            opf_path,
            _epub_zip_path(opf_path, ncx["href"]),
            href_items,
        )
        if chapters:
            return chapters
    nav = next(
        (
            item
            for item in manifest
            if "nav" in str(item.get("properties") or "").split()
        ),
        None,
    )
    if nav and nav.get("href"):
        chapters = _parse_nav(
            _read_zip_text_optional(archive, _epub_zip_path(opf_path, nav["href"])),
            opf_path,
            _epub_zip_path(opf_path, nav["href"]),
            href_items,
        )
        if chapters:
            return chapters
    chapters = []
    by_id = {item.get("id"): item for item in manifest}
    for index, ref in enumerate(spine, start=1):
        item = by_id.get(ref.get("idref"))
        if item and item.get("href"):
            title = (
                _chapter_heading(archive, opf_path, item["href"]) or f"第 {index} 章"
            )
            chapters.append(
                {
                    "title": title,
                    "href": item["href"],
                    "idref": ref.get("idref"),
                    "mediaType": item.get("mediaType"),
                    "sortOrder": index,
                }
            )
    return chapters


def _parse_ncx(
    xml: str | None, opf_path: str, ncx_path: str, href_items: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    if not xml:
        return []
    entries = []
    for index, block in enumerate(
        re.findall(r"<navPoint\b[\s\S]*?</navPoint>", xml, re.IGNORECASE), start=1
    ):
        title = _first_text(block, "text") or ""
        src = (_attrs(block, "content")[0] if _attrs(block, "content") else {}).get(
            "src", ""
        )
        chapter = _chapter_from_toc(title, src, index, opf_path, ncx_path, href_items)
        if chapter:
            entries.append(chapter)
    return entries


def _parse_nav(
    xml: str | None, opf_path: str, nav_path: str, href_items: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    if not xml:
        return []
    entries = []
    nav_blocks = list(
        re.finditer(r"<nav\b([^>]*)>([\s\S]*?)</nav>", xml, re.IGNORECASE)
    )
    toc_block = next(
        (
            match.group(2)
            for match in nav_blocks
            if re.search(
                r"\b(?:epub:)?type\s*=\s*['\"][^'\"]*\btoc\b",
                match.group(1),
                re.IGNORECASE,
            )
            or re.search(
                r"\brole\s*=\s*['\"]doc-toc['\"]", match.group(1), re.IGNORECASE
            )
        ),
        nav_blocks[0].group(2) if nav_blocks else xml,
    )
    for index, match in enumerate(
        re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", toc_block, re.IGNORECASE), start=1
    ):
        title = _decode_xml_text(match.group(2))
        href = (
            _attrs(f"<a{match.group(1)}>", "a")[0]
            if _attrs(f"<a{match.group(1)}>", "a")
            else {}
        ).get("href", "")
        chapter = _chapter_from_toc(title, href, index, opf_path, nav_path, href_items)
        if chapter:
            entries.append(chapter)
    return entries


def _chapter_from_toc(
    title: str,
    href: str,
    index: int,
    opf_path: str,
    toc_path: str,
    href_items: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    if not title or not href:
        return None
    path_part, _, fragment = href.partition("#")
    absolute = _normalize_epub_path(str(PurePosixPath(toc_path).parent / path_part))
    relative = _normalize_epub_path(
        os.path.relpath(absolute, str(PurePosixPath(opf_path).parent)).replace(
            "\\", "/"
        )
    )
    full_href = f"{relative}#{fragment}" if fragment else relative
    item = href_items.get(_normalize_epub_path(relative))
    return {
        "title": title,
        "href": full_href,
        "idref": item.get("id") if item else None,
        "mediaType": item.get("mediaType") if item else None,
        "sortOrder": index,
    }


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
    meta_cover = next(
        (
            attrs.get("content")
            for attrs in _attrs(opf_xml, "meta")
            if attrs.get("name") == "cover"
        ),
        None,
    )
    return (
        next((item for item in manifest if item.get("id") == meta_cover), None)
        or next(
            (
                item
                for item in manifest
                if "cover-image" in str(item.get("properties") or "")
            ),
            None,
        )
        or next(
            (
                item
                for item in manifest
                if "image" in str(item.get("mediaType") or "")
                and re.search(
                    r"(cover|front|folder|封面)",
                    str(item.get("href") or ""),
                    re.IGNORECASE,
                )
            ),
            None,
        )
    )


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


def _extract_epub_cover(
    settings: ImportRuntimeConfig,
    staged: Path,
    work_id: str,
    media_version_id: str,
    metadata: dict[str, Any],
    volume_id: str | None = None,
) -> str | None:
    if not metadata.get("coverPath"):
        return None
    rel = _epub_zip_path(metadata["opfPath"], metadata["coverPath"])
    with zipfile.ZipFile(staged) as archive:
        resolved = _resolve_epub_archive_entry(archive, rel)
        if not resolved:
            return None
        cover = archive.read(resolved)
    ext = Path(unquote(metadata["coverPath"])).suffix or ".jpg"
    target = (
        settings.resolved_storage_root
        / "books"
        / work_id
        / media_version_id
        / (volume_id or "")
        / f"cover{ext}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(cover)
    return str(target)
