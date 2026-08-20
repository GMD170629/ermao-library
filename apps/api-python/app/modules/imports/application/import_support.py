"""Shared helpers used across media-specific import commands.

Pure parsing/naming utilities plus small store/queries-bound helpers that are
not specific to one media format (EPUB/PDF/Comic/Audio/Text).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from app.core.time import now_timestamp_ms
from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    SeriesVolumeInfo,
)
from app.modules.imports.application.errors import ImportExecutionError
from app.modules.imports.application.identity_policy import (
    normalize_identity_part,
    parse_bracketed_series_identity,
)
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)
from app.modules.imports.application.query_ports import Record
from app.modules.imports.application.release_titles import parse_release_title
from app.modules.imports.domain.content_classification import ContentClassification
from app.modules.imports.domain.reflowable_formats import (
    REFLOWABLE_SOURCE_EXTENSIONS,
)

SUPPORTED_EXTS = {
    ".epub",
    ".cbr",
    ".cbz",
    ".rar",
    ".zip",
    ".pdf",
    *REFLOWABLE_SOURCE_EXTENSIONS,
}


@dataclass(frozen=True, slots=True)
class BoundTopologyTarget:
    work: Record
    volume: Record

    @property
    def version_id(self) -> str:
        return str(self.volume["versionId"])


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_EPUB_SIZE_BYTES = 512 * 1024 * 1024
MAX_TEXT_EBOOK_SIZE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_SIZE_BYTES = 2 * 1024 * 1024 * 1024


def import_file_size_limit_bytes_for_ext(ext: str) -> int | None:
    normalized = ext if ext.startswith(".") else f".{ext}"
    normalized = normalized.lower()
    if normalized == ".epub":
        return MAX_EPUB_SIZE_BYTES
    if normalized in REFLOWABLE_SOURCE_EXTENSIONS:
        return MAX_TEXT_EBOOK_SIZE_BYTES
    if normalized in {".cbr", ".cbz", ".rar", ".zip"}:
        return MAX_ARCHIVE_SIZE_BYTES
    return None


def _id() -> str:
    return f"py_{time.time_ns()}"


def _now() -> int:
    return now_timestamp_ms()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_key(value: Any) -> str:
    return normalize_identity_part(value)


def _usable_merge_identifier(identifier: str | None) -> bool:
    if not identifier:
        return False
    value = str(identifier).strip().lower()
    return not (
        value.startswith("urn:uuid:")
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value
        )
    )


def _source_filename_title(options: ImportOptions) -> str:
    """Return the user-visible source filename without its final extension."""

    original_name = str(options.original_name or "").replace("\\", "/")
    filename = original_name.rsplit("/", 1)[-1] or options.source_file_path.name
    return Path(filename).stem.strip() or options.source_file_path.stem


def _file_resource_key(fmt: str, path: Path) -> str:
    return f"{fmt}:{_hash_text(str(path.resolve()))[:24]}"


def _prepared_default_cover(options: ImportOptions) -> str:
    if not options.default_cover_path:
        raise RuntimeError("导入文件准备阶段未生成默认封面")
    return options.default_cover_path


def _classification_columns(
    classification: ContentClassification,
) -> dict[str, object]:
    return {
        "classificationSource": classification.source.value,
        "classificationReason": classification.reason,
        "suggestedMediaKind": classification.suggested_media_kind,
    }


def _classification_result_type(classification: ContentClassification) -> str:
    return {
        "COMIC": "comic",
        "AUDIOBOOK": "audiobook",
    }.get(classification.media_kind, "ebook")


def _extract_isbn(ids: list[str]) -> str | None:
    for value in ids:
        if "isbn" not in str(value).lower():
            continue
        candidates = re.findall(
            r"(?:97[89][-\s]?)?[0-9][0-9Xx\-\s]{8,16}[0-9Xx]", value
        )
        for candidate in candidates:
            normalized = re.sub(r"[^0-9Xx]", "", candidate).upper()
            if _valid_isbn(normalized):
                return normalized
    return None


def _preferred_identifier(ids: list[str]) -> str | None:
    for value in ids:
        if "isbn" in str(value).lower():
            continue
        cleaned = str(value or "").strip()
        if cleaned and _usable_merge_identifier(cleaned):
            return cleaned
    return None


def _valid_isbn(value: str) -> bool:
    if len(value) == 13 and value.isdigit():
        total = sum(
            (1 if index % 2 == 0 else 3) * int(char)
            for index, char in enumerate(value[:12])
        )
        return (10 - total % 10) % 10 == int(value[-1])
    if len(value) == 10 and re.fullmatch(r"[0-9]{9}[0-9X]", value):
        total = sum(
            (10 - index) * (10 if char == "X" else int(char))
            for index, char in enumerate(value)
        )
        return total % 11 == 0
    return False


def _sanitize_description(value: str | None) -> str | None:
    return (
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip() if value else None
    )


def _title_from_file(path: Path) -> str:
    return re.sub(r"[_-]+", " ", Path(path).stem).strip() or Path(path).name


def _safe_entry_name(name: str) -> bool:
    normalized = str(PurePosixPath(name.replace("\\", "/")))
    return bool(
        name
        and not name.startswith("/")
        and not re.match(r"^[a-zA-Z]:", name)
        and not normalized.startswith("../")
        and "/../" not in normalized
    )


def _ignored_entry(name: str) -> bool:
    parts = name.split("/")
    last = parts[-1]
    return (
        "__MACOSX" in parts
        or last in {".DS_Store", "Thumbs.db"}
        or last.startswith("._")
        or any(part.startswith(".") for part in parts)
    )


def _natural_key(value: str) -> list[Any]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def _split_tags(value: str | None) -> list[str]:
    return [tag.strip() for tag in re.split(r"[,，;]", value or "") if tag.strip()]


def _clean_title_part(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()


def _bracketed_folder_metadata(value: str) -> dict[str, str] | None:
    parts = [
        _clean_title_part(match.group(1))
        for match in re.finditer(r"\[([^\]]+)\]", value)
    ]
    if len(parts) == 2 and "".join(parts) and _is_exact_bracket_sequence(value, 2):
        return {"title": parts[0], "author": parts[1]}
    return None


def _series_folder_metadata(
    value: str, filename: str | None = None
) -> dict[str, str] | None:
    inferred = parse_bracketed_series_identity(value, filename)
    if inferred:
        return {"title": inferred[0], "author": inferred[1]}
    raw_parts = [match.group(1) for match in re.finditer(r"\[([^\]]+)\]", value)]
    parts = [_clean_title_part(part) for part in raw_parts]
    if (
        len(parts) >= 3
        and parts[0]
        and parts[1]
        and _volume_range_part(raw_parts[2])
        and _is_exact_bracket_sequence(value)
    ):
        return {"title": parts[0], "author": parts[1]}
    if len(parts) == 2 and "".join(parts) and _is_exact_bracket_sequence(value, 2):
        return {"title": parts[0], "author": parts[1]}
    return None


def _is_exact_bracket_sequence(value: str, count: int | None = None) -> bool:
    repeat = f"{{{count}}}" if count is not None else "+"
    return bool(re.fullmatch(rf"\s*(?:\[[^\]]+\]\s*){repeat}", value))


def _volume_range_part(value: str) -> bool:
    return bool(
        re.search(
            r"(?:vol\.?|volume|v|第)?\s*\d+(?:\.\d+)?\s*[-~至到]\s*(?:vol\.?|volume|v|第)?\s*\d+(?:\.\d+)?",
            value,
            re.IGNORECASE,
        )
    )


def _volume_index_from_suffix(value: str) -> float | None:
    suffix = _clean_title_part(value).strip()
    suffix = re.sub(r"^[\s._\-~～]+", "", suffix)
    if not suffix:
        return None
    for pattern in [
        r"(?:^|\s)(?:vol\.?|volume|v)\s*(\d+(?:\.\d+)?)$",
        r"(?:^|\s)(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"(?:^|\s)(\d+(?:\.\d+)?)$",
    ]:
        match = re.search(pattern, suffix, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def parse_series_volume_info(
    path: Path,
    original_name: str | None = None,
    origin: str = "SCAN",
) -> SeriesVolumeInfo | None:
    source = original_name or path.name
    base = _clean_title_part(Path(source).stem)
    folder = (
        _series_folder_metadata(path.parent.name, source) if origin == "SCAN" else None
    )
    folder_title = (folder or {}).get("title")
    author = (folder or {}).get("author")
    if folder_title:
        suffix = base
        title_key = _normalize_key(folder_title)
        base_key = _normalize_key(base)
        if base_key.startswith(title_key):
            suffix = base[len(folder_title) :].strip()
        volume_index = _volume_index_from_suffix(suffix)
        if volume_index is not None:
            return SeriesVolumeInfo(
                series_name=folder_title,
                series_index=volume_index,
                title=f"第 {volume_index:g} 卷",
                author=author,
            )
    parsed_release = parse_release_title(base)
    if parsed_release is not None:
        return SeriesVolumeInfo(
            series_name=parsed_release.series_name,
            series_index=parsed_release.volume_index,
            title=f"第 {parsed_release.volume_index:g} 卷",
            author=author,
        )
    return None


def _first_text(xml: str, tag: str) -> str | None:
    values = _texts(xml, tag)
    return values[0] if values else None


def _texts(xml: str, tag: str) -> list[str]:
    values = []
    for match in re.finditer(
        rf"<(?:[\w]+:)?{re.escape(tag)}\b[^>]*>([\s\S]*?)</(?:[\w]+:)?{re.escape(tag)}>",
        xml,
        re.IGNORECASE,
    ):
        text_value = _decode_xml_text(match.group(1))
        if text_value:
            values.append(text_value)
    return values


def _decode_xml_text(value: str) -> str:
    value = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    try:
        value = ElementTree.fromstring(f"<x>{value}</x>").text or value
    except ElementTree.ParseError:
        pass
    return re.sub(r"\s+", " ", value).strip()


def _attrs(xml: str, name: str) -> list[dict[str, str]]:
    output = []
    for match in re.finditer(rf"<{name}\b([^>]*)/?>(?:</{name}>)?", xml, re.IGNORECASE):
        output.append(
            {
                item.group(1): item.group(2) or item.group(3) or ""
                for item in re.finditer(
                    r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", match.group(1)
                )
            }
        )
    return output


def _bound_topology_target(
    queries: ImportLibraryQueries,
    options: ImportOptions,
) -> BoundTopologyTarget:
    """Load and validate the structure selected by the library-root scanner."""

    if options.topology_work_id is None or options.topology_volume_id is None:
        raise ImportExecutionError(
            "TOPOLOGY_TARGET_REQUIRED",
            "导入任务必须由书库根目录扫描器绑定 Work 与 Volume",
            retryable=False,
        )
    work = queries.get_work_by_id(options.topology_work_id)
    volume = queries.get_volume_context_by_id(options.topology_volume_id)
    if work is None or volume is None:
        raise ImportExecutionError(
            "TOPOLOGY_TARGET_NOT_FOUND",
            "扫描任务对应的目录拓扑不存在",
            retryable=False,
        )
    if str(volume.get("workId") or "") != options.topology_work_id:
        raise ImportExecutionError(
            "TOPOLOGY_TARGET_MISMATCH",
            "扫描任务的 Work 与 Volume 不属于同一目录拓扑",
            retryable=False,
        )
    if options.library_id is not None and str(work.get("libraryId") or "") != str(
        options.library_id
    ):
        raise ImportExecutionError(
            "TOPOLOGY_LIBRARY_MISMATCH",
            "扫描任务的目录拓扑不属于目标书库",
            retryable=False,
        )
    return BoundTopologyTarget(work=work, volume=volume)


def _import_work(
    _store: LibraryImportStore,
    _queries: ImportLibraryQueries,
    _options: ImportOptions,
    _data: dict[str, object],
    target: BoundTopologyTarget,
) -> tuple[Record, bool]:
    return target.work, False


def _import_version(
    _store: LibraryImportStore,
    _work_id: object,
    target: BoundTopologyTarget,
) -> Record:
    return {
        "id": target.version_id,
        "workId": target.work["id"],
        "sourceKey": target.volume.get("sourceKey"),
    }


_TOPOLOGY_VOLUME_COLUMNS = frozenset(
    {
        "id",
        "versionId",
        "title",
        "volumeIndex",
        "sortOrder",
        "resourceKey",
        "libraryId",
        "origin",
        "createdAt",
    }
)


def _persist_import_volume(
    store: LibraryImportStore,
    columns: dict[str, object],
    target: BoundTopologyTarget,
) -> Record:
    metadata_columns = {
        key: value
        for key, value in columns.items()
        if key not in _TOPOLOGY_VOLUME_COLUMNS
    }
    store.update_library_volume(
        str(target.volume["id"]),
        columns=metadata_columns,
    )
    return {**target.volume, **metadata_columns}


def _preferred_work_cover_path(
    queries: ImportLibraryQueries,
    work_id: str,
    version_id: str | None,
    services: ImportOrchestrationServices,
) -> str | None:
    if version_id:
        volumes = queries.list_volume_cover_paths_for_version(str(version_id))
        volume = next(
            (
                item
                for item in volumes
                if not services.is_default_cover_path(item.get("coverPath"))
            ),
            volumes[0] if volumes else None,
        )
        if volume and volume.get("coverPath"):
            return str(volume["coverPath"])
    cover_volume = queries.find_work_cover_volume(work_id)
    return (
        str(cover_volume["coverPath"])
        if cover_volume and cover_volume.get("coverPath")
        else None
    )


def _is_generated_work_cover_path(
    queries: ImportLibraryQueries, work_id: str, cover_path: str
) -> bool:
    return bool(queries.has_generated_cover_path(work_id, cover_path))


def _finalize_work_cover(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    work_id: str,
    version_id: str,
    cover_path: str | None,
    default_cover_path: str,
) -> None:
    work = queries.get_work_by_id(work_id)
    if not work:
        return
    preferred_cover_path = (
        _preferred_work_cover_path(queries, work_id, version_id, services)
        or cover_path
        or default_cover_path
    )
    current_cover_path = work.get("coverPath")
    should_update_cover = not current_cover_path or _is_generated_work_cover_path(
        queries, work_id, str(current_cover_path)
    )
    store.update_library_work(
        work_id,
        columns={
            "coverPath": preferred_cover_path
            if should_update_cover
            else current_cover_path,
            "coverStatus": services.cover_status(
                preferred_cover_path if should_update_cover else current_cover_path,
            ),
            "updatedAt": _now(),
        },
    )


def _insert_identity_metadata(
    store: LibraryImportStore, volume_id: str, identity: Any
) -> None:
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume_id,
            "source": f"identity_{identity.source}",
            "rawJson": json.dumps(identity.raw_metadata(), ensure_ascii=False),
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )


def _log_import(
    store: LibraryImportStore, task_id: str | None, level: str, message: str
) -> None:
    if task_id:
        store.insert_import_log(
            columns={
                "id": _id(),
                "importTaskId": task_id,
                "level": level,
                "message": message,
                "createdAt": _now(),
            }
        )


def _existing_file_result(
    queries: ImportLibraryQueries, path: Path
) -> ImportResult | None:
    existing = queries.existing_file_import_snapshot(path)
    if not existing:
        return None
    file_format = str(existing.get("format") or "").lower()
    total_units = (
        0
        if file_format in {"epub", "mobi", "azw", "azw3", "prc", "fb2", "txt"}
        else int(existing.get("pageCount") or existing.get("chapterCount") or 0)
    )
    result_type = (
        "comic"
        if file_format == "comic"
        else "audiobook"
        if file_format == "audio"
        else "ebook"
    )
    return ImportResult(
        str(existing["workId"]),
        str(existing["workId"]),
        str(existing["versionId"]),
        str(existing["volumeId"]) if existing.get("volumeId") else None,
        str(existing.get("title") or "未命名作品"),
        result_type,
        file_format,
        total_units,
        "completed",
        True,
        True,
        "duplicate-file-path",
    )


def _existing_audio_bundle_result(
    queries: ImportLibraryQueries, paths: list[Path]
) -> ImportResult | None:
    if not paths:
        return None
    rows = queries.list_file_volumes_by_paths([str(path.resolve()) for path in paths])
    if len(rows) != len(paths) or len({row.get("volumeId") for row in rows}) != 1:
        return None
    return _existing_file_result(queries, paths[0])
