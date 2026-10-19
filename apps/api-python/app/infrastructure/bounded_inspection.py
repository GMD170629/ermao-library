"""Selective local metadata I/O without file-size admission quotas."""

from __future__ import annotations

import logging
from io import FileIO, UnsupportedOperation
from typing import TYPE_CHECKING

from app.core.exception_diagnostics import capture_exception, record_exception

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer
from pathlib import Path


class InspectionLimitReached(ValueError):
    """Optional inspection stopped without rejecting the source."""


class LimitedReader(FileIO):
    """Allow requested metadata reads; prohibit whole-publication read-all requests."""

    def __init__(self, path: Path | int) -> None:
        super().__init__(path, "rb")

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            raise InspectionLimitReached("read-all is not an import operation")
        data = super().read(size)
        return data

    def readinto(self, buffer: WriteableBuffer) -> int:
        data = self.read(memoryview(buffer).nbytes)
        memoryview(buffer)[: len(data)] = data
        return len(data)

    def readline(self, size: int | None = -1) -> bytes:
        limit = size if size is not None and size >= 0 else None
        data = bytearray()
        while limit is None or len(data) < limit:
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
        raise UnsupportedOperation("import parsers must use selective reads")


def read_optional_file(path: Path) -> bytes | None:
    try:
        with path.open("rb") as source:
            return source.read()
    except FileNotFoundError as _caught_error:
        # diagnostics-control-flow: An optional sidecar is permitted to be absent; no read operation is required.
        capture_exception(_caught_error, level="debug")
        return None
    except OSError as error:
        capture_exception(error, persist=False)
        record_exception(logging.getLogger(__name__), "infrastructure.bounded_inspection.read_optional_file.failed", error)
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
