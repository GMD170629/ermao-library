"""Selective OPF edits preserve package structure and unrelated metadata."""

from lxml import etree  # type: ignore[import-untyped]

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.opf import (
    DC_NAMESPACE,
    MAX_OPF_BYTES,
    OPF_NAMESPACE,
    opf_role_refinements,
)
from app.modules.metadata.application.standard_files import StandardMetadataError

OPF_WRITABLE_FIELDS = frozenset(
    {
        "title",
        "authors",
        "description",
        "subjects",
        "language",
        "publisher",
        "published_at",
        "identifier",
        "isbn",
        "narrators",
        "abridged",
        "series_name",
        "series_index",
        "volume_index",
    }
)
_DC_FIELDS = {
    "title": "title",
    "authors": "creator",
    "description": "description",
    "subjects": "subject",
    "language": "language",
    "publisher": "publisher",
    "published_at": "date",
}
_META_FIELDS = {
    "series_name": "calibre:series",
    "series_index": "shuku:series_index",
    "volume_index": "calibre:series_index",
    "abridged": "shuku:abridged",
}


def parse_editable_opf(content: bytes | None) -> tuple[etree._Element, etree._Element]:
    if content is None:
        package = etree.Element(
            f"{{{OPF_NAMESPACE}}}package",
            nsmap={None: OPF_NAMESPACE, "dc": DC_NAMESPACE},
            version="3.0",
        )
        return package, etree.SubElement(package, f"{{{OPF_NAMESPACE}}}metadata")
    if (
        len(content) > MAX_OPF_BYTES
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise StandardMetadataError("INVALID_OPF")
    try:
        package = etree.fromstring(
            content,
            etree.XMLParser(
                resolve_entities=False, no_network=True, recover=False, huge_tree=False
            ),
        )
    except etree.XMLSyntaxError as error:
        raise StandardMetadataError("INVALID_OPF") from error
    if etree.QName(package).localname not in {"package", "metadata"}:
        raise StandardMetadataError("INVALID_OPF")
    if etree.QName(package).localname == "metadata":
        return package, package
    metadata = [
        node
        for node in package
        if isinstance(node.tag, str) and etree.QName(node).localname == "metadata"
    ]
    if len(metadata) != 1:
        raise StandardMetadataError("INVALID_OPF")
    return package, metadata[0]


def patch_opf_metadata(
    content: bytes | None, values: PublicationMetadata, fields: frozenset[str]
) -> bytes:
    if not fields or not fields <= OPF_WRITABLE_FIELDS:
        raise StandardMetadataError("UNSUPPORTED_METADATA_FIELD")
    package, metadata = parse_editable_opf(content)

    def nodes(name: str) -> list[etree._Element]:
        return [
            node
            for node in metadata
            if isinstance(node.tag, str) and node.tag == f"{{{DC_NAMESPACE}}}{name}"
        ]

    refinements = opf_role_refinements(metadata)

    def role(node: etree._Element) -> str:
        return str(
            node.get(f"{{{OPF_NAMESPACE}}}role")
            or node.get("role")
            or refinements.get(str(node.get("id")), "")
        ).casefold()

    def replace_nodes(
        existing: list[etree._Element],
        name: str,
        replacements: tuple[str, ...],
        *,
        contributor_role: str | None = None,
    ) -> None:
        removed_ids: set[str] = set()
        for index, node in enumerate(existing):
            if index < len(replacements):
                node.text = replacements[index]
                node.attrib.pop(f"{{{OPF_NAMESPACE}}}file-as", None)
            else:
                if node.get("id"):
                    removed_ids.add(str(node.get("id")))
                metadata.remove(node)
        for value in replacements[len(existing) :]:
            node = etree.SubElement(metadata, f"{{{DC_NAMESPACE}}}{name}")
            node.text = value
            if contributor_role:
                node.set(f"{{{OPF_NAMESPACE}}}role", contributor_role)
        for item in list(metadata):
            if (
                isinstance(item.tag, str)
                and str(item.get("refines") or "").removeprefix("#") in removed_ids
            ):
                metadata.remove(item)

    for field in sorted(fields):
        value = getattr(values, field)
        if field in _DC_FIELDS:
            name = _DC_FIELDS[field]
            existing = nodes(name)
            if field == "title":
                existing = existing[:1]
            if field == "authors":
                existing = [
                    node for node in existing if role(node) in {"", "aut", "author"}
                ]
            replacements = (
                value
                if isinstance(value, tuple)
                else (() if value is None else (str(value),))
            )
            replace_nodes(existing, name, replacements)
        elif field == "narrators":
            replace_nodes(
                [
                    node
                    for node in nodes("contributor")
                    if role(node) in {"nrt", "narrator"}
                ],
                "contributor",
                values.narrators,
                contributor_role="nrt",
            )
        elif field in {"isbn", "identifier"}:
            existing = nodes("identifier")

            def is_isbn(node: etree._Element) -> bool:
                return str(
                    node.get(f"{{{OPF_NAMESPACE}}}scheme") or ""
                ).casefold() == "isbn" or str(node.text or "").casefold().startswith(
                    "urn:isbn:"
                )

            selected = [node for node in existing if is_isbn(node) == (field == "isbn")]
            if field == "identifier":
                primary = next(
                    (
                        node
                        for node in selected
                        if node.get("id") == package.get("unique-identifier")
                    ),
                    None,
                )
                selected = [primary] if primary is not None else selected[:1]
            if value is None and any(
                node.get("id") == package.get("unique-identifier") for node in selected
            ):
                raise StandardMetadataError("PRIMARY_IDENTIFIER_REQUIRED")
            replacement = (
                ()
                if value is None
                else (("urn:isbn:" + str(value)) if field == "isbn" else str(value),)
            )
            replace_nodes(selected, "identifier", replacement)
        else:
            name = _META_FIELDS[field]
            existing = [
                node
                for node in metadata
                if isinstance(node.tag, str)
                and etree.QName(node).localname == "meta"
                and node.get("name") == name
            ]
            for node in existing:
                metadata.remove(node)
            if value is not None:
                node = etree.SubElement(metadata, f"{{{OPF_NAMESPACE}}}meta", name=name)
                node.set(
                    "content",
                    ("true" if value else "false")
                    if isinstance(value, bool)
                    else str(value),
                )
            if field in {"series_name", "volume_index"}:
                property_name = (
                    "belongs-to-collection"
                    if field == "series_name"
                    else "group-position"
                )
                for node in metadata:
                    if (
                        isinstance(node.tag, str)
                        and node.get("property") == property_name
                    ):
                        if value is None:
                            metadata.remove(node)
                        else:
                            node.text = str(value)
                        break
    result = etree.tostring(package, xml_declaration=True, encoding="utf-8")
    if len(result) > MAX_OPF_BYTES:
        raise StandardMetadataError("METADATA_TOO_LARGE")
    return result
