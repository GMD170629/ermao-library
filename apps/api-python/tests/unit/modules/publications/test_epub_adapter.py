from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import (
    PublicationSecurityError,
    PublicationStructureError,
)
from app.modules.publications.infrastructure.epub_adapter import EpubPublicationAdapter


def _source(path: Path) -> PublicationSource:
    return PublicationSource(
        volume_id="epub-volume",
        file_id="epub-file",
        source_format="epub",
        path=str(path),
        full_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        title="Fallback",
        author=None,
    )


def _write_epub(
    path: Path,
    *,
    package: str,
    navigation: dict[str, str],
    document_prefix: str = "",
    document_body_prefix: str = "",
    second_document: str | None = None,
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>',
        )
        archive.writestr("OPS/package.opf", package)
        archive.writestr(
            "OPS/Text/one.xhtml",
            document_prefix
            + '<html xmlns="http://www.w3.org/1999/xhtml"><head/><body>'
            + document_body_prefix
            + '<h1 id="one">一</h1></body></html>',
        )
        archive.writestr(
            "OPS/Text/two.xhtml",
            second_document
            or document_prefix
            + '<html xmlns="http://www.w3.org/1999/xhtml"><head/><body>'
            + '<h1 id="two">二</h1></body></html>',
        )
        for href, content in navigation.items():
            archive.writestr(f"OPS/{href}", content)


def test_epub3_navigation_preserves_nested_toc(tmp_path: Path) -> None:
    path = tmp_path / "nested.epub"
    _write_epub(
        path,
        package="""<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
        <dc:title>嵌套目录</dc:title></metadata><manifest>
        <item id="nav" href="Navigation/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        <item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
        <item id="unused" href="Images/unused.jpg" media-type="image/jpeg"/>
        </manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>""",
        navigation={
            "Navigation/nav.xhtml": """<html xmlns="http://www.w3.org/1999/xhtml"
            xmlns:epub="http://www.idpf.org/2007/ops"><head/><body><nav epub:type="toc"><ol>
            <li><a href="../Text/one.xhtml#one">第一部</a><ol>
            <li><a href="../Text/two.xhtml#two">第二章</a></li></ol></li>
            </ol></nav></body></html>"""
        },
    )

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert len(publication.toc) == 1
    assert publication.toc[0].title == "第一部"
    assert publication.toc[0].href == "OPS/Text/one.xhtml#one"
    assert publication.toc[0].children[0].title == "第二章"
    assert publication.toc[0].children[0].href == "OPS/Text/two.xhtml#two"


def test_epub2_ncx_is_used_when_navigation_document_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "legacy.epub"
    _write_epub(
        path,
        package="""<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
        <dc:title>EPUB 2</dc:title></metadata><manifest>
        <item id="ncx" href="Navigation/toc.ncx" media-type="application/x-dtbncx+xml"/>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        <item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine toc="ncx"><itemref idref="one"/><itemref idref="two"/></spine></package>""",
        navigation={
            "Navigation/toc.ncx": """<?xml version="1.0"?>
            <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
              "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
            <navMap><navPoint id="p1"><navLabel><text>第一部</text></navLabel>
            <content src="../Text/one.xhtml#one"/><navPoint id="p2">
            <navLabel><text>第二章</text></navLabel><content src="../Text/two.xhtml#two"/>
            </navPoint></navPoint></navMap></ncx>"""
        },
        document_prefix="""<?xml version="1.0"?>
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
          "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
        """,
        document_body_prefix="<p>&nbsp;</p>",
    )

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert [(entry.title, entry.href) for entry in publication.toc] == [
        ("第一部", "OPS/Text/one.xhtml#one")
    ]
    assert [(entry.title, entry.href) for entry in publication.toc[0].children] == [
        ("第二章", "OPS/Text/two.xhtml#two")
    ]


def test_navigation_does_not_require_every_spine_document_to_be_well_formed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "malformed-body.epub"
    _write_epub(
        path,
        package="""<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
        <dc:title>正文损坏仍有目录</dc:title></metadata><manifest>
        <item id="ncx" href="Navigation/toc.ncx" media-type="application/x-dtbncx+xml"/>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        <item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine toc="ncx"><itemref idref="one"/><itemref idref="two"/></spine></package>""",
        navigation={
            "Navigation/toc.ncx": """<ncx><navMap><navPoint><navLabel><text>可用章节</text></navLabel>
            <content src="../Text/one.xhtml#one"/></navPoint></navMap></ncx>"""
        },
        second_document='<html><head></head><body><p><img src="cover.jpg"></p></body></html>',
    )

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert [(entry.title, entry.href) for entry in publication.toc] == [
        ("可用章节", "OPS/Text/one.xhtml#one")
    ]
    assert [link.href for link in publication.reading_order] == [
        "OPS/Text/one.xhtml",
        "OPS/Text/two.xhtml",
    ]


def test_invalid_epub3_navigation_falls_back_to_valid_ncx(tmp_path: Path) -> None:
    path = tmp_path / "nav-fallback.epub"
    _write_epub(
        path,
        package="""<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
        <dc:title>Nav fallback</dc:title></metadata><manifest>
        <item id="nav" href="Navigation/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="ncx" href="Navigation/toc.ncx" media-type="application/x-dtbncx+xml"/>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        <item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine toc="ncx"><itemref idref="one"/><itemref idref="two"/></spine></package>""",
        navigation={
            "Navigation/nav.xhtml": "<html><body><nav><ol><li>broken</ol></nav></body></html>",
            "Navigation/toc.ncx": """<ncx><navMap><navPoint><navLabel><text>NCX 章节</text></navLabel>
            <content src="../Text/two.xhtml#two"/></navPoint></navMap></ncx>""",
        },
    )

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert [(entry.title, entry.href) for entry in publication.toc] == [
        ("NCX 章节", "OPS/Text/two.xhtml#two")
    ]


def test_invalid_zip_is_a_structure_error_not_a_security_rejection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.epub"
    path.write_bytes(b"not a zip archive")

    with pytest.raises(PublicationStructureError):
        EpubPublicationAdapter(tmp_path).open(_source(path))


def test_active_entity_declaration_is_security_rejected(tmp_path: Path) -> None:
    path = tmp_path / "active-entity.epub"
    _write_epub(
        path,
        package="""<!DOCTYPE package [<!ENTITY payload SYSTEM "file:///etc/passwd">]>
        <package><metadata><title>&payload;</title></metadata><manifest>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )

    with pytest.raises(PublicationSecurityError):
        EpubPublicationAdapter(tmp_path).open(_source(path))


def test_remote_package_resource_is_security_rejected(tmp_path: Path) -> None:
    path = tmp_path / "remote-resource.epub"
    _write_epub(
        path,
        package="""<package><metadata><title>Remote</title></metadata><manifest>
        <item id="one" href="https://example.invalid/chapter.xhtml"
          media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )

    with pytest.raises(PublicationSecurityError):
        EpubPublicationAdapter(tmp_path).open(_source(path))
