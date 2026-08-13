"""Safe zero-copy EPUB to Readium Web Publication adapter."""

from __future__ import annotations

import mimetypes
import posixpath
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
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.source_files import (
    publication_sha256,
    resolve_publication_source,
)

EPUB_PARSER_IDENTIFIER = "epub-package:1"
EPUB_NORMALIZATION_IDENTIFIER = "shuku-epub-raw-v1"
MAX_ARCHIVE_ENTRIES = 20_000
MAX_SINGLE_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000


@dataclass(frozen=True, slots=True)
class _IndexedEpub:
    source_path: Path
    source_mtime: float
    original_file_hash: str
    publication: NormalizedPublication
    entries_by_href: dict[str, str]
    media_types_by_href: dict[str, str]


def _xml_root(content: bytes) -> ElementTree.Element:
    prefix = content[:4096].upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise PublicationCorruptError("active XML declarations are not allowed")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise PublicationCorruptError("publication XML is invalid") from error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _canonical_href(base: str, href: str) -> str:
    split = urlsplit(href)
    if split.scheme or split.netloc or split.query:
        raise PublicationCorruptError("publication href must be local")
    decoded = unquote(split.path)
    if "\\" in decoded or decoded.startswith("/"):
        raise PublicationCorruptError("publication href escapes its archive")
    joined = posixpath.normpath(posixpath.join(base, decoded))
    if joined in {"", ".", ".."} or joined.startswith("../"):
        raise PublicationCorruptError("publication href escapes its archive")
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
        raise PublicationCorruptError("publication has too many resources")
    entries: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        try:
            key = _entry_key(info.filename)
        except PublicationResourceNotFoundError as error:
            raise PublicationCorruptError(
                "publication contains an unsafe resource path"
            ) from error
        if key in entries:
            raise PublicationCorruptError(
                "publication contains duplicate resource paths"
            )
        unix_mode = info.external_attr >> 16
        if stat.S_ISLNK(unix_mode) or info.flag_bits & 0x1:
            raise PublicationCorruptError(
                "linked or encrypted resources are unsupported"
            )
        if info.file_size > MAX_SINGLE_RESOURCE_BYTES:
            raise PublicationCorruptError("publication resource exceeds the size limit")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise PublicationCorruptError("publication exceeds the expanded size limit")
        if info.compress_size == 0 and info.file_size > 0:
            raise PublicationCorruptError(
                "publication resource has an invalid compression ratio"
            )
        if (
            info.compress_size
            and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise PublicationCorruptError(
                "publication resource compression ratio is unsafe"
            )
        entries[key] = info
    return entries


def _container_opf_path(
    archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo]
) -> str:
    container = entries.get("META-INF/container.xml")
    if container is None:
        raise PublicationCorruptError("EPUB container is missing")
    root = _xml_root(archive.read(container))
    for element in root.iter():
        if _local_name(element.tag) == "rootfile":
            value = element.attrib.get("full-path", "")
            key = _entry_key(value)
            if key in entries:
                return key
    raise PublicationCorruptError("EPUB package document is missing")


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
    root = _xml_root(archive.read(nav_info))
    nav_base = posixpath.dirname(nav_key)
    results: list[PublicationTocEntry] = []
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
        for anchor in element.iter():
            if _local_name(anchor.tag) != "a" or not anchor.attrib.get("href"):
                continue
            title = " ".join("".join(anchor.itertext()).split())
            if not title:
                continue
            results.append(
                PublicationTocEntry(
                    href=_canonical_href(nav_base, anchor.attrib["href"]),
                    title=title,
                )
            )
        break
    return tuple(results)


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
            opf_root = _xml_root(archive.read(entries[opf_path]))
            opf_base = posixpath.dirname(opf_path)
            manifest_by_id: dict[str, tuple[str, str, str]] = {}
            nav_href: str | None = None
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
                    raise PublicationCorruptError(
                        "EPUB manifest references a missing resource"
                    )
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
            reading_order: list[PublicationLink] = []
            reading_ids: set[str] = set()
            for element in opf_root.iter():
                if _local_name(element.tag) != "itemref":
                    continue
                item_id = element.attrib.get("idref", "")
                manifest_item = manifest_by_id.get(item_id)
                if manifest_item is None:
                    raise PublicationCorruptError(
                        "EPUB spine references a missing manifest item"
                    )
                reading_ids.add(item_id)
                reading_order.append(
                    PublicationLink(href=manifest_item[0], media_type=manifest_item[1])
                )
            if not reading_order:
                raise PublicationCorruptError("EPUB reading order is empty")
            resources = tuple(
                PublicationLink(
                    href=href,
                    media_type=media_type,
                    rel=("contents",) if "nav" in properties.split() else (),
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
                toc=_toc_from_nav(archive, entries, nav_href),
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
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise PublicationCorruptError("EPUB archive is invalid") from error


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
