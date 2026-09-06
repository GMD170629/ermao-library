from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import (
    PublicationCorruptError,
    PublicationParserLimitError,
    PublicationResourceBlockedError,
    PublicationResourceNotFoundError,
)
from app.modules.publications.infrastructure import fb2_adapter as fb2_adapter_module
from app.modules.publications.infrastructure.fb2_adapter import Fb2PublicationAdapter


def test_fb2_body_contract_matches_native_shared_fixture() -> None:
    corpus = Path(__file__).resolve().parents[6] / "test-data/library/fb2"
    path = corpus / "reader-contract.fb2"
    original = path.read_bytes()
    adapter = Fb2PublicationAdapter(corpus)
    source = _source(path)
    publication = adapter.open(source)
    expected = json.loads(
        (corpus / "reader-contract-bodies.json").read_text(encoding="utf-8")
    )

    assert [link.href for link in publication.reading_order] == list(expected)
    for link in publication.reading_order:
        markup = adapter.read_resource(source, link.href).content.decode()
        assert (
            markup.split("<body>", 1)[1].split("</body>", 1)[0] == expected[link.href]
        )
    assert path.read_bytes() == original


def _source(path: Path) -> PublicationSource:
    return PublicationSource(
        resource_id="fb2-resource",
        asset_id="fb2-asset",
        source_format="fb2",
        path=str(path),
        size_bytes=path.stat().st_size,
        mtime_ms=int(path.stat().st_mtime * 1000),
        title="Fallback",
        author="Fallback Author",
    )


def test_fb2_mixed_body_order_and_untitled_sections_do_not_create_extra_chapters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mixed.fb2"
    path.write_text(
        "<FictionBook><body><p>Before</p>"
        "<section><p>Untitled before</p><section><title><p>Nested</p></title>"
        "<p>Nested body</p></section><p>Untitled after</p></section>"
        "<p>Between</p><section><title><p>Last</p></title><p>Last body</p></section>"
        "<p>After</p></body></FictionBook>",
        encoding="utf-8",
    )
    source = _source(path)
    adapter = Fb2PublicationAdapter(tmp_path)
    publication = adapter.open(source)
    assert [entry.title for entry in publication.toc] == ["Nested", "Last"]
    assert [entry.navigation_key for entry in publication.toc] == [
        "chapter-0",
        "chapter-1",
    ]
    markup = "".join(
        adapter.read_resource(source, link.href).content.decode()
        for link in publication.reading_order
    )
    markers = [
        ">Before<",
        ">Untitled before<",
        ">Nested body<",
        ">Untitled after<",
        ">Between<",
        ">Last body<",
        ">After<",
    ]
    assert [markup.index(marker) for marker in markers] == sorted(
        markup.index(marker) for marker in markers
    )
    for entry in publication.toc:
        assert entry.href is not None
        href, _, anchor = entry.href.partition("#")
        assert f'id="{anchor}"' in adapter.read_resource(source, href).content.decode()


def test_fb2_adapter_builds_nested_toc_and_safe_virtual_resources(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested.fb2"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:l="http://www.w3.org/1999/xlink">
 <description><title-info><author><first-name>测试</first-name><last-name>作者</last-name></author>
 <book-title>原始 FB2</book-title><lang>zh-CN</lang></title-info></description>
 <body><section id="part-one"><title><p>第一部</p></title><p>开篇 &amp; 正文</p>
   <section id="chapter-two"><title><p>第二章</p></title>
   <p>含有<emphasis>重点</emphasis><a l:href="#note-one">注释</a></p>
   <image l:href="#cover"/></section></section></body>
 <body name="notes"><section id="note-one"><title><p>注释</p></title><p>注释正文</p></section></body>
 <binary id="cover" content-type="image/png">
 iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=
 </binary>
</FictionBook>""",
        encoding="utf-8",
    )
    source = _source(path)
    adapter = Fb2PublicationAdapter(tmp_path)

    publication = adapter.open(source)

    assert publication.title == "原始 FB2"
    assert publication.author == "测试 作者"
    assert publication.language == "zh-CN"
    assert publication.revision.parser == "shuku-fb2-parser-v1"
    assert publication.revision.normalization == "shuku-fb2-publication-v3"
    assert [entry.title for entry in publication.toc] == ["第一部", "注释"]
    assert [entry.title for entry in publication.toc[0].children] == ["第二章"]
    assert [link.href for link in publication.reading_order] == [
        "fb2/section-0001.xhtml",
        "fb2/section-0002.xhtml",
    ]

    chapter = adapter.read_resource(source, "fb2/section-0001.xhtml")
    markup = chapter.content.decode()
    assert "开篇 &amp; 正文" in markup
    assert 'data-shuku-security-profile="web-v2"' in markup
    assert "<em>重点</em>" in markup
    assert 'href="section-0002.xhtml#chapter-node-' in markup
    assert 'src="images/' in markup
    image = next(
        link for link in publication.resources if link.media_type == "image/png"
    )
    assert adapter.read_resource(source, image.href).content.startswith(b"\x89PNG")


def test_fb2_adapter_literalizes_external_xml_and_rejects_unindexed_resources(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsafe.fb2"
    path.write_text(
        '<!DOCTYPE FictionBook [<!ENTITY leak SYSTEM "file:///etc/passwd">]>'
        "<FictionBook><body><section><p>&leak;</p></section></body></FictionBook>",
        encoding="utf-8",
    )
    adapter = Fb2PublicationAdapter(tmp_path)

    source = _source(path)
    publication = adapter.open(source)
    markup = adapter.read_resource(source, publication.reading_order[0].href)
    assert "&amp;leak;" in markup.content.decode()

    path.write_text(
        "<FictionBook><body><section><title><p>正文</p></title></section></body></FictionBook>",
        encoding="utf-8",
    )
    source = _source(path)
    with pytest.raises(PublicationResourceNotFoundError):
        adapter.read_resource(source, "../secret")


def test_fb2_adapter_repairs_legacy_l_href_bound_as_xlink(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-link-prefix.fb2"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <description><title-info><book-title>Legacy links</book-title></title-info></description>
 <body><section id="start"><title><p>Start</p></title>
 <p><a l:href="#start">Return to start</a></p></section></body>
</FictionBook>""",
        encoding="utf-8",
    )
    adapter = Fb2PublicationAdapter(tmp_path)
    source = _source(path)

    publication = adapter.open(source)
    markup = adapter.read_resource(
        source, publication.reading_order[0].href
    ).content.decode()

    assert publication.title == "Legacy links"
    assert 'href="section-0001.xhtml#chapter-node-' in markup


def test_fb2_adapter_still_rejects_unbound_non_link_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unbound-prefix.fb2"
    path.write_text(
        """<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <body><section><p bad:value="1">Unsafe</p></section></body>
</FictionBook>""",
        encoding="utf-8",
    )

    with pytest.raises(PublicationCorruptError):
        Fb2PublicationAdapter(tmp_path).open(_source(path))


def test_fb2_image_budget_blocks_only_the_oversized_optional_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fb2_adapter_module, "MAX_ENCODED_BINARY_BYTES", 4)
    path = tmp_path / "oversized-image.fb2"
    path.write_text(
        """<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:l="http://www.w3.org/1999/xlink">
 <description><title-info><book-title>Readable text</book-title></title-info></description>
 <body><section><title><p>Chapter</p></title><p>Still readable</p>
 <image l:href="#oversized"/></section></body>
 <binary id="oversized" content-type="image/png">aGVsbG8=</binary>
</FictionBook>""",
        encoding="utf-8",
    )
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    adapter = Fb2PublicationAdapter(tmp_path)
    source = _source(path)

    publication = adapter.open(source)
    markup = adapter.read_resource(
        source, publication.reading_order[0].href
    ).content.decode()

    assert "Still readable" in markup
    assert '<img src="images/' in markup
    image = next(link for link in publication.resources if "images/" in link.href)
    with pytest.raises(PublicationResourceBlockedError) as failure:
        adapter.read_resource(source, image.href)
    assert failure.value.rule_id == "FB2.IMAGE_BUDGET"
    assert failure.value.code == "PUBLICATION_RESOURCE_BLOCKED"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash


def test_fb2_structure_budget_failure_carries_generated_rule_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fb2_adapter_module, "MAX_XML_ELEMENTS", 2)
    path = tmp_path / "too-many-nodes.fb2"
    path.write_text(
        "<FictionBook><body><section><p>text</p></section></body></FictionBook>",
        encoding="utf-8",
    )

    with pytest.raises(PublicationParserLimitError) as failure:
        Fb2PublicationAdapter(tmp_path).open(_source(path))

    assert failure.value.code == "PUBLICATION_PARSER_LIMIT"
    assert failure.value.rule_id == "FB2.STRUCTURE_BUDGET"


@pytest.mark.parametrize("media_type", ["image/future-format", ""])
def test_fb2_unknown_image_metadata_reaches_resource_decoder(
    tmp_path: Path,
    media_type: str,
) -> None:
    path = tmp_path / "unknown-image.fb2"
    original = (
        '<FictionBook xmlns:l="http://www.w3.org/1999/xlink">'
        '<body><section><p>Readable</p><image l:href="#image"/></section></body>'
        f'<binary id="image" content-type="{media_type}">aGVsbG8=</binary>'
        "</FictionBook>"
    ).encode()
    path.write_bytes(original)
    adapter = Fb2PublicationAdapter(tmp_path)
    source = _source(path)
    publication = adapter.open(source)
    resource = next(link for link in publication.resources if "images/" in link.href)
    assert adapter.read_resource(source, resource.href).content == b"hello"
    assert (
        "<img"
        in adapter.read_resource(
            source, publication.reading_order[0].href
        ).content.decode()
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "binary",
    [
        '<binary id="image" content-type="image/png">invalid!</binary>',
        (
            '<binary id="image" content-type="image/png">aGVsbG8=</binary>'
            '<binary id="image" content-type="image/future-format">d29ybGQ=</binary>'
        ),
    ],
)
def test_fb2_corrupt_optional_binary_does_not_reject_body(
    tmp_path: Path,
    binary: str,
) -> None:
    path = tmp_path / "corrupt-image.fb2"
    path.write_text(
        "<FictionBook><body><section><p>Still readable</p></section></body>"
        + binary
        + "</FictionBook>",
        encoding="utf-8",
    )
    adapter = Fb2PublicationAdapter(tmp_path)
    source = _source(path)
    publication = adapter.open(source)
    assert (
        "Still readable"
        in adapter.read_resource(
            source, publication.reading_order[0].href
        ).content.decode()
    )
    resource = next(link for link in publication.resources if "images/" in link.href)
    with pytest.raises(PublicationResourceBlockedError) as failure:
        adapter.read_resource(source, resource.href)
    assert failure.value.rule_id == "REFLOWABLE.OPTIONAL_RESOURCE_FAILURE"
