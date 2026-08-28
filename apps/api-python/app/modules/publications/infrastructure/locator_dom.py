"""Locator DOM Projection v2 and head-only publication security decoration."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from xml.etree import ElementTree

from app.modules.publications.domain.model import (
    PublicationMarkupError,
    PublicationSecurityError,
)
from app.modules.publications.domain.security import (
    WEB_SECURITY_PROFILE,
    PublicationSecurityProfile,
)

MAXIMUM_MARKUP_BYTES = 64 * 1024 * 1024
_LOCATOR_BLOCKS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "pre",
        "blockquote",
        "figcaption",
        "td",
        "th",
    }
)
_XML_DECLARATION = re.compile(r"<\?xml\b[^?]*\?>", re.IGNORECASE)
_XML_ENCODING = re.compile(
    r"encoding\s*=\s*([\"'])(?P<encoding>[^\"']+)\1", re.IGNORECASE
)
_HEAD_OPEN = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?head\b[^>]*>", re.IGNORECASE)
_HEAD_CLOSE = re.compile(r"</(?:[A-Za-z_][\w.-]*:)?head\s*>", re.IGNORECASE)
_BASE_TAG = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?base\b[^>]*(?:/\s*)?>", re.IGNORECASE)
_META_TAG = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?meta\b[^>]*(?:/\s*)?>", re.IGNORECASE)
_HTTP_EQUIV = re.compile(
    r"\bhttp-equiv\s*=\s*([\"'])(?P<value>[^\"']+)\1", re.IGNORECASE
)
_NON_MARKUP = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>", re.DOTALL)
_DOCTYPE_OPEN = re.compile(r"<!DOCTYPE\b", re.IGNORECASE)
_DOCTYPE_DECLARATION = re.compile(r"<!DOCTYPE\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ENTITY_OPEN = re.compile(r"<!ENTITY\b", re.IGNORECASE)
# ElementTree does not resolve external DTDs. Permit only the fixed declarations
# used by EPUB content documents; arbitrary external and internal DTDs stay blocked.
_SAFE_EPUB_DOCTYPE = re.compile(
    r"""<!DOCTYPE\s+html\s*(?:
        PUBLIC\s+
        (?P<public_quote>[\"'])
        -//W3C//DTD\s+XHTML\s+
        (?:1\.1|1\.0\s+(?:Strict|Transitional|Frameset))//EN
        (?P=public_quote)\s+
        (?P<system_quote>[\"'])
        https?://www\.w3\.org/TR/(?:
            xhtml11/DTD/xhtml11\.dtd|
            xhtml1/DTD/xhtml1-(?:strict|transitional|frameset)\.dtd
        )
        (?P=system_quote)
    )?\s*>""",
    re.IGNORECASE | re.VERBOSE,
)
_NAMED_ENTITY_REFERENCE = re.compile(r"&(?P<name>[A-Za-z][A-Za-z0-9]+);")
_STANDARD_XHTML_ENTITY_CODEPOINTS = {"nbsp": 0xA0}
_SPACE = re.compile(r"\s+")


_SECURITY_STYLE = (
    "iframe,frame,object,embed,applet{display:none!important;}"
    "input,button,select,textarea{pointer-events:none!important;}"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _decode_markup(content: bytes) -> str:
    if not content or len(content) > MAXIMUM_MARKUP_BYTES:
        raise PublicationSecurityError("publication markup exceeds the size limit")
    try:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            decoded = content.decode("utf-16", errors="strict")
        elif content.startswith(b"\xef\xbb\xbf"):
            decoded = content.decode("utf-8-sig", errors="strict")
        else:
            prefix = content[:512].decode("ascii", errors="ignore")
            declaration = _XML_DECLARATION.search(prefix)
            encoding_match = (
                _XML_ENCODING.search(declaration.group(0)) if declaration else None
            )
            encoding = (
                encoding_match.group("encoding").lower().replace("_", "-")
                if encoding_match
                else "utf-8"
            )
            if encoding not in {"utf-8", "utf8"}:
                raise PublicationMarkupError(
                    "publication markup encoding is unsupported"
                )
            decoded = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise PublicationMarkupError(
            "publication markup encoding is invalid"
        ) from error
    return decoded


def _validate_markup_declarations(markup: str) -> None:
    lexical_markup = _NON_MARKUP.sub(lambda match: " " * len(match.group(0)), markup)
    if _ENTITY_OPEN.search(lexical_markup):
        raise PublicationSecurityError(
            "publication markup declarations are unsupported"
        )

    doctype_opens = list(_DOCTYPE_OPEN.finditer(lexical_markup))
    if not doctype_opens:
        return
    declarations = list(_DOCTYPE_DECLARATION.finditer(lexical_markup))
    if len(doctype_opens) != 1 or len(declarations) != 1:
        raise PublicationSecurityError(
            "publication markup declarations are unsupported"
        )

    declaration = declarations[0]
    if declaration.start() != doctype_opens[0].start():
        raise PublicationSecurityError(
            "publication markup declarations are unsupported"
        )
    if _SAFE_EPUB_DOCTYPE.fullmatch(declaration.group(0)) is None:
        raise PublicationSecurityError(
            "publication markup declarations are unsupported"
        )
    if lexical_markup[: declaration.start()].strip():
        raise PublicationSecurityError(
            "publication markup declarations are unsupported"
        )


def _replace_standard_entity_references(markup: str) -> str:
    """Create a parser-only copy with fixed XHTML entities encoded numerically."""

    def replace_in_markup(segment: str) -> str:
        def replace(match: re.Match[str]) -> str:
            codepoint = _STANDARD_XHTML_ENTITY_CODEPOINTS.get(match.group("name"))
            return f"&#x{codepoint:X};" if codepoint is not None else match.group(0)

        return _NAMED_ENTITY_REFERENCE.sub(replace, segment)

    parts: list[str] = []
    previous_end = 0
    for non_markup in _NON_MARKUP.finditer(markup):
        parts.append(replace_in_markup(markup[previous_end : non_markup.start()]))
        parts.append(non_markup.group(0))
        previous_end = non_markup.end()
    parts.append(replace_in_markup(markup[previous_end:]))
    return "".join(parts)


def validate_xhtml(content: bytes) -> tuple[str, ElementTree.Element]:
    """Decode and validate one XHTML resource without rewriting its body."""

    markup, root = parse_safe_markup_root(content)
    if _local_name(root.tag) != "html":
        raise PublicationMarkupError("publication XHTML root must be html")
    heads = [child for child in root if _local_name(child.tag) == "head"]
    bodies = [child for child in root if _local_name(child.tag) == "body"]
    if len(heads) != 1 or len(bodies) != 1:
        raise PublicationMarkupError(
            "publication XHTML must contain one head and one body"
        )
    return markup, root


def parse_safe_markup_root(content: bytes) -> tuple[str, ElementTree.Element]:
    """Parse well-formed markup after blocking active declarations.

    Navigation documents use this boundary because their XML tree is useful even
    when optional XHTML document structure such as ``head`` is absent.
    """

    markup = _decode_markup(content)
    _validate_markup_declarations(markup)
    try:
        root = ElementTree.fromstring(_replace_standard_entity_references(markup))
    except ElementTree.ParseError as error:
        raise PublicationMarkupError("publication XHTML is not well formed") from error
    return markup, root


def _normalized_text(element: ElementTree.Element) -> str:
    text = "".join(element.itertext()).replace("\r\n", "\n").replace("\r", "\n")
    return _SPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _element_projection(
    element: ElementTree.Element,
    path: str,
) -> list[dict[str, str]]:
    local_name = _local_name(element.tag)
    record = {"path": path, "localName": local_name}
    element_id = element.attrib.get("id")
    if element_id is not None:
        record["id"] = element_id
    if local_name in _LOCATOR_BLOCKS:
        record["text"] = _normalized_text(element)
    records = [record]
    sibling_counts: dict[str, int] = {}
    for child in element:
        child_name = _local_name(child.tag)
        sibling_counts[child_name] = sibling_counts.get(child_name, 0) + 1
        records.extend(
            _element_projection(
                child,
                f"{path}/{child_name}[{sibling_counts[child_name]}]",
            )
        )
    return records


def _body_projection(root: ElementTree.Element) -> list[dict[str, str]]:
    body = next(child for child in root if _local_name(child.tag) == "body")
    return _element_projection(body, "/body[1]")


def locator_dom_projection(
    *,
    normalization: str,
    resources: tuple[tuple[str, str, bytes], ...],
) -> dict[str, object]:
    reading_order: list[dict[str, object]] = []
    for href, media_type, content in resources:
        _markup, root = validate_xhtml(content)
        reading_order.append(
            {
                "href": href,
                "mediaType": media_type,
                "elements": _body_projection(root),
            }
        )
    return {
        "schemaVersion": 2,
        "normalization": normalization,
        "readingOrder": reading_order,
    }


def locator_dom_projection_hash(projection: dict[str, object]) -> str:
    """Return the language-neutral SHA-256 identity for a v2 projection."""

    canonical = json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _remove_unsafe_head_elements(head: str) -> str:
    without_base = _BASE_TAG.sub("", head)

    def remove_meta(match: re.Match[str]) -> str:
        http_equiv = _HTTP_EQUIV.search(match.group(0))
        if http_equiv and http_equiv.group("value").strip().lower() in {
            "content-security-policy",
            "refresh",
        }:
            return ""
        return match.group(0)

    return _META_TAG.sub(remove_meta, without_base)


def publication_security_head(profile: PublicationSecurityProfile) -> str:
    """Trusted head markup for application-generated chapters and decoration."""

    return (
        '<meta http-equiv="Content-Security-Policy" '
        f'content="{profile.content_security_policy}" '
        f'data-shuku-security-profile="{profile.identifier}"/>'
        f'<style data-shuku-security-profile="{profile.identifier}">'
        f"{_SECURITY_STYLE}</style>"
    )


def decorate_markup_head(
    content: bytes,
    profile: PublicationSecurityProfile,
) -> bytes:
    """Install a platform CSP without parsing or serializing the author body."""

    markup, root = validate_xhtml(content)
    lexical_markup = _NON_MARKUP.sub(lambda match: " " * len(match.group(0)), markup)
    head_open = _HEAD_OPEN.search(lexical_markup)
    if head_open is None:
        raise PublicationMarkupError("publication XHTML head cannot be decorated")
    head_close = _HEAD_CLOSE.search(lexical_markup, head_open.end())
    if head_close is None:
        raise PublicationMarkupError("publication XHTML head cannot be decorated")
    original_head = markup[head_open.end() : head_close.start()]
    safe_head = _remove_unsafe_head_elements(original_head)
    decoration = publication_security_head(profile)
    decorated = (
        markup[: head_open.end()]
        + decoration
        + safe_head
        + markup[head_close.start() :]
    )
    declaration = _XML_DECLARATION.search(decorated)
    if declaration is not None:
        updated = _XML_ENCODING.sub('encoding="utf-8"', declaration.group(0), count=1)
        decorated = (
            decorated[: declaration.start()] + updated + decorated[declaration.end() :]
        )
    decorated_bytes = decorated.encode("utf-8")
    _decorated_markup, decorated_root = validate_xhtml(decorated_bytes)
    if _body_projection(root) != _body_projection(decorated_root):
        raise PublicationMarkupError(
            "publication security decoration changed the locator DOM projection"
        )
    return decorated_bytes


__all__ = [
    "MAXIMUM_MARKUP_BYTES",
    "WEB_SECURITY_PROFILE",
    "PublicationSecurityProfile",
    "decorate_markup_head",
    "locator_dom_projection",
    "locator_dom_projection_hash",
    "validate_xhtml",
]
