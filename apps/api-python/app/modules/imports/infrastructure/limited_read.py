"""Read budgets for import inspection, never publication admission limits."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from io import FileIO, UnsupportedOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer
from pathlib import Path

from app.modules.metadata.public import MAX_OPF_BYTES

STRUCTURE_BYTES = 8 * 1024 * 1024
METADATA_BYTES = MAX_OPF_BYTES
COVER_BYTES = 20 * 1024 * 1024


class InspectionLimitReached(ValueError):
    """Optional inspection stopped without rejecting the source."""


class LimitedReader(FileIO):
    """Count actual parser reads; prohibit unbounded read-all requests."""

    def __init__(self, path: Path, budget: int = STRUCTURE_BYTES) -> None:
        super().__init__(path, "rb")
        self.remaining = budget

    @contextmanager
    def independent_read(self, limit: int) -> Iterator[None]:
        """A located cover/navigation document has its own bounded allowance."""
        structure_remaining = self.remaining
        self.remaining = limit
        try:
            yield
        finally:
            self.remaining = structure_remaining

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            raise InspectionLimitReached("read-all is not an import operation")
        if size > self.remaining:
            raise InspectionLimitReached("import read budget exceeded")
        data = super().read(size)
        self.remaining -= len(data)
        return data

    def readinto(self, buffer: WriteableBuffer) -> int:
        data = self.read(memoryview(buffer).nbytes)
        memoryview(buffer)[: len(data)] = data
        return len(data)

    def readline(self, size: int | None = -1) -> bytes:
        limit = (
            self.remaining if size is None or size < 0 else min(size, self.remaining)
        )
        if limit == 0:
            raise InspectionLimitReached("import read budget exceeded")
        data = bytearray()
        while len(data) < limit:
            char = self.read(1)
            if not char:
                break
            data.extend(char)
            if char == b"\n":
                break
        return bytes(data)

    def readall(self) -> bytes:
        raise InspectionLimitReached("read-all is not an import operation")

    def fileno(self) -> int:
        raise UnsupportedOperation("import parsers must use counted reads")


def read_optional_file(path: Path, limit: int) -> bytes | None:
    try:
        with path.open("rb") as source:
            if path.stat().st_size > limit:
                return None
            content = source.read(limit + 1)
            return content if len(content) <= limit else None
    except OSError:
        return None


class ZipInspectionReader(LimitedReader):
    """ZIP permits an explicitly bounded EOCD tail read, not arbitrary read-all."""

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            position = self.tell()
            size = self.seek(0, 2) - position
            self.seek(position)
            if size > 65558:
                raise InspectionLimitReached("ZIP tail exceeds EOCD window")
        return super().read(size)
