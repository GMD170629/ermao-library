"""Selective EPUB package metadata access shared by import and standard writers."""

from zipfile import ZipFile

from lxml import etree  # type: ignore[import-untyped]


def read_zip_metadata(archive: ZipFile, name: str) -> bytes:
    with archive.open(name) as source:
        return source.read()


def read_epub_package(archive: ZipFile) -> tuple[str, bytes]:
    container = read_zip_metadata(archive, "META-INF/container.xml")
    if b"<!DOCTYPE" in container.upper() or b"<!ENTITY" in container.upper():
        raise ValueError("unsafe container XML")
    root = etree.fromstring(
        container, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    )
    rootfiles = root.xpath("//*[local-name()='rootfile']/@full-path")
    if len(rootfiles) != 1:
        raise ValueError("ambiguous EPUB rootfile")
    name = str(rootfiles[0])
    if (
        name.startswith("/")
        or "\\" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("unsafe EPUB rootfile")
    return name, read_zip_metadata(archive, name)
