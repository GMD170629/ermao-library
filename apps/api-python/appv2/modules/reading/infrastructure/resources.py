from __future__ import annotations

import email.utils
import mimetypes
import posixpath
import re
import threading
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from defusedxml import ElementTree

from appv2.modules.catalog.contracts import CatalogFile
from appv2.modules.reading.contracts import (
    ComicPage,
    EpubUnit,
    ReaderResourcePort,
    ResourceStream,
)
from appv2.platform.http.ranges import ByteRange

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element  # noqa: S405 - annotation only; parsing is defused


class LocalReaderResources(ReaderResourcePort):
    def __init__(
        self,
        *,
        allowed_roots: tuple[Path, ...],
        streams_per_user: int,
    ) -> None:
        self._roots = tuple(root.expanduser().resolve() for root in allowed_roots)
        self._limit = streams_per_user
        self._active: defaultdict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def open(
        self,
        file: CatalogFile,
        *,
        requested_range: ByteRange | None,
        stream_key: str,
    ) -> ResourceStream:
        path = Path(file.storage_path).expanduser().resolve()
        if not any(path.is_relative_to(root) for root in self._roots):
            raise ValueError("catalog file escapes configured storage roots")
        stat = path.stat()
        start, end = _resolve_range(requested_range, stat.st_size)
        status_code = 206 if requested_range is not None else 200
        length = end - start + 1
        content_range = f"bytes {start}-{end}/{stat.st_size}" if status_code == 206 else None
        return ResourceStream(
            body=self._iter_file(
                path,
                start=start,
                length=length,
                stream_key=stream_key,
            ),
            media_type=file.media_type,
            status_code=status_code,
            content_length=length,
            content_range=content_range,
            etag=f'"{file.checksum}"',
            last_modified=email.utils.formatdate(stat.st_mtime, usegmt=True),
            filename=file.original_name,
        )

    def comic_pages(self, file: CatalogFile) -> list[ComicPage]:
        path = self._catalog_path(file)
        with zipfile.ZipFile(path) as archive:
            entries = self._comic_entries(archive)
            return [
                ComicPage(
                    page_index=index,
                    title=Path(entry.filename).name,
                    media_type=mimetypes.guess_type(entry.filename)[0] or "image/jpeg",
                    size_bytes=entry.file_size,
                )
                for index, entry in enumerate(entries, start=1)
            ]

    def epub_units(self, file: CatalogFile) -> list[EpubUnit]:
        path = self._catalog_path(file)
        with zipfile.ZipFile(path) as archive:
            container = self._xml_member(archive, "META-INF/container.xml")
            rootfile = next(
                (
                    element.attrib.get("full-path")
                    for element in container.iter()
                    if self._local_name(element.tag) == "rootfile"
                    and element.attrib.get("full-path")
                ),
                None,
            )
            if not rootfile:
                raise ValueError("EPUB container does not identify a package document")
            package_path = self._safe_member_name(rootfile)
            package = self._xml_member(archive, package_path)
            manifest: dict[str, tuple[str, str, str]] = {}
            spine_ids: list[str] = []
            for element in package.iter():
                name = self._local_name(element.tag)
                if name == "item":
                    item_id = element.attrib.get("id")
                    href = element.attrib.get("href")
                    if item_id and href:
                        manifest[item_id] = (
                            href,
                            element.attrib.get("properties", ""),
                            element.attrib.get("media-type", ""),
                        )
                elif name == "itemref" and element.attrib.get("idref"):
                    spine_ids.append(element.attrib["idref"])

            nav_item = next(
                (item for item in manifest.values() if "nav" in item[1].split()),
                None,
            )
            units = self._navigation_units(
                archive,
                package_path=package_path,
                nav_href=nav_item[0] if nav_item else None,
            )
            if units:
                return units
            return [
                EpubUnit(index=index, title=Path(href).stem, href=href)
                for index, item_id in enumerate(spine_ids, start=1)
                if (item := manifest.get(item_id)) is not None
                for href in [item[0]]
            ]

    def open_comic_page(
        self,
        file: CatalogFile,
        *,
        page_index: int,
        stream_key: str,
    ) -> ResourceStream:
        path = self._catalog_path(file)
        with zipfile.ZipFile(path) as archive:
            entries = self._comic_entries(archive)
            if page_index < 1 or page_index > len(entries):
                raise ValueError("comic page does not exist")
            entry = entries[page_index - 1]
            if entry.file_size > 128 * 1024 * 1024:
                raise ValueError("comic page exceeds safety limit")
            content = archive.read(entry)
        stat = path.stat()
        return ResourceStream(
            body=self._iter_bytes(content, stream_key=stream_key),
            media_type=mimetypes.guess_type(entry.filename)[0] or "image/jpeg",
            status_code=200,
            content_length=len(content),
            content_range=None,
            etag=f'"{file.checksum}-{page_index}"',
            last_modified=email.utils.formatdate(stat.st_mtime, usegmt=True),
            filename=Path(entry.filename).name,
        )

    def _catalog_path(self, file: CatalogFile) -> Path:
        path = Path(file.storage_path).expanduser().resolve()
        if not any(path.is_relative_to(root) for root in self._roots):
            raise ValueError("catalog file escapes configured storage roots")
        if not zipfile.is_zipfile(path):
            raise ValueError("comic resource is not a ZIP archive")
        return path

    @classmethod
    def _navigation_units(
        cls,
        archive: zipfile.ZipFile,
        *,
        package_path: str,
        nav_href: str | None,
    ) -> list[EpubUnit]:
        if not nav_href:
            return []
        package_directory = posixpath.dirname(package_path)
        nav_path = cls._safe_member_name(posixpath.join(package_directory, nav_href))
        navigation = cls._xml_member(archive, nav_path)
        toc = next(
            (
                element
                for element in navigation.iter()
                if cls._local_name(element.tag) == "nav"
                and "toc"
                in (
                    element.attrib.get("{http://www.idpf.org/2007/ops}type", "")
                    or element.attrib.get("type", "")
                ).split()
            ),
            None,
        )
        if toc is None:
            return []
        units: list[EpubUnit] = []
        for element in toc.iter():
            if cls._local_name(element.tag) != "li":
                continue
            target = next(
                (
                    child
                    for child in element.iter()
                    if child is not element and cls._local_name(child.tag) in {"a", "span"}
                ),
                None,
            )
            if target is None:
                continue
            title = " ".join("".join(target.itertext()).split())
            href = target.attrib.get("href")
            if not title or not href:
                continue
            units.append(EpubUnit(index=len(units) + 1, title=title, href=href))
        return units

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _safe_member_name(name: str) -> str:
        normalized = posixpath.normpath(name.replace("\\", "/")).lstrip("/")
        if normalized == ".." or normalized.startswith("../"):
            raise ValueError("archive member escapes the EPUB root")
        return normalized

    @classmethod
    def _xml_member(cls, archive: zipfile.ZipFile, name: str) -> Element:
        safe_name = cls._safe_member_name(name)
        try:
            entry = archive.getinfo(safe_name)
        except KeyError as error:
            raise ValueError(f"EPUB member is missing: {safe_name}") from error
        if entry.file_size > 4 * 1024 * 1024:
            raise ValueError("EPUB metadata document exceeds safety limit")
        try:
            return ElementTree.fromstring(archive.read(entry))
        except ElementTree.ParseError as error:
            raise ValueError("EPUB metadata XML is invalid") from error

    @staticmethod
    def _comic_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        supported = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
        entries = [
            entry
            for entry in archive.infolist()
            if not entry.is_dir()
            and not entry.filename.startswith("__MACOSX/")
            and Path(entry.filename).suffix.lower() in supported
        ]
        if len(entries) > 10_000:
            raise ValueError("comic archive exceeds page limit")

        def natural_key(entry: zipfile.ZipInfo) -> tuple[object, ...]:
            return tuple(
                int(part) if part.isdigit() else part.casefold()
                for part in re.split(r"(\d+)", entry.filename)
            )

        entries.sort(key=natural_key)
        if not entries:
            raise ValueError("comic archive contains no readable pages")
        return entries

    def _iter_file(
        self, path: Path, *, start: int, length: int, stream_key: str
    ) -> Iterable[bytes]:
        with self._lock:
            if self._active[stream_key] >= self._limit:
                raise ValueError("concurrent stream limit exceeded")
            self._active[stream_key] += 1

        def iterator() -> Iterator[bytes]:
            remaining = length
            try:
                with path.open("rb") as source:
                    source.seek(start)
                    while remaining > 0:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            finally:
                with self._lock:
                    self._active[stream_key] -= 1
                    if self._active[stream_key] == 0:
                        del self._active[stream_key]

        return iterator()

    def _iter_bytes(self, content: bytes, *, stream_key: str) -> Iterable[bytes]:
        with self._lock:
            if self._active[stream_key] >= self._limit:
                raise ValueError("concurrent stream limit exceeded")
            self._active[stream_key] += 1

        def iterator() -> Iterator[bytes]:
            try:
                yield content
            finally:
                with self._lock:
                    self._active[stream_key] -= 1
                    if self._active[stream_key] == 0:
                        del self._active[stream_key]

        return iterator()


def _resolve_range(requested: ByteRange | None, size: int) -> tuple[int, int]:
    if size <= 0:
        raise ValueError("resource is empty")
    if requested is None:
        return 0, size - 1
    if requested.start is None:
        suffix = requested.end or 0
        if suffix <= 0:
            raise ValueError("invalid suffix range")
        return max(0, size - suffix), size - 1
    if requested.start >= size:
        raise ValueError("range start exceeds resource size")
    requested_end = requested.end if requested.end is not None else size - 1
    return requested.start, min(requested_end, size - 1)
