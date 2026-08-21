from __future__ import annotations

import pytest

from app.modules.metadata.application.opf import OpfMetadataError, parse_opf_metadata


def _opf(*, title: str) -> bytes:
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
 <metadata>
  <dc:title>{title}</dc:title>
  <dc:creator>作者甲</dc:creator><dc:creator>作者乙</dc:creator>
  <dc:description>简介</dc:description>
  <dc:subject>科幻</dc:subject><dc:subject>冒险</dc:subject>
  <dc:language>zh-CN</dc:language><dc:publisher>出版社</dc:publisher>
  <dc:date>2024-03-02</dc:date>
  <dc:identifier opf:scheme="ISBN" xmlns:opf="http://www.idpf.org/2007/opf">978-7-0000-0000-1</dc:identifier>
  <meta property="belongs-to-collection">星海系列</meta>
  <meta property="group-position">2.5</meta>
 </metadata>
</package>""".encode()


def test_parse_opf_maps_multiple_authors_series_isbn_and_subjects() -> None:
    metadata = parse_opf_metadata(_opf(title="星海列车"))

    assert metadata.title == "星海系列"
    assert metadata.volume_title == "星海列车"
    assert metadata.authors == ("作者甲", "作者乙")
    assert metadata.author == "作者甲 / 作者乙"
    assert metadata.subjects == ("科幻", "冒险")
    assert metadata.series_name == "星海系列"
    assert metadata.series_index == 2.5
    assert metadata.isbn == "978-7-0000-0000-1"


def test_epub3_group_position_supplements_calibre_series_without_index() -> None:
    metadata = parse_opf_metadata(
        """<package xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <metadata>
  <dc:title>第一部</dc:title>
  <meta name="calibre:series" content="Calibre 系列"/>
  <meta property="belongs-to-collection">EPUB3 系列</meta>
  <meta property="group-position">4</meta>
 </metadata>
</package>""".encode()
    )

    assert metadata.title == "Calibre 系列"
    assert metadata.volume_title == "第一部"
    assert metadata.series_name == "Calibre 系列"
    assert metadata.series_index == 4
    assert metadata.volume_index == 4


def test_calibre_series_index_wins_over_epub3_group_position() -> None:
    metadata = parse_opf_metadata(
        """<package xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <metadata>
  <dc:title>第一部</dc:title>
  <meta name="calibre:series" content="Calibre 系列"/>
  <meta name="calibre:series_index" content="2"/>
  <meta property="group-position">9</meta>
 </metadata>
</package>""".encode()
    )

    assert metadata.series_index == 2
    assert metadata.volume_index == 2


@pytest.mark.parametrize(
    "payload",
    (
        b'<!DOCTYPE package [<!ENTITY secret SYSTEM "file:///etc/passwd">]><package/>',
        b"<package><metadata>",
        b"x" * (2 * 1024 * 1024 + 1),
    ),
)
def test_parser_rejects_entities_invalid_xml_and_oversized_input(
    payload: bytes,
) -> None:
    with pytest.raises(OpfMetadataError):
        parse_opf_metadata(payload)
