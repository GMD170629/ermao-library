from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import (
    PublicationCorruptError,
    PublicationResourceNotFoundError,
)
from app.modules.publications.infrastructure.txt_adapter import TxtPublicationAdapter


def _source(path: Path) -> PublicationSource:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return PublicationSource(
        volume_id="txt-volume",
        file_id="txt-file",
        source_format="txt",
        path=str(path),
        full_hash=digest,
        title="确定性文本",
        author="测试作者",
    )


@pytest.mark.parametrize(
    ("encoded", "marker"),
    [
        ("第一章\r\n天地玄黄".encode(), "天地玄黄"),
        (b"\xef\xbb\xbf" + "第一章\r天地玄黄".encode(), "天地玄黄"),
        (b"\xff\xfe" + "第一章\n天地玄黄".encode("utf-16-le"), "天地玄黄"),
        (b"\xfe\xff" + "第一章\n天地玄黄".encode("utf-16-be"), "天地玄黄"),
        ("第一章\n天地玄黄".encode("gb18030"), "天地玄黄"),
    ],
)
def test_txt_adapter_has_fixed_encoding_and_newline_policy(
    tmp_path: Path, encoded: bytes, marker: str
) -> None:
    path = tmp_path / "book.txt"
    path.write_bytes(encoded)
    adapter = TxtPublicationAdapter(tmp_path)

    publication = adapter.open(_source(path))
    resource = adapter.read_resource(_source(path), "text/chapter-0001.xhtml")

    assert publication.fingerprint.parser == "shuku-txt-parser-v1"
    assert publication.fingerprint.normalization == "shuku-txt-publication-v2"
    assert publication.reading_order[0].href == "text/chapter-0001.xhtml"
    assert publication.toc[0].href == ("text/chapter-0001.xhtml#heading-000001")
    assert marker in resource.content.decode("utf-8")
    assert "\r" not in resource.content.decode("utf-8")


def test_txt_adapter_golden_chapters_hrefs_and_dom_ids_are_stable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "golden.txt"
    path.write_text(
        "序言第一行\r\n\r\n第一章 开端\r天地 & <宇宙>  \n第二行\u2028"
        "Chapter II: Finale\n终章",
        encoding="utf-8",
    )
    source = _source(path)
    adapter = TxtPublicationAdapter(tmp_path)

    first = adapter.open(source)
    second = adapter.open(source)

    assert first == second
    assert [link.href for link in first.reading_order] == [
        "text/chapter-0001.xhtml",
        "text/chapter-0002.xhtml",
        "text/chapter-0003.xhtml",
    ]
    assert [entry.title for entry in first.toc] == [
        "确定性文本 1",
        "第一章 开端",
        "Chapter II: Finale",
    ]
    assert [entry.href for entry in first.toc] == [
        "text/chapter-0001.xhtml#heading-000001",
        "text/chapter-0002.xhtml#heading-000001",
        "text/chapter-0003.xhtml#heading-000001",
    ]
    first_xhtml = adapter.read_resource(source, first.reading_order[0].href).content
    second_xhtml = adapter.read_resource(source, first.reading_order[1].href).content
    assert 'id="heading-000001"' in first_xhtml.decode()
    assert 'id="block-000001"' in first_xhtml.decode()
    assert 'id="heading-000001"' in second_xhtml.decode()
    assert 'id="block-000001"' in second_xhtml.decode()
    assert "天地 &amp; &lt;宇宙&gt;" in second_xhtml.decode()
    assert "&gt;<br/>第二行" in second_xhtml.decode()


def test_txt_adapter_rejects_binary_and_unindexed_resources(tmp_path: Path) -> None:
    path = tmp_path / "binary.txt"
    path.write_bytes(b"valid\x00binary")
    adapter = TxtPublicationAdapter(tmp_path)

    with pytest.raises(PublicationCorruptError):
        adapter.open(_source(path))

    path.write_text("正文", encoding="utf-8")
    source = _source(path)
    with pytest.raises(PublicationResourceNotFoundError):
        adapter.read_resource(source, "../secret")
    with pytest.raises(PublicationResourceNotFoundError):
        adapter.read_resource(source, "text/not-indexed.xhtml")
