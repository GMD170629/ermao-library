"""Source-range adapter for the installed html5lib 1.1 parser.

The SDK owns tokenization, namespaces, insertion modes and scripting semantics.
Original attribute references reach the document owner before parser context is
chosen. The owner supplies complete DOCTYPE ends and accounts for SDK-projected
values and literal ranges; entity interpretation and budgets never live here.
"""

from __future__ import annotations

import re
from array import array
from collections.abc import Iterator
from typing import TextIO

# html5lib 1.1 has no PEP 561 metadata; the dynamic SDK stays at this boundary.
import html5lib  # type: ignore[import-untyped]
from html5lib import _tokenizer  # type: ignore[import-untyped]

from app.modules.publications.infrastructure.html_serialization import (
    quoted_html_attribute,
)
from app.modules.publications.infrastructure.xml_policy import (
    MarkupPreparationSession,
    MarkupSourceRange,
    XmlPolicyPreparationError,
)


def _decode_attribute_reference(source: str) -> str:
    # The owner escaped a single original reference. Decode that prepared text
    # once with the native SDK; never search an already-decoded attribute for
    # another authored reference (notably &amp;mime;).
    tokens = [
        token
        for token in _tokenizer.HTMLTokenizer(f'<i value="{source}">')
        if token["type"] == html5lib.constants.tokenTypes["StartTag"]
    ]
    if len(tokens) != 1 or tokens[0]["name"] != "i":
        raise XmlPolicyPreparationError(
            "HTML SDK attribute decode has an invalid wrapper"
        )
    attributes = tokens[0]["data"]
    if not isinstance(attributes, dict) or set(attributes) != {"value"}:
        raise XmlPolicyPreparationError(
            "HTML SDK attribute decode returned invalid attributes"
        )
    value: object = attributes["value"]
    if not isinstance(value, str):
        raise XmlPolicyPreparationError("HTML SDK attribute decode returned non-text")
    return value


class _MarkupTokenizer(_tokenizer.HTMLTokenizer):
    def __init__(
        self,
        source: str,
        parser: _MarkupParser,
        source_stream: TextIO | None,
    ) -> None:
        self.source = source
        self.range_parser = parser
        self.session = parser.session
        # SDK positions count normalized lines/columns. Compact offsets map
        # CRLF, lone CR and LF back to the owner's decoded original source.
        self.line_starts = array("Q", [0])
        self.line_starts.extend(
            match.end() for match in re.finditer(r"\r\n|\r|\n", source)
        )
        self.literal_end = 0
        self.literal_start: int | None = None
        self.less_than: int | None = None
        self.attribute_start: int | None = None
        self.attribute_projected = False
        self.iterations = 0
        super().__init__(
            source if source_stream is None else source_stream, parser=parser
        )

    def source_position(self) -> int:
        line, column = self.stream.position()
        if not 1 <= line <= len(self.line_starts):
            raise XmlPolicyPreparationError("HTML SDK line is outside the source")
        offset = self.line_starts[line - 1] + column
        if not 0 <= offset <= len(self.source):
            raise XmlPolicyPreparationError("HTML SDK position is outside the source")
        return int(offset)

    def begin_literal(self) -> None:
        if self.literal_start is None:
            node = self.range_parser.tree.openElements[-1]
            if node.namespace != html5lib.constants.namespaces["html"]:
                raise XmlPolicyPreparationError(
                    "HTML SDK literal state has a foreign namespace"
                )
            self.literal_start = self.source_position()
            self.less_than = None

    def finish_literal(self, end: int) -> None:
        start = self.literal_start
        if start is None or end < start or start < self.literal_end:
            raise XmlPolicyPreparationError(
                "HTML SDK literal boundaries are inconsistent"
            )
        self.session.literal(MarkupSourceRange(start, end))
        self.literal_end = end
        self.literal_start = None
        self.less_than = None

    def remember_less_than(self) -> None:
        self.less_than = self.source_position() - 1
        if self.source[self.less_than : self.less_than + 1] != "<":
            raise XmlPolicyPreparationError(
                "HTML SDK end-tag position does not match source"
            )

    def doctypeState(self) -> bool:
        position = self.source_position()
        start = position - len("<!DOCTYPE")
        end = self.session.doctype_end(start)
        if end is None:
            # Incomplete declarations keep the SDK's normal HTML behavior.
            return bool(super().doctypeState())
        normalized_length = end - position - self.source.count("\r\n", position, end)
        for _ in range(normalized_length):
            if self.stream.char() is None:
                raise XmlPolicyPreparationError(
                    "HTML SDK ended inside a complete declaration"
                )
        if self.source_position() != end:
            raise XmlPolicyPreparationError(
                "HTML SDK declaration boundary does not match source"
            )
        # The policy removes this parser dependency. Consume it atomically so
        # quoted markup/internal subsets never reach the HTML insertion modes.
        self.state = self.dataState
        return True

    def rawtextState(self) -> bool:
        self.begin_literal()
        return bool(super().rawtextState())

    def scriptDataState(self) -> bool:
        self.begin_literal()
        return bool(super().scriptDataState())

    def plaintextState(self) -> bool:
        self.begin_literal()
        return bool(super().plaintextState())

    def rawtextLessThanSignState(self) -> bool:
        self.remember_less_than()
        return bool(super().rawtextLessThanSignState())

    def scriptDataLessThanSignState(self) -> bool:
        self.remember_less_than()
        return bool(super().scriptDataLessThanSignState())

    def scriptDataEscapedLessThanSignState(self) -> bool:
        self.remember_less_than()
        return bool(super().scriptDataEscapedLessThanSignState())

    def beforeAttributeValueState(self) -> bool:
        start = self.source_position()
        result = bool(super().beforeAttributeValueState())
        if self.state in (
            self.attributeValueDoubleQuotedState,
            self.attributeValueSingleQuotedState,
        ):
            self.attribute_start = self.source_position() - 1
        elif self.state == self.attributeValueUnQuotedState:
            self.attribute_start = start
        return result

    def processEntityInAttribute(self, allowedChar: str) -> None:
        if self.currentToken["type"] != html5lib.constants.tokenTypes["StartTag"]:
            super().processEntityInAttribute(allowedChar)
            return
        start = self.source_position() - 1
        if self.attribute_start is None or self.source[start : start + 1] != "&":
            raise XmlPolicyPreparationError(
                "HTML SDK original attribute position is invalid"
            )
        prepared = self.session.attribute_reference(
            start, value_start=self.attribute_start
        )
        if prepared is None:
            super().processEntityInAttribute(allowedChar)
            return
        for _ in range(prepared.end - self.source_position()):
            if self.stream.char() is None:
                raise XmlPolicyPreparationError(
                    "HTML SDK ended inside an attribute reference"
                )
        if self.source_position() != prepared.end:
            raise XmlPolicyPreparationError(
                "HTML SDK reference position does not match source"
            )
        self.currentToken["data"][-1][1] += _decode_attribute_reference(
            prepared.parser_text
        )
        self.attribute_projected = True

    def finish_attribute(self, end: int) -> None:
        if self.attribute_projected:
            value: object = self.currentToken["data"][-1][1]
            if not isinstance(value, str):
                raise XmlPolicyPreparationError("HTML SDK attribute value is not text")
            self.session.project_attribute(end, quoted_html_attribute(value))
        self.attribute_start = None
        self.attribute_projected = False

    def attributeValueDoubleQuotedState(self) -> bool:
        result = bool(super().attributeValueDoubleQuotedState())
        if self.state == self.afterAttributeValueState:
            self.finish_attribute(self.source_position())
        return result

    def attributeValueSingleQuotedState(self) -> bool:
        result = bool(super().attributeValueSingleQuotedState())
        if self.state == self.afterAttributeValueState:
            self.finish_attribute(self.source_position())
        return result

    def attributeValueUnQuotedState(self) -> bool:
        end = self.source_position()
        result = bool(super().attributeValueUnQuotedState())
        if self.state == self.beforeAttributeNameState:
            self.finish_attribute(end)
        return result

    def emitCurrentToken(self) -> None:
        if self.currentToken["type"] == html5lib.constants.tokenTypes["StartTag"]:
            # A '>' can end an unquoted value inside the SDK state method.
            self.finish_attribute(self.source_position() - 1)
        if (
            self.literal_start is not None
            and self.currentToken["type"] == html5lib.constants.tokenTypes["EndTag"]
        ):
            if self.less_than is None:
                raise XmlPolicyPreparationError(
                    "HTML SDK literal end has no source position"
                )
            self.finish_literal(self.less_than)
        super().emitCurrentToken()

    def __iter__(self) -> Iterator[object]:
        self.iterations += 1
        if self.iterations != 1:
            raise XmlPolicyPreparationError("HTML SDK attempted a second token pass")
        yield from super().__iter__()
        self.session.incomplete_attribute()
        if self.literal_start is not None:
            # A recognized, incomplete end tag is dropped by SDK at EOF;
            # an incomplete nonmatching name remains literal character data.
            if self.currentToken["type"] == html5lib.constants.tokenTypes["EndTag"]:
                if self.less_than is None:
                    raise XmlPolicyPreparationError(
                        "HTML SDK incomplete end has no position"
                    )
                self.finish_literal(self.less_than)
            else:
                self.finish_literal(len(self.source))


class _MarkupParser(html5lib.HTMLParser):
    def __init__(
        self,
        session: MarkupPreparationSession,
        source_stream: TextIO | None,
    ) -> None:
        if html5lib.__version__ != "1.1":
            raise XmlPolicyPreparationError("HTML source adapter requires html5lib 1.1")
        self.source = session.source
        self.session = session
        self.source_stream = source_stream
        self.resets = 0
        super().__init__(tree=html5lib.getTreeBuilder("etree"))

    def reset(self) -> None:
        self.resets += 1
        if self.resets != 1 or self.innerHTMLMode:
            raise XmlPolicyPreparationError(
                "HTML source adapter requires one Unicode document parse"
            )
        super().reset()
        # Per-instance SDK extension: its default tokenizer has not been
        # iterated. _parse, mainLoop and the tokenizer loop remain SDK methods.
        self.tokenizer = _MarkupTokenizer(self.source, self, self.source_stream)


def prepare_html_markup(
    session: MarkupPreparationSession,
    *,
    source_stream: TextIO | None = None,
) -> None:
    """Apply SDK facts in causal source order, with scripting enabled."""
    parser = _MarkupParser(session, source_stream)
    try:
        parser.parse(session.source, scripting=True)
    except TypeError as error:
        raise XmlPolicyPreparationError(
            "HTML SDK attribute projection is inconsistent"
        ) from error
