from __future__ import annotations

from xml.etree import ElementTree

import pytest

from app.modules.publications.domain.model import PublicationSecurityError
from app.modules.publications.infrastructure.render_markup import canonicalize_markup


def test_recovers_common_html_errors_as_deterministic_xhtml() -> None:
    malformed = b"""<html xmlns="http://www.w3.org/1999/xhtml"><head></head>
    <body><p>A & B<img src="cover.jpg"></p></body></html>"""

    first = canonicalize_markup(malformed, href="Text/broken.xhtml")
    second = canonicalize_markup(malformed, href="Text/broken.xhtml")

    assert first == second
    assert first.recovered is True
    assert first.unreadable is False
    root = ElementTree.fromstring(first.content)
    assert root.tag == "{http://www.w3.org/1999/xhtml}html"
    assert "A &amp; B" in first.content.decode()


def test_recovers_missing_epub_namespace_without_losing_semantics() -> None:
    malformed = b"""<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body>
    <a epub:type="noteref" href="#note">note</a></body></html>"""

    result = canonicalize_markup(malformed, href="Text/chapter.xhtml")

    assert result.recovered is True
    assert b'xmlns:epub="http://www.idpf.org/2007/ops"' in result.content
    assert b'epub:type="noteref"' in result.content
    ElementTree.fromstring(result.content)


def test_recovers_legacy_mobipocket_pagebreak_element() -> None:
    legacy_mobi = b"""<html><head></head><body><p>Before</p>
    <mbp:pagebreak><p>After</p></body></html>"""

    result = canonicalize_markup(legacy_mobi, href="part00000.html")

    assert result.recovered is True
    assert result.unreadable is False
    root = ElementTree.fromstring(result.content)
    pagebreak = root.find(".//{http://www.w3.org/1999/xhtml}hr")
    assert pagebreak is not None
    assert pagebreak.attrib["data-shuku-original-element"] == "mbp:pagebreak"
    assert pagebreak.attrib["data-shuku-pagebreak"] == "true"


def test_active_entity_declaration_is_rejected_instead_of_recovered() -> None:
    malicious = b"""<!DOCTYPE html [<!ENTITY leak SYSTEM "file:///etc/passwd">]>
    <html><head></head><body>&leak;</body></html>"""

    with pytest.raises(PublicationSecurityError):
        canonicalize_markup(malicious, href="Text/chapter.xhtml")
