"""Safe direct FB2 to Readium Web Publication adapter."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
    reader_safety_fb2_embedded_image_extension,
)
from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.application.safety_policy import (
    publication_integrity_failure,
    publication_native_parser_implementation_failure,
    publication_optional_resource_failure,
    publication_parser_limit,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationMarkupError,
    PublicationReadError,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationStructureError,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.chapter_core import (
    ChapterCore,
    xml_chapter_events,
)
from app.modules.publications.infrastructure.locator_dom import (
    WEB_SECURITY_PROFILE,
    publication_security_head,
)
from app.modules.publications.infrastructure.snapshot_cache import (
    PublicationSnapshotCache,
    publication_snapshot_weight,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)
from app.modules.publications.infrastructure.xml_policy import (
    XmlPolicyDecodeError,
    XmlPolicyExpansionLimitError,
    XmlPolicyPreparationError,
    parse_xml,
)

FB2_PARSER_IDENTIFIER = "shuku-fb2-parser-v1"
FB2_NORMALIZATION_IDENTIFIER = "shuku-fb2-publication-v3"
MAX_FB2_SOURCE_BYTES = reader_safety_budget(ReaderSafetyBudgetName.FB2_TEXT_MAX_BYTES)
MAX_FB2_XML_EXPANSION_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES
)
MAX_ENCODED_BINARY_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.FB2_ENCODED_IMAGE_MAX_BYTES
)
MAX_BINARY_RESOURCE_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.FB2_DECODED_IMAGE_MAX_BYTES
)
MAX_TOTAL_BINARY_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.FB2_DECODED_IMAGES_TOTAL_MAX_BYTES
)
MAX_XML_ELEMENTS = reader_safety_budget(ReaderSafetyBudgetName.FB2_MAX_NODES)
MAX_XML_DEPTH = reader_safety_budget(ReaderSafetyBudgetName.FB2_MAX_DEPTH)
MAX_TEXT_CHARACTERS = reader_safety_budget(
    ReaderSafetyBudgetName.FB2_TEXT_MAX_CHARACTERS
)
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


@dataclass(frozen=True, slots=True)
class _Fb2Section:
    element: ElementTree.Element
    resource_href: str
    anchor: str
    title: str
    children: tuple[_Fb2Section, ...]


@dataclass(frozen=True, slots=True)
class _Fb2ResourceMarker:
    """Deferred optional-resource decision retained in the publication index.

    FB2 image budgets are enforced when the resource is first requested.  The
    marker keeps the original encoded text and digest for provenance while
    avoiding a speculative base64 decode during publication construction.
    """

    rule_id: ReaderSafetyRuleId
    message: str
    original_text: str
    original_text_sha256: str


@dataclass(frozen=True, slots=True)
class _Fb2Snapshot:
    publication: NormalizedPublication
    source_mtime: float
    resources_by_href: dict[str, tuple[str, bytes | str | _Fb2ResourceMarker | None]]
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
    if len(content) > MAX_FB2_SOURCE_BYTES:
        raise publication_parser_limit(
            ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
            "FB2 source exceeds the size limit",
        )
    content = _normalize_legacy_link_prefix(content)
    try:
        _projection, root = parse_xml(
            content,
            expansion_limit_bytes=MAX_FB2_XML_EXPANSION_BYTES,
        )
    except (ElementTree.ParseError, UnicodeDecodeError) as error:
        raise PublicationMarkupError("FB2 XML is invalid") from error
    except XmlPolicyExpansionLimitError as error:
        raise publication_parser_limit(
            ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
            "FB2 XML entity expansion exceeds the size limit",
        ) from error
    except XmlPolicyDecodeError as error:
        raise PublicationMarkupError("FB2 XML encoding is invalid") from error
    except XmlPolicyPreparationError as error:
        raise publication_native_parser_implementation_failure(
            ReaderSafetyRuleId.REFLOWABLE_PREPARE_XML,
            parser="reader-xml-policy",
            operation="prepare",
            reason="generated XML preparation defense is unavailable",
        ) from error
    if _local_name(root.tag) != "FictionBook":
        raise PublicationStructureError("FB2 root element is invalid")
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
    text_characters = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_XML_ELEMENTS:
            raise publication_parser_limit(
                ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
                "FB2 contains too many XML elements",
            )
        if depth > MAX_XML_DEPTH:
            raise publication_parser_limit(
                ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
                "FB2 XML nesting is too deep",
            )
        text_characters += len(element.text or "") + len(element.tail or "")
        if text_characters > MAX_TEXT_CHARACTERS:
            raise publication_parser_limit(
                ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
                "FB2 text exceeds the character limit",
            )
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
) -> tuple[
    dict[str, tuple[str, bytes | str | _Fb2ResourceMarker | None]],
    dict[str, str],
]:
    resources: dict[str, tuple[str, bytes | str | _Fb2ResourceMarker | None]] = {}
    href_by_identifier: dict[str, str] = {}
    seen_identifiers: set[str] = set()
    total_size = 0
    for binary in (item for item in root if _local_name(item.tag) == "binary"):
        identifier = (_attribute(binary, "id") or "").strip()
        media_type = (_attribute(binary, "content-type") or "").strip().lower()
        extension = reader_safety_fb2_embedded_image_extension(media_type) or ""
        if not identifier:
            continue
        if identifier in seen_identifiers:
            previous_href = href_by_identifier.get(identifier)
            if previous_href is not None:
                previous_media_type, _ = resources[previous_href]
                resources[previous_href] = (previous_media_type, None)
            continue
        seen_identifiers.add(identifier)
        encoded = "".join("".join(binary.itertext()).split())

        safe_identifier = hashlib.sha256(identifier.encode()).hexdigest()[:20]
        href = f"fb2/images/{safe_identifier}{extension}"

        def mark(
            rule_id: ReaderSafetyRuleId,
            message: str,
            *,
            resource_href: str = href,
            resource_media_type: str = media_type,
            original_encoded: str = encoded,
            resource_identifier: str = identifier,
        ) -> None:
            resources[resource_href] = (
                resource_media_type,
                _Fb2ResourceMarker(
                    rule_id=rule_id,
                    message=message,
                    original_text=original_encoded,
                    original_text_sha256=hashlib.sha256(
                        original_encoded.encode("ascii", "replace")
                    ).hexdigest(),
                ),
            )
            href_by_identifier[resource_identifier] = resource_href

        if len(encoded) > MAX_ENCODED_BINARY_BYTES:
            mark(
                ReaderSafetyRuleId.FB2_IMAGE_BUDGET,
                "FB2 encoded image exceeds the generated resource budget",
            )
            continue
        estimated_size = (len(encoded) // 4) * 3 - (
            len(encoded) - len(encoded.rstrip("="))
        )
        if not encoded or estimated_size < 1:
            mark(
                ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
                "FB2 binary resource has no valid encoded content",
            )
            continue
        if estimated_size > MAX_BINARY_RESOURCE_BYTES:
            mark(
                ReaderSafetyRuleId.FB2_IMAGE_BUDGET,
                "FB2 decoded image exceeds the generated resource budget",
            )
            continue
        if total_size + estimated_size > MAX_TOTAL_BINARY_BYTES:
            mark(
                ReaderSafetyRuleId.FB2_IMAGE_BUDGET,
                "FB2 decoded images exceed the generated aggregate budget",
            )
            continue
        total_size += estimated_size
        resources[href] = (media_type, encoded)
        href_by_identifier[identifier] = href
    return resources, href_by_identifier


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
    # IDs reflect source element order, including unnamed sections. They are
    # renderer addresses; chapter selection belongs exclusively to the C core.
    element_anchors = {
        element: f"chapter-node-{index}" for index, element in enumerate(root.iter())
    }
    original_targets: dict[str, str] = {}

    def build(element: ElementTree.Element, href: str) -> _Fb2Section:
        for descendant in element.iter():
            identifier = (_attribute(descendant, "id") or "").strip()
            if identifier:
                target = f"{href}#{element_anchors[descendant]}"
                if (
                    identifier in original_targets
                    and original_targets[identifier] != target
                ):
                    raise PublicationCorruptError("FB2 contains duplicate identifiers")
                original_targets[identifier] = target
        return _Fb2Section(
            element,
            href,
            element_anchors.get(element, "body"),
            _section_title(element, ""),
            tuple(build(child, href) for child in _direct_children(element, "section")),
        )

    roots: list[_Fb2Section] = []
    section_index = 0
    for body_index, body in enumerate(_direct_children(root, "body"), start=1):
        loose = ElementTree.Element("body")
        loose.text = body.text
        part_index = 0

        def flush_loose(body_number: int = body_index) -> None:
            nonlocal loose, part_index
            if len(loose) or (loose.text or "").strip():
                part_index += 1
                href = f"fb2/body-{body_number}-part-{part_index}.xhtml"
                roots.append(build(loose, href))
            loose = ElementTree.Element("body")

        for child in body:
            if _local_name(child.tag) == "section":
                flush_loose()
                section_index += 1
                roots.append(build(child, f"fb2/section-{section_index:04d}.xhtml"))
                loose.text = child.tail
            else:
                loose.append(child)
        flush_loose()
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
    anchor = element_anchors.get(element) if _attribute(element, "id") else None
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
    child_sections = {child.element: child for child in section.children}
    rendered = [_escape(section.element.text or "")]
    for child in section.element:
        if _local_name(child.tag) == "title":
            continue
        nested = child_sections.get(child)
        if nested is not None:
            rendered.append(
                _render_section(
                    nested,
                    depth=depth + 1,
                    element_anchors=element_anchors,
                    original_targets=original_targets,
                    image_hrefs=image_hrefs,
                )
            )
        else:
            rendered.append(
                _render_element(
                    child,
                    element_anchors=element_anchors,
                    original_targets=original_targets,
                    image_hrefs=image_hrefs,
                )
            )
        rendered.append(_escape(child.tail or ""))
    title = (
        f"<h{heading}>{_escape(section.title)}</h{heading}>" if section.title else ""
    )
    return f'<section id="{section.anchor}">{title}{"".join(rendered)}</section>'


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
<head>{publication_security_head(WEB_SECURITY_PROFILE)}<meta charset="utf-8"/><title>{_escape(section.title)}</title>
<link rel="stylesheet" type="text/css" href="reader.css"/></head>
<body>{body}</body></html>""".encode()
    return document


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
        raise PublicationReadError("FB2 source is unavailable") from error
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
        raise PublicationStructureError("FB2 reading order is empty")
    targets = {
        element: f"{section.resource_href}#{element_anchors[element]}"
        for section in sections
        for element in section.element.iter()
        if element in element_anchors
    }
    projection = ChapterCore.load().parse_xml(
        3, tuple(xml_chapter_events(root, targets.get))
    )
    chapter_titles = {
        entry.href: entry.title for entry in projection.entries if entry.href
    }

    def titled(section: _Fb2Section) -> _Fb2Section:
        return replace(
            section,
            title=chapter_titles.get(
                f"{section.resource_href}#{section.anchor}", section.title
            ),
            children=tuple(titled(child) for child in section.children),
        )

    sections = tuple(titled(section) for section in sections)

    resources_by_href: dict[
        str, tuple[str, bytes | str | _Fb2ResourceMarker | None]
    ] = {
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
        toc=projection.table_of_contents(),
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
            if payload is None:
                raise publication_integrity_failure(
                    ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
                    "FB2 binary resource is ambiguous",
                    optional=True,
                )
            if isinstance(payload, _Fb2ResourceMarker):
                if payload.rule_id is ReaderSafetyRuleId.FB2_IMAGE_BUDGET:
                    raise publication_optional_resource_failure(
                        payload.rule_id,
                        payload.message,
                    )
                raise publication_integrity_failure(
                    payload.rule_id,
                    payload.message,
                    optional=True,
                )
            if isinstance(payload, str):
                try:
                    content = base64.b64decode(payload, validate=True)
                except (ValueError, binascii.Error) as error:
                    raise publication_integrity_failure(
                        ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
                        "FB2 binary resource is invalid",
                        optional=True,
                    ) from error
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
            raise publication_parser_limit(
                ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET,
                "FB2 source exceeds the size limit",
            )
        key = (
            str(source_path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.title,
            source.author,
        )
        return self._cache.get(
            key,
            lambda: _snapshot(*key),
            publication_snapshot_weight(stat_result.st_size),
        )

    def close(self) -> None:
        self._cache.close()


__all__ = [
    "FB2_NORMALIZATION_IDENTIFIER",
    "FB2_PARSER_IDENTIFIER",
    "Fb2PublicationAdapter",
]
