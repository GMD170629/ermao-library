from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import (
    PublicationCorruptError,
    PublicationResourceNotFoundError,
)
from app.modules.publications.infrastructure.fb2_adapter import Fb2PublicationAdapter


def test_fb2_body_contract_matches_native_shared_fixture() -> None:
    corpus = Path(__file__).resolve().parents[6] / "test-data/library/fb2"
    path = corpus / "reader-contract.fb2"
    original = path.read_bytes()
    adapter = Fb2PublicationAdapter(corpus)
    source = _source(path)
    publication = adapter.open(source)
    expected = json.loads((corpus / "reader-contract-bodies.json").read_text())

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
    assert publication.revision.normalization == "shuku-fb2-publication-v1"
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
    assert 'href="section-0002.xhtml#fb2-node-' in markup
    assert 'src="images/' in markup
    image = next(
        link for link in publication.resources if link.media_type == "image/png"
    )
    assert adapter.read_resource(source, image.href).content.startswith(b"\x89PNG")


def test_fb2_adapter_rejects_active_xml_and_unindexed_resources(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsafe.fb2"
    path.write_text(
        '<!DOCTYPE FictionBook [<!ENTITY leak SYSTEM "file:///etc/passwd">]>'
        "<FictionBook><body><section><p>&leak;</p></section></body></FictionBook>",
        encoding="utf-8",
    )
    adapter = Fb2PublicationAdapter(tmp_path)

    with pytest.raises(PublicationCorruptError):
        adapter.open(_source(path))

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
    assert 'href="section-0001.xhtml#fb2-node-' in markup


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
