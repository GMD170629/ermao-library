"""Native metadata adapters for TXT, FB2, MOBI, AZW, AZW3, and PRC."""

from __future__ import annotations

import base64
import binascii
import html
import re
import struct
from dataclasses import replace
from pathlib import Path

# lxml does not publish PEP 561 type metadata; values are validated at this
# adapter boundary.
from lxml import etree  # type: ignore[import-untyped]

from app.modules.imports.application.reflowable_types import (
    EmbeddedBookCover,
    ReflowableBookMetadata,
)
from app.modules.imports.domain.volume_index import parse_structured_volume_index
from app.modules.imports.infrastructure.text_encoding import (
    TextEncodingError,
    detect_txt_encoding,
)

_MOBI_FAMILY_FORMATS = {"MOBI", "AZW", "AZW3", "PRC"}
_MAX_COVER_BYTES = 20 * 1024 * 1024


class ReflowableMetadataError(ValueError):
    pass


def inspect_reflowable_book(path: Path, source_format: str) -> ReflowableBookMetadata:
    normalized_format = source_format.upper()
    if normalized_format == "TXT":
        metadata = _inspect_txt(path)
    elif normalized_format == "FB2":
        metadata = _inspect_fb2(path)
    elif normalized_format in _MOBI_FAMILY_FORMATS:
        metadata = _inspect_mobi_family(path, normalized_format)
    else:
        raise ReflowableMetadataError(f"Unsupported reflowable format: {source_format}")
    if metadata.cover is not None:
        return metadata
    sidecar_cover = _sidecar_cover(path)
    if sidecar_cover is None:
        return metadata
    return replace(
        metadata,
        cover=sidecar_cover,
        raw_metadata={
            **metadata.raw_metadata,
            "coverEmbedded": False,
            "coverSidecar": True,
        },
    )


def _inspect_txt(path: Path) -> ReflowableBookMetadata:
    try:
        encoding = detect_txt_encoding(path)
        text = path.read_text(encoding=encoding, errors="strict")
    except (OSError, UnicodeError, TextEncodingError) as exc:
        raise ReflowableMetadataError("Unable to inspect TXT metadata") from exc
    return ReflowableBookMetadata(
        title=None,
        authors=(),
        language=_guess_text_language(text),
        publisher=None,
        published_at=None,
        identifier=None,
        isbn=None,
        description=None,
        subjects=(),
        cover=None,
        raw_metadata={
            "sourceFormat": "TXT",
            "inputEncoding": encoding,
        },
    )


def _inspect_fb2(path: Path) -> ReflowableBookMetadata:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=True,
        huge_tree=False,
    )
    try:
        root = etree.parse(str(path), parser).getroot()
    except (OSError, etree.XMLSyntaxError) as exc:
        raise ReflowableMetadataError("Unable to inspect FB2 metadata") from exc
    if _local_name(root) != "FictionBook":
        raise ReflowableMetadataError("Invalid FB2 root element")
    title_info = _first_descendant(root, "title-info")
    document_info = _first_descendant(root, "document-info")
    publish_info = _first_descendant(root, "publish-info")
    title = _element_text(_first_descendant(title_info, "book-title")) or path.stem
    authors = tuple(
        value
        for node in _direct_children(title_info, "author")
        if (value := _fb2_person(node))
    )
    language = _element_text(_first_descendant(title_info, "lang")) or None
    publisher = _element_text(_first_descendant(publish_info, "publisher")) or None
    published_at = (
        _attribute(_first_descendant(title_info, "date"), "value")
        or _element_text(_first_descendant(title_info, "date"))
        or None
    )
    identifier = _element_text(_first_descendant(document_info, "id")) or None
    isbn = _element_text(_first_descendant(publish_info, "isbn")) or None
    description = _element_text(_first_descendant(title_info, "annotation")) or None
    subjects = tuple(
        value
        for node in _direct_children(title_info, "genre")
        if (value := _element_text(node))
    )
    sequence = _first_descendant(title_info, "sequence")
    series_name = _attribute(sequence, "name") or None
    series_index_raw = _attribute(sequence, "number") or None
    try:
        series_index = float(series_index_raw) if series_index_raw else None
    except ValueError:
        series_index = None
    cover = _fb2_cover(root, title_info)
    return ReflowableBookMetadata(
        title=_clean(title),
        authors=authors,
        language=_clean(language),
        publisher=_clean(publisher),
        published_at=_clean(published_at),
        identifier=_clean(identifier),
        isbn=_clean(isbn),
        description=_clean(description, limit=4_000),
        subjects=subjects,
        cover=cover,
        raw_metadata={
            "sourceFormat": "FB2",
            "coverEmbedded": cover is not None,
            "seriesName": series_name,
            "seriesIndex": series_index_raw,
        },
        series_name=_clean(series_name),
        series_index=series_index,
    )


def _inspect_mobi_family(path: Path, source_format: str) -> ReflowableBookMetadata:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ReflowableMetadataError("Unable to read MOBI-family publication") from exc
    records = _pdb_records(content)
    if not records:
        raise ReflowableMetadataError("MOBI-family publication has no records")
    header = records[0]
    if len(header) < 132 or header[16:20] != b"MOBI":
        raise ReflowableMetadataError("Missing MOBI header")
    mobi_length = _uint(header, 20)
    encoding_code = _uint(header, 28)
    encoding = "utf-8" if encoding_code == 65001 else "cp1252"
    uid = _uint(header, 32)
    version = _uint(header, 36)
    title_offset = _uint(header, 84)
    title_length = _uint(header, 88)
    resource_start = _uint(header, 108)
    exth = _parse_exth(header, mobi_length, encoding)
    title = _first(exth, 503) or _decode(
        header[title_offset : title_offset + title_length], encoding
    )
    authors = tuple(
        cleaned for value in exth.get(100, ()) if (cleaned := _clean(value)) is not None
    )
    publisher = _first(exth, 101)
    description = _first(exth, 103)
    isbn = _first(exth, 104)
    series_source = _first(exth, 112)
    series_index_raw = _first(exth, 113)
    series_index = parse_structured_volume_index(series_index_raw)
    has_structured_series = bool(
        series_source
        and series_index is not None
        and not series_source.casefold().startswith(("calibre:", "urn:"))
    )
    series_name = series_source if has_structured_series else None
    if not has_structured_series:
        series_index = None
    identifier = _first(exth, 504)
    if identifier is None and not has_structured_series:
        identifier = _first(exth, 113)
    identifier = identifier or str(uid)
    published_at = _first(exth, 106)
    language = _first(exth, 524) or _mobi_language(header)
    subjects = tuple(
        cleaned for value in exth.get(105, ()) if (cleaned := _clean(value)) is not None
    )
    cover = _mobi_family_cover(records, resource_start, exth)
    compression = struct.unpack_from(">H", header, 0)[0]
    return ReflowableBookMetadata(
        title=_clean(html.unescape(title or path.stem)),
        authors=authors,
        language=_clean(language),
        publisher=_clean(html.unescape(publisher or "")),
        published_at=_clean(published_at),
        identifier=_clean(identifier),
        isbn=_clean(isbn),
        description=_clean(html.unescape(description or ""), limit=4_000),
        subjects=subjects,
        cover=cover,
        raw_metadata={
            "sourceFormat": source_format,
            "mobiVersion": version,
            "compression": compression,
            "recordCount": len(records),
            "coverEmbedded": cover is not None,
            "seriesName": series_name,
            "seriesIndex": series_index_raw if has_structured_series else None,
        },
        series_name=_clean(series_name),
        series_index=series_index,
    )


def _pdb_records(content: bytes) -> tuple[bytes, ...]:
    if len(content) < 78:
        return ()
    count = struct.unpack_from(">H", content, 76)[0]
    if count <= 0 or 78 + count * 8 > len(content):
        return ()
    offsets = [
        struct.unpack_from(">I", content, 78 + index * 8)[0] for index in range(count)
    ]
    if offsets != sorted(offsets) or any(offset >= len(content) for offset in offsets):
        return ()
    offsets.append(len(content))
    return tuple(content[offsets[index] : offsets[index + 1]] for index in range(count))


def _parse_exth(
    header: bytes, mobi_length: int, encoding: str
) -> dict[int, tuple[str, ...]]:
    offset = 16 + mobi_length
    if offset + 12 > len(header) or header[offset : offset + 4] != b"EXTH":
        return {}
    total_length = _uint(header, offset + 4)
    count = min(_uint(header, offset + 8), 10_000)
    end = min(len(header), offset + total_length)
    cursor = offset + 12
    result: dict[int, list[str]] = {}
    for _ in range(count):
        if cursor + 8 > end:
            break
        record_type = _uint(header, cursor)
        length = _uint(header, cursor + 4)
        if length < 8 or cursor + length > end:
            break
        raw = header[cursor + 8 : cursor + length]
        if record_type in {121, 125, 201, 202}:
            value = str(int.from_bytes(raw, "big"))
        else:
            value = _decode(raw, encoding)
        result.setdefault(record_type, []).append(value)
        cursor += length
    return {key: tuple(values) for key, values in result.items()}


def _mobi_family_cover(
    records: tuple[bytes, ...], resource_start: int, exth: dict[int, tuple[str, ...]]
) -> EmbeddedBookCover | None:
    raw_offset = _first(exth, 201) or _first(exth, 202)
    if raw_offset is None:
        return None
    try:
        index = resource_start + int(raw_offset)
    except ValueError:
        return None
    if not 0 <= index < len(records):
        return None
    return _image_cover(records[index])


def _image_cover(content: bytes) -> EmbeddedBookCover | None:
    if not content or len(content) > _MAX_COVER_BYTES:
        return None
    if content.startswith(b"\xff\xd8\xff"):
        return EmbeddedBookCover(content, "image/jpeg", ".jpg")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return EmbeddedBookCover(content, "image/png", ".png")
    if content.startswith((b"GIF87a", b"GIF89a")):
        return EmbeddedBookCover(content, "image/gif", ".gif")
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return EmbeddedBookCover(content, "image/webp", ".webp")
    return None


def _sidecar_cover(path: Path) -> EmbeddedBookCover | None:
    candidates = (
        *(
            path.with_suffix(extension)
            for extension in (".jpg", ".jpeg", ".png", ".webp", ".gif")
        ),
        *(
            path.parent / f"cover{extension}"
            for extension in (".jpg", ".jpeg", ".png", ".webp", ".gif")
        ),
        *(
            path.parent / f"folder{extension}"
            for extension in (".jpg", ".jpeg", ".png", ".webp", ".gif")
        ),
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size <= _MAX_COVER_BYTES:
                cover = _image_cover(candidate.read_bytes())
                if cover is not None:
                    return cover
        except OSError:
            continue
    return None


def _fb2_cover(
    root: etree._Element, title_info: etree._Element | None
) -> EmbeddedBookCover | None:
    coverpage = _first_descendant(title_info, "coverpage")
    image = _first_descendant(coverpage, "image")
    cover_id = _attribute(image, "href").lstrip("#") if image is not None else ""
    if not cover_id:
        return None
    binary = next(
        (
            node
            for node in root.iter()
            if _local_name(node) == "binary" and _attribute(node, "id") == cover_id
        ),
        None,
    )
    if binary is None:
        return None
    try:
        content = base64.b64decode(
            re.sub(rb"\s+", b"", (binary.text or "").encode("ascii")), validate=True
        )
    except (UnicodeEncodeError, binascii.Error, ValueError):
        return None
    return _image_cover(content)


def _direct_children(
    node: etree._Element | None, name: str
) -> tuple[etree._Element, ...]:
    if node is None:
        return ()
    return tuple(child for child in node if _local_name(child) == name)


def _fb2_person(node: etree._Element) -> str:
    parts = [
        _element_text(_first_descendant(node, field))
        for field in ("first-name", "middle-name", "last-name", "nickname")
    ]
    present_parts = [part for part in parts if part]
    separator = (
        ""
        if present_parts and all(_contains_only_cjk(part) for part in present_parts)
        else " "
    )
    return _clean(separator.join(present_parts)) or ""


def _contains_only_cjk(value: str) -> bool:
    characters = [character for character in value if not character.isspace()]
    return bool(characters) and all(
        "\u3400" <= character <= "\u9fff" for character in characters
    )


def _local_name(node: etree._Element | None) -> str:
    return (
        etree.QName(node).localname
        if node is not None and isinstance(node.tag, str)
        else ""
    )


def _first_descendant(node: etree._Element | None, name: str) -> etree._Element | None:
    if node is None:
        return None
    return next(
        (candidate for candidate in node.iter() if _local_name(candidate) == name), None
    )


def _element_text(node: etree._Element | None) -> str:
    if node is None:
        return ""
    return " ".join(part.strip() for part in node.itertext() if part.strip()).strip()


def _attribute(node: etree._Element | None, name: str) -> str:
    if node is None:
        return ""
    return next(
        (
            value
            for key, value in node.attrib.items()
            if key == name or key.endswith(f"}}{name}")
        ),
        "",
    )


def _first(values: dict[int, tuple[str, ...]], key: int) -> str | None:
    items = values.get(key, ())
    return items[0] if items else None


def _decode(content: bytes, encoding: str) -> str:
    return content.decode(encoding, errors="replace").strip("\x00\ufeff ")


def _uint(content: bytes, offset: int) -> int:
    return struct.unpack_from(">I", content, offset)[0]


def _mobi_language(header: bytes) -> str | None:
    language = header[95] if len(header) > 95 else 0
    region = (header[94] >> 2) if len(header) > 94 else 0
    languages = {
        4: ("zh", "zh-TW", "zh-CN", "zh-HK", "zh-SG"),
        9: ("en", "en-US", "en-GB"),
        17: ("ja",),
        18: ("ko",),
        25: ("ru",),
    }
    values = languages.get(language)
    return values[min(region, len(values) - 1)] if values else None


def _guess_text_language(value: str) -> str:
    sample = value[:100_000]
    chinese = sum("\u4e00" <= character <= "\u9fff" for character in sample)
    return "zh-CN" if chinese >= max(8, len(sample) // 100) else "en-US"


def _clean(value: object, *, limit: int = 500) -> str | None:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned[:limit] or None
