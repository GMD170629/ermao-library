"""Safe direct FB2 to Readium Web Publication adapter."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.locator_dom import (
    WEB_SECURITY_PROFILE,
    decorate_markup_head,
)
from app.modules.publications.infrastructure.snapshot_cache import (
    PublicationSnapshotCache,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)

FB2_PARSER_IDENTIFIER = "shuku-fb2-parser-v1"
FB2_NORMALIZATION_IDENTIFIER = "shuku-fb2-publication-v1"
MAX_FB2_SOURCE_BYTES = 64 * 1024 * 1024
MAX_BINARY_RESOURCE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BINARY_BYTES = 128 * 1024 * 1024
MAX_SECTIONS = 10_000
MAX_XML_ELEMENTS = 200_000
MAX_XML_DEPTH = 128
_UNSAFE_XML_DECLARATION = re.compile(rb"<!DOCTYPE\b|<!ENTITY\b", re.IGNORECASE)
_XLINK_NAMESPACE_DECLARATION = re.compile(
    rb"\bxmlns:xlink\s*=\s*(['\"])http://www\.w3\.org/1999/xlink\1"
)
_L_NAMESPACE_DECLARATION = re.compile(rb"\bxmlns:l\s*=")
_LEGACY_L_HREF_ATTRIBUTE = re.compile(rb"(?P<spacing>\s)l:href(?P<equals>\s*=)")
_STYLESHEET_HREF = "fb2/reader.css"
_STYLESHEET = b"""body {
  margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere;
}
section { margin: 0 0 2rem; } h1,h2,h3,h4,h5,h6 { line-height: 1.3; }
p { margin: 0 0 1em; } img { max-width: 100%; height: auto; }
blockquote { margin: 1em 1.5em; } .stanza { margin: 1em 0; }
"""
_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


@dataclass(frozen=True, slots=True)
class _Fb2Section:
    element: ElementTree.Element
    resource_href: str
    anchor: str
    title: str
    children: tuple[_Fb2Section, ...]


@dataclass(frozen=True, slots=True)
class _Fb2Snapshot:
    publication: NormalizedPublication
    source_mtime: float
    resources_by_href: dict[str, tuple[str, bytes | str]]
    sections_by_href: dict[str, _Fb2Section]
    element_anchors: dict[ElementTree.Element, str]
    original_targets: dict[str, str]
    image_hrefs: dict[str, str]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _attribute(element: ElementTree.Element, name: str) -> str | None:
    return next(
        (value for key, value in element.attrib.items() if _local_name(key) == name),
        None,
    )


def _direct_children(
    element: ElementTree.Element, name: str
) -> list[ElementTree.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _first_descendant(
    element: ElementTree.Element | None, name: str
) -> ElementTree.Element | None:
    if element is None:
        return None
    return next(
        (child for child in element.iter() if _local_name(child.tag) == name),
        None,
    )


def _normalized_text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _xml_root(content: bytes) -> ElementTree.Element:
    if not content or len(content) > MAX_FB2_SOURCE_BYTES:
        raise PublicationCorruptError("FB2 source exceeds the size limit")
    if _UNSAFE_XML_DECLARATION.search(content):
        raise PublicationCorruptError("active XML declarations are not allowed")
    content = _normalize_legacy_link_prefix(content)
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise PublicationCorruptError("FB2 XML is invalid") from error
    if _local_name(root.tag) != "FictionBook":
        raise PublicationCorruptError("FB2 root element is invalid")
    _validate_tree_shape(root)
    return root


def _normalize_legacy_link_prefix(content: bytes) -> bytes:
    """Repair the common FB2 `l:href` / `xmlns:xlink` namespace mismatch.

    Some otherwise valid reading-media fixtures declare the standard XLink
    namespace under `xlink` but use the conventional FB2 `l:href` spelling.
    Rebinding only that attribute to the already-declared namespace keeps the
    original file untouched and does not make arbitrary undeclared prefixes
    parseable.
    """

    if (
        _L_NAMESPACE_DECLARATION.search(content)
        or not _XLINK_NAMESPACE_DECLARATION.search(content)
        or not _LEGACY_L_HREF_ATTRIBUTE.search(content)
    ):
        return content
    return _LEGACY_L_HREF_ATTRIBUTE.sub(rb"\g<spacing>xlink:href\g<equals>", content)


def _validate_tree_shape(root: ElementTree.Element) -> None:
    count = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_XML_ELEMENTS:
            raise PublicationCorruptError("FB2 contains too many XML elements")
        if depth > MAX_XML_DEPTH:
            raise PublicationCorruptError("FB2 XML nesting is too deep")
        stack.extend((child, depth + 1) for child in element)


def _person_name(person: ElementTree.Element) -> str:
    nickname = _normalized_text(_first_descendant(person, "nickname"))
    if nickname:
        return nickname
    values = [
        _normalized_text(_first_descendant(person, name))
        for name in ("first-name", "middle-name", "last-name")
    ]
    return " ".join(value for value in values if value)


def _safe_resource_href(raw_href: str) -> str:
    split = urlsplit(raw_href)
    decoded = unquote(split.path)
    if (
        split.scheme
        or split.netloc
        or split.query
        or split.fragment
        or not decoded
        or decoded.startswith("/")
        or "\\" in decoded
        or ".." in decoded.split("/")
    ):
        raise PublicationResourceNotFoundError
    return decoded


def _binary_resources(
    root: ElementTree.Element,
) -> tuple[dict[str, tuple[str, bytes | str]], dict[str, str]]:
    resources: dict[str, tuple[str, bytes | str]] = {}
    href_by_identifier: dict[str, str] = {}
    seen_identifiers: set[str] = set()
    total_size = 0
    for binary in (item for item in root if _local_name(item.tag) == "binary"):
        identifier = (_attribute(binary, "id") or "").strip()
        media_type = (_attribute(binary, "content-type") or "").strip().lower()
        extension = _IMAGE_TYPES.get(media_type)
        if not identifier or extension is None:
            continue
        if identifier in seen_identifiers:
            raise PublicationCorruptError("FB2 contains duplicate binary identifiers")
        seen_identifiers.add(identifier)
        encoded = "".join("".join(binary.itertext()).split())
        estimated_size = (len(encoded) // 4) * 3 - (
            len(encoded) - len(encoded.rstrip("="))
        )
        if (
            not encoded
            or estimated_size < 1
            or estimated_size > MAX_BINARY_RESOURCE_BYTES
        ):
            raise PublicationCorruptError("FB2 binary resource exceeds the size limit")
        total_size += estimated_size
        if total_size > MAX_TOTAL_BINARY_BYTES:
            raise PublicationCorruptError("FB2 binary resources exceed the size limit")
        safe_identifier = hashlib.sha256(identifier.encode()).hexdigest()[:20]
        href = f"fb2/images/{safe_identifier}.{extension}"
        resources[href] = (media_type, encoded)
        href_by_identifier[identifier] = href
    return resources, href_by_identifier


def _matches_image_type(content: bytes, media_type: str) -> bool:
    if media_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if media_type == "image/webp":
        return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def _section_title(element: ElementTree.Element, fallback: str) -> str:
    title = next(
        (child for child in element if _local_name(child.tag) == "title"),
        None,
    )
    return _normalized_text(title) or fallback


def _build_sections(
    root: ElementTree.Element,
    publication_title: str,
) -> tuple[tuple[_Fb2Section, ...], dict[ElementTree.Element, str], dict[str, str]]:
    element_anchors: dict[ElementTree.Element, str] = {}
    original_targets: dict[str, str] = {}
    sequence = 0

    def allocate_anchor(element: ElementTree.Element, resource_href: str) -> str:
        nonlocal sequence
        current = element_anchors.get(element)
        if current is not None:
            return current
        sequence += 1
        if sequence > MAX_SECTIONS * 20:
            raise PublicationCorruptError("FB2 document has too many addressable nodes")
        anchor = f"fb2-node-{sequence:06d}"
        element_anchors[element] = anchor
        original_identifier = (_attribute(element, "id") or "").strip()
        if original_identifier:
            if original_identifier in original_targets:
                raise PublicationCorruptError("FB2 contains duplicate identifiers")
            original_targets[original_identifier] = f"{resource_href}#{anchor}"
        return anchor

    section_count = 0

    def build(
        element: ElementTree.Element,
        resource_href: str,
        fallback: str,
    ) -> _Fb2Section:
        nonlocal section_count
        section_count += 1
        if section_count > MAX_SECTIONS:
            raise PublicationCorruptError("FB2 contains too many sections")
        anchor = allocate_anchor(element, resource_href)
        title = _section_title(element, fallback)
        children = tuple(
            build(child, resource_href, f"{title} {index}")
            for index, child in enumerate(_direct_children(element, "section"), start=1)
        )
        return _Fb2Section(element, resource_href, anchor, title, children)

    roots: list[_Fb2Section] = []
    root_index = 0
    for body in _direct_children(root, "body"):
        sections = _direct_children(body, "section")
        if not sections:
            sections = [body]
        for section in sections:
            root_index += 1
            resource_href = f"fb2/section-{root_index:04d}.xhtml"
            roots.append(
                build(section, resource_href, f"{publication_title} {root_index}")
            )
            for element in section.iter():
                if _attribute(element, "id"):
                    allocate_anchor(element, resource_href)
    return tuple(roots), element_anchors, original_targets


def _escape(value: str) -> str:
    return html.escape(value, quote=True).replace("&#x27;", "&apos;")


def _relative_target(target: str) -> str:
    return target.removeprefix("fb2/")


def _render_element(
    element: ElementTree.Element,
    *,
    element_anchors: dict[ElementTree.Element, str],
    original_targets: dict[str, str],
    image_hrefs: dict[str, str],
) -> str:
    name = _local_name(element.tag)
    if name in {"section", "title", "binary"}:
        return ""
    if name == "empty-line":
        return "<br/>"
    if name == "image":
        source_identifier = (_attribute(element, "href") or "").removeprefix("#")
        image_href = image_hrefs.get(source_identifier)
        if image_href is None:
            return ""
        return f'<img src="{_escape(_relative_target(image_href))}" alt=""/>'

    content = _escape(element.text or "")
    for child in element:
        content += _render_element(
            child,
            element_anchors=element_anchors,
            original_targets=original_targets,
            image_hrefs=image_hrefs,
        )
        content += _escape(child.tail or "")

    mapped_name = {
        "p": "p",
        "subtitle": "h3",
        "emphasis": "em",
        "strong": "strong",
        "strikethrough": "s",
        "sub": "sub",
        "sup": "sup",
        "code": "code",
        "poem": "blockquote",
        "cite": "blockquote",
        "epigraph": "blockquote",
        "annotation": "aside",
        "stanza": "div",
        "v": "p",
        "text-author": "p",
        "table": "table",
        "tr": "tr",
        "th": "th",
        "td": "td",
    }.get(name)
    if name == "a":
        source_target = (_attribute(element, "href") or "").removeprefix("#")
        target = original_targets.get(source_target)
        if target is None:
            return content
        return f'<a href="{_escape(_relative_target(target))}">{content}</a>'
    if mapped_name is None:
        return content
    attributes = ""
    anchor = element_anchors.get(element)
    if anchor is not None:
        attributes = f' id="{anchor}"'
    if name == "stanza":
        attributes += ' class="stanza"'
    return f"<{mapped_name}{attributes}>{content}</{mapped_name}>"


def _render_section(
    section: _Fb2Section,
    *,
    depth: int,
    element_anchors: dict[ElementTree.Element, str],
    original_targets: dict[str, str],
    image_hrefs: dict[str, str],
) -> str:
    heading = min(depth, 6)
    content = "".join(
        _render_element(
            child,
            element_anchors=element_anchors,
            original_targets=original_targets,
            image_hrefs=image_hrefs,
        )
        for child in section.element
        if _local_name(child.tag) not in {"title", "section"}
    )
    nested = "".join(
        _render_section(
            child,
            depth=depth + 1,
            element_anchors=element_anchors,
            original_targets=original_targets,
            image_hrefs=image_hrefs,
        )
        for child in section.children
    )
    return (
        f'<section id="{section.anchor}"><h{heading}>{_escape(section.title)}'
        f"</h{heading}>{content}{nested}</section>"
    )


def _section_xhtml(
    section: _Fb2Section,
    *,
    language: str | None,
    element_anchors: dict[ElementTree.Element, str],
    original_targets: dict[str, str],
    image_hrefs: dict[str, str],
) -> bytes:
    body = _render_section(
        section,
        depth=1,
        element_anchors=element_anchors,
        original_targets=original_targets,
        image_hrefs=image_hrefs,
    )
    document = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{_escape(language or "und")}">
<head><meta charset="utf-8"/><title>{_escape(section.title)}</title>
<link rel="stylesheet" type="text/css" href="reader.css"/></head>
<body>{body}</body></html>""".encode()
    return decorate_markup_head(document, WEB_SECURITY_PROFILE)


def _toc_entry(section: _Fb2Section) -> PublicationTocEntry:
    return PublicationTocEntry(
        href=f"{section.resource_href}#{section.anchor}",
        title=section.title,
        children=tuple(_toc_entry(child) for child in section.children),
    )


def _snapshot(
    source_path_value: str,
    source_size: int,
    source_mtime_ns: int,
    fallback_title: str,
    fallback_author: str | None,
) -> _Fb2Snapshot:
    source_path = Path(source_path_value)
    try:
        content = source_path.read_bytes()
    except OSError as error:
        raise PublicationCorruptError("FB2 source is unavailable") from error
    root = _xml_root(content)
    description = _first_descendant(root, "description")
    title_info = _first_descendant(description, "title-info")
    title = (
        _normalized_text(_first_descendant(title_info, "book-title")) or fallback_title
    )
    author_values = (
        [_person_name(author) for author in _direct_children(title_info, "author")]
        if title_info is not None
        else []
    )
    author = ", ".join(value for value in author_values if value) or fallback_author
    language = _normalized_text(_first_descendant(title_info, "lang")) or None
    binary_resources, image_hrefs = _binary_resources(root)
    sections, element_anchors, original_targets = _build_sections(root, title)
    if not sections:
        raise PublicationCorruptError("FB2 reading order is empty")
    resources_by_href: dict[str, tuple[str, bytes | str]] = {
        _STYLESHEET_HREF: ("text/css", _STYLESHEET),
        **binary_resources,
    }
    reading_order: list[PublicationLink] = []
    for section in sections:
        reading_order.append(
            PublicationLink(
                href=section.resource_href,
                media_type="application/xhtml+xml",
                title=section.title,
            )
        )
    publication = NormalizedPublication(
        identifier=f"urn:shuku:fb2:{source_size}:{source_mtime_ns}",
        title=title,
        author=author,
        language=language,
        reading_progression="ltr",
        revision=PublicationRevision(
            source_size_bytes=source_size,
            source_mtime_ms=source_mtime_ns // 1_000_000,
            parser=FB2_PARSER_IDENTIFIER,
            normalization=FB2_NORMALIZATION_IDENTIFIER,
        ),
        reading_order=tuple(reading_order),
        resources=tuple(
            PublicationLink(href=href, media_type=media_type)
            for href, (media_type, _content) in resources_by_href.items()
            if href not in {link.href for link in reading_order}
        ),
        toc=tuple(_toc_entry(section) for section in sections),
    )
    return _Fb2Snapshot(
        publication=publication,
        source_mtime=source_path.stat().st_mtime,
        resources_by_href=resources_by_href,
        sections_by_href={section.resource_href: section for section in sections},
        element_anchors=element_anchors,
        original_targets=original_targets,
        image_hrefs=image_hrefs,
    )


class Fb2PublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root
        self._cache: PublicationSnapshotCache[_Fb2Snapshot] = PublicationSnapshotCache()

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._require_snapshot(source).publication

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        snapshot = self._require_snapshot(source)
        safe_href = _safe_resource_href(href)
        indexed = snapshot.resources_by_href.get(safe_href)
        section = snapshot.sections_by_href.get(safe_href)
        if section is not None:
            media_type = "application/xhtml+xml"
            content = _section_xhtml(
                section,
                language=snapshot.publication.language,
                element_anchors=snapshot.element_anchors,
                original_targets=snapshot.original_targets,
                image_hrefs=snapshot.image_hrefs,
            )
        elif indexed is not None:
            media_type, payload = indexed
            if isinstance(payload, str):
                try:
                    content = base64.b64decode(payload, validate=True)
                except (ValueError, binascii.Error) as error:
                    raise PublicationCorruptError(
                        "FB2 binary resource is invalid"
                    ) from error
                if not _matches_image_type(content, media_type):
                    raise PublicationCorruptError(
                        "FB2 image resource content is invalid"
                    )
            else:
                content = payload
        else:
            raise PublicationResourceNotFoundError
        return PublicationResource(
            href=safe_href,
            media_type=media_type,
            content=content,
            source_mtime=snapshot.source_mtime,
        )

    def _require_snapshot(self, source: PublicationSource) -> _Fb2Snapshot:
        if source.source_format != "fb2":
            raise PublicationUnsupportedError(source.source_format)
        source_path = resolve_publication_source(
            source.path,
            select_publication_source_root(source.library_root, self._storage_root),
        )
        stat_result = source_path.stat()
        if stat_result.st_size > MAX_FB2_SOURCE_BYTES:
            raise PublicationCorruptError("FB2 source exceeds the size limit")
        key = (
            str(source_path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.title,
            source.author,
        )
        return self._cache.get(
            key, lambda: _snapshot(*key), max(1, stat_result.st_size * 8)
        )

    def close(self) -> None:
        self._cache.close()


__all__ = [
    "FB2_NORMALIZATION_IDENTIFIER",
    "FB2_PARSER_IDENTIFIER",
    "Fb2PublicationAdapter",
]
