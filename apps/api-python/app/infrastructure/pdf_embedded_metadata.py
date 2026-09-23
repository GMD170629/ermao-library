"""Bounded, read-only PDF Info/XMP projection shared by file readers."""

from __future__ import annotations

import logging
import re
import zlib
from collections.abc import Iterable

from lxml import etree  # type: ignore[import-untyped]
from pypdf.errors import PdfReadError
from pypdf.generic import IndirectObject, StreamObject

from app.contracts.publication_metadata import PublicationMetadata
from app.core.exception_diagnostics import record_exception
from app.core.publication_date import validated_publication_date
from app.infrastructure.pdf_metadata_reader import StrictMetadataPdfReader

XMP_BYTES_LIMIT = 2 * 1024**2
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC = "http://purl.org/dc/elements/1.1/"
_PDF = "http://ns.adobe.com/pdf/1.3/"
_XML = "http://www.w3.org/XML/1998/namespace"
_EMPTY_TITLES = {"cover", "frontcover", "title", "untitled", "封面", "封皮"}
_LOGGER = logging.getLogger(__name__)


class PdfXmpDecodeError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _clean(value: object, *, limit: int = 8_000) -> str | None:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned[:limit] or None


def _title(value: object) -> str | None:
    title = _clean(value)
    if title and re.sub(r"[\s._-]+", "", title).casefold() in _EMPTY_TITLES:
        return None
    return title


def _subjects(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        subject
        for value in values
        for item in re.split(r"[,，;/\\\-－–]", value)
        if (subject := _clean(item))
    )


def _info_metadata(pdf: StrictMetadataPdfReader) -> PublicationMetadata:
    info = pdf.metadata
    if info is None:
        return PublicationMetadata()
    author = _clean(info.get("/Author"))
    keywords = _clean(info.get("/Keywords"))
    return PublicationMetadata(
        title=_title(info.get("/Title")),
        authors=(author,) if author else (),
        description=_clean(info.get("/Subject")),
        subjects=_subjects((keywords,)) if keywords else (),
    )


def decode_pdf_xmp_stream(value: object) -> bytes | None:
    """Decode a PDF catalog metadata stream within one encoded/decoded limit."""
    if value is None:
        return None
    if isinstance(value, IndirectObject):
        value = value.get_object()
    if not isinstance(value, StreamObject):
        raise PdfXmpDecodeError("INVALID_XMP")
    raw = value._data
    if len(raw) > XMP_BYTES_LIMIT:
        raise PdfXmpDecodeError("XMP_TOO_LARGE")
    filters = value.get("/Filter")
    if filters is None:
        return raw
    if filters not in ("/FlateDecode", ["/FlateDecode"]) or value.get("/DecodeParms"):
        raise PdfXmpDecodeError("UNSUPPORTED_XMP_ENCODING")
    decoder = zlib.decompressobj()
    try:
        content = decoder.decompress(raw, XMP_BYTES_LIMIT + 1)
    except zlib.error as error:
        raise PdfXmpDecodeError("INVALID_XMP") from error
    if (
        len(content) > XMP_BYTES_LIMIT
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise PdfXmpDecodeError("INVALID_XMP")
    return content


def _values(
    descriptions: list[etree._Element], namespace: str, name: str
) -> list[tuple[str | None, str]]:
    result: list[tuple[str | None, str]] = []
    tag = f"{{{namespace}}}{name}"
    for description in descriptions:
        attribute = _clean(description.get(tag))
        if attribute:
            result.append((None, attribute))
        for node in description.findall(tag):
            items = node.findall(f".//{{{_RDF}}}li")
            if items:
                for item in items:
                    value = _clean("".join(item.itertext()))
                    if value:
                        result.append((item.get(f"{{{_XML}}}lang"), value))
            else:
                value = _clean("".join(node.itertext()))
                if value:
                    result.append((node.get(f"{{{_XML}}}lang"), value))
    return result


def _preferred(values: list[tuple[str | None, str]]) -> str | None:
    return next(
        (value for language, value in values if language == "x-default"), None
    ) or (values[0][1] if values else None)


def _xmp_metadata(content: bytes) -> PublicationMetadata:
    if (
        len(content) > XMP_BYTES_LIMIT
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("invalid PDF XMP document")
    root = etree.fromstring(
        content,
        parser=etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            recover=False,
            huge_tree=False,
        ),
    )
    rdf = root if root.tag == f"{{{_RDF}}}RDF" else root.find(f".//{{{_RDF}}}RDF")
    if rdf is None:
        raise ValueError("PDF XMP RDF missing")
    descriptions = list(rdf.findall(f"{{{_RDF}}}Description"))

    def dc(name: str) -> list[tuple[str | None, str]]:
        return _values(descriptions, _DC, name)

    creators = tuple(value for _, value in dc("creator"))
    if not creators:
        creators = tuple(value for _, value in _values(descriptions, _PDF, "Author"))
    identifiers = [value for _, value in dc("identifier")]
    isbn = next(
        (
            value.split(":", 2)[-1].strip()
            for value in identifiers
            if re.match(r"(?i)^(?:urn:isbn:|isbn:)", value)
        ),
        None,
    )
    return PublicationMetadata(
        title=_title(_preferred(dc("title"))),
        authors=creators,
        description=_preferred(dc("description")),
        subjects=_subjects(value for _, value in dc("subject")),
        language=_preferred(dc("language")),
        publisher=_preferred(dc("publisher")),
        published_at=next(
            (
                valid
                for _, value in dc("date")
                if (valid := validated_publication_date(_clean(value, limit=191)))
            ),
            None,
        ),
        identifier=identifiers[0] if identifiers else None,
        isbn=isbn,
    )


def read_pdf_embedded_metadata(pdf: StrictMetadataPdfReader) -> PublicationMetadata:
    """Use each valid XMP field, falling back to its Info counterpart."""
    info = _info_metadata(pdf)
    try:
        content = decode_pdf_xmp_stream(pdf.root_object.get("/Metadata"))
        if content is None:
            return info
        xmp = _xmp_metadata(content)
    except (
        ValueError,
        TypeError,
        KeyError,
        PdfReadError,
        etree.XMLSyntaxError,
    ) as error:
        record_exception(
            _LOGGER,
            "infrastructure.pdf_embedded_metadata.xmp_unavailable",
            error,
            context={"step": "read_xmp"},
        )
        return info
    return PublicationMetadata(
        title=xmp.title or info.title,
        authors=xmp.authors or info.authors,
        description=xmp.description or info.description,
        subjects=xmp.subjects or info.subjects,
        language=xmp.language,
        publisher=xmp.publisher,
        published_at=xmp.published_at,
        identifier=xmp.identifier,
        isbn=xmp.isbn,
    )
