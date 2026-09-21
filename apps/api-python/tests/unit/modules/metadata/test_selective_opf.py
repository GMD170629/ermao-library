import pytest
from lxml import etree

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.infrastructure.selective_opf import patch_opf_metadata

SOURCE = b"""<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" unique-identifier="primary" version="3.0">
<metadata><dc:identifier id="primary">stable-id</dc:identifier><dc:title id="title">Old</dc:title><dc:title xml:lang="fr">French</dc:title>
<dc:creator id="author">Old author</dc:creator><meta refines="#author" property="role">aut</meta><dc:creator id="artist">Artist</dc:creator><meta refines="#artist" property="role">ill</meta>
<dc:description>Original description</dc:description><meta property="custom">Keep</meta><!-- retained comment --></metadata>
<manifest><item id="chapter" href="text/chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>"""
NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


def test_selected_title_and_authors_preserve_other_metadata_and_structure():
    changed = patch_opf_metadata(
        SOURCE,
        PublicationMetadata(title="New", authors=("New author",)),
        frozenset({"title", "authors"}),
    )
    root = etree.fromstring(changed)
    old = etree.fromstring(SOURCE)
    assert root.xpath("//dc:title/text()", namespaces=NS) == ["New", "French"]
    assert root.xpath("//dc:creator/text()", namespaces=NS) == ["New author", "Artist"]
    assert root.xpath("//dc:identifier/text()", namespaces=NS) == ["stable-id"]
    assert root.xpath("//dc:description/text()", namespaces=NS) == [
        "Original description"
    ]
    assert root.xpath("//opf:meta[@property='custom']/text()", namespaces=NS) == [
        "Keep"
    ]
    assert b"retained comment" in changed
    for name in ("manifest", "spine"):
        assert etree.tostring(root.find("opf:" + name, NS)) == etree.tostring(
            old.find("opf:" + name, NS)
        )


def test_explicit_clear_does_not_remove_other_fields():
    root = etree.fromstring(
        patch_opf_metadata(SOURCE, PublicationMetadata(), frozenset({"description"}))
    )
    assert root.xpath("//dc:description", namespaces=NS) == []
    assert root.xpath("//dc:title/text()", namespaces=NS) == ["Old", "French"]
    with pytest.raises(StandardMetadataError, match="PRIMARY_IDENTIFIER_REQUIRED"):
        patch_opf_metadata(SOURCE, PublicationMetadata(), frozenset({"identifier"}))


@pytest.mark.parametrize(
    "content", [b"broken", b"<!DOCTYPE package><package/>", b"<package/>"]
)
def test_malformed_metadata_cannot_be_replaced_as_empty(content):
    with pytest.raises(StandardMetadataError, match="INVALID_OPF"):
        patch_opf_metadata(
            content, PublicationMetadata(title="New"), frozenset({"title"})
        )
