"""Pure OPF parsing and serialization for sidecar round trips."""

from __future__ import annotations

import re
from datetime import date, datetime
from xml.sax.saxutils import escape, quoteattr

# lxml does not publish PEP 561 metadata. Inputs are constrained at this boundary.
from lxml import etree  # type: ignore[import-untyped]

from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source

MAX_OPF_BYTES = 2 * 1024 * 1024
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
OPF_NAMESPACE = "http://www.idpf.org/2007/opf"
COVER_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class OpfMetadataError(ValueError):
    pass


def cover_media_type(href: str) -> str:
    suffix = href.rsplit(".", 1)[-1].casefold() if "." in href else ""
    return COVER_MEDIA_TYPES.get(f".{suffix}", "image/jpeg")


def _clean(value: object, *, limit: int = 8_000) -> str | None:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    return normalized[:limit] or None


def _local_name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _text_nodes(root: etree._Element, name: str) -> tuple[str, ...]:
    values: list[str] = []
    for node in root.iter():
        if not isinstance(node.tag, str) or _local_name(node) != name:
            continue
        value = _clean("".join(node.itertext()))
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _meta_values(root: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in root.iter():
        if not isinstance(node.tag, str) or _local_name(node) != "meta":
            continue
        name = _clean(node.get("name") or node.get("property"), limit=191)
        value = _clean(node.get("content") or "".join(node.itertext()))
        if name and value:
            result[name.casefold()] = value
    return result


def _float(value: str | None) -> float | None:
    try:
        parsed = float(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _date(value: str | None) -> str | None:
    cleaned = _clean(value, limit=191)
    if not cleaned:
        return None
    try:
        if re.fullmatch(r"\d{4}", cleaned):
            date.fromisoformat(f"{cleaned}-01-01")
        elif re.fullmatch(r"\d{4}-\d{2}", cleaned):
            date.fromisoformat(f"{cleaned}-01")
        else:
            datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return cleaned


def _isbn(root: etree._Element, identifiers: tuple[str, ...]) -> str | None:
    for node in root.iter():
        if not isinstance(node.tag, str) or _local_name(node) != "identifier":
            continue
        value = _clean("".join(node.itertext()), limit=191)
        scheme = _clean(
            node.get(f"{{{OPF_NAMESPACE}}}scheme") or node.get("scheme"), limit=32
        )
        if value and (
            str(scheme or "").casefold() == "isbn" or "isbn" in value.casefold()
        ):
            normalized = re.sub(r"(?i)^urn:isbn:", "", value).strip()
            return normalized or None
    return next((value for value in identifiers if "isbn" in value.casefold()), None)


def _cover_href(root: etree._Element, metadata: dict[str, str]) -> str | None:
    cover_id = metadata.get("cover")
    for node in root.iter():
        if not isinstance(node.tag, str) or _local_name(node) != "item":
            continue
        properties = str(node.get("properties") or "").casefold().split()
        if "cover-image" in properties or (cover_id and node.get("id") == cover_id):
            return _clean(node.get("href"), limit=1_024)
    return metadata.get("shuku:cover") or metadata.get("calibre:cover")


def parse_opf_metadata(content: bytes) -> PublicationMetadata:
    if not content or len(content) > MAX_OPF_BYTES:
        raise OpfMetadataError("OPF 文件为空或超过 2 MiB")
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise OpfMetadataError("OPF 不允许文档类型或实体声明")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=True,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise OpfMetadataError("OPF XML 格式无效") from exc
    if _local_name(root) not in {"package", "metadata"}:
        raise OpfMetadataError("OPF 缺少 package 或 metadata 根元素")

    metadata = _meta_values(root)
    titles = _text_nodes(root, "title")
    authors = _text_nodes(root, "creator")
    identifiers = _text_nodes(root, "identifier")
    series_name = metadata.get("calibre:series")
    series_index_raw = metadata.get("calibre:series_index")
    series_index = _float(series_index_raw)
    epub3_series_name: str | None = None
    epub3_series_index_raw: str | None = None
    for node in root.iter():
        if not isinstance(node.tag, str) or _local_name(node) != "meta":
            continue
        property_name = str(node.get("property") or "").casefold()
        if property_name == "belongs-to-collection" and epub3_series_name is None:
            epub3_series_name = _clean("".join(node.itertext()))
        elif property_name == "group-position" and epub3_series_index_raw is None:
            epub3_series_index_raw = _clean("".join(node.itertext()))
    if series_name is None:
        series_name = epub3_series_name
    if series_index is None:
        series_index_raw = epub3_series_index_raw or series_index_raw
        series_index = _float(series_index_raw)

    dates = _text_nodes(root, "date")
    date_raw = dates[0] if dates else None
    published_at = _date(date_raw)
    unparsed: list[tuple[str, str]] = []
    if date_raw and published_at is None:
        unparsed.append(("publishedAt", date_raw))
    if series_index_raw and series_index is None:
        unparsed.append(("seriesIndex", series_index_raw))

    title = titles[0] if titles else None
    publication_titles = titles_from_local_source(
        title,
        series_name=series_name,
        volume_index=series_index,
    )
    return PublicationMetadata(
        title=publication_titles.work_title,
        volume_title=publication_titles.volume_title,
        authors=authors,
        description=next(iter(_text_nodes(root, "description")), None),
        subjects=_text_nodes(root, "subject"),
        series_name=series_name,
        series_index=series_index,
        volume_index=publication_titles.volume_index,
        language=next(iter(_text_nodes(root, "language")), None),
        publisher=next(iter(_text_nodes(root, "publisher")), None),
        published_at=published_at,
        identifier=identifiers[0] if identifiers else None,
        isbn=_isbn(root, identifiers),
        cover_href=_cover_href(root, metadata),
        unparsed_values=tuple(unparsed),
    )


def serialize_opf_metadata(metadata: PublicationMetadata) -> bytes:
    def element(name: str, value: object | None) -> str:
        return (
            f"    <dc:{name}>{escape(str(value))}</dc:{name}>\n"
            if value not in (None, "")
            else ""
        )

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>\n',
        f'<package xmlns={quoteattr(OPF_NAMESPACE)} xmlns:dc={quoteattr(DC_NAMESPACE)} version="3.0" unique-identifier="book-id">\n',
        "  <metadata>\n",
        element("title", metadata.volume_title or metadata.title),
        *(element("creator", author) for author in metadata.authors),
        element("description", metadata.description),
        *(element("subject", subject) for subject in metadata.subjects),
        element("language", metadata.language),
        element("publisher", metadata.publisher),
        element("date", metadata.published_at),
        element("identifier", metadata.identifier or metadata.isbn),
    ]
    if metadata.isbn:
        lines.append(
            f'    <dc:identifier opf:scheme="ISBN" xmlns:opf={quoteattr(OPF_NAMESPACE)}>{escape(metadata.isbn)}</dc:identifier>\n'
        )
    effective_series_name = metadata.series_name
    if (
        effective_series_name is None
        and metadata.title
        and (
            metadata.volume_index is not None
            or (
                metadata.volume_title is not None
                and metadata.volume_title != metadata.title
            )
        )
    ):
        effective_series_name = metadata.title
    if effective_series_name:
        lines.append(
            f'    <meta name="calibre:series" content={quoteattr(effective_series_name)} />\n'
        )
    if metadata.volume_index is not None:
        lines.append(
            f'    <meta name="calibre:series_index" content={quoteattr(str(metadata.volume_index))} />\n'
        )
    if metadata.cover_href:
        lines.append('    <meta name="cover" content="cover-image" />\n')
    lines.append("  </metadata>\n")
    lines.append("  <manifest>\n")
    if metadata.cover_href:
        media_type = cover_media_type(metadata.cover_href)
        lines.append(
            f'    <item id="cover-image" href={quoteattr(metadata.cover_href)} '
            f'media-type={quoteattr(media_type)} properties="cover-image" />\n'
        )
    lines.extend(("  </manifest>\n", "  <spine />\n", "</package>\n"))
    return "".join(lines).encode("utf-8")
