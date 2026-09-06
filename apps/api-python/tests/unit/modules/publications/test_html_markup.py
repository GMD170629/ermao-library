from typing import Literal
from unittest.mock import patch
from xml.etree import ElementTree

import pytest

from app.contracts.reader_safety_policy_generated import ReaderSafetyRuleId
from app.modules.publications.domain.model import (
    PublicationMarkupError,
    PublicationParserError,
    PublicationParserLimitError,
)
from app.modules.publications.infrastructure.locator_dom import (
    MAXIMUM_MARKUP_BYTES,
    sanitize_markup_resource,
)
from app.modules.publications.infrastructure.xml_policy import XmlPolicyPreparationError

_OWNER = "app.modules.publications.infrastructure.locator_dom"


def test_html_comments_preserve_adjacent_readable_text() -> None:
    protected = sanitize_markup_resource(
        b"<p>Before<!-- comment --> after <b>bold</b><!-- next --> tail</p>",
        syntax="html",
    )
    assert b"<p>Before after <b>bold</b> tail</p>" in protected


@pytest.mark.parametrize("scripting", [False, True])
def test_html_noscript_literal_markup_stays_inert_after_reparse(
    scripting: bool,
) -> None:
    import html5lib

    protected = sanitize_markup_resource(
        b"<body><noscript>&lt;/noscript&gt;&lt;img src=x onerror=bad()&gt;"
        b"&lt;script&gt;bad()&lt;/script&gt;</noscript>"
        b"<p>Readable &amp; safe</p></body>",
        syntax="html",
    )
    root = html5lib.parse(protected.decode("utf-8"), scripting=scripting)
    assert isinstance(root, ElementTree.Element)
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        assert element.tag.rsplit("}", 1)[-1].lower() not in {"img", "script"}
        assert all(
            not key.rsplit("}", 1)[-1].lower().startswith("on")
            for key in element.attrib
        )
    paragraph = root.find(".//{http://www.w3.org/1999/xhtml}p")
    assert paragraph is not None
    assert "".join(paragraph.itertext()) == "Readable & safe"


@pytest.mark.parametrize("syntax", ["xml", "html"])
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "<p><script>bad()</script>AFTER<script>bad()</script>FINAL</p>",
            "AFTERFINAL",
        ),
        (
            (
                "<p>Before<b>bold</b> tail<script>bad()</script>AFTER"
                "<!-- comment --> comment-tail<script>bad()</script>FINAL</p>"
            ),
            "Beforebold tailAFTER comment-tailFINAL",
        ),
        (
            "<div>Before<form><p>blocked-content</p></form>AFTER</div>",
            "BeforeAFTER",
        ),
        (
            (
                '<svg xmlns="http://www.w3.org/2000/svg"><text>Before</text>'
                "<foreignObject><p>blocked-content</p></foreignObject>AFTER</svg>"
            ),
            "BeforeAFTER",
        ),
    ],
)
def test_removed_active_nodes_preserve_only_following_readable_text(
    syntax: Literal["xml", "html"], body: str, expected: str
) -> None:
    import html5lib

    source = f"<html><head></head><body>{body}</body></html>".encode()
    protected = sanitize_markup_resource(source, syntax=syntax)
    if syntax == "html":
        root = html5lib.parse(protected.decode("utf-8"), scripting=True)
    else:
        root = ElementTree.fromstring(protected)
    assert isinstance(root, ElementTree.Element)
    assert "".join(root.itertext()) == expected
    assert all(
        element.tag.rsplit("}", 1)[-1].lower()
        not in {"script", "form", "foreignobject"}
        for element in root.iter()
    )


def test_html_entity_preparation_and_readable_unknown_vocabulary() -> None:
    content = (
        b'<!DOCTYPE html [<!ENTITY external SYSTEM "file:///not-read">'
        b'<!ENTITY internal "Readable">]><html><body><mbp:pagebreak>'
        b"<p>&internal; &external; &unknown; &copy;</body></html>"
    )
    protected = sanitize_markup_resource(content, syntax="html")
    assert b"Readable &amp;external; &amp;unknown;" in protected
    assert "©" in protected.decode()
    assert b"mbp:pagebreak" in protected
    assert b"not-read" not in protected
    assert b"<!DOCTYPE" not in protected


@pytest.mark.parametrize(
    "content",
    [
        (
            b'<svg><foreignObject><p onclick="bad()">Readable</p></foreignObject>'
            b'<a xlink:href="javascript:bad()"><text>link</text></a></svg>'
        ),
        (
            b"<math><mtext><table><mglyph><style><!--</style>"
            b'<img title="--><img src=x onerror=bad()>">'
        ),
        b'<p title="&quot;&gt;&lt;img src=x onerror=bad()&gt;">Readable</p>',
        b"<svg><style>&lt;/style&gt;&lt;img src=x onerror=bad()&gt;</style></svg>",
    ],
)
def test_html_serialization_does_not_reintroduce_active_dom(content: bytes) -> None:
    import html5lib

    protected = sanitize_markup_resource(content, syntax="html")
    root = html5lib.parse(protected)
    assert isinstance(root, ElementTree.Element)
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        assert element.tag.rsplit("}", 1)[-1].lower() != "script"
        for key, value in element.attrib.items():
            assert not key.rsplit("}", 1)[-1].lower().startswith("on")
            if key.rsplit("}", 1)[-1] in {"href", "src"}:
                assert not value.lower().startswith("javascript:")


def test_xml_does_not_fall_back_to_html() -> None:
    with (
        patch(f"{_OWNER}.html5lib.parse") as html_parser,
        pytest.raises(PublicationMarkupError),
    ):
        sanitize_markup_resource(b"<svg><unbound:child/></svg>")
    html_parser.assert_not_called()


@pytest.mark.parametrize("content", [b"", b"\xff"])
def test_html_rejects_empty_or_undecodable_input(content: bytes) -> None:
    with pytest.raises(PublicationMarkupError):
        sanitize_markup_resource(content, syntax="html")


def test_html_budget_fails_before_parser() -> None:
    with (
        patch(f"{_OWNER}.prepare_html_markup") as range_detector,
        patch(f"{_OWNER}.html5lib.parse") as html_parser,
        pytest.raises(PublicationParserLimitError) as failure,
    ):
        sanitize_markup_resource(b"x" * (MAXIMUM_MARKUP_BYTES + 1), syntax="html")
    range_detector.assert_not_called()
    html_parser.assert_not_called()
    assert failure.value.rule_id == ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES.value


def test_preparation_failure_never_reaches_html_parser() -> None:
    with (
        patch(
            f"{_OWNER}.prepare_xml", side_effect=XmlPolicyPreparationError("missing")
        ),
        patch(f"{_OWNER}.html5lib.parse") as html_parser,
        pytest.raises(PublicationParserError) as failure,
    ):
        sanitize_markup_resource(b"<p>Readable</p>", syntax="html")
    html_parser.assert_not_called()
    assert failure.value.code == "ENGINE_POLICY_ALGORITHM_UNSUPPORTED"


@pytest.mark.parametrize("operation", ["parse", "serializer.HTMLSerializer.render"])
def test_html_engine_contract_failure_is_not_content_corruption(operation: str) -> None:
    with (
        patch(f"{_OWNER}.html5lib.{operation}", return_value=None),
        pytest.raises(PublicationParserError) as failure,
    ):
        sanitize_markup_resource(b"<p>Readable</p>", syntax="html")
    assert failure.value.code == "ENGINE_POLICY_ALGORITHM_UNSUPPORTED"


def test_html_foreign_attribute_namespaces_and_unprefixed_target_are_preserved() -> (
    None
):
    import html5lib

    protected = sanitize_markup_resource(
        b'<svg><a xlink:href="#one" href="#two" xml:lang="en">safe</a></svg>',
        syntax="html",
    )
    root = html5lib.parse(protected.decode("utf-8"))
    link = root.find(".//{http://www.w3.org/2000/svg}a")
    assert link is not None
    assert link.attrib == {
        "{http://www.w3.org/1999/xlink}href": "#one",
        "href": "#two",
        "{http://www.w3.org/XML/1998/namespace}lang": "en",
    }


def test_html_style_keeps_css_raw_text_while_svg_style_keeps_literal_text() -> None:
    import html5lib

    protected = sanitize_markup_resource(
        b"<style>p > span { color: red }</style><svg><style>&lt;/style&gt;"
        b"&lt;img src=x onerror=bad()&gt;</style></svg>",
        syntax="html",
    )
    root = html5lib.parse(protected.decode("utf-8"))
    html_style = root.find(".//{http://www.w3.org/1999/xhtml}style")
    svg_style = root.find(".//{http://www.w3.org/2000/svg}style")
    assert html_style is not None and html_style.text == "p > span { color: red }"
    assert (
        svg_style is not None and svg_style.text == "</style><img src=x onerror=bad()>"
    )
    assert list(svg_style) == []


@pytest.mark.parametrize(
    ("source", "tag", "expected"),
    [
        (
            "<xmp>&copy; &unknown; &amp; &lt;b&gt;</xmp>",
            "xmp",
            "&copy; &unknown; &amp; &lt;b&gt;",
        ),
        (
            '<style>p::after{content:"&copy;"}</style>',
            "style",
            'p::after{content:"&copy;"}',
        ),
        ("<noembed>&copy; &unknown;</noembed>", "noembed", "&copy; &unknown;"),
        ("<noframes>&amp; body</noframes>", "noframes", "&amp; body"),
        ("<noscript>&copy; &unknown;</noscript>", "noscript", "&copy; &unknown;"),
        ("<svg><title><style>&copy;</style></title></svg>", "style", "&copy;"),
        (
            '<math><annotation-xml encoding="text/html"><style>&copy;</style></annotation-xml></math>',
            "style",
            "&copy;",
        ),
        ("<xmp>one</xmX>&copy;<b>two</b></XmP>", "xmp", "one</xmX>&copy;<b>two</b>"),
        ('<xmp>&copy;</xmp title="&copy;', "xmp", "&copy;"),
        ("<xmp>中文\r\n尾\r🙂 &copy;", "xmp", "中文\n尾\n🙂 &copy;"),
        ("<xmp>literal\x01 &copy;</xmp>", "xmp", "literal\x01 &copy;"),
    ],
)
def test_html_literal_text_preserves_sdk_readable_semantics(
    source: str, tag: str, expected: str
) -> None:
    import html5lib

    protected = sanitize_markup_resource(source.encode(), syntax="html")
    root = html5lib.parse(protected.decode(), scripting=True)
    element = root.find(f".//{{{html5lib.constants.namespaces['html']}}}{tag}")
    assert element is not None
    assert element.text == expected
    assert list(element) == []


def test_real_doctype_internal_subset_cannot_change_html_literal_state() -> None:
    import html5lib

    source = (
        b'<!DOCTYPE html [\r\n<!ENTITY e "x><xmp>">\r'
        b'<!ENTITY external SYSTEM "file:///not-read">\n]>'
        b"<xmp>&e;</xmp><p>&e; &external;</p>"
    )
    protected = sanitize_markup_resource(source, syntax="html")
    root = html5lib.parse(protected.decode(), scripting=True)
    assert root.find(".//{http://www.w3.org/1999/xhtml}xmp").text == "&e;"
    assert root.find(".//{http://www.w3.org/1999/xhtml}p").text == "x><xmp> &external;"
    assert b"DOCTYPE" not in protected and b"not-read" not in protected


def test_literal_doctype_is_readable_and_never_defines_entities() -> None:
    import html5lib

    literal = '<!DOCTYPE html [<!ENTITY e "altered">]> &e;'
    protected = sanitize_markup_resource(
        f"<xmp>{literal}</xmp><p>&e;</p>".encode(), syntax="html"
    )
    root = html5lib.parse(protected.decode(), scripting=True)
    assert root.find(".//{http://www.w3.org/1999/xhtml}xmp").text == literal
    assert root.find(".//{http://www.w3.org/1999/xhtml}p").text == "&e;"


@pytest.mark.parametrize("scripting", [False, True])
@pytest.mark.parametrize(
    "prefix",
    [
        "<body>",
        "<div><b>before",
        "<table>",
        "<table><tr>",
        "<table><tbody><tr><td>cell</td></tr>",
        "<b><table>before",
        "<div><table><caption>caption</caption>",
        "<table><tbody><tr><td>in-cell",
        "<table><colgroup>",
        "<table><tr><td><table><tr><td>nested</td></tr>",
        "<svg><title><table><tr><td>integration</td></tr>",
        '<math><annotation-xml encoding="text/html"><table><tr><td>integration</td></tr>',
    ],
)
def test_plaintext_eof_and_earlier_table_content_survive_reparse(
    prefix: str, scripting: bool
) -> None:
    import html5lib

    source = (
        prefix
        + '<plaintext id="keep"> &copy;\r\n</plaintext><img src=x onerror=bad()> &unknown;'
    )
    expected = html5lib.parse(source, scripting=scripting)
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    actual = html5lib.parse(protected.decode(), scripting=scripting)
    assert ElementTree.tostring(actual) == ElementTree.tostring(expected)
    assert actual.find(".//{http://www.w3.org/1999/xhtml}img") is None
    assert protected.decode().endswith(
        "</plaintext><img src=x onerror=bad()> &unknown;"
    )


def test_html_range_failure_does_not_retry_or_reach_the_final_parser() -> None:
    with (
        patch(
            f"{_OWNER}.prepare_html_markup",
            side_effect=XmlPolicyPreparationError("SDK unavailable"),
        ),
        patch(f"{_OWNER}._parse_html_root") as final_parser,
        pytest.raises(PublicationParserError) as failure,
    ):
        sanitize_markup_resource(b"<p>Readable</p>", syntax="html")
    final_parser.assert_not_called()
    assert failure.value.code == "ENGINE_POLICY_ALGORITHM_UNSUPPORTED"


@pytest.mark.parametrize(
    ("declarations", "attribute", "expected_attribute"),
    [
        ('<!ENTITY mime "text/html">', '"&mime;"', '"text/html"'),
        ('<!ENTITY mime "text/html">', "'&mime;'", '"text/html"'),
        ('<!ENTITY mime "text/html">', "&mime;", '"text/html"'),
        ('<!ENTITY mime "text/html ">', "&mime;", '"text/html "'),
        ('<!ENTITY mime "text/html">', '"&amp;mime;"', '"&amp;mime;"'),
        ('<!ENTITY mime "text/html">', '"&#38;mime;"', '"&amp;mime;"'),
        ('<!ENTITY mime "text/html">', '"&amp;amp;mime;"', '"&amp;amp;mime;"'),
        (
            '<!ENTITY mime "&later;"><!ENTITY later "text/html">',
            '"&mime;"',
            '"text/html"',
        ),
        ("", '"text&sol;html"', '"text&amp;sol;html"'),
    ],
)
def test_html_attribute_owner_precedes_mathml_context(
    declarations: str, attribute: str, expected_attribute: str
) -> None:
    import html5lib

    def body(value: str) -> str:
        return (
            f"<math><annotation-xml encoding={value}>"
            '<style>p::after{content:"&copy;"}</style></annotation-xml></math>'
        )

    source = f"<!DOCTYPE html [{declarations}]>" + body(attribute)
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    actual = html5lib.parse(protected.decode(), scripting=True)
    expected = html5lib.parse(body(expected_attribute), scripting=True)
    assert ElementTree.tostring(actual) == ElementTree.tostring(expected)


def test_html_late_declarations_only_affect_later_original_references() -> None:
    import html5lib

    def body(value: str) -> str:
        return (
            f'<math><annotation-xml encoding="{value}">'
            '<style>p::after{content:"&copy;"}</style></annotation-xml></math>'
        )

    source = (
        body("&mime;")
        + '<!DOCTYPE html [<!ENTITY mime "not-html">]>'
        + body("&mime;")
        + '<!DOCTYPE html [<!ENTITY mime "text/html">]>'
        + body("&mime;")
    )
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    actual = html5lib.parse(protected.decode(), scripting=True)
    expected = html5lib.parse(
        body("&amp;mime;") + body("not-html") + body("text/html"), scripting=True
    )
    assert ElementTree.tostring(actual) == ElementTree.tostring(expected)


def test_html_late_declaration_does_not_reclassify_its_earlier_context() -> None:
    import html5lib

    source = (
        '<math><annotation-xml encoding="&mime;"><style>'
        '<!DOCTYPE html [<!ENTITY mime "text/html">]>'
        "</style></annotation-xml></math><p>&mime;</p>"
    )
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    root = html5lib.parse(protected.decode(), scripting=True)
    annotation = root.find(".//{http://www.w3.org/1998/Math/MathML}annotation-xml")
    assert annotation.attrib["encoding"] == "&mime;"
    assert annotation.find("{http://www.w3.org/1998/Math/MathML}style").text is None
    assert root.find(".//{http://www.w3.org/1999/xhtml}p").text == "text/html"


def test_html_contextual_rawtext_never_prepares_fake_attributes_or_doctypes() -> None:
    import html5lib

    literal = '<a encoding="&mime;" title="&amp;mime;">&copy;</a>'
    literal += '<!DOCTYPE html [<!ENTITY hidden "wrong">]>'
    source = (
        '<!DOCTYPE html [<!ENTITY mime "text/html">]>'
        '<math><annotation-xml encoding="&mime;"><style>'
        + literal
        + "</style></annotation-xml></math><p>&hidden;</p>"
    )
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    root = html5lib.parse(protected.decode(), scripting=True)
    assert root.find(".//{http://www.w3.org/1999/xhtml}style").text == literal
    assert root.find(".//{http://www.w3.org/1999/xhtml}p").text == "&hidden;"


@pytest.mark.parametrize("suffix", [" ", "\r\n", ">", "/>"])
def test_html_unquoted_attribute_projection_preserves_sdk_value_boundaries(
    suffix: str,
) -> None:
    import html5lib

    source = (
        '<!DOCTYPE html [<!ENTITY e "two words &#34; &amp; &#39;">]>'
        "<p title=pre&e;post" + suffix
    )
    if suffix not in (">", "/>"):
        source += 'id="keep">'
    source += "Readable</p>"
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    paragraph = html5lib.parse(protected.decode()).find(
        ".//{http://www.w3.org/1999/xhtml}p"
    )
    # With no separating space, '/' is part of the SDK unquoted value.
    assert paragraph.attrib["title"] == "pretwo words \" & 'post" + (
        "/" if suffix == "/>" else ""
    )
    assert paragraph.text == "Readable"
    assert list(paragraph) == []


def test_html_reference_projection_keeps_sdk_duplicate_and_foreign_attributes() -> None:
    import html5lib

    source = (
        '<!DOCTYPE html [<!ENTITY mime "text/html"><!ENTITY href "#local">]>'
        '<math><annotation-xml encoding="&amp;mime;" encoding="&mime;">'
        "<style>&copy;</style></annotation-xml></math>"
        '<svg><a xlink:href="&href;" href=&href; xml:lang="en">link</a></svg>'
    )
    protected = sanitize_markup_resource(source.encode(), syntax="html")
    root = html5lib.parse(protected.decode(), scripting=True)
    annotation = root.find(".//{http://www.w3.org/1998/Math/MathML}annotation-xml")
    assert annotation.attrib == {"encoding": "&mime;"}
    assert annotation.find("{http://www.w3.org/1998/Math/MathML}style").text == "©"
    link = root.find(".//{http://www.w3.org/2000/svg}a")
    assert link.attrib == {
        "{http://www.w3.org/1999/xlink}href": "#local",
        "href": "#local",
        "{http://www.w3.org/XML/1998/namespace}lang": "en",
    }


def test_html_attribute_projection_and_literal_body_share_the_owner_budget() -> None:
    import html5lib

    from app.modules.publications.infrastructure.html_syntax import prepare_html_markup
    from app.modules.publications.infrastructure.xml_policy import prepare_xml

    source = (
        '<!DOCTYPE html [<!ENTITY e "' + "E" * 80 + '">]>'
        "<xmp>" + "A" * 60 + '</xmp><p a="&e;" b="&e;">&e;</p>'
        "<xmp>" + "B" * 60 + "</xmp>"
    )
    projection = prepare_xml(
        source.encode(),
        expansion_limit_bytes=len(source),
        prepare_markup=prepare_html_markup,
    )
    root = html5lib.parse(projection.parser_source, scripting=True)
    paragraph = root.find(".//{http://www.w3.org/1999/xhtml}p")
    assert paragraph.attrib == {"a": "E" * 80, "b": "&e;"}
    assert paragraph.text == "&e;"
    assert [
        node.text for node in root.findall(".//{http://www.w3.org/1999/xhtml}xmp")
    ] == ["A" * 60, "B" * 60]
    assert len(projection.parser_source.encode()) <= len(source)


@pytest.mark.parametrize("budget_delta", [0, -1])
def test_html_sdk_attribute_quotes_are_charged_to_existing_output_budget(
    budget_delta: int,
) -> None:
    from app.modules.publications.infrastructure.html_syntax import prepare_html_markup
    from app.modules.publications.infrastructure.xml_policy import (
        XmlPolicyExpansionLimitError,
        prepare_xml,
    )

    source = b"<p a=&amp;>Readable</p>"
    expected = '<p a="&amp;">Readable</p>'
    budget = len(expected.encode()) + budget_delta
    if budget_delta < 0:
        with pytest.raises(XmlPolicyExpansionLimitError):
            prepare_xml(
                source, expansion_limit_bytes=budget, prepare_markup=prepare_html_markup
            )
    else:
        projection = prepare_xml(
            source, expansion_limit_bytes=budget, prepare_markup=prepare_html_markup
        )
        assert projection.parser_source == expected


@pytest.mark.parametrize("chunk", [2, 7])
def test_html_sdk_attribute_coordinates_survive_crlf_and_small_input_chunks(
    chunk: int,
) -> None:
    from io import StringIO

    import html5lib

    from app.modules.publications.infrastructure.html_syntax import prepare_html_markup
    from app.modules.publications.infrastructure.xml_policy import prepare_xml

    class InputChunks(StringIO):
        def read(self, size: int = -1) -> str:
            return super().read(chunk if size < 0 else min(chunk, size))

    source = (
        '<!DOCTYPE html [\r\n<!ENTITY mime "text/html">]>'
        "\r\n<math><annotation-xml\r encoding=&mime;\r\n>"
        "<style>中文\r\n&copy;</style></annotation-xml></math>"
    )
    projection = prepare_xml(
        source.encode(),
        expansion_limit_bytes=MAXIMUM_MARKUP_BYTES,
        prepare_markup=lambda session: prepare_html_markup(
            session, source_stream=InputChunks(session.source)
        ),
    )
    root = html5lib.parse(projection.parser_source, scripting=True)
    assert root.find(
        ".//{http://www.w3.org/1998/Math/MathML}annotation-xml"
    ).attrib == {"encoding": "text/html"}
    assert root.find(".//{http://www.w3.org/1999/xhtml}style").text == "中文\n&copy;"
