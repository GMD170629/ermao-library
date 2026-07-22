from __future__ import annotations

import hashlib
import posixpath
import zipfile
from pathlib import Path
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree

import pytest

from app.services.epub_normalizer import (
    EPUB_NORMALIZER_VERSION,
    EpubNormalizationError,
    _relative_href,
    inspect_libmobi_epub,
    normalize_libmobi_epub,
    validate_normalized_epub,
)


def test_relative_href_preserves_safe_apostrophe_in_python_311() -> None:
    assert _relative_href("OEBPS/chapter.xhtml", "OEBPS/chapter.xhtml", "note's-anchor") == "#note's-anchor"


def _write_libmobi_style_epub(path: Path, *, oversized: bool = True, duplicate_anchor: bool = False) -> None:
    repeated_text = "福尔摩斯沿着走廊观察每一个细节。" * (1_900 if oversized else 1)
    body_parts = [
        '<a id="start"></a>',
        '<p><a href="#note">同章注释</a><a href="#later">跨章链接</a></p>',
        '<p><a href="other.xhtml#back">其他章节</a><img src="image.jpg"></p>',
        '<a id="note"></a><p>注释内容</p>',
    ]
    for index in range(24 if oversized else 1):
        if index and index % 4 == 0:
            body_parts.append("<mbp:pagebreak></mbp:pagebreak>")
        body_parts.append(f'<p id="paragraph-{index}">{repeated_text}</p>')
    body_parts.extend(
        [
            '<a id="later"></a><p>最后一节<a href="#start">返回开始</a></p>',
            '<a id="start"></a>' if duplicate_anchor else "",
        ]
    )
    chapter = f"<html><head><title>测试书</title><link rel=\"stylesheet\" href=\"style.css\"></head><body>{''.join(body_parts)}</body></html>"
    other = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>其他</title></head>'
        '<body><a id="back"></a><a href="part00000.html#later">前往最后一节</a></body></html>'
    )
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">normalizer-test</dc:identifier><dc:title>测试书</dc:title><dc:language>zh-CN</dc:language></metadata>
  <manifest>
    <item id="chapter" href="part00000.html" media-type="application/xhtml+xml"/>
    <item id="other" href="other.xhtml" media-type="application/xhtml+xml"/>
    <item id="image" href="image.jpg" media-type="image/jpeg"/>
    <item id="style" href="style.css" media-type="text/css"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine toc="ncx"><itemref idref="chapter"/><itemref idref="other"/></spine>
  <guide><reference type="text" title="开始" href="part00000.html#start"/><reference type="toc" title="结尾" href="part00000.html#later"/></guide>
</package>"""
    ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
  <navPoint id="start"><navLabel><text>开始</text></navLabel><content src="part00000.html#start"/></navPoint>
  <navPoint id="later"><navLabel><text>结尾</text></navLabel><content src="part00000.html#later"/></navPoint>
</navMap></ncx>"""
    nav = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body>
  <nav epub:type="toc"><ol><li><a href="part00000.html#start">开始</a></li><li><a href="part00000.html#later">结尾</a></li></ol></nav>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/part00000.html", chapter)
        archive.writestr("OEBPS/other.xhtml", other)
        archive.writestr("OEBPS/toc.ncx", ncx)
        archive.writestr("OEBPS/nav.xhtml", nav)
        archive.writestr("OEBPS/style.css", "body{line-height:1.7} .cover{background:url(image.jpg)}")
        archive.writestr("OEBPS/image.jpg", b"fake-jpeg-resource")


def _anchors_and_hrefs(path: Path) -> tuple[set[str], list[tuple[str, str]]]:
    anchors: set[str] = set()
    hrefs: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith((".html", ".xhtml")):
                continue
            root = ElementTree.fromstring(archive.read(name))
            for node in root.iter():
                for attribute in ("id", "name"):
                    if node.attrib.get(attribute):
                        anchors.add(node.attrib[attribute])
                if node.attrib.get("href"):
                    hrefs.append((name, node.attrib["href"]))
    return anchors, hrefs


def _resolve_href(source: str, href: str) -> tuple[str, str]:
    path, fragment = urldefrag(href)
    target = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(path))) if path else source
    return target, unquote(fragment)


def test_normalizer_repairs_and_splits_libmobi_output_without_losing_links(tmp_path) -> None:
    source = tmp_path / "libmobi.epub"
    target = tmp_path / "normalized.epub"
    _write_libmobi_style_epub(source)

    before = inspect_libmobi_epub(source)
    assert before.requires_normalization is True
    assert any(reason.startswith("invalid-xhtml:") for reason in before.reasons)
    assert any(reason.startswith("section-bytes:") for reason in before.reasons)

    result = normalize_libmobi_epub(source, target, before)

    assert result.applied is True
    assert result.after.spine_count > before.spine_count
    assert result.after.reasons == ()
    assert result.after.metrics()["maxSectionBytes"] <= 1024 * 1024
    assert result.after.metrics()["maxSectionElements"] <= 10_000
    assert result.after.metrics()["maxSectionImages"] <= 100
    assert result.options()["normalizerVersion"] == EPUB_NORMALIZER_VERSION

    anchors, hrefs = _anchors_and_hrefs(target)
    assert {"start", "note", "later", "back"}.issubset(anchors)
    with zipfile.ZipFile(target) as archive:
        content_names = {name for name in archive.namelist() if name.endswith((".html", ".xhtml"))}
        for source_name, href in hrefs:
            if href.startswith(("http:", "https:", "mailto:")):
                continue
            target_name, fragment = _resolve_href(source_name, href)
            assert target_name in content_names or target_name in archive.namelist()
            if fragment:
                target_root = ElementTree.fromstring(archive.read(target_name))
                target_anchors = {
                    value
                    for node in target_root.iter()
                    for value in (node.attrib.get("id"), node.attrib.get("name"))
                    if value
                }
                assert fragment in target_anchors

        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        ncx = archive.read("OEBPS/toc.ncx").decode("utf-8")
        other = archive.read("OEBPS/other.xhtml").decode("utf-8")
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "part00000-shuku-" in opf
        assert "part00000-shuku-" in ncx
        assert "part00000-shuku-" in other
        assert "part00000-shuku-" in nav


def test_normalizer_keeps_normal_libmobi_epub_byte_identical(tmp_path) -> None:
    source = tmp_path / "normal.epub"
    target = tmp_path / "copied.epub"
    _write_libmobi_style_epub(source, oversized=False)
    inspection = inspect_libmobi_epub(source)
    assert inspection.requires_normalization is True  # mbp is absent, but the source HTML lacks an XHTML namespace.

    # A genuinely strict XHTML fixture must bypass rewriting and remain byte-identical.
    strict = tmp_path / "strict.epub"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(strict, "w") as output:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "OEBPS/part00000.html":
                data = (
                    b'<?xml version="1.0" encoding="utf-8"?>'
                    b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>normal</title></head>'
                    b'<body><a id="start" name="start"></a><a id="note"></a><a id="later"></a>'
                    b'<a href="#note">note</a><a href="#later">later</a><a href="other.xhtml#back">other</a>'
                    b'<img src="image.jpg"/></body></html>'
                )
            output.writestr(info, data)
    strict_inspection = inspect_libmobi_epub(strict)
    assert strict_inspection.requires_normalization is False

    result = normalize_libmobi_epub(strict, target, strict_inspection)

    assert result.applied is False
    assert hashlib.sha256(strict.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()


def test_normalizer_rejects_duplicate_anchors_and_unbreakable_nodes(tmp_path) -> None:
    duplicate = tmp_path / "duplicate.epub"
    _write_libmobi_style_epub(duplicate, oversized=False, duplicate_anchor=True)
    with pytest.raises(EpubNormalizationError, match="重复锚点"):
        inspect_libmobi_epub(duplicate)

    base = tmp_path / "unbreakable-base.epub"
    unbreakable = tmp_path / "unbreakable.epub"
    _write_libmobi_style_epub(base, oversized=False)
    huge_chapter = (
        "<html><body><div><a id=\"start\"></a><a id=\"note\"></a>"
        "<a id=\"later\"></a><a href=\"other.xhtml#back\">other</a>"
        + ("无法拆分" * 300_000)
        + "</div></body></html>"
    ).encode("utf-8")
    with zipfile.ZipFile(base) as original, zipfile.ZipFile(unbreakable, "w") as output:
        for info in original.infolist():
            data = huge_chapter if info.filename == "OEBPS/part00000.html" else original.read(info.filename)
            output.writestr(info, data)
    inspection = inspect_libmobi_epub(unbreakable)
    with pytest.raises(EpubNormalizationError, match="无法在不破坏结构"):
        normalize_libmobi_epub(unbreakable, tmp_path / "should-not-exist.epub", inspection)


def test_validate_normalized_epub_rejects_remaining_abnormal_sections(tmp_path) -> None:
    source = tmp_path / "abnormal.epub"
    _write_libmobi_style_epub(source)
    with pytest.raises(EpubNormalizationError, match="仍未满足约束"):
        validate_normalized_epub(source)
