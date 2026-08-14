"""Safe zero-copy EPUB to Readium Web Publication adapter."""

from __future__ import annotations

import mimetypes
import posixpath
import re
import stat
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationFingerprint,
    PublicationLink,
    PublicationMarkupError,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationSecurityError,
    PublicationStructureError,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.locator_dom import parse_safe_markup_root
from app.modules.publications.infrastructure.source_files import (
    publication_sha256,
    resolve_publication_source,
)

EPUB_PARSER_IDENTIFIER = "epub-package:1"
EPUB_NORMALIZATION_IDENTIFIER = "shuku-epub-locator-dom-v2"
MAX_ARCHIVE_ENTRIES = 20_000
MAX_SINGLE_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000
_XML_NON_MARKUP = re.compile(
    rb"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>",
    re.DOTALL,
)
_XML_DOCTYPE_OPEN = re.compile(rb"<!DOCTYPE\b", re.IGNORECASE)
_XML_DOCTYPE = re.compile(rb"<!DOCTYPE\b[^>]*>", re.IGNORECASE | re.DOTALL)
_XML_ENTITY_OPEN = re.compile(rb"<!ENTITY\b", re.IGNORECASE)
_SAFE_NCX_DOCTYPE = re.compile(
    rb"""<!DOCTYPE\s+ncx\s+PUBLIC\s+
    (?P<public_quote>[\"'])-//NISO//DTD\s+ncx\s+2005-1//EN(?P=public_quote)\s+
    (?P<system_quote>[\"'])https?://www\.daisy\.org/z3986/2005/ncx-2005-1\.dtd
    (?P=system_quote)\s*>""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class _IndexedEpub:
    source_path: Path
    source_mtime: float
    original_file_hash: str
    publication: NormalizedPublication
    entries_by_href: dict[str, str]
    media_types_by_href: dict[str, str]


def _xml_root(content: bytes) -> ElementTree.Element:
    lexical = _XML_NON_MARKUP.sub(lambda match: b" " * len(match.group(0)), content)
    if _XML_ENTITY_OPEN.search(lexical):
        raise PublicationSecurityError("active XML declarations are not allowed")
    doctype_opens = list(_XML_DOCTYPE_OPEN.finditer(lexical))
    if doctype_opens:
        declarations = list(_XML_DOCTYPE.finditer(lexical))
        if (
            len(doctype_opens) != 1
            or len(declarations) != 1
            or declarations[0].start() != doctype_opens[0].start()
            or _SAFE_NCX_DOCTYPE.fullmatch(declarations[0].group(0)) is None
            or lexical[: declarations[0].start()].strip()
        ):
            raise PublicationSecurityError("active XML declarations are not allowed")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise PublicationMarkupError("publication XML is invalid") from error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _canonical_href(base: str, href: str) -> str:
    split = urlsplit(href)
    if split.scheme or split.netloc or split.query:
        raise PublicationSecurityError("publication href must be local")
    decoded = unquote(split.path)
    if "\\" in decoded or decoded.startswith("/"):
        raise PublicationSecurityError("publication href escapes its archive")
    joined = posixpath.normpath(posixpath.join(base, decoded))
    if joined in {"", ".", ".."} or joined.startswith("../"):
        raise PublicationSecurityError("publication href escapes its archive")
    encoded = quote(joined, safe="/!$&'()*+,-.:;=@_~")
    return encoded + (f"#{split.fragment}" if split.fragment else "")


def _entry_key(href: str) -> str:
    path = unquote(urlsplit(href).path)
    normalized = posixpath.normpath(path)
    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.startswith(("../", "/"))
        or "\\" in normalized
    ):
        raise PublicationResourceNotFoundError
    return normalized


def _validated_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise PublicationSecurityError("publication has too many resources")
    entries: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        try:
            key = _entry_key(info.filename)
        except PublicationResourceNotFoundError as error:
            raise PublicationSecurityError(
                "publication contains an unsafe resource path"
            ) from error
        if key in entries:
            raise PublicationStructureError(
                "publication contains duplicate resource paths"
            )
        unix_mode = info.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise PublicationSecurityError("linked resources are not allowed")
        if info.flag_bits & 0x1:
            raise PublicationUnsupportedError(
                "encrypted EPUB resources are unsupported"
            )
        if info.file_size > MAX_SINGLE_RESOURCE_BYTES:
            raise PublicationSecurityError(
                "publication resource exceeds the size limit"
            )
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise PublicationSecurityError(
                "publication exceeds the expanded size limit"
            )
        if info.compress_size == 0 and info.file_size > 0:
            raise PublicationSecurityError(
                "publication resource has an invalid compression ratio"
            )
        if (
            info.compress_size
            and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise PublicationSecurityError(
                "publication resource compression ratio is unsafe"
            )
        entries[key] = info
    return entries


def _container_opf_path(
    archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]
) -> str:
    container = entries.get("META-INF/container.xml")
    if container is None:
        raise PublicationStructureError("EPUB container is missing")
    try:
        root = _xml_root(archive.read(container))
    except PublicationMarkupError as error:
        raise PublicationStructureError("EPUB container is invalid") from error
    for element in root.iter():
        if _local_name(element.tag) == "rootfile":
            value = element.attrib.get("full-path", "")
            try:
                key = _entry_key(value)
            except PublicationResourceNotFoundError as error:
                raise PublicationSecurityError(
                    "EPUB package path escapes its archive"
                ) from error
            if key in entries:
                return key
    raise PublicationStructureError("EPUB package document is missing")


def _metadata_value(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == name and element.text and element.text.strip():
            return element.text.strip()
    return None


def _reading_progression(root: ElementTree.Element) -> str:
    for element in root.iter():
        if _local_name(element.tag) == "spine":
            return (
                "rtl"
                if element.attrib.get("page-progression-direction") == "rtl"
                else "ltr"
            )
    return "ltr"


def _toc_from_nav(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    nav_href: str | None,
) -> tuple[PublicationTocEntry, ...]:
    if nav_href is None:
        return ()
    nav_key = _entry_key(nav_href)
    nav_info = entries.get(nav_key)
    if nav_info is None:
        return ()
    _markup, root = parse_safe_markup_root(archive.read(nav_info))
    if _local_name(root.tag) != "html":
        return ()
    nav_base = posixpath.dirname(nav_key)

    def direct_children(
        element: ElementTree.Element, name: str
    ) -> list[ElementTree.Element]:
        return [child for child in element if _local_name(child.tag) == name]

    def list_entries(
        ordered_list: ElementTree.Element,
    ) -> tuple[PublicationTocEntry, ...]:
        results: list[PublicationTocEntry] = []
        for list_item in direct_children(ordered_list, "li"):
            nested_lists = direct_children(list_item, "ol")
            children = tuple(
                entry for nested in nested_lists for entry in list_entries(nested)
            )
            label_element = next(
                (
                    child
                    for child in list_item
                    if _local_name(child.tag) in {"a", "span"}
                ),
                None,
            )
            anchor = next(
                (
                    child
                    for child in list_item
                    if _local_name(child.tag) == "a" and child.attrib.get("href")
                ),
                None,
            )
            title = (
                " ".join("".join(label_element.itertext()).split())
                if label_element is not None
                else ""
            )
            href = ""
            if anchor is not None:
                try:
                    href = _canonical_href(nav_base, anchor.attrib["href"])
                except (PublicationCorruptError, PublicationResourceNotFoundError):
                    href = ""
            elif children:
                href = children[0].href
            if title and href:
                results.append(
                    PublicationTocEntry(
                        href=href,
                        title=title,
                        children=children,
                    )
                )
            elif children:
                results.extend(children)
        return tuple(results)

    for element in root.iter():
        if _local_name(element.tag) != "nav":
            continue
        nav_type = next(
            (
                value
                for key, value in element.attrib.items()
                if _local_name(key) == "type"
            ),
            "",
        )
        if nav_type != "toc":
            continue
        ordered_list = next(
            (
                child
                for child in element.iter()
                if child is not element and _local_name(child.tag) == "ol"
            ),
            None,
        )
        return list_entries(ordered_list) if ordered_list is not None else ()
    return ()


def _toc_from_ncx(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    ncx_href: str | None,
) -> tuple[PublicationTocEntry, ...]:
    if ncx_href is None:
        return ()
    ncx_key = _entry_key(ncx_href)
    ncx_info = entries.get(ncx_key)
    if ncx_info is None:
        return ()
    root = _xml_root(archive.read(ncx_info))
    ncx_base = posixpath.dirname(ncx_key)

    def nav_point(element: ElementTree.Element) -> PublicationTocEntry | None:
        children = tuple(
            entry
            for child in element
            if _local_name(child.tag) == "navPoint"
            for entry in [nav_point(child)]
            if entry is not None
        )
        label = next(
            (child for child in element if _local_name(child.tag) == "navLabel"),
            None,
        )
        content = next(
            (child for child in element if _local_name(child.tag) == "content"),
            None,
        )
        title = " ".join("".join(label.itertext()).split()) if label is not None else ""
        raw_href = content.attrib.get("src", "") if content is not None else ""
        href = ""
        if raw_href:
            try:
                href = _canonical_href(ncx_base, raw_href)
            except (PublicationCorruptError, PublicationResourceNotFoundError):
                href = ""
        elif children:
            href = children[0].href
        if not title or not href:
            return None
        return PublicationTocEntry(href=href, title=title, children=children)

    nav_map = next(
        (element for element in root.iter() if _local_name(element.tag) == "navMap"),
        None,
    )
    if nav_map is None:
        return ()
    return tuple(
        entry
        for child in nav_map
        if _local_name(child.tag) == "navPoint"
        for entry in [nav_point(child)]
        if entry is not None
    )


@lru_cache(maxsize=64)
def _index_epub(
    source_path_value: str,
    source_size: int,
    source_mtime_ns: int,
    known_hash: str | None,
    fallback_title: str,
    fallback_author: str | None,
) -> _IndexedEpub:
    del source_size, source_mtime_ns
    source_path = Path(source_path_value)
    try:
        with zipfile.ZipFile(source_path) as archive:
            entries = _validated_entries(archive)
            opf_path = _container_opf_path(archive, entries)
            try:
                opf_root = _xml_root(archive.read(entries[opf_path]))
            except PublicationMarkupError as error:
                raise PublicationStructureError(
                    "EPUB package document is invalid"
                ) from error
            opf_base = posixpath.dirname(opf_path)
            manifest_by_id: dict[str, tuple[str, str, str]] = {}
            nav_href: str | None = None
            ncx_hrefs_by_id: dict[str, str] = {}
            for element in opf_root.iter():
                if _local_name(element.tag) != "item":
                    continue
                item_id = element.attrib.get("id")
                raw_href = element.attrib.get("href")
                if not item_id or not raw_href:
                    continue
                href = _canonical_href(opf_base, raw_href)
                key = _entry_key(href)
                if key not in entries:
                    continue
                media_type = (
                    element.attrib.get("media-type")
                    or mimetypes.guess_type(key)[0]
                    or "application/octet-stream"
                )
                manifest_by_id[item_id] = (
                    href,
                    media_type,
                    element.attrib.get("properties", ""),
                )
                if "nav" in element.attrib.get("properties", "").split():
                    nav_href = href
                if media_type == "application/x-dtbncx+xml":
                    ncx_hrefs_by_id[item_id] = href
            spine = next(
                (
                    element
                    for element in opf_root.iter()
                    if _local_name(element.tag) == "spine"
                ),
                None,
            )
            ncx_href = (
                ncx_hrefs_by_id.get(spine.attrib.get("toc", ""))
                if spine is not None
                else None
            ) or next(iter(ncx_hrefs_by_id.values()), None)
            reading_order: list[PublicationLink] = []
            reading_ids: set[str] = set()
            for element in opf_root.iter():
                if _local_name(element.tag) != "itemref":
                    continue
                item_id = element.attrib.get("idref", "")
                manifest_item = manifest_by_id.get(item_id)
                if manifest_item is None:
                    raise PublicationStructureError(
                        "EPUB spine references a missing manifest item"
                    )
                reading_ids.add(item_id)
                reading_order.append(
                    PublicationLink(href=manifest_item[0], media_type=manifest_item[1])
                )
            if not reading_order:
                raise PublicationStructureError("EPUB reading order is empty")
            resources = tuple(
                PublicationLink(
                    href=href,
                    media_type=media_type,
                    rel=("contents",)
                    if "nav" in properties.split() or href == ncx_href
                    else (),
                )
                for item_id, (href, media_type, properties) in manifest_by_id.items()
                if item_id not in reading_ids
            )
            original_hash = known_hash or publication_sha256(source_path)
            if original_hash.startswith("sha256:"):
                original_hash = original_hash.removeprefix("sha256:")
            if len(original_hash) != 64:
                original_hash = publication_sha256(source_path)
            canonical_original_hash = f"sha256:{original_hash.lower()}"
            try:
                toc = _toc_from_nav(archive, entries, nav_href)
            except PublicationSecurityError:
                raise
            except PublicationCorruptError:
                toc = ()
            if not toc:
                try:
                    toc = _toc_from_ncx(archive, entries, ncx_href)
                except PublicationSecurityError:
                    raise
                except PublicationCorruptError:
                    toc = ()
            publication = NormalizedPublication(
                identifier=f"urn:shuku:volume:{source_path.name}",
                title=_metadata_value(opf_root, "title") or fallback_title,
                author=_metadata_value(opf_root, "creator") or fallback_author,
                language=_metadata_value(opf_root, "language"),
                reading_progression=_reading_progression(opf_root),
                fingerprint=PublicationFingerprint(
                    original_file_hash=canonical_original_hash,
                    parser=EPUB_PARSER_IDENTIFIER,
                    normalization=EPUB_NORMALIZATION_IDENTIFIER,
                ),
                reading_order=tuple(reading_order),
                resources=resources,
                toc=toc,
            )
            media_types = {
                _entry_key(link.href): link.media_type
                for link in (*publication.reading_order, *publication.resources)
            }
            return _IndexedEpub(
                source_path=source_path,
                source_mtime=source_path.stat().st_mtime,
                original_file_hash=canonical_original_hash,
                publication=publication,
                entries_by_href={key: info.filename for key, info in entries.items()},
                media_types_by_href=media_types,
            )
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise PublicationStructureError("EPUB archive is invalid") from error
    except OSError as error:
        raise PublicationCorruptError("EPUB archive cannot be read") from error


class EpubPublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._index(source).publication

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        indexed = self._index(source)
        key = _entry_key(href)
        archive_name = indexed.entries_by_href.get(key)
        if archive_name is None or key not in indexed.media_types_by_href:
            raise PublicationResourceNotFoundError
        try:
            with zipfile.ZipFile(indexed.source_path) as archive:
                content = archive.read(archive_name)
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
            raise PublicationCorruptError("EPUB resource cannot be read") from error
        return PublicationResource(
            href=href,
            media_type=indexed.media_types_by_href[key],
            content=content,
            source_mtime=indexed.source_mtime,
        )

    def _index(self, source: PublicationSource) -> _IndexedEpub:
        if source.source_format != "epub":
            raise PublicationUnsupportedError(source.source_format)
        path = resolve_publication_source(source.path, self._storage_root)
        stat_result = path.stat()
        return _index_epub(
            str(path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.full_hash,
            source.title,
            source.author,
        )
