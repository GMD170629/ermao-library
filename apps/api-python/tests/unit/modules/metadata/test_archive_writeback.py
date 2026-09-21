from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from lxml import etree

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.opf import parse_opf_metadata
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.infrastructure.archive_writeback import write_archive_metadata
from tests.unit.modules.metadata.test_selective_opf import SOURCE


def epub(version="3.0", extra=None):
    stream = BytesIO()
    opf = SOURCE.replace(b'version="3.0"', f'version="{version}"'.encode()).replace(
        b"<metadata>", b"<metadata><dc:language>en</dc:language>"
    )
    with ZipFile(stream, "w") as archive:
        archive.comment = b"original archive comment"
        archive.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            b'<container><rootfiles><rootfile full-path="content/package.opf"/></rootfiles></container>',
        )
        archive.writestr("content/package.opf", opf, compress_type=ZIP_DEFLATED)
        archive.writestr(
            "content/text/chapter.xhtml",
            b"<html><body>Original chapter</body></html>",
            compress_type=ZIP_DEFLATED,
        )
        archive.writestr(
            "content/style.css", b"body {color: black}", compress_type=ZIP_STORED
        )
        if extra:
            archive.writestr(extra, b"signed or encrypted")
    return stream.getvalue()


@pytest.mark.parametrize("version", ["2.0", "3.0"])
def test_epub_preserves_members_order_content_and_unselected_metadata(version):
    original = epub(version)
    source, target = BytesIO(original), BytesIO()
    proof = write_archive_metadata(
        source,
        target,
        format="EPUB",
        values=PublicationMetadata(title="New title", authors=("New author",)),
        fields=frozenset({"title", "authors"}),
    )
    assert source.getvalue() == original
    with ZipFile(BytesIO(original)) as before, ZipFile(target) as after:
        assert before.namelist() == after.namelist()
        assert before.comment == after.comment
        for name in before.namelist():
            assert (
                before.getinfo(name).compress_type == after.getinfo(name).compress_type
            )
            if name != proof.metadata_member:
                assert before.read(name) == after.read(name)
        metadata = parse_opf_metadata(after.read(proof.metadata_member))
        assert metadata.title == "New title"
        assert metadata.authors == ("New author",)
        assert metadata.identifier == "stable-id"
        assert metadata.description == "Original description"
        root = etree.fromstring(after.read(proof.metadata_member))
        assert root.get("version") == version
        assert b"Artist" in after.read(proof.metadata_member)


@pytest.mark.parametrize(
    "extra", ["META-INF/signatures.xml", "META-INF/encryption.xml"]
)
def test_signed_or_encrypted_epub_is_rejected_before_output(extra):
    source, target = BytesIO(epub(extra=extra)), BytesIO()
    original = source.getvalue()
    with pytest.raises(StandardMetadataError, match="SIGNED_OR_ENCRYPTED"):
        write_archive_metadata(
            source,
            target,
            format="EPUB",
            values=PublicationMetadata(title="New"),
            fields=frozenset({"title"}),
        )
    assert source.getvalue() == original
    assert target.getvalue() == b""


def test_cbz_preserves_page_order_and_comicinfo_page_mapping():
    source = BytesIO()
    comic = b'<ComicInfo><Title>Old</Title><Writer>Original writer</Writer><Pages><Page Image="1" Type="FrontCover"/><Page Image="0"/></Pages><Custom>Keep</Custom></ComicInfo>'
    with ZipFile(source, "w") as archive:
        archive.writestr("02.jpg", b"page two")
        archive.writestr("01.jpg", b"page one")
        archive.writestr("ComicInfo.xml", comic)
    original = source.getvalue()
    target = BytesIO()
    write_archive_metadata(
        source,
        target,
        format="CBZ",
        values=PublicationMetadata(title="New comic"),
        fields=frozenset({"title"}),
    )
    with ZipFile(target) as archive:
        assert archive.namelist() == ["02.jpg", "01.jpg", "ComicInfo.xml"]
        assert archive.read("02.jpg") == b"page two"
        root = etree.fromstring(archive.read("ComicInfo.xml"))
        assert root.findtext("Title") == "New comic"
        assert root.findtext("Writer") == "Original writer"
        assert root.findtext("Custom") == "Keep"
        assert etree.tostring(root.find("Pages")) == etree.tostring(
            etree.fromstring(comic).find("Pages")
        )
    assert source.getvalue() == original


def test_source_cannot_be_used_as_preparation():
    source = BytesIO(epub())
    original = source.getvalue()
    with pytest.raises(StandardMetadataError, match="SEPARATE_PREPARATION_REQUIRED"):
        write_archive_metadata(
            source,
            source,
            format="EPUB",
            values=PublicationMetadata(title="New"),
            fields=frozenset({"title"}),
        )
    assert source.getvalue() == original
