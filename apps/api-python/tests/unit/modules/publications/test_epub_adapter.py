from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from app.contracts.reader_safety_policy_generated import ReaderSafetyRuleId
from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import (
    PublicationIntegrityError,
    PublicationParserLimitError,
    PublicationResourceBlockedError,
    PublicationStructureError,
)
from app.modules.publications.infrastructure import epub_adapter as epub_adapter_module
from app.modules.publications.infrastructure.epub_adapter import (
    EpubPublicationAdapter,
    _read_archive_resource,
)


def _source(path: Path) -> PublicationSource:
    return PublicationSource(
        resource_id="epub-resource",
        asset_id="epub-asset",
        source_format="epub",
        path=str(path),
        size_bytes=path.stat().st_size,
        mtime_ms=int(path.stat().st_mtime * 1000),
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


def test_first_navigation_document_resolves_its_fragment_only_target(
    tmp_path: Path,
) -> None:
    path = tmp_path / "local-fragment.epub"
    _write_epub(
        path,
        package="""<package><manifest>
        <item id="body" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        <item id="nav" href="Navigation/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="other-nav" href="Navigation/other.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        </manifest><spine><itemref idref="body"/></spine></package>""",
        navigation={
            "Navigation/nav.xhtml": """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
            <body><nav epub:type="toc"><ol><li><a href="#section">Section</a></li></ol></nav>
            <section id="section">Readable text</section></body></html>""",
            "Navigation/other.xhtml": """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
            <body><nav epub:type="toc"><ol><li><a href="../Text/one.xhtml">Other</a></li></ol></nav></body></html>""",
        },
    )
    publication = EpubPublicationAdapter(tmp_path).open(_source(path))
    assert publication.toc[0].href == "OPS/Navigation/nav.xhtml#section"
    assert publication.toc[0].navigation_key == "chapter-0"


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


@pytest.mark.parametrize(
    "ncx_media_type", ["application/x-dtbncx+xml", "application/future-navigation"]
)
def test_epub2_ncx_is_used_when_navigation_document_is_absent(
    tmp_path: Path, ncx_media_type: str
) -> None:
    path = tmp_path / "legacy.epub"
    _write_epub(
        path,
        package=f"""<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
        <dc:title>EPUB 2</dc:title></metadata><manifest>
        <item id="ncx" href="Navigation/toc.ncx" media-type="{ncx_media_type}"/>
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


def test_unused_unsafe_and_symlink_entries_are_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "unused-unsafe-entries.epub"
    _write_epub(
        path,
        package="""<package><metadata><title>Quarantine</title></metadata><manifest>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("../../unused.xhtml", b"ignored")
        linked = zipfile.ZipInfo("OPS/linked.xhtml")
        linked.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(linked, b"ignored")

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert [link.href for link in publication.reading_order] == ["OPS/Text/one.xhtml"]


def test_unused_remote_manifest_item_is_isolated(tmp_path: Path) -> None:
    path = tmp_path / "unused-remote-resource.epub"
    _write_epub(
        path,
        package="""<package><metadata><title>Remote optional</title></metadata><manifest>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        <item id="remote" href="https://example.invalid/chapter.xhtml"
          media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert [link.href for link in publication.reading_order] == ["OPS/Text/one.xhtml"]


def test_unused_entry_with_invalid_crc_isolated_as_optional_resource(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid-unused-crc.epub"
    _write_epub(
        path,
        package="""<package><metadata><title>CRC</title></metadata><manifest>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )
    payload = b"unused-entry-crc-payload"
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("OPS/Images/unused.bin", payload)
    archive_bytes = bytearray(path.read_bytes())
    payload_offset = archive_bytes.index(payload)
    archive_bytes[payload_offset] ^= 0x01
    path.write_bytes(archive_bytes)

    EpubPublicationAdapter(tmp_path).open(_source(path))
    with (
        zipfile.ZipFile(path) as archive,
        pytest.raises(PublicationResourceBlockedError) as raised,
    ):
        _read_archive_resource(
            archive,
            archive.getinfo("OPS/Images/unused.bin"),
            required=False,
        )

    assert (
        raised.value.rule_id
        == ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE.value
    )


def test_active_entity_declaration_is_literalized(tmp_path: Path) -> None:
    path = tmp_path / "active-entity.epub"
    _write_epub(
        path,
        package="""<!DOCTYPE package [<!ENTITY payload SYSTEM "file:///etc/passwd">]>
        <package><metadata><title>&payload;</title></metadata><manifest>
        <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )

    publication = EpubPublicationAdapter(tmp_path).open(_source(path))

    assert publication.title == "&payload;"


def test_required_remote_package_resource_is_a_missing_required_item(
    tmp_path: Path,
) -> None:
    path = tmp_path / "remote-resource.epub"
    _write_epub(
        path,
        package="""<package><metadata><title>Remote</title></metadata><manifest>
        <item id="one" href="https://example.invalid/chapter.xhtml"
          media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>""",
        navigation={},
    )

    with pytest.raises(PublicationIntegrityError) as failure:
        EpubPublicationAdapter(tmp_path).open(_source(path))
    assert (
        failure.value.rule_id
        == ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP.value
    )


def test_unknown_spine_mime_still_runs_resource_sanitization(tmp_path: Path) -> None:
    path = tmp_path / "unknown-spine.epub"
    _write_epub(
        path,
        package='<package><metadata/><manifest><item id="one" href="Text/one.xhtml" '
        'media-type="application/future-document"/></manifest>'
        '<spine><itemref idref="one"/></spine></package>',
        navigation={},
        document_prefix='<!DOCTYPE unknown SYSTEM "https://example.invalid/dtd">',
        document_body_prefix="<script>window.executed=true</script><future-tag>kept</future-tag>",
    )
    original = path.read_bytes()
    adapter = EpubPublicationAdapter(tmp_path)
    source = _source(path)
    publication = adapter.open(source)
    for _ in range(2):
        body = adapter.read_resource(source, publication.reading_order[0].href).content
        assert b"window.executed" not in body
        assert b"DOCTYPE" not in body
        assert b"kept" in body
    assert path.read_bytes() == original


def test_optional_ncx_capacity_failure_does_not_trigger_navigation_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ncx-budget.epub"
    _write_epub(
        path,
        package='<package><metadata/><manifest><item id="one" href="Text/one.xhtml" '
        'media-type="application/xhtml+xml"/><item id="ncx" href="toc.ncx" '
        'media-type="application/x-dtbncx+xml"/></manifest>'
        '<spine toc="ncx"><itemref idref="one"/></spine></package>',
        navigation={"toc.ncx": "<ncx><navMap/>" + " " * 800 + "</ncx>"},
    )
    monkeypatch.setattr(epub_adapter_module, "MAX_XML_CONTROL_DOCUMENT_BYTES", 512)
    reads: list[str] = []
    original_read = zipfile.ZipFile.read

    def read_member(
        archive: zipfile.ZipFile, name: str | zipfile.ZipInfo, pwd: bytes | None = None
    ) -> bytes:
        reads.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return original_read(archive, name, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "read", read_member)
    with pytest.raises(PublicationParserLimitError) as failure:
        EpubPublicationAdapter(tmp_path).open(_source(path))
    assert (
        failure.value.rule_id
        == ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES.value
    )
    assert reads == ["META-INF/container.xml", "OPS/package.opf"]


def test_required_regular_member_colliding_with_symlink_is_not_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "symlink-collision.epub"
    _write_epub(
        path,
        package='<package><metadata/><manifest><item id="one" href="Text/one.xhtml" '
        'media-type="application/future-document"/></manifest>'
        '<spine><itemref idref="one"/></spine></package>',
        navigation={},
    )
    with zipfile.ZipFile(path, "a") as archive:
        linked = zipfile.ZipInfo("OPS/Text/./one.xhtml")
        linked.create_system = 3
        linked.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(linked, b"untrusted-target")
    with pytest.raises(PublicationIntegrityError) as failure:
        EpubPublicationAdapter(tmp_path).open(_source(path))
    assert failure.value.rule_id == ReaderSafetyRuleId.EPUB_RESOURCE_INTEGRITY.value


def test_epub_extra_css_uses_shared_filter_on_first_read(tmp_path: Path) -> None:
    path = tmp_path / "authored-css.epub"
    _write_epub(
        path,
        package='<package><metadata/><manifest><item id="one" href="Text/one.xhtml" '
        'media-type="application/xhtml+xml"/><item id="css" href="style.css" '
        'media-type="text/css"/></manifest><spine><itemref idref="one"/></spine></package>',
        navigation={
            "style.css": "p { color: red; behavior: url(https://example.invalid/evil.htc); }"
        },
    )
    original = path.read_bytes()
    adapter = EpubPublicationAdapter(tmp_path)
    source = _source(path)
    publication = adapter.open(source)
    stylesheet = next(
        link for link in publication.resources if link.media_type == "text/css"
    )
    content = adapter.read_resource(source, stylesheet.href).content
    assert b"color: red" in content
    assert b"behavior" not in content
    assert b"example.invalid" not in content
    assert path.read_bytes() == original
