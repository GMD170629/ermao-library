from __future__ import annotations

import json
from pathlib import Path

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
    _ROOT / "packages" / "reader-contracts" / "fixtures" / "normalization-v2"
)


def test_projection_matches_cross_language_fixture_and_normalizes_text() -> None:
    markup = _FIXTURE_ROOT.joinpath("chapter.xhtml").read_bytes()
    expected = json.loads(_FIXTURE_ROOT.joinpath("projection.json").read_text())

    projection = locator_dom_projection(
        normalization="shuku-epub-locator-dom-v2",
        resources=(("OPS/chapter.xhtml", "application/xhtml+xml", markup),),
    )

    assert projection == expected
    assert (
        locator_dom_projection_hash(projection)
        == _FIXTURE_ROOT.joinpath("projection.sha256").read_text().strip()
    )


def test_security_decoration_changes_only_head_and_preserves_projection() -> None:
    markup = _FIXTURE_ROOT.joinpath("chapter.xhtml").read_bytes()
    before = locator_dom_projection(
        normalization="shuku-epub-locator-dom-v2",
        resources=(("OPS/chapter.xhtml", "application/xhtml+xml", markup),),
    )

    decorated = decorate_markup_head(markup, WEB_SECURITY_PROFILE)
    after = locator_dom_projection(
        normalization="shuku-epub-locator-dom-v2",
        resources=(("OPS/chapter.xhtml", "application/xhtml+xml", decorated),),
    )

    assert after == before
    text = decorated.decode("utf-8")
    assert "script-src blob:" in text
    assert 'data-shuku-security-profile="web-v2"' in text
    assert 'http-equiv="refresh"' not in text
    assert "<base " not in text
    assert "<script>globalThis.shukuBookScriptExecuted" in text
    assert "<form action=" in text
    assert "<iframe src=" in text


def test_security_decoration_ignores_fake_head_in_comment_and_cdata() -> None:
    markup = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<!-- <head><script>fake()</script></head><!DOCTYPE html> -->
<head><title>Real</title></head>
<body><script><![CDATA["<head>fake</head><!ENTITY inert>"]]></script><p>Body</p></body>
</html>"""

    decorated = decorate_markup_head(markup, WEB_SECURITY_PROFILE).decode()

    profile_index = decorated.index('data-shuku-security-profile="web-v2"')
    assert profile_index > decorated.index("<!-- <head>")
    assert profile_index < decorated.index("<title>Real</title>")
    assert '<![CDATA["<head>fake</head><!ENTITY inert>"]]>' in decorated


@pytest.mark.parametrize(
    "doctype",
    [
        "<!DOCTYPE html>",
        (
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"\n'
            '  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
        ),
        (
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"\n'
            '  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">'
        ),
    ],
)
def test_standard_epub_doctype_is_accepted(doctype: str) -> None:
    markup = f"""<?xml version="1.0"?>
{doctype}
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Standard EPUB</title></head>
<body><h1 id="chapter">Chapter&nbsp;One</h1></body>
</html>""".encode()

    _decoded, root = validate_xhtml(markup)

    assert root.tag == "{http://www.w3.org/1999/xhtml}html"
    assert "Chapter\N{NO-BREAK SPACE}One" in "".join(root.itertext())


@pytest.mark.parametrize(
    "markup",
    [
        b"<html><head></head><body><p>not closed</p>",
        b"<html><body><p>missing head</p></body></html>",
        b"<html><head></head><body>&external;</body></html>",
        (
            b"<!DOCTYPE html [<!ENTITY external SYSTEM 'file:///etc/passwd'>]>"
            b"<html><head></head><body>&external;</body></html>"
        ),
        (
            b"<!DOCTYPE html SYSTEM 'https://attacker.invalid/book.dtd'>"
            b"<html><head></head><body><p>Body</p></body></html>"
        ),
    ],
)
def test_invalid_or_unsafe_xhtml_is_rejected_without_blank_fallback(
    markup: bytes,
) -> None:
    with pytest.raises(PublicationCorruptError):
        validate_xhtml(markup)
