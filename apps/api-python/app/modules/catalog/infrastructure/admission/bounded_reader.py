"""Small byte-budget wrapper for read-only random-access parsers."""

from __future__ import annotations

import io
from typing import BinaryIO

from typing_extensions import Buffer


class ProbeBudgetExceeded(Exception):
    """Internal signal that a third-party parser exceeded its read budget."""


class BoundedRandomAccess(io.BufferedIOBase):
    """Delegate seek/read while counting every byte returned by the parser."""

    def __init__(self, source: BinaryIO, *, maximum_read_bytes: int) -> None:
        super().__init__()
        if maximum_read_bytes <= 0:
            raise ValueError("maximum_read_bytes must be positive")
        self._source = source
        self._maximum_read_bytes = maximum_read_bytes
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def read(self, size: int | None = -1) -> bytes:
        remaining = self._maximum_read_bytes - self.bytes_read
        if remaining < 0:
            raise ProbeBudgetExceeded
        maximum_next_read = remaining + 1
        requested = (
            maximum_next_read
            if size is None or size < 0
            else min(size, maximum_next_read)
        )
        content = self._source.read(requested)
        self.bytes_read += len(content)
        if self.bytes_read > self._maximum_read_bytes:
            raise ProbeBudgetExceeded
        return content

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def readinto(self, buffer: Buffer, /) -> int:
        view = memoryview(buffer).cast("B")
        content = self.read(len(view))
        view[: len(content)] = content
        return len(content)

    def readinto1(self, buffer: Buffer, /) -> int:
        return self.readinto(buffer)

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._source.seek(offset, whence)

    def tell(self) -> int:
        return self._source.tell()

    def close(self) -> None:
        if not self.closed:
            self._source.close()
        super().close()


__all__ = ["BoundedRandomAccess", "ProbeBudgetExceeded"]
