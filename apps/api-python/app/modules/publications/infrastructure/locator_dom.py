"""Locator DOM projection and generated-policy in-memory markup sanitization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit
from xml.etree import ElementTree

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_POLICY_DIGEST,
    READER_SAFETY_POLICY_ID,
    READER_SAFETY_POLICY_VERSION,
    READER_SAFETY_REFLOWABLE_PROFILE,
    ReaderSafetyBudgetName,
    ReaderSafetyErrorCode,
    ReaderSafetyRuleId,
    ReaderSafetyUriAttributePolicy,
    ReaderSafetyUriPurpose,
    ReaderSafetyUriSyntax,
    reader_safety_budget,
)
from app.modules.publications.application.safety_policy import (
    publication_parser_limit,
    publication_security_rejection,
)
from app.modules.publications.domain.model import (
    PublicationMarkupError,
)
from app.modules.publications.domain.security import (
    WEB_SECURITY_PROFILE,
    PublicationSecurityProfile,
)

MAXIMUM_MARKUP_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES
)
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
_NON_MARKUP = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>", re.DOTALL)
_DOCTYPE_OPEN = re.compile(r"<!DOCTYPE\b", re.IGNORECASE)
_DOCTYPE_DECLARATION = re.compile(r"<!DOCTYPE\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ENTITY_OPEN = re.compile(r"<!ENTITY\b", re.IGNORECASE)
_PUBLIC_DOCTYPE = re.compile(
    r"""<!DOCTYPE\s+(?P<name>[A-Za-z][\w.-]*)\s+PUBLIC\s+
    (?P<public_quote>[\"'])(?P<public_id>[^\"']+)(?P=public_quote)\s+
    (?P<system_quote>[\"'])(?P<system_id>[^\"']+)(?P=system_quote)\s*>""",
    re.IGNORECASE | re.VERBOSE,
)
_NAMED_ENTITY_REFERENCE = re.compile(r"&(?P<name>[A-Za-z][A-Za-z0-9]+);")
_STANDARD_XHTML_ENTITY_CODEPOINTS = dict(
    READER_SAFETY_REFLOWABLE_PROFILE.named_entity_codepoints
)
_SPACE = re.compile(r"\s+")
_CSS_URL = re.compile(
    r"url\(\s*(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|(?P<bare>(?:[^()]|\([^()]*\))*))\s*\)",
    re.IGNORECASE,
)
_CSS_IMPORT = re.compile(
    r"""@import\s+(?:url\(\s*)?(?:(?P<quote>["'])(?P<quoted>.*?)(?P=quote)|(?P<bare>[^\s;)]+))\s*\)?[^;]*;""",
    re.IGNORECASE | re.DOTALL,
)
_CSS_EXPRESSION_DECLARATION = re.compile(
    r"(?P<prefix>^|[;{])\s*[-A-Za-z_][\w-]*\s*:[^;{}]*expression\s*\([^;{}]*(?:;|(?=}))",
    re.IGNORECASE | re.DOTALL,
)
_CSS_BEHAVIOR_DECLARATION = re.compile(
    r"(?P<prefix>^|[;{])\s*behavior\s*:[^;{}]*(?:;|(?=}))",
    re.IGNORECASE | re.DOTALL,
)
_CSS_MOZ_BINDING_DECLARATION = re.compile(
    r"(?P<prefix>^|[;{])\s*-moz-binding\s*:[^;{}]*(?:;|(?=}))",
    re.IGNORECASE | re.DOTALL,
)
_EMPTY_CSS_RULE = re.compile(r"[^{}]+\{\s*}", re.DOTALL)
_CSS_ESCAPE = re.compile(r"\\(?:(?P<hex>[0-9a-fA-F]{1,6})\s?|(?P<escaped>.))")


_SECURITY_STYLE = (
    "iframe,frame,object,embed,applet{display:none!important;}"
    "input,button,select,textarea{pointer-events:none!important;}"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _decode_markup(content: bytes) -> str:
    if not content:
        raise PublicationMarkupError("publication markup is empty")
    if len(content) > MAXIMUM_MARKUP_BYTES:
        raise publication_parser_limit(
            ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
            "publication markup exceeds the size limit",
        )
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
        raise publication_security_rejection(
            ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            "publication markup declares a custom entity",
        )

    for reference in _NAMED_ENTITY_REFERENCE.finditer(lexical_markup):
        name = reference.group("name")
        if name not in _STANDARD_XHTML_ENTITY_CODEPOINTS:
            raise publication_security_rejection(
                ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
                "publication markup references a custom entity",
            )

    doctype_opens = list(_DOCTYPE_OPEN.finditer(lexical_markup))
    if not doctype_opens:
        return
    declarations = list(_DOCTYPE_DECLARATION.finditer(lexical_markup))
    if len(doctype_opens) != 1 or len(declarations) != 1:
        raise publication_security_rejection(
            ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            "publication markup contains an invalid document type",
        )

    declaration = declarations[0]
    if declaration.start() != doctype_opens[0].start():
        raise publication_security_rejection(
            ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            "publication markup contains an invalid document type",
        )
    match = _PUBLIC_DOCTYPE.fullmatch(declaration.group(0))
    allowed = {
        (entry.name.lower(), entry.public_id, entry.system_id)
        for entry in READER_SAFETY_REFLOWABLE_PROFILE.safe_doctypes
    }
    identity = (
        (
            match.group("name").lower(),
            match.group("public_id"),
            match.group("system_id"),
        )
        if match is not None
        else None
    )
    if identity not in allowed:
        raise publication_security_rejection(
            ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            "publication markup document type is not allowed",
        )
    if lexical_markup[: declaration.start()].strip():
        raise publication_security_rejection(
            ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            "publication markup document type is misplaced",
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
    _sanitize_markup_tree(root)
    return markup, root


def _attribute_local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _attribute_policy_name(name: str) -> str:
    if name == "{http://www.w3.org/XML/1998/namespace}base":
        return "xml:base"
    if name == "{http://www.w3.org/1999/xlink}href":
        return "xlink:href"
    return name.rsplit("}", 1)[-1].lower()


def _uri_attribute_policy(
    *, element: str, attribute: str
) -> ReaderSafetyUriAttributePolicy | None:
    for policy in READER_SAFETY_REFLOWABLE_PROFILE.uri_attribute_policies:
        if policy.attribute.casefold() != attribute:
            continue
        elements = {value.casefold() for value in policy.elements}
        if "*" in elements or element in elements:
            return policy
    return None


def _is_remote_or_blocked_reference(value: str, *, user_navigation: bool) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.startswith("//"):
        return True
    scheme = urlsplit(candidate).scheme.lower()
    if scheme in READER_SAFETY_REFLOWABLE_PROFILE.blocked_author_schemes:
        return True
    if scheme in READER_SAFETY_REFLOWABLE_PROFILE.remote_subresource_schemes:
        return not user_navigation
    if scheme and user_navigation:
        return scheme not in READER_SAFETY_REFLOWABLE_PROFILE.user_navigation_schemes
    return bool(scheme)


def _decode_css_for_detection(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        hexadecimal = match.group("hex")
        if hexadecimal is not None:
            codepoint = int(hexadecimal, 16)
            return chr(codepoint) if 0 < codepoint <= 0x7F else ""
        return match.group("escaped") or ""

    return _CSS_ESCAPE.sub(replace, value)


def _css_has_active_reference(value: str) -> bool:
    folded = _decode_css_for_detection(value).casefold()
    for construct in READER_SAFETY_REFLOWABLE_PROFILE.css_sanitized_constructs:
        if construct == "REMOTE_IMPORT":
            if any(
                _is_remote_or_blocked_reference(
                    match.group("quoted") or match.group("bare") or "",
                    user_navigation=False,
                )
                for match in _CSS_IMPORT.finditer(folded)
            ):
                return True
        elif construct == "REMOTE_URL":
            if any(
                _is_remote_or_blocked_reference(
                    match.group("quoted") or match.group("bare") or "",
                    user_navigation=False,
                )
                for match in _CSS_URL.finditer(folded)
            ):
                return True
        elif construct == "EXPRESSION":
            if re.search(r"expression\s*\(", folded):
                return True
        elif construct == "BEHAVIOR":
            if re.search(r"(?:^|[;{])\s*behavior\s*:", folded):
                return True
        elif construct == "MOZ_BINDING":
            if re.search(r"(?:^|[;{])\s*-moz-binding\s*:", folded):
                return True
        else:
            raise RuntimeError(
                ReaderSafetyErrorCode.PLATFORM_POLICY_ALGORITHM_UNSUPPORTED.value
                + ":"
                + construct
            )
    return False


def _sanitize_css_text(value: str) -> str:
    sanitized = value
    for construct in READER_SAFETY_REFLOWABLE_PROFILE.css_sanitized_constructs:
        if construct == "REMOTE_IMPORT":
            sanitized = _CSS_IMPORT.sub(
                lambda match: (
                    ""
                    if _is_remote_or_blocked_reference(
                        match.group("quoted") or match.group("bare") or "",
                        user_navigation=False,
                    )
                    else match.group(0)
                ),
                sanitized,
            )
        elif construct == "REMOTE_URL":
            sanitized = _CSS_URL.sub(
                lambda match: (
                    'url("")'
                    if _is_remote_or_blocked_reference(
                        match.group("quoted") or match.group("bare") or "",
                        user_navigation=False,
                    )
                    else match.group(0)
                ),
                sanitized,
            )
        elif construct == "EXPRESSION":
            sanitized = _CSS_EXPRESSION_DECLARATION.sub(
                lambda match: match.group("prefix"), sanitized
            )
        elif construct == "BEHAVIOR":
            sanitized = _CSS_BEHAVIOR_DECLARATION.sub(
                lambda match: match.group("prefix"), sanitized
            )
        elif construct == "MOZ_BINDING":
            sanitized = _CSS_MOZ_BINDING_DECLARATION.sub(
                lambda match: match.group("prefix"), sanitized
            )
        else:
            raise RuntimeError(
                ReaderSafetyErrorCode.PLATFORM_POLICY_ALGORITHM_UNSUPPORTED.value
                + ":"
                + construct
            )
    if _css_has_active_reference(sanitized):
        return ""
    previous = None
    while sanitized != previous:
        previous = sanitized
        sanitized = _EMPTY_CSS_RULE.sub("", sanitized)
    return sanitized


def _sanitize_uri_attribute_value(
    value: str,
    policy: ReaderSafetyUriAttributePolicy,
) -> str | None:
    if policy.purpose is ReaderSafetyUriPurpose.ALWAYS_REMOVE:
        return None
    if policy.syntax is ReaderSafetyUriSyntax.CSS:
        return _sanitize_css_text(value) or None
    if policy.syntax is ReaderSafetyUriSyntax.SRCSET:
        user_navigation = policy.purpose is ReaderSafetyUriPurpose.USER_NAVIGATION
        components = []
        for component in value.split(","):
            candidate = component.strip()
            if not candidate:
                continue
            reference = candidate.split(maxsplit=1)[0]
            if not _is_remote_or_blocked_reference(
                reference, user_navigation=user_navigation
            ):
                components.append(candidate)
        return ", ".join(components) or None
    elif policy.syntax is ReaderSafetyUriSyntax.SPACE_SEPARATED:
        user_navigation = policy.purpose is ReaderSafetyUriPurpose.USER_NAVIGATION
        space_separated_components = tuple(
            candidate
            for candidate in value.split()
            if not _is_remote_or_blocked_reference(
                candidate, user_navigation=user_navigation
            )
        )
        return " ".join(space_separated_components) or None
    user_navigation = policy.purpose is ReaderSafetyUriPurpose.USER_NAVIGATION
    return (
        None
        if _is_remote_or_blocked_reference(
            value,
            user_navigation=user_navigation,
        )
        else value
    )


def _sanitize_markup_tree(root: ElementTree.Element) -> None:
    sanitized_elements = {
        value.casefold()
        for value in READER_SAFETY_REFLOWABLE_PROFILE.sanitized_elements
    }
    svg_elements = {
        value.casefold()
        for value in READER_SAFETY_REFLOWABLE_PROFILE.svg_sanitized_elements
    }
    sanitized_attributes = {
        value.casefold()
        for value in READER_SAFETY_REFLOWABLE_PROFILE.sanitized_attributes
    }
    attribute_prefixes = tuple(
        value.casefold()
        for value in READER_SAFETY_REFLOWABLE_PROFILE.sanitized_attribute_prefixes
    )
    blocked_http_equiv = {
        value.casefold()
        for value in READER_SAFETY_REFLOWABLE_PROFILE.sanitized_meta_http_equiv_values
    }

    def sanitize(element: ElementTree.Element, *, inside_svg: bool) -> None:
        local_name = _local_name(element.tag)
        current_svg = inside_svg or local_name == "svg"
        for child in list(element):
            child_name = _local_name(child.tag)
            http_equiv = next(
                (
                    value.strip().casefold()
                    for key, value in child.attrib.items()
                    if _attribute_local_name(key) == "http-equiv"
                ),
                None,
            )
            if (
                child_name in sanitized_elements
                or (current_svg and child_name in svg_elements)
                or (child_name == "meta" and http_equiv in blocked_http_equiv)
            ):
                element.remove(child)
                continue
            sanitize(child, inside_svg=current_svg)

        for key, value in list(element.attrib.items()):
            attribute = _attribute_local_name(key)
            if attribute in sanitized_attributes or attribute.startswith(
                attribute_prefixes
            ):
                del element.attrib[key]
                continue
            uri_policy = _uri_attribute_policy(
                element=local_name,
                attribute=_attribute_policy_name(key),
            )
            if uri_policy is not None:
                replacement = _sanitize_uri_attribute_value(value, uri_policy)
                if replacement is None:
                    del element.attrib[key]
                elif replacement != value:
                    element.attrib[key] = replacement

        if (
            local_name in READER_SAFETY_REFLOWABLE_PROFILE.css_text_elements
            and element.text
        ):
            element.text = _sanitize_css_text(element.text)

    sanitize(root, inside_svg=False)


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
        "schemaVersion": 3,
        "normalization": normalization,
        "policyId": READER_SAFETY_POLICY_ID,
        "policyVersion": READER_SAFETY_POLICY_VERSION,
        "policyDigest": READER_SAFETY_POLICY_DIGEST,
        "readingOrder": reading_order,
    }


def locator_dom_projection_hash(projection: dict[str, object]) -> str:
    """Return the language-neutral SHA-256 identity for a policy-bound projection."""

    canonical = json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


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
    """Sanitize author markup in memory and install the trusted platform head."""

    _markup, root = validate_xhtml(content)
    head = next(child for child in root if _local_name(child.tag) == "head")
    namespace = head.tag.rsplit("}", 1)[0] + "}" if "}" in head.tag else ""
    meta = ElementTree.Element(
        f"{namespace}meta",
        {
            "http-equiv": "Content-Security-Policy",
            "content": profile.content_security_policy,
            "data-shuku-security-profile": profile.identifier,
        },
    )
    style = ElementTree.Element(
        f"{namespace}style",
        {"data-shuku-security-profile": profile.identifier},
    )
    style.text = _SECURITY_STYLE
    head.insert(0, style)
    head.insert(0, meta)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


__all__ = [
    "MAXIMUM_MARKUP_BYTES",
    "WEB_SECURITY_PROFILE",
    "PublicationSecurityProfile",
    "decorate_markup_head",
    "locator_dom_projection",
    "locator_dom_projection_hash",
    "validate_xhtml",
]
