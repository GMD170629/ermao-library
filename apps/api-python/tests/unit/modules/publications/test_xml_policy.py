from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from unittest.mock import patch

import pytest

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_REFLOWABLE_PROFILE,
    READER_SAFETY_RULES,
    ReaderSafetyAction,
    ReaderSafetyAlgorithmId,
    ReaderSafetyRuleId,
)
from app.modules.publications.infrastructure import xml_policy
from app.modules.publications.infrastructure.xml_policy import (
    MarkupPreparationSession,
    MarkupSourceRange,
    XmlPolicyExpansionLimitError,
    XmlPolicyPreparationError,
    parse_xml,
    prepare_xml,
)


def test_scanner_ignores_comments_cdata_and_processing_instructions() -> None:
    source = (
        b"<!-- <!DOCTYPE ignored> --><?pi <!DOCTYPE ignored?>"
        b"<root><![CDATA[<!DOCTYPE ignored>]]></root>"
    )

    projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert projection.doctype_count == 0
    assert "<!DOCTYPE ignored>" in "".join(root.itertext())


def test_doctype_boundary_ignores_nested_dtd_comments_and_processing_instructions() -> (
    None
):
    source = (
        b"<!DOCTYPE root [<!-- misleading ] > -->"
        b'<?pi misleading " ] > " ?><!ENTITY value "ok">]>'
        b"<root>&value;</root>"
    )

    _projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert "ok" == "".join(root.itertext())


def test_quoted_doctype_identifier_cannot_create_an_internal_subset() -> None:
    source = (
        b"<!DOCTYPE root SYSTEM \"urn:book[<!ENTITY masked 'bad'>]\">"
        b"<root>&masked;</root>"
    )

    _projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert "&masked;" == "".join(root.itertext())


def test_quoted_non_entity_declaration_cannot_smuggle_entity_declaration() -> None:
    source = (
        b"<!DOCTYPE root [<!ATTLIST root marker \"<!ENTITY masked 'bad'>\">"
        b'<!ENTITY declared "ok">]><root>&declared;&masked;</root>'
    )

    _projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert "ok&masked;" == "".join(root.itertext())


def test_generated_xml_preparation_algorithm_is_validated() -> None:
    rule_id = ReaderSafetyRuleId.REFLOWABLE_PREPARE_XML
    rules = dict(READER_SAFETY_RULES)
    rules[rule_id] = replace(
        rules[rule_id], algorithm=ReaderSafetyAlgorithmId.MAX_XML_BYTES
    )

    with (
        patch.object(xml_policy, "READER_SAFETY_RULES", MappingProxyType(rules)),
        pytest.raises(XmlPolicyPreparationError, match="preparation rule"),
    ):
        parse_xml(b"<root />", expansion_limit_bytes=1024)


def test_generated_xml_preparation_action_is_validated() -> None:
    rule_id = ReaderSafetyRuleId.REFLOWABLE_PREPARE_XML
    rules = dict(READER_SAFETY_RULES)
    rules[rule_id] = replace(
        rules[rule_id], action=ReaderSafetyAction.REJECT_PUBLICATION
    )

    with (
        patch.object(xml_policy, "READER_SAFETY_RULES", MappingProxyType(rules)),
        pytest.raises(XmlPolicyPreparationError, match="preparation rule"),
    ):
        parse_xml(b"<root />", expansion_limit_bytes=1024)


def test_generated_xml_preparation_requires_external_resolution_disabled() -> None:
    profile = replace(READER_SAFETY_REFLOWABLE_PROFILE, external_dtd_resolution=True)

    with (
        patch.object(xml_policy, "READER_SAFETY_REFLOWABLE_PROFILE", profile),
        pytest.raises(XmlPolicyPreparationError, match="preparation rule"),
    ):
        parse_xml(b"<root />", expansion_limit_bytes=1024)


def test_external_unknown_and_recursive_entities_render_as_literal_text() -> None:
    source = (
        b"<!DOCTYPE root ["
        b'<!ENTITY external SYSTEM "file:///etc/passwd">'
        b'<!ENTITY first "first &second;">'
        b'<!ENTITY second "second &first;">]>'
        b"<root>&external; &unknown; &first;</root>"
    )

    _projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert "&external; &unknown; first second &first;" == "".join(root.itertext())


def test_internal_numeric_entity_references_are_expanded_as_text() -> None:
    source = b'<!DOCTYPE root [<!ENTITY plain "A &#x42; &#67;">]><root>&plain;</root>'

    _projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert "A B C" == "".join(root.itertext())


def test_expansion_amplification_literalizes_the_reference_within_budget() -> None:
    source = (
        b'<!DOCTYPE root [<!ENTITY large "0123456789abcdef0123456789abcdef">]>'
        b"<root>&large;</root>"
    )

    _projection, root = parse_xml(source, expansion_limit_bytes=30)

    assert "&large;" == "".join(root.itertext())


def test_repeated_entity_references_are_bounded_as_one_prepared_document() -> None:
    source = (
        b'<!DOCTYPE root [<!ENTITY payload "0123456789abcdef0123456789abcdef">]>'
        b"<root>&payload;&payload;&payload;</root>"
    )

    _projection, root = parse_xml(source, expansion_limit_bytes=90)

    expected = (
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef&payload;"
    )
    assert expected == "".join(root.itertext())


def test_entity_expansion_reserves_space_for_remaining_readable_xml() -> None:
    source = (
        b'<!DOCTYPE root [<!ENTITY payload "0123456789abcdef0123456789abcdef">]>'
        b"<root>&payload;</root>"
    )

    projection, root = parse_xml(source, expansion_limit_bytes=40)

    assert "&payload;" == "".join(root.itertext())
    assert len(projection.parser_source.encode("utf-8")) <= 40


def test_deep_entity_chain_uses_bounded_iterative_resolution() -> None:
    declarations = "".join(
        f'<!ENTITY e{index} "&e{index + 1};">' for index in range(1200)
    )
    source = (
        f'<!DOCTYPE root [{declarations}<!ENTITY e1200 "ok">]><root>&e0;</root>'
    ).encode()

    _projection, root = parse_xml(source, expansion_limit_bytes=4096)

    assert "ok" == "".join(root.itertext())


def test_declared_legacy_encoding_is_preserved_for_fb2_style_xml() -> None:
    source = (
        '<?xml version="1.0" encoding="windows-1251"?><root>Привет</root>'
    ).encode("cp1251")

    _projection, root = parse_xml(source, expansion_limit_bytes=1024)

    assert "Привет" == "".join(root.itertext())


def test_syntax_ranges_preserve_literal_declarations_and_share_the_entity_owner() -> (
    None
):
    literal = '<!DOCTYPE html [<!ENTITY e "wrong">]> &e; &copy;'
    declaration = '<!DOCTYPE html [<!ENTITY e "Readable">]>'
    source = f"<xmp>{literal}</xmp>{declaration}<p>&e;</p><xmp>&e;</xmp>"

    def prepare(session: MarkupPreparationSession) -> None:
        assert session.source == source
        session.literal(MarkupSourceRange(len("<xmp>"), len("<xmp>") + len(literal)))
        start = source.index(declaration)
        end = session.doctype_end(start)
        assert end == start + len(declaration)
        session.literal(
            MarkupSourceRange(source.rindex("&e;"), source.rindex("&e;") + len("&e;"))
        )

    projection = prepare_xml(
        source.encode(), expansion_limit_bytes=1024, prepare_markup=prepare
    )
    assert projection.source == source
    assert projection.doctype_count == 1
    assert (
        projection.parser_source == f"<xmp>{literal}</xmp><p>Readable</p><xmp>&e;</xmp>"
    )


def test_syntax_literals_and_entity_expansion_use_one_document_budget() -> None:
    declaration = '<!DOCTYPE html [<!ENTITY e "' + "E" * 80 + '">]>'
    source = (
        declaration
        + "<xmp>"
        + "A" * 60
        + "</xmp><p>&e;&e;&e;</p><xmp>"
        + "B" * 60
        + "</xmp>"
    )

    def prepare(session: MarkupPreparationSession) -> None:
        assert session.doctype_end(0) == len(declaration)
        for text in ("A" * 60, "B" * 60):
            session.literal(
                MarkupSourceRange(source.index(text), source.index(text) + len(text))
            )

    projection = prepare_xml(
        source.encode(), expansion_limit_bytes=len(source), prepare_markup=prepare
    )
    assert projection.parser_source == (
        "<xmp>"
        + "A" * 60
        + "</xmp><p>"
        + "E" * 80
        + "&amp;e;&amp;e;</p><xmp>"
        + "B" * 60
        + "</xmp>"
    )
    assert len(projection.parser_source.encode()) <= len(source)


def test_syntax_literal_xml_comment_does_not_hide_following_ordinary_entities() -> None:
    source = "<xmp><!-- &copy;</xmp><p>&copy;</p><!-- end -->"

    def prepare(session: MarkupPreparationSession) -> None:
        session.literal(MarkupSourceRange(len("<xmp>"), source.index("</xmp>")))

    projection = prepare_xml(
        source.encode(), expansion_limit_bytes=1024, prepare_markup=prepare
    )
    assert projection.parser_source == "<xmp><!-- &copy;</xmp><p>©</p><!-- end -->"


@pytest.mark.parametrize("budget_delta", [0, -1])
def test_literal_bytes_obey_the_existing_exact_output_budget(budget_delta: int) -> None:
    content = b"<xmp>&unknown;</xmp>"

    def prepare(session: MarkupPreparationSession) -> None:
        session.literal(MarkupSourceRange(len("<xmp>"), session.source.index("</xmp>")))

    if budget_delta < 0:
        with pytest.raises(XmlPolicyExpansionLimitError):
            prepare_xml(
                content,
                expansion_limit_bytes=len(content) + budget_delta,
                prepare_markup=prepare,
            )
    else:
        projection = prepare_xml(
            content, expansion_limit_bytes=len(content), prepare_markup=prepare
        )
        assert projection.parser_source.encode() == content


@pytest.mark.parametrize(
    "ranges",
    [
        (MarkupSourceRange(0, 50),),
        (MarkupSourceRange(0, 5), MarkupSourceRange(2, 6)),
    ],
)
def test_invalid_sdk_ranges_are_implementation_failures(
    ranges: tuple[MarkupSourceRange, ...],
) -> None:
    def prepare(session: MarkupPreparationSession) -> None:
        for span in ranges:
            session.literal(span)

    with pytest.raises(XmlPolicyPreparationError):
        prepare_xml(
            b"<p>readable</p>",
            expansion_limit_bytes=1024,
            prepare_markup=prepare,
        )


def test_xml_late_and_duplicate_declarations_keep_global_replacement() -> None:
    source = (
        b'<!DOCTYPE root [<!ENTITY e "old">]><root a="&e;">&e;</root>'
        b'<!DOCTYPE root [<!ENTITY e "last">]>'
    )
    projection, root = parse_xml(source, expansion_limit_bytes=1024)
    assert root.attrib == {"a": "last"}
    assert root.text == "last"
    assert projection.doctype_count == 2


def test_sdk_cannot_register_a_doctype_overlapping_already_reported_literal() -> None:
    source = "<xmp><!DOCTYPE html></xmp>"

    def prepare(session: MarkupPreparationSession) -> None:
        session.literal(MarkupSourceRange(len("<xmp>"), source.index("</xmp>")))
        session.doctype_end(len("<xmp>"))

    with pytest.raises(XmlPolicyPreparationError, match="overlap"):
        prepare_xml(source.encode(), expansion_limit_bytes=1024, prepare_markup=prepare)
