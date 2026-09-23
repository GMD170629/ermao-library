from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.infrastructure.pdf_writeback import (
    inspect_pdf_write,
    write_pdf_metadata,
)


def source_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    writer.add_outline_item("Opening", 0)
    writer.add_attachment("original.txt", b"attachment bytes")
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("reader-note"),
            NameObject("/V"): TextStringObject("keep this"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(n) for n in (0, 0, 100, 20)]
            ),
        }
    )
    reference = writer._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([reference])
    writer.root_object[NameObject("/AcroForm")] = writer._add_object(
        DictionaryObject({NameObject("/Fields"): ArrayObject([reference])})
    )
    writer.add_metadata(
        {"/Title": "Original", "/Author": "Before", "/Custom": "keep custom"}
    )
    writer.xmp_metadata = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:c="urn:custom" c:value="preserve"/></rdf:RDF></x:xmpmeta>'
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def test_pdf_increment_preserves_objects_and_syncs_info_xmp():
    original = source_pdf()
    output = BytesIO()
    write_pdf_metadata(
        BytesIO(original),
        output,
        values=PublicationMetadata(title="新标题", authors=("作者甲", "作者乙")),
        fields=frozenset({"title", "authors"}),
    )
    assert output.getvalue().startswith(original)
    before, after = PdfReader(BytesIO(original)), PdfReader(output)
    assert after.metadata.title == "新标题"
    assert after.metadata.author == "作者甲 / 作者乙"
    assert after.metadata["/Custom"] == "keep custom"
    assert after.xmp_metadata.dc_title == {"x-default": "新标题"}
    assert after.xmp_metadata.dc_creator == ["作者甲", "作者乙"]
    assert dict(after.attachments) == dict(before.attachments)
    assert after.get_fields()["reader-note"]["/V"] == "keep this"
    assert after.outline[0].title == before.outline[0].title
    assert after.pages[0].mediabox == before.pages[0].mediabox
    assert b"preserve" in after.xmp_metadata.stream.get_data()


def test_pdf_write_preview_uses_merged_xmp_value():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.add_metadata({"/Title": "Info 标题", "/Subject": "Info 简介"})
    writer.xmp_metadata = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<rdf:RDF><rdf:Description rdf:about="">'
        '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">XMP 标题'
        '</rdf:li></rdf:Alt></dc:title>'
        '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">XMP 简介'
        '</rdf:li></rdf:Alt></dc:description>'
        '</rdf:Description></rdf:RDF></x:xmpmeta>'
    ).encode()
    original = BytesIO()
    writer.write(original)
    source = BytesIO(original.getvalue())

    before = inspect_pdf_write(
        source, PublicationMetadata(title="之后"), frozenset({"title"})
    )

    assert before.title == "XMP 标题"
    assert before.description == "XMP 简介"
    assert source.getvalue() == original.getvalue()


@pytest.mark.parametrize("encrypted", [False, True])
def test_signed_or_encrypted_pdf_is_rejected_before_output(encrypted):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    if encrypted:
        writer.encrypt("password")
    else:
        writer.root_object[NameObject("/AcroForm")] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Fields"): ArrayObject(
                        [
                            writer._add_object(
                                DictionaryObject(
                                    {
                                        NameObject("/FT"): NameObject("/Sig"),
                                        NameObject("/T"): TextStringObject("Signature"),
                                    }
                                )
                            )
                        ]
                    )
                }
            )
        )
    source = BytesIO()
    writer.write(source)
    output = BytesIO()
    with pytest.raises(StandardMetadataError, match="ENCRYPTED_FILE|SIGNED_PDF"):
        write_pdf_metadata(
            source,
            output,
            values=PublicationMetadata(title="New"),
            fields=frozenset({"title"}),
        )
    assert output.getvalue() == b""


def test_pdf_publication_preserves_original_backup(tmp_path):
    from app.modules.library.infrastructure.source_file_access import (
        open_library_directory,
        open_library_file,
    )
    from app.modules.metadata.application.standard_writeback import StandardWriteFile
    from app.modules.metadata.infrastructure.standard_publication import (
        StandardMetadataPublication,
    )

    source = tmp_path / "book.pdf"
    original = source_pdf()
    source.write_bytes(original)
    publisher = StandardMetadataPublication(open_library_directory, open_library_file)
    values = PublicationMetadata(title="Published")
    fields = frozenset({"title"})
    inspected = publisher.inspect(tmp_path, "book.pdf", "PDF", values, fields)
    request = StandardWriteFile(
        "library",
        tmp_path,
        "book.pdf",
        inspected.parent_device,
        inspected.parent_inode,
        "PDF",
        inspected.original,
        values,
        fields,
        ".ermao-mcp-" + "a" * 32 + "-target",
        ".ermao-mcp-" + "a" * 32 + "-source",
    )
    prepared = publisher.prepare(request)
    assert source.read_bytes() == original
    publisher.publish(request, prepared)
    assert PdfReader(source).metadata.title == "Published"
    assert (tmp_path / request.backup_name).read_bytes() == original
