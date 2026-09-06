"""Namespace adapter for the pinned html5lib HTML serializer.

html5lib 1.1 drops attribute namespaces and treats foreign ``style`` text as
HTML raw text. Adapt its existing token stream; policy and sanitization remain
with locator_dom, and HTML parsing never retries a failed security projection.
"""

from collections.abc import Iterable, Iterator
from html import escape
from itertools import chain

# html5lib 1.1 lacks PEP 561 metadata. Tokens are validated at this SDK boundary.
import html5lib  # type: ignore[import-untyped]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("HTML serializer token text is invalid")
    return value


def quoted_html_attribute(value: str) -> str:
    """Let the SDK quote one complete value, including authored whitespace.

    The fixed wrapper exposes only the SDK attribute-value serialization; it
    cannot alter tag names, self-closing syntax or foreign attribute namespaces.
    """
    serializer = html5lib.serializer.HTMLSerializer(
        quote_attr_values="always",
        minimize_boolean_attributes=False,
        omit_optional_tags=False,
        inject_meta_charset=False,
        escape_lt_in_attrs=True,
    )
    serialized = _text(
        serializer.render(
            [{"type": "StartTag", "name": "i", "data": {(None, "value"): value}}]
        )
    )
    prefix = "<i value="
    if not serialized.startswith(prefix) or not serialized.endswith(">"):
        raise TypeError("HTML SDK attribute serialization has an invalid wrapper")
    return serialized[len(prefix) : -1]


def _qualified_attributes(value: object) -> dict[tuple[None, str], str]:
    if not isinstance(value, dict):
        raise TypeError("HTML serializer token attributes are invalid")
    attributes: dict[tuple[None, str], str] = {}
    for key, raw_text in value.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise TypeError("HTML serializer attribute name is invalid")
        namespace, name = key
        name = _text(name)
        if namespace is not None:
            # These prefixes belong to HTML's foreign-attribute syntax, not a
            # Reader policy vocabulary. Preserve href alongside xlink:href.
            prefix = _text(html5lib.constants.prefixes[_text(namespace)])
            if not (prefix == "xmlns" and name == "xmlns"):
                name = f"{prefix}:{name}"
        attributes[(None, name)] = _text(raw_text)
    return attributes


def html_serialization_tokens(
    raw_tokens: Iterable[object],
) -> Iterator[dict[str, object]]:
    """Preserve foreign namespaces and text through html5lib's own serializer."""
    namespaces: list[object] = []
    in_raw_text = False
    for raw_token in raw_tokens:
        if not isinstance(raw_token, dict):
            raise TypeError("HTML serializer token is invalid")
        token: dict[str, object] = {
            _text(key): value for key, value in raw_token.items()
        }
        kind = _text(token.get("type"))
        if kind in {"StartTag", "EmptyTag"}:
            name = _text(token.get("name"))
            token["data"] = _qualified_attributes(token.get("data"))
            if kind == "StartTag":
                namespaces.append(token.get("namespace"))
            if name in html5lib.constants.rcdataElements:
                in_raw_text = True
        elif kind == "EndTag":
            if _text(token.get("name")) in html5lib.constants.rcdataElements:
                in_raw_text = False
            namespaces.pop()
        elif (
            kind in {"Characters", "SpaceCharacters"}
            and in_raw_text
            and namespaces
            and namespaces[-1] != html5lib.constants.namespaces["html"]
        ):
            # The SDK writes these tokens verbatim while in raw-text mode.
            # Foreign content needs entity escaping; normal HTML style/xmp
            # retain their original raw-text behavior and CSS semantics.
            token["data"] = escape(_text(token.get("data")), quote=False)
        yield token


def _html_tag(token: dict[str, object], kind: str, name: str) -> bool:
    return (
        token.get("type") == kind
        and token.get("name") == name
        and token.get("namespace") == html5lib.constants.namespaces["html"]
    )


def _plaintext_prefix(
    tokens: Iterator[dict[str, object]], literal: list[str]
) -> Iterator[dict[str, object]]:
    for token in tokens:
        if not _html_tag(token, "StartTag", "plaintext"):
            yield token
            continue
        opening = token
        for token in tokens:
            if token.get("type") in {"Characters", "SpaceCharacters"}:
                literal.append(_text(token.get("data")))
            elif _html_tag(token, "EndTag", "plaintext"):
                break
            else:
                raise TypeError("HTML SDK plaintext unexpectedly contains child markup")
        else:
            raise TypeError("HTML SDK plaintext tree has no end token")

        following = next(tokens, None)
        if following is not None and _html_tag(following, "StartTag", "table"):
            # SDK insertElementTable/getTableMisnestedNodePosition foster a
            # plaintext node immediately before the open table. Serialize that
            # table first, leaving it open when plaintext begins; the SDK's
            # own next parse reconstructs the same siblings and retains all
            # earlier table text. No HTML lexer or serializer loop is copied.
            yield following
            depth = 1
            for token in tokens:
                if token.get("type") == "StartTag":
                    depth += 1
                elif token.get("type") == "EndTag":
                    depth -= 1
                if depth == 0:
                    break
                yield token
            else:
                raise TypeError("HTML SDK foster table has no end token")
            following = next(tokens, None)

        # A SDK-parsed plaintext consumes EOF. Only ancestor end tokens can
        # remain after its subtree (or foster table); they must not become
        # visible literal closing tags. A different shape is an SDK contract
        # failure, never a reason to silently discard additional content.
        for token in chain(() if following is None else (following,), tokens):
            if token.get("type") != "EndTag":
                raise TypeError("HTML SDK has content after its terminal plaintext")
        yield opening
        return


class PublicationHTMLSerializer(html5lib.serializer.HTMLSerializer):
    """Delegate ordinary serialization; plaintext's terminal text stays raw."""

    def serialize(
        self,
        treewalker: Iterable[dict[str, object]],
        encoding: str | None = None,
    ) -> Iterator[str | bytes]:
        literal: list[str] = []
        yield from super().serialize(
            _plaintext_prefix(iter(treewalker), literal), encoding
        )
        for text in literal:
            yield self.encode(text)
