"""Deterministic, server-owned rendering normalization for reflowable markup."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import html5lib  # type: ignore[import-untyped]  # Upstream ships no type metadata.

from app.modules.publications.domain.model import (
    PublicationMarkupError,
    PublicationSecurityError,
)
from app.modules.publications.domain.rendering import (
    RENDER_ARTIFACT_SCHEMA_VERSION,
    RENDER_NORMALIZATION_IDENTIFIER,
)
from app.modules.publications.infrastructure.locator_dom import (
    WEB_SECURITY_PROFILE,
    _decode_markup,
    _validate_markup_declarations,
    decorate_markup_head,
)

XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
EPUB_NAMESPACE = "http://www.idpf.org/2007/ops"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
ERROR_MARKER_ATTRIBUTE = "data-shuku-resource-error"

ElementTree.register_namespace("", XHTML_NAMESPACE)
ElementTree.register_namespace("epub", EPUB_NAMESPACE)


@dataclass(frozen=True, slots=True)
class CanonicalMarkup:
    content: bytes
    recovered: bool
    unreadable: bool


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _canonical_attribute_name(name: str) -> str | None:
    if name == "xmlns" or name.startswith("xmlns:"):
        return None
    if name.startswith("epub:"):
        return f"{{{EPUB_NAMESPACE}}}{name.split(':', 1)[1]}"
    if name.startswith("xml:"):
        return f"{{{XML_NAMESPACE}}}{name.split(':', 1)[1]}"
    if ":" in name and not name.startswith("{"):
        return f"data-shuku-{name.replace(':', '-')}"
    return name


def _canonicalize_attributes(root: ElementTree.Element) -> None:
    for element in root.iter():
        attributes = [
            (canonical, value)
            for name, value in element.attrib.items()
            if (canonical := _canonical_attribute_name(name)) is not None
        ]
        element.attrib.clear()
        element.attrib.update(sorted(attributes, key=lambda value: value[0]))


def _canonicalize_element_names(root: ElementTree.Element) -> None:
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag.startswith("{") and "}" in element.tag:
            namespace, local_name = element.tag[1:].split("}", 1)
        else:
            namespace, local_name = XHTML_NAMESPACE, element.tag
        if ":" not in local_name:
            continue
        element.tag = f"{{{namespace}}}{local_name.replace(':', '-')}"
        element.attrib.setdefault("data-shuku-original-element", local_name)


_MOBIPOCKET_PAGEBREAK_START = re.compile(
    r"<\s*mbp:pagebreak\b[^>]*>",
    flags=re.IGNORECASE,
)
_MOBIPOCKET_PAGEBREAK_END = re.compile(
    r"</\s*mbp:pagebreak\s*>",
    flags=re.IGNORECASE,
)


def _normalize_legacy_mobipocket_markup(markup: str) -> str:
    normalized = _MOBIPOCKET_PAGEBREAK_START.sub(
        '<hr data-shuku-original-element="mbp:pagebreak" data-shuku-pagebreak="true"/>',
        markup,
    )
    return _MOBIPOCKET_PAGEBREAK_END.sub("", normalized)


def _secure_head(root: ElementTree.Element) -> None:
    head = next(
        (element for element in root.iter() if _local_name(element.tag) == "head"), None
    )
    if head is None:
        head = ElementTree.Element(f"{{{XHTML_NAMESPACE}}}head")
        root.insert(0, head)
    for element in list(head):
        local_name = _local_name(element.tag)
        if local_name == "base":
            head.remove(element)
            continue
        if local_name != "meta":
            continue
        http_equiv = next(
            (
                value.lower()
                for name, value in element.attrib.items()
                if _local_name(name) == "http-equiv"
            ),
            "",
        )
        if http_equiv in {"content-security-policy", "refresh"}:
            head.remove(element)
    meta = ElementTree.Element(
        f"{{{XHTML_NAMESPACE}}}meta",
        {
            "http-equiv": "Content-Security-Policy",
            "content": WEB_SECURITY_PROFILE.content_security_policy.replace(
                "script-src blob:", "script-src 'none'"
            ),
            "data-shuku-security-profile": "canonical-v1",
        },
    )
    style = ElementTree.Element(
        f"{{{XHTML_NAMESPACE}}}style",
        {"data-shuku-security-profile": "canonical-v1"},
    )
    style.text = (
        "iframe,frame,object,embed,applet{display:none!important;}"
        "input,button,select,textarea{pointer-events:none!important;}"
        "[data-shuku-pagebreak]{border:0;height:0;break-after:page;"
        "page-break-after:always;}"
    )
    head.insert(0, style)
    head.insert(0, meta)


def _recover_html5(markup: str) -> bytes:
    root = html5lib.parse(
        _normalize_legacy_mobipocket_markup(markup),
        treebuilder="etree",
        namespaceHTMLElements=True,
    )
    if not isinstance(root, ElementTree.Element):
        raise PublicationMarkupError("publication HTML5 recovery produced no root")
    _canonicalize_element_names(root)
    _canonicalize_attributes(root)
    _secure_head(root)
    content = ElementTree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=True,
    )
    try:
        ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise PublicationMarkupError(
            "publication HTML5 recovery did not produce valid XHTML"
        ) from error
    return content


def unreadable_markup(
    *,
    href: str,
    previous_href: str | None = None,
    next_href: str | None = None,
    contents_href: str | None = None,
) -> bytes:
    safe_href = html.escape(href, quote=True)
    previous_label = "".join(map(chr, (19978, 19968, 39029))) + " / Previous"
    next_label = "".join(map(chr, (19979, 19968, 39029))) + " / Next"
    contents_label = "".join(map(chr, (30446, 24405))) + " / Contents"
    error_heading = "".join(map(chr, (27492, 39029, 38754, 26080, 27861, 26174, 31034)))
    navigation_label = (
        "".join(map(chr, (38405, 35835, 23548, 33322))) + " / Reading navigation"
    )
    links = []
    if previous_href is not None:
        links.append(
            f'<a rel="prev" href="{html.escape(previous_href, quote=True)}">'
            f"{previous_label}</a>"
        )
    if next_href is not None:
        links.append(
            f'<a rel="next" href="{html.escape(next_href, quote=True)}">'
            f"{next_label}</a>"
        )
    if contents_href is not None:
        links.append(
            f'<a rel="contents" href="{html.escape(contents_href, quote=True)}">'
            f"{contents_label}</a>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<html xmlns="{XHTML_NAMESPACE}"><head>'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\"/>"
        "<style>body{font-family:system-ui,sans-serif;display:grid;min-height:80vh;"
        "place-content:center;text-align:center;padding:2rem;color:#282421}"
        "nav{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap}"
        "a{color:inherit;padding:.7rem 1rem;border:1px solid currentColor;"
        "border-radius:999px;text-decoration:none}</style>"
        "<title>This page cannot be displayed</title></head>"
        f'<body {ERROR_MARKER_ATTRIBUTE}="RESOURCE_UNREADABLE" '
        f'data-shuku-resource-href="{safe_href}"><main role="alert">'
        f"<h1>{error_heading}</h1>"
        '<p lang="en">This page can’t be displayed</p>'
        f'<nav aria-label="{navigation_label}">'
        f"{''.join(links)}</nav>"
        "</main></body></html>"
    ).encode()


def canonicalize_markup(content: bytes, *, href: str) -> CanonicalMarkup:
    """Return safe render bytes without mutating the source publication."""

    try:
        return CanonicalMarkup(
            content=decorate_markup_head(content, WEB_SECURITY_PROFILE),
            recovered=False,
            unreadable=False,
        )
    except PublicationSecurityError:
        raise
    except PublicationMarkupError:
        try:
            markup = _decode_markup(content)
            _validate_markup_declarations(markup)
            recovered = _recover_html5(markup)
        except PublicationSecurityError:
            raise
        except (PublicationMarkupError, ValueError):
            return CanonicalMarkup(
                content=unreadable_markup(href=href),
                recovered=False,
                unreadable=True,
            )
        return CanonicalMarkup(
            content=recovered,
            recovered=True,
            unreadable=False,
        )


__all__ = [
    "ERROR_MARKER_ATTRIBUTE",
    "RENDER_ARTIFACT_SCHEMA_VERSION",
    "RENDER_NORMALIZATION_IDENTIFIER",
    "CanonicalMarkup",
    "canonicalize_markup",
    "unreadable_markup",
]
