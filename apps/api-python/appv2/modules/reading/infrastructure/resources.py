from __future__ import annotations

import email.utils
import threading
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from appv2.modules.catalog.contracts import CatalogFile
from appv2.modules.reading.contracts import ReaderResourcePort, ResourceStream
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
