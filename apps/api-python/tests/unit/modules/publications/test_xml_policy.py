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
    XmlPolicyPreparationError,
    parse_xml,
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
