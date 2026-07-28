"""PDF media import command."""

from __future__ import annotations

import json
import re
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
    _ensure_work,
    _file_version_key,
    _finalize_work_primary,
    _hash_text,
    _id,
    _insert_identity_metadata,
    _next_edition_name,
    _now,
    _sanitize_description,
    _should_be_media_primary,
    _split_tags,
    _title_from_file,
    _work_merge_key,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)


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
) -> ImportResult:
    metadata = parse_pdf_metadata(options.source_file_path, options.original_name)
    raw_metadata = metadata.get("rawMetadata")
    identity = resolve_import_identity(
        identity,
        embedded=EmbeddedIdentityMetadata(
            title=(
                str(raw_metadata.get("Title") or "").strip() or None
                if isinstance(raw_metadata, dict)
                else None
            ),
            author=(
                str(raw_metadata.get("Author") or "").strip() or None
                if isinstance(raw_metadata, dict)
                else None
            ),
            source="pdf_metadata",
            confidence=0.9,
        ),
        requested_title=options.requested_title,
        requested_author=options.requested_author,
    )
    merge_key = _work_merge_key("pdf", identity.title, identity.author)
    work, created = _ensure_work(
        store,
        queries,
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
        store.update_import_task(task_id, columns={"message": "正在建立 PDF 记录"})
        edition = store.insert_library_edition(
            columns={
                "id": _id(),
                "workId": work["id"],
                "monitorFolderId": options.monitor_folder_id,
                "origin": options.origin,
                "mediaKind": "EBOOK",
                "format": "PDF",
                "versionName": _next_edition_name(queries, work["id"], "PDF", "EBOOK"),
                "versionKey": _file_version_key("pdf", source_path),
                "description": metadata.get("description"),
                "sizeBytes": file_size,
                "pageCount": metadata["pageCount"],
                "coverStatus": "PENDING",
                "importStatus": "PARSING",
                "primary": _should_be_media_primary(queries, work["id"], "EBOOK"),
                "hidden": False,
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        cover_path = _extract_pdf_cover(
            settings, source_path, work["id"], edition["id"], metadata
        )
        stored_cover_path = cover_path or services.ensure_default_cover()
        volume = store.insert_library_volume(
            columns={
                "id": _id(),
                "editionId": edition["id"],
                "title": "PDF",
                "sortOrder": 0,
                "pageCount": metadata["pageCount"],
                "coverPath": stored_cover_path,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        file = store.insert_library_file(
            columns={
                "id": _id(),
                "editionId": edition["id"],
                "volumeId": volume["id"],
                "path": str(source_path),
                "filePathHash": _hash_text(str(source_path)),
                "hashStatus": "PARTIAL_PENDING",
                "kind": "PDF",
                "mimeType": "application/pdf",
                "sizeBytes": file_size,
                "mtimeMs": int(source_path.stat().st_mtime * 1000),
                "sortOrder": 0,
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        for index in range(1, max(1, metadata["pageCount"]) + 1):
            store.insert_library_reading_unit(
                columns={
                    "id": _id(),
                    "editionId": edition["id"],
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
                "editionId": edition["id"],
                "source": "pdf",
                "rawJson": json.dumps(metadata["rawMetadata"], ensure_ascii=False),
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        _insert_identity_metadata(store, edition["id"], identity)
        store.update_library_edition(
            edition["id"],
            columns={
                "coverPath": stored_cover_path,
                "coverStatus": services.cover_status(stored_cover_path),
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
            stored_cover_path,
        )
        return ImportResult(
            work["id"],
            work["id"],
            edition["id"],
            volume["id"],
            work["title"],
            "ebook",
            "pdf",
            metadata["pageCount"],
            "completed",
            False,
            not created,
            "new-pdf-work" if created else "same-pdf-work",
        )
    except Exception:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)
        raise


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
    return {
        "title": title,
        "author": author,
        "description": description,
        "tags": tags,
        "pageCount": page_count,
        "rawMetadata": raw_metadata,
    }


def _pdf_inline_metadata(path: Path) -> dict[str, str]:
    try:
        content = path.read_bytes()
    except OSError:
        return {}
    metadata: dict[str, str] = {}
    for key in ["Title", "Author", "Subject", "Keywords"]:
        match = re.search(
            rb"/" + key.encode("ascii") + rb"\s*\(([^()]*)\)", content, re.DOTALL
        )
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


def _extract_pdf_cover(
    settings: ImportRuntimeConfig,
    staged: Path,
    work_id: str,
    edition_id: str,
    metadata: dict[str, Any],
) -> str | None:
    target = (
        settings.resolved_storage_root / "books" / work_id / edition_id / "cover.jpg"
    )
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
