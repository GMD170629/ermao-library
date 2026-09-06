from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.modules.publications.domain.model import PublicationCorruptError
from app.modules.publications.infrastructure.locator_dom import (
    WEB_SECURITY_PROFILE,
    decorate_markup_head,
    locator_dom_projection,
    locator_dom_projection_hash,
    validate_xhtml,
)

_ROOT = Path(__file__).parents[6]
_FIXTURE_ROOT = (
    _ROOT / "packages" / "reader-contracts" / "fixtures" / "normalization-v4"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def test_projection_matches_policy_bound_cross_language_fixture() -> None:
    markup = _FIXTURE_ROOT.joinpath("chapter.xhtml").read_bytes()
    expected = json.loads(
        _FIXTURE_ROOT.joinpath("projection.json").read_text(encoding="utf-8")
    )

    projection = locator_dom_projection(
        normalization="shuku-epub-locator-dom-v4",
        resources=(("OPS/chapter.xhtml", "application/xhtml+xml", markup),),
    )

    assert projection == expected
    assert (
        locator_dom_projection_hash(projection)
        == _FIXTURE_ROOT.joinpath("projection.sha256").read_text().strip()
    )


def test_security_decoration_sanitizes_body_in_memory_and_preserves_projection() -> (
    None
):
    markup = _FIXTURE_ROOT.joinpath("chapter.xhtml").read_bytes()
    before = locator_dom_projection(
        normalization="shuku-epub-locator-dom-v4",
        resources=(("OPS/chapter.xhtml", "application/xhtml+xml", markup),),
    )

    decorated = decorate_markup_head(markup, WEB_SECURITY_PROFILE)
    after = locator_dom_projection(
        normalization="shuku-epub-locator-dom-v4",
        resources=(("OPS/chapter.xhtml", "application/xhtml+xml", decorated),),
    )

    assert after == before
    root = ElementTree.fromstring(decorated)
    names = {_local_name(element.tag) for element in root.iter()}
    assert {"script", "base", "form", "iframe"}.isdisjoint(names)
    assert all(
        not key.rsplit("}", 1)[-1].lower().startswith("on")
        for element in root.iter()
        for key in element.attrib
    )
    trusted_meta = next(
        element
        for element in root.iter()
        if _local_name(element.tag) == "meta"
        and element.attrib.get("data-shuku-security-profile") == "web-v2"
    )
    assert "script-src blob:" in trusted_meta.attrib["content"]


def test_security_decoration_does_not_treat_comment_or_cdata_as_declarations() -> None:
    markup = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<!-- <head><script>fake()</script></head><!DOCTYPE html> -->
<head><title>Real</title></head>
<body><script><![CDATA["<head>fake</head><!ENTITY inert>"]]></script><p>Body</p></body>
</html>"""

    decorated = decorate_markup_head(markup, WEB_SECURITY_PROFILE)
    root = ElementTree.fromstring(decorated)

    assert "Body" in "".join(root.itertext())
    assert all(_local_name(element.tag) != "script" for element in root.iter())
    assert any(
        element.attrib.get("data-shuku-security-profile") == "web-v2"
        for element in root.iter()
    )


@pytest.mark.parametrize(
    "declaration",
    [
        "<!DOCTYPE html>",
        '<!DOCTYPE html SYSTEM "https://example.invalid/xhtml.dtd">',
        '<!DOCTYPE html PUBLIC "-//Example//DTD XHTML//EN" "urn:example:xhtml">',
        '<!DOCTYPE html [<!ENTITY plain "Readable">]>',
    ],
)
def test_arbitrary_well_formed_xhtml_doctypes_are_accepted(
    declaration: str,
) -> None:
    entity_reference = "&plain;" if "<!ENTITY plain" in declaration else "&unknown;"
    expected_entity = "Readable" if entity_reference == "&plain;" else "&unknown;"
    markup = f"""<?xml version="1.0"?>
{declaration}
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Standard EPUB</title></head>
<body><h1 id="chapter">Chapter&nbsp;One &copy; {entity_reference}</h1></body>
</html>""".encode()

    _decoded, root = validate_xhtml(markup)

    assert root.tag == "{http://www.w3.org/1999/xhtml}html"
    assert f"Chapter\u00a0One \u00a9 {expected_entity}" in "".join(root.itertext())


@pytest.mark.parametrize(
    "markup",
    [
        b"<html><head></head><body><p>not closed</p>",
        b"<html><body><p>missing head</p></body></html>",
    ],
)
def test_malformed_or_incomplete_xhtml_is_rejected_without_blank_fallback(
    markup: bytes,
) -> None:
    with pytest.raises(PublicationCorruptError):
        validate_xhtml(markup)


def test_external_and_unknown_entities_are_literalized_in_memory() -> None:
    markup = (
        b'<!DOCTYPE html [<!ENTITY external SYSTEM "file:///etc/passwd">]>'
        b"<html><head></head><body>&external; &unknown;</body></html>"
    )

    _decoded, root = validate_xhtml(markup)

    assert "&external; &unknown;" in "".join(root.itertext())


def test_generated_uri_and_css_profiles_preserve_navigation_and_safe_declarations() -> (
    None
):
    markup = b"""<html xmlns="http://www.w3.org/1999/xhtml"><head>
<style>@import url(https://example.test/x.css);p{behavior:url(x);color:red}</style>
</head><body><a href="https://example.test/read">read</a>
<img src="https://example.test/cover.jpg" srcset="local.png 1x, //example.test/remote.png 2x"/>
<p style="color:red;background:url(javascript:alert(1))">safe</p></body></html>"""

    _decoded, root = validate_xhtml(markup)

    style = next(
        element for element in root.iter() if _local_name(element.tag) == "style"
    )
    anchor = next(element for element in root.iter() if _local_name(element.tag) == "a")
    image = next(
        element for element in root.iter() if _local_name(element.tag) == "img"
    )
    paragraph = next(
        element for element in root.iter() if _local_name(element.tag) == "p"
    )
    assert style.text == "p{color:red}"
    assert anchor.attrib["href"] == "https://example.test/read"
    assert "src" not in image.attrib
    assert image.attrib["srcset"] == "local.png 1x"
    assert paragraph.attrib["style"] == 'color:red;background:url("")'
