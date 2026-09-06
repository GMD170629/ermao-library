"""Policy-bound, in-memory preparation of publication XML.

The publication readers must accept the XML vocabulary found in real books while
keeping XML parser dependencies out of the reader process.  This module is the
single boundary used by package/control XML, XHTML locator markup, FB2, and
markup returned by the MOBI adapter.  It only prepares a parser copy: callers
continue to retain and publish the original bytes.
"""

from __future__ import annotations

import codecs
import html
import re
from dataclasses import dataclass
from xml.etree import ElementTree

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_REFLOWABLE_PROFILE,
    READER_SAFETY_RULES,
    ReaderSafetyAction,
    ReaderSafetyAlgorithmId,
    ReaderSafetyRuleId,
)

_NAME = r"[A-Za-z_:][A-Za-z0-9_.:-]*"
_ENTITY_REFERENCE = re.compile(
    r"&(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*);|&#(?P<decimal>[0-9]+);|&#x(?P<hex>[0-9A-Fa-f]+);"
)
_ENTITY_DECLARATION = re.compile(
    rf"<!ENTITY\s+(?P<parameter>%\s+)?(?P<name>{_NAME})\s+(?P<value>.*?)>\s*$",
    re.IGNORECASE | re.DOTALL,
)
_DOCTYPE_OPEN = re.compile(r"<!DOCTYPE\b", re.IGNORECASE)

_XML_ENCODING = re.compile(
    rb"<\?xml\b[^?]*?\bencoding\s*=\s*['\"](?P<encoding>[A-Za-z][A-Za-z0-9._:-]*)['\"]",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class XmlPolicyProjection:
    """Original and parser-only forms of one XML document."""

    source: str
    parser_source: str
    doctype_count: int


@dataclass(frozen=True, slots=True)
class _EntityDeclaration:
    value: str | None
    parameter: bool
    external: bool


@dataclass(frozen=True, slots=True)
class _Doctype:
    start: int
    end: int
    text: str


@dataclass(slots=True)
class _EntityFrame:
    name: str
    value: str
    cursor: int = 0
    pieces: list[str] | None = None
    encoded_bytes: int = 0
    had_cycle: bool = False
    pending_reference: str | None = None
    failed: bool = False

    def __post_init__(self) -> None:
        self.pieces = []


class XmlPolicyPreparationError(ValueError):
    """The generated XML preparation contract is unavailable or inconsistent."""


class XmlPolicyDecodeError(XmlPolicyPreparationError):
    """The authored XML bytes cannot be decoded using their declared encoding."""


class XmlPolicyExpansionLimitError(ValueError):
    """A parser-only entity expansion exceeded the role's existing byte budget."""


def _require_xml_preparation_profile() -> None:
    """Fail closed if the generated XML preparation contract drifts."""

    rule = READER_SAFETY_RULES[ReaderSafetyRuleId.REFLOWABLE_PREPARE_XML]
    preparation = READER_SAFETY_REFLOWABLE_PROFILE.xml_preparation
    if (
        rule.algorithm is not ReaderSafetyAlgorithmId.PREPARE_XML
        or rule.action is not ReaderSafetyAction.SANITIZE
        or rule.error_code is not None
        or READER_SAFETY_REFLOWABLE_PROFILE.external_dtd_resolution is not False
    ):
        raise XmlPolicyPreparationError(
            "generated Reader safety XML preparation rule is unsupported"
        )
    expected = {
        "externalEntityAction": "LITERALIZE_REFERENCE",
        "recursiveEntityAction": "LITERALIZE_REFERENCE",
        "unknownEntityAction": "LITERALIZE_REFERENCE",
        "parameterEntityAction": "LITERALIZE_REFERENCE",
        "internalTextEntityAction": "BOUNDED_EXPANSION",
        "declarationAction": "REMOVE_PARSER_DEPENDENCY",
        "expansionLimitAction": "LITERALIZE_REFERENCE",
    }
    for field, expected_value in expected.items():
        actual_value = preparation.get(field)
        if actual_value is None:
            raise XmlPolicyPreparationError(
                f"generated Reader safety XML preparation field is missing: {field}"
            )
        if actual_value != expected_value:
            raise XmlPolicyPreparationError(
                f"generated XML preparation policy {field} is {actual_value!r}, "
                f"expected {expected_value!r}"
            )


def _decode_source(content: bytes) -> str:
    if content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return content.decode("utf-32", errors="strict")
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16", errors="strict")
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig", errors="strict")
    encoding_match = _XML_ENCODING.search(content[:1024])
    if encoding_match is None:
        return content.decode("utf-8", errors="strict")
    encoding = encoding_match.group("encoding").decode("ascii")
    try:
        codecs.lookup(encoding)
        return content.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as error:
        raise XmlPolicyDecodeError(
            f"XML source encoding cannot be decoded: {encoding}"
        ) from error


def _skip_ignored_construct(source: str, index: int) -> int | None:
    """Return the end of a comment, CDATA, or processing instruction."""

    if source.startswith("<!--", index):
        end = source.find("-->", index + 4)
        return None if end < 0 else end + 3
    if source.startswith("<![CDATA[", index):
        end = source.find("]]>", index + 9)
        return None if end < 0 else end + 3
    if source.startswith("<?", index):
        end = source.find("?>", index + 2)
        return None if end < 0 else end + 2
    return index


def _scan_doctypes(source: str) -> tuple[_Doctype, ...]:
    """Find well-formed DOCTYPE declarations outside ignored XML constructs."""

    found: list[_Doctype] = []
    index = 0
    while index < len(source):
        if source.startswith("<", index):
            skipped = _skip_ignored_construct(source, index)
            if skipped is None:
                break
            if skipped != index:
                index = skipped
                continue
            match = _DOCTYPE_OPEN.match(source, index)
            if match is not None:
                cursor = match.end()
                quote: str | None = None
                subset_depth = 0
                doctype_end: int | None = None
                while cursor < len(source):
                    character = source[cursor]
                    if quote is None and source.startswith(
                        ("<!--", "<![CDATA[", "<?"), cursor
                    ):
                        skipped = _skip_ignored_construct(source, cursor)
                        if skipped is None:
                            cursor = len(source)
                            break
                        cursor = skipped
                        continue
                    if quote is not None:
                        if character == quote:
                            quote = None
                    elif character in {"'", '"'}:
                        quote = character
                    elif character == "[":
                        subset_depth += 1
                    elif character == "]" and subset_depth:
                        subset_depth -= 1
                    elif character == ">" and subset_depth == 0:
                        doctype_end = cursor + 1
                        break
                    cursor += 1
                if doctype_end is None:
                    # Leave an incomplete declaration for ElementTree to reject
                    # as malformed XML rather than guessing at its boundary.
                    break
                found.append(_Doctype(index, doctype_end, source[index:doctype_end]))
                index = doctype_end
                continue
        index += 1
    return tuple(found)


def _internal_subset(doctype: _Doctype) -> str:
    opening: int | None = None
    subset_depth = 0
    quote: str | None = None
    index = 0
    while index < len(doctype.text):
        character = doctype.text[index]
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "<":
            skipped = _skip_ignored_construct(doctype.text, index)
            if skipped is None:
                return ""
            if skipped != index:
                index = skipped
                continue
        if character == "[":
            if opening is None:
                opening = index
            subset_depth += 1
        elif character == "]" and subset_depth:
            subset_depth -= 1
            if subset_depth == 0 and opening is not None:
                return doctype.text[opening + 1 : index]
        index += 1
    return ""


def _declaration_end(source: str, start: int) -> int | None:
    quote: str | None = None
    index = start + 2
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == ">":
            return index + 1
        index += 1
    return None


def _is_entity_declaration_start(source: str, index: int) -> bool:
    prefix = "<!ENTITY"
    if source[index : index + len(prefix)].upper() != prefix:
        return False
    following = source[index + len(prefix) : index + len(prefix) + 1]
    return not following or not re.match(r"[A-Za-z0-9_.:-]", following)


def _scan_entity_declarations(subset: str) -> dict[str, _EntityDeclaration]:
    declarations: dict[str, _EntityDeclaration] = {}
    index = 0
    while index < len(subset):
        if subset.startswith("<!--", index):
            skipped = _skip_ignored_construct(subset, index)
            if skipped is None:
                break
            index = skipped
            continue
        if subset.startswith("<?", index):
            skipped = _skip_ignored_construct(subset, index)
            if skipped is None:
                break
            index = skipped
            continue
        if subset.startswith("<![CDATA[", index):
            skipped = _skip_ignored_construct(subset, index)
            if skipped is None:
                break
            index = skipped
            continue
        if subset[index] != "<" or not _is_entity_declaration_start(subset, index):
            if subset[index] != "<" or subset[index : index + 2] != "<!":
                index += 1
                continue
            skipped = _declaration_end(subset, index)
            if skipped is None:
                break
            index = skipped
            continue
        cursor = _declaration_end(subset, index)
        if cursor is None:
            break
        declaration = _ENTITY_DECLARATION.fullmatch(subset[index:cursor])
        if declaration is not None:
            raw_value = declaration.group("value").strip()
            parameter = declaration.group("parameter") is not None
            value: str | None = None
            external = True
            if (
                len(raw_value) >= 2
                and raw_value[0] in {"'", '"'}
                and raw_value[-1] == raw_value[0]
            ):
                value = raw_value[1:-1]
                external = False
            declarations[declaration.group("name")] = _EntityDeclaration(
                value=value,
                parameter=parameter,
                external=external,
            )
        index = cursor
    return declarations


def _escape_reference(reference: str) -> str:
    # ``html.escape`` with quote=True also protects replacements used inside
    # attribute values.  The parser therefore sees text, never replacement
    # markup supplied by an authored entity declaration.
    return html.escape(reference, quote=True)


def _escaped_reference_size(reference: str) -> int:
    replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#x27;",
    }
    return sum(
        len(replacements.get(character, character).encode("utf-8"))
        for character in reference
    )


def _named_entity_values() -> dict[str, str]:
    values = {
        str(name): chr(int(codepoint))
        for name, codepoint in READER_SAFETY_REFLOWABLE_PROFILE.named_entity_codepoints.items()
    }
    return values


def _replace_references(
    source: str,
    declarations: dict[str, _EntityDeclaration],
    *,
    expansion_limit_bytes: int,
) -> str:
    named_values = _named_entity_values()
    memo: dict[str, str] = {}
    memo_escaped_sizes: dict[str, int] = {}
    active_materialized_bytes = 0

    def numeric_value(match: re.Match[str]) -> str | None:
        try:
            codepoint = int(
                match.group("decimal") or match.group("hex") or "",
                16 if match.group("hex") is not None else 10,
            )
        except ValueError:
            return None
        if (
            codepoint in {0x9, 0xA, 0xD}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            return chr(codepoint)
        return None

    def append_bounded(
        frame: _EntityFrame,
        candidate: str,
        fallback: str | None = None,
    ) -> bool:
        nonlocal active_materialized_bytes
        assert frame.pieces is not None
        candidate_bytes = len(candidate.encode("utf-8"))
        if active_materialized_bytes + candidate_bytes <= expansion_limit_bytes:
            frame.pieces.append(candidate)
            frame.encoded_bytes += candidate_bytes
            active_materialized_bytes += candidate_bytes
            return True
        if fallback is None:
            frame.failed = True
            return False
        fallback_bytes = len(fallback.encode("utf-8"))
        if active_materialized_bytes + fallback_bytes > expansion_limit_bytes:
            frame.failed = True
            return False
        frame.pieces.append(fallback)
        frame.encoded_bytes += fallback_bytes
        active_materialized_bytes += fallback_bytes
        return True

    continue_marker = object()

    def resolve_entity(name: str) -> str:
        """Resolve authored entities with an explicit iterative stack."""

        nonlocal active_materialized_bytes

        if name in named_values:
            return named_values[name]
        declaration = declarations.get(name)
        if (
            declaration is None
            or declaration.parameter
            or declaration.external
            or declaration.value is None
        ):
            return f"&{name};"
        cached = memo.get(name)
        if cached is not None:
            return cached

        active_names = {name}
        stack: list[_EntityFrame] = [_EntityFrame(name=name, value=declaration.value)]
        while stack:
            frame = stack[-1]
            result: str | None | object = continue_marker
            if frame.failed:
                result = None
            else:
                assert frame.pieces is not None
                match = _ENTITY_REFERENCE.search(frame.value, frame.cursor)
                if match is None:
                    if append_bounded(frame, frame.value[frame.cursor :]):
                        result = "".join(frame.pieces)
                    else:
                        result = None
                else:
                    if not append_bounded(
                        frame,
                        frame.value[frame.cursor : match.start()],
                    ):
                        result = None
                    else:
                        frame.cursor = match.end()
                        raw_reference = match.group(0)
                        referenced_name = match.group("name")
                        if referenced_name is None:
                            numeric = numeric_value(match)
                            candidate = numeric or raw_reference
                            result = (
                                continue_marker
                                if append_bounded(frame, candidate, raw_reference)
                                else None
                            )
                        elif referenced_name in named_values:
                            result = (
                                continue_marker
                                if append_bounded(
                                    frame,
                                    named_values[referenced_name],
                                    raw_reference,
                                )
                                else None
                            )
                        else:
                            declaration = declarations.get(referenced_name)
                            if (
                                declaration is None
                                or declaration.parameter
                                or declaration.external
                                or declaration.value is None
                                or referenced_name in active_names
                            ):
                                if referenced_name in active_names:
                                    frame.had_cycle = True
                                result = (
                                    continue_marker
                                    if append_bounded(
                                        frame, raw_reference, raw_reference
                                    )
                                    else None
                                )
                            elif referenced_name in memo:
                                result = (
                                    continue_marker
                                    if append_bounded(
                                        frame,
                                        memo[referenced_name],
                                        raw_reference,
                                    )
                                    else None
                                )
                            else:
                                frame.pending_reference = raw_reference
                                active_names.add(referenced_name)
                                stack.append(
                                    _EntityFrame(
                                        name=referenced_name,
                                        value=declaration.value,
                                    )
                                )
                                result = continue_marker

            # A marker means the current frame consumed one token and
            # should continue scanning; a non-empty string finishes it.
            if result is continue_marker:
                continue
            finished = stack.pop()
            finished_result = result if isinstance(result, str) else None
            active_names.remove(finished.name)
            active_materialized_bytes -= finished.encoded_bytes
            if finished_result is not None and not finished.had_cycle:
                result_bytes = len(finished_result.encode("utf-8"))
                if active_materialized_bytes + result_bytes <= expansion_limit_bytes:
                    memo[finished.name] = finished_result
                    active_materialized_bytes += result_bytes
            if not stack:
                return finished_result if finished_result is not None else f"&{name};"
            parent = stack[-1]
            parent.had_cycle = parent.had_cycle or finished.had_cycle
            reference = parent.pending_reference
            parent.pending_reference = None
            if reference is None:
                parent.failed = True
            else:
                child_value = (
                    finished_result if finished_result is not None else reference
                )
                if not append_bounded(parent, child_value, reference):
                    parent.failed = True

        return f"&{name};"

    output: list[str] = []
    output_bytes = 0
    source_bytes_remaining = len(source.encode("utf-8"))

    def consume_source(original: str) -> None:
        nonlocal source_bytes_remaining
        source_bytes_remaining -= len(original.encode("utf-8"))

    def append_original(original: str) -> None:
        consume_source(original)
        append_output(original)

    def append_output(candidate: str, fallback: str | None = None) -> None:
        nonlocal output_bytes
        candidate_bytes = len(candidate.encode("utf-8"))
        if output_bytes + candidate_bytes <= expansion_limit_bytes:
            output.append(candidate)
            output_bytes += candidate_bytes
            return
        if fallback is None:
            raise XmlPolicyExpansionLimitError(
                "prepared XML exceeds the role's byte budget"
            )
        fallback_bytes = len(fallback.encode("utf-8"))
        if output_bytes + fallback_bytes > expansion_limit_bytes:
            raise XmlPolicyExpansionLimitError(
                "prepared XML exceeds the role's byte budget"
            )
        output.append(fallback)
        output_bytes += fallback_bytes

    def append_escaped_output(name: str, value: str, fallback: str) -> None:
        escaped_bytes = memo_escaped_sizes.get(name)
        if escaped_bytes is None:
            escaped_bytes = _escaped_reference_size(value)
            # Only memoized resolutions have a stable representation independent
            # of the current recursive path. Cache their length, not another copy.
            if memo.get(name) is value:
                memo_escaped_sizes[name] = escaped_bytes
        if (
            output_bytes + escaped_bytes + source_bytes_remaining
            <= expansion_limit_bytes
        ):
            append_output(_escape_reference(value))
            return
        append_output(fallback)

    def replace_segment(segment: str) -> None:
        end = 0
        for match in _ENTITY_REFERENCE.finditer(segment):
            append_original(segment[end : match.start()])
            consume_source(match.group(0))
            name = match.group("name")
            if name is None:
                append_output(match.group(0))
            else:
                expanded = resolve_entity(name)
                # Every authored value, including an expanded value, becomes
                # character data in the parser copy.
                append_escaped_output(
                    name,
                    expanded,
                    _escape_reference(match.group(0)),
                )
            end = match.end()
        append_original(segment[end:])

    previous_end = 0
    for ignored in re.finditer(
        r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>", source, re.DOTALL
    ):
        replace_segment(source[previous_end : ignored.start()])
        append_original(ignored.group(0))
        previous_end = ignored.end()
    replace_segment(source[previous_end:])
    return "".join(output)


def prepare_xml(content: bytes, *, expansion_limit_bytes: int) -> XmlPolicyProjection:
    """Prepare XML for the standard-library parser without external I/O.

    ``expansion_limit_bytes`` is the caller's existing role budget: control
    documents use ``xmlControlDocumentMaxBytes`` and reflowable resources use
    ``reflowableMarkupMaxBytes``.  The function never writes the prepared copy
    to disk and never mutates the original bytes.
    """

    _require_xml_preparation_profile()
    source = _decode_source(content)
    doctypes = _scan_doctypes(source)
    declarations: dict[str, _EntityDeclaration] = {}
    for doctype in doctypes:
        declarations.update(_scan_entity_declarations(_internal_subset(doctype)))

    if doctypes:
        parts: list[str] = []
        previous_end = 0
        for doctype in doctypes:
            parts.append(source[previous_end : doctype.start])
            previous_end = doctype.end
        parts.append(source[previous_end:])
        parser_source = "".join(parts)
    else:
        parser_source = source
    parser_source = _replace_references(
        parser_source,
        declarations,
        expansion_limit_bytes=expansion_limit_bytes,
    )
    return XmlPolicyProjection(
        source=source,
        parser_source=parser_source,
        doctype_count=len(doctypes),
    )


def parse_xml(
    content: bytes,
    *,
    expansion_limit_bytes: int,
) -> tuple[XmlPolicyProjection, ElementTree.Element]:
    """Prepare and parse one XML document using the policy projection."""

    projection = prepare_xml(content, expansion_limit_bytes=expansion_limit_bytes)
    return projection, ElementTree.fromstring(projection.parser_source)


__all__ = [
    "XmlPolicyDecodeError",
    "XmlPolicyExpansionLimitError",
    "XmlPolicyPreparationError",
    "XmlPolicyProjection",
    "parse_xml",
    "prepare_xml",
]
