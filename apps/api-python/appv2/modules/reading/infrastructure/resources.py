from __future__ import annotations

import email.utils
import mimetypes
import re
import threading
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from appv2.modules.catalog.contracts import CatalogFile
from appv2.modules.reading.contracts import ComicPage, ReaderResourcePort, ResourceStream
from appv2.platform.http.ranges import ByteRange


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
