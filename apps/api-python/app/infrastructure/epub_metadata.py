"""Bounded EPUB package metadata access shared by import and standard writers."""

from zipfile import ZipFile

from lxml import etree  # type: ignore[import-untyped]

from app.modules.metadata.public import MAX_OPF_BYTES


def read_zip_metadata(archive: ZipFile, name: str) -> bytes:
    if archive.getinfo(name).file_size > MAX_OPF_BYTES:
        raise ValueError("metadata inspection limit")
    with archive.open(name) as source:
        content = source.read(MAX_OPF_BYTES + 1)
    if len(content) > MAX_OPF_BYTES:
        raise ValueError("metadata inspection limit")
    return content


def read_epub_package(archive: ZipFile) -> tuple[str, bytes]:
    container = read_zip_metadata(archive, "META-INF/container.xml")
    if b"<!DOCTYPE" in container.upper() or b"<!ENTITY" in container.upper():
        raise ValueError("unsafe container XML")
    root = etree.fromstring(
        container, parser=etree.XMLParser(resolve_entities=False, no_network=True)
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
