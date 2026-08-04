from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from app.modules.opds.application.dto import (
    OPDS_PROGRESSION_MEDIA_TYPE,
    OPDS_PROGRESSION_REL,
    PSE_STREAM_REL,
    OpdsEntryDto,
    OpdsFeedDto,
)

ATOM_NS = "http://www.w3.org/2005/Atom"
OPDS_NS = "http://opds-spec.org/2010/catalog"
PSE_NS = "http://vaemendis.net/opds-pse/ns"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
CATALOG_MEDIA_TYPE = "application/atom+xml;profile=opds-catalog;kind={kind}"


def _atom_date(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(parent: ET.Element, tag: str, value: str) -> None:
    ET.SubElement(parent, tag).text = value


def _link(
    parent: ET.Element,
    *,
    href: str,
    rel: str,
    media_type: str,
    title: str | None = None,
) -> ET.Element:
    attributes = {"href": href, "rel": rel, "type": media_type}
    if title:
        attributes["title"] = title
    return ET.SubElement(parent, "link", attributes)


def _entry_element(parent: ET.Element, entry: OpdsEntryDto) -> None:
    node = ET.SubElement(parent, "entry")
    _text(node, "id", entry.id)
    _text(node, "title", entry.title)
    _text(node, "updated", _atom_date(entry.updated_at))
    for author in entry.authors:
        author_node = ET.SubElement(node, "author")
        _text(author_node, "name", author.name)
        if author.uri:
            _text(author_node, "uri", author.uri)
    if entry.summary:
        _text(node, "summary", entry.summary)
    for link in entry.links:
        _link(
            node,
            href=link.href,
            rel=link.rel,
            media_type=link.media_type,
            title=link.title,
        )
    if entry.pse_stream:
        pse = entry.pse_stream
        attributes = {
            "href": pse.href_template,
            "rel": PSE_STREAM_REL,
            "type": pse.media_type,
            "pse:count": str(pse.page_count),
        }
        if pse.last_read is not None:
            attributes["pse:lastRead"] = str(pse.last_read)
        if pse.last_read_date is not None:
            attributes["pse:lastReadDate"] = _atom_date(pse.last_read_date)
        ET.SubElement(node, "link", attributes)


def serialize_opds_feed(feed: OpdsFeedDto) -> bytes:
    root = ET.Element(
        "feed",
        {
            "xmlns": ATOM_NS,
            "xmlns:opds": OPDS_NS,
            "xmlns:pse": PSE_NS,
            "xmlns:opensearch": OPENSEARCH_NS,
        },
    )
    _text(root, "id", feed.id)
    _text(root, "title", feed.title)
    _text(root, "updated", _atom_date(feed.updated_at))
    feed_media_type = CATALOG_MEDIA_TYPE.format(kind=feed.kind)
    _link(root, href=feed.self_url, rel="self", media_type=feed_media_type)
    _link(root, href=feed.start_url, rel="start", media_type=feed_media_type)
    if feed.search_url_template:
        _link(
            root,
            href=feed.search_url_template,
            rel="search",
            media_type="application/opensearchdescription+xml",
        )
    if feed.next_url:
        _link(root, href=feed.next_url, rel="next", media_type=feed_media_type)
    if feed.previous_url:
        _link(root, href=feed.previous_url, rel="previous", media_type=feed_media_type)
    _text(root, "opensearch:totalResults", str(feed.total_results))
    _text(root, "opensearch:startIndex", str(feed.start_index))
    _text(root, "opensearch:itemsPerPage", str(feed.items_per_page))
    for entry in feed.entries:
        _entry_element(root, entry)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def progression_link(href: str) -> tuple[str, str, str]:
    return href, OPDS_PROGRESSION_REL, OPDS_PROGRESSION_MEDIA_TYPE
