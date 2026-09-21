"""Edit named ComicInfo fields without changing page order or unknown extensions."""

from lxml import etree  # type: ignore[import-untyped]

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.opf import MAX_OPF_BYTES
from app.modules.metadata.application.standard_files import StandardMetadataError

COMIC_FIELDS = {
    "title": "Title",
    "authors": "Writer",
    "description": "Summary",
    "subjects": "Tags",
    "series_name": "Series",
    "series_index": "Number",
    "volume_index": "Volume",
    "language": "LanguageISO",
    "publisher": "Publisher",
    "isbn": "GTIN",
    "published_at": "Year",
}
COMIC_WRITABLE_FIELDS = frozenset(COMIC_FIELDS)


def patch_comicinfo(
    content: bytes | None, values: PublicationMetadata, fields: frozenset[str]
) -> bytes:
    if not fields or not fields <= COMIC_WRITABLE_FIELDS:
        raise StandardMetadataError("UNSUPPORTED_METADATA_FIELD")
    if content is None:
        root = etree.Element("ComicInfo")
    else:
        if (
            len(content) > MAX_OPF_BYTES
            or b"<!DOCTYPE" in content.upper()
            or b"<!ENTITY" in content.upper()
        ):
            raise StandardMetadataError("INVALID_COMICINFO")
        try:
            root = etree.fromstring(
                content,
                etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    recover=False,
                    huge_tree=False,
                ),
            )
        except etree.XMLSyntaxError as error:
            raise StandardMetadataError("INVALID_COMICINFO") from error
        if root.tag != "ComicInfo":
            raise StandardMetadataError("INVALID_COMICINFO")
    for field in sorted(fields):
        value = getattr(values, field)
        updates: dict[str, str | None]
        if field == "published_at":
            date = str(value).split("T")[0].split("-") if value else []
            updates = {
                name: date[index] if index < len(date) else None
                for index, name in enumerate(("Year", "Month", "Day"))
            }
        else:
            text = (
                ", ".join(value)
                if isinstance(value, tuple)
                else str(value)
                if value is not None
                else None
            )
            updates = {COMIC_FIELDS[field]: text or None}
        for name, text in updates.items():
            existing = list(root.findall(name))
            for node in existing[1:]:
                root.remove(node)
            if text is None:
                if existing:
                    root.remove(existing[0])
            elif existing:
                existing[0].text = text
            else:
                etree.SubElement(root, name).text = text
    result = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    if len(result) > MAX_OPF_BYTES:
        raise StandardMetadataError("METADATA_TOO_LARGE")
    return result
