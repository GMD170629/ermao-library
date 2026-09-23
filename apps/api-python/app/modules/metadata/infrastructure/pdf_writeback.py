"""Incremental PDF Info/XMP updates with an explicit unchanged-object boundary."""

from io import BytesIO
from typing import IO, Any, BinaryIO

from lxml import etree  # type: ignore[import-untyped]
from pypdf import PdfWriter
from pypdf.generic import (
    DictionaryObject,
    NameObject,
    StreamObject,
    TextStringObject,
)

from app.contracts.publication_metadata import PublicationMetadata
from app.infrastructure.pdf_embedded_metadata import (
    XMP_BYTES_LIMIT,
    PdfXmpDecodeError,
    decode_pdf_xmp_stream,
    read_pdf_embedded_metadata,
)
from app.infrastructure.pdf_metadata_reader import StrictMetadataPdfReader
from app.modules.metadata.application.standard_files import StandardMetadataError

PDF_WRITABLE_FIELDS = frozenset({"title", "authors", "description"})
PDF_WRITE_BYTES_LIMIT = 64 * 1024**2
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC = "http://purl.org/dc/elements/1.1/"
_XML = "http://www.w3.org/XML/1998/namespace"
_FIELDS = {"title": "/Title", "authors": "/Author", "description": "/Subject"}


def _xmp_bytes(value: object) -> bytes | None:
    try:
        return decode_pdf_xmp_stream(value)
    except PdfXmpDecodeError as error:
        raise StandardMetadataError(error.code) from error


def patch_xmp(
    content: bytes | None, values: PublicationMetadata, fields: frozenset[str]
) -> bytes:
    if content is None:
        root = etree.Element("{adobe:ns:meta/}xmpmeta", nsmap={"x": "adobe:ns:meta/"})
        rdf = etree.SubElement(root, f"{{{_RDF}}}RDF", nsmap={"rdf": _RDF})
    else:
        if (
            len(content) > XMP_BYTES_LIMIT
            or b"<!DOCTYPE" in content.upper()
            or b"<!ENTITY" in content.upper()
        ):
            raise StandardMetadataError("INVALID_XMP")
        root = etree.fromstring(
            content,
            etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
        )
        rdf = root if root.tag == f"{{{_RDF}}}RDF" else root.find(f"{{{_RDF}}}RDF")
        if rdf is None:
            raise StandardMetadataError("INVALID_XMP")
    descriptions = list(rdf.findall(f"{{{_RDF}}}Description"))
    if not descriptions:
        descriptions = [
            etree.SubElement(rdf, f"{{{_RDF}}}Description", {f"{{{_RDF}}}about": ""})
        ]
    names = {"title": "title", "authors": "creator", "description": "description"}
    for field in fields:
        name = f"{{{_DC}}}{names[field]}"
        nodes = []
        for description in descriptions:
            description.attrib.pop(name, None)
            nodes.extend(description.findall(name))
        value = getattr(values, field)
        for node in nodes:
            node.getparent().remove(node)
        if value:
            node = etree.SubElement(descriptions[0], name, nsmap={"dc": _DC})
            collection = etree.SubElement(
                node, f"{{{_RDF}}}{'Seq' if field == 'authors' else 'Alt'}"
            )
            for text in value if field == "authors" else (value,):
                item = etree.SubElement(collection, f"{{{_RDF}}}li")
                if field != "authors":
                    item.set(f"{{{_XML}}}lang", "x-default")
                item.text = text
    result = etree.tostring(root.getroottree(), encoding="utf-8")
    if len(result) > XMP_BYTES_LIMIT:
        raise StandardMetadataError("XMP_TOO_LARGE")
    return result


class _StreamingIncrementalWriter(PdfWriter):
    """pypdf 6.14.2's incremental writer with a bounded original-file copy."""

    def write_stream(self, stream: IO[Any]) -> None:
        self._resolve_links()
        self._reader.stream.seek(0)
        while chunk := self._reader.stream.read(1024**2):
            stream.write(chunk)
        if self.list_objects_in_increment():
            self._write_increment(stream)


def _load(
    source: BinaryIO,
) -> tuple[StrictMetadataPdfReader, _StreamingIncrementalWriter]:
    size = source.seek(0, 2)
    if size > PDF_WRITE_BYTES_LIMIT:
        raise StandardMetadataError("PDF_WRITE_SIZE_LIMIT")
    source.seek(0)
    reader = StrictMetadataPdfReader(source, strict=True, root_object_recovery_limit=0)
    if reader.is_encrypted:
        raise StandardMetadataError("ENCRYPTED_FILE")
    writer = _StreamingIncrementalWriter(
        reader,
        incremental=True,
        strict=True,
        incremental_clone_object_count_limit=50_000,
        incremental_clone_object_id_limit=100_000,
    )
    for dictionary in (writer.root_object, writer._info):
        if dictionary is not None:
            encoded = BytesIO()
            dictionary.write_to_stream(encoded)
            if encoded.tell() > XMP_BYTES_LIMIT:
                raise StandardMetadataError("PDF_METADATA_STRUCTURE_LIMIT")
    for item in writer._objects:
        if isinstance(item, DictionaryObject) and (
            item.get("/Type") == "/Sig"
            or item.get("/FT") == "/Sig"
            or "/ByteRange" in item
        ):
            raise StandardMetadataError("SIGNED_PDF")
    if "/Perms" in writer.root_object:
        raise StandardMetadataError("SIGNED_PDF")
    if writer.list_objects_in_increment():
        raise StandardMetadataError("UNSUPPORTED_PDF_STRUCTURE")
    return reader, writer


def inspect_pdf_write(
    source: BinaryIO, values: PublicationMetadata, fields: frozenset[str]
) -> PublicationMetadata:
    if not fields or not fields <= PDF_WRITABLE_FIELDS:
        raise StandardMetadataError("UNSUPPORTED_METADATA_FIELD")
    reader, writer = _load(source)
    patch_xmp(_xmp_bytes(writer.root_object.get("/Metadata")), values, fields)
    return read_pdf_embedded_metadata(reader)


def write_pdf_metadata(
    source: BinaryIO,
    output: BinaryIO,
    *,
    values: PublicationMetadata,
    fields: frozenset[str],
) -> None:
    if not fields or not fields <= PDF_WRITABLE_FIELDS:
        raise StandardMetadataError("UNSUPPORTED_METADATA_FIELD")
    reader, writer = _load(source)
    info = dict(reader.metadata or {})
    for field in fields:
        value = getattr(values, field)
        key = _FIELDS[field]
        if value:
            info[key] = TextStringObject(
                " / ".join(value) if field == "authors" else value
            )
        else:
            info.pop(key, None)
    writer.metadata = info
    writer.xmp_metadata = patch_xmp(
        _xmp_bytes(writer.root_object.get("/Metadata")), values, fields
    )
    xmp = writer.root_object["/Metadata"]
    if not isinstance(xmp, StreamObject):
        raise StandardMetadataError("INVALID_XMP")
    xmp[NameObject("/Type")] = NameObject("/Metadata")
    xmp[NameObject("/Subtype")] = NameObject("/XML")
    references = [writer.root_object.indirect_reference, xmp.indirect_reference]
    if writer._info is not None:
        references.append(writer._info.indirect_reference)
    if any(reference is None for reference in references):
        raise StandardMetadataError("UNSUPPORTED_PDF_STRUCTURE")
    allowed = {reference.idnum for reference in references if reference is not None}
    if any(
        reference.idnum not in allowed
        for reference in writer.list_objects_in_increment()
    ):
        raise StandardMetadataError("PDF_CONTENT_CHANGED")
    output.seek(0)
    output.truncate()
    writer.write_stream(output)
    output.flush()
    # The full original revision is retained; only the allowlisted objects can be revised.
    source.seek(0)
    output.seek(0)
    while original := source.read(1024**2):
        if output.read(len(original)) != original:
            raise StandardMetadataError("PDF_CONTENT_CHANGED")
    verified = StrictMetadataPdfReader(
        output, strict=True, root_object_recovery_limit=0
    )
    expected_info = writer.metadata
    if dict(verified.metadata or {}) != dict(expected_info or {}):
        raise StandardMetadataError("METADATA_VERIFICATION_FAILED")
    if _xmp_bytes(verified.root_object.get("/Metadata")) != _xmp_bytes(
        writer.root_object.get("/Metadata")
    ):
        raise StandardMetadataError("METADATA_VERIFICATION_FAILED")
