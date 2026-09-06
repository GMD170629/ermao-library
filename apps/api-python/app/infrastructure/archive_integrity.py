"""Archive address and ZIP byte-span detection shared by EPUB and comics.

These adapters return facts only. Publication owners apply their generated
resource-role decisions; no archive member is extracted to the filesystem.
"""

from __future__ import annotations

import struct
import zipfile
from enum import StrEnum


class ArchivePathProblem(StrEnum):
    NUL_PATH = "NUL_PATH"
    ABSOLUTE_PATH = "ABSOLUTE_PATH"
    PATH_ESCAPE = "PATH_ESCAPE"
    EMPTY_PATH = "EMPTY_PATH"


class UnsafeArchivePathError(ValueError):
    """An archive address cannot be resolved within its virtual root."""

    def __init__(self, problem: ArchivePathProblem) -> None:
        super().__init__(
            "archive address cannot identify a resource within its virtual root"
        )
        self.problem = problem


def normalize_archive_path(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized:
        raise UnsafeArchivePathError(ArchivePathProblem.EMPTY_PATH)
    if "\x00" in normalized:
        raise UnsafeArchivePathError(ArchivePathProblem.NUL_PATH)
    if normalized.startswith("/") or (
        len(normalized) >= 2
        and normalized[0].isascii()
        and normalized[0].isalpha()
        and normalized[1] == ":"
    ):
        raise UnsafeArchivePathError(ArchivePathProblem.ABSOLUTE_PATH)
    segments: list[str] = []
    for segment in normalized.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if not segments:
                raise UnsafeArchivePathError(ArchivePathProblem.PATH_ESCAPE)
            segments.pop()
        else:
            segments.append(segment)
    if not segments:
        raise UnsafeArchivePathError(ArchivePathProblem.EMPTY_PATH)
    return "/".join(segments)


def zip_entry_data_span(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo
) -> tuple[int, int] | None:
    file_pointer = archive.fp
    if file_pointer is None:
        return None
    position = file_pointer.tell()
    try:
        file_pointer.seek(info.header_offset + 26)
        header = file_pointer.read(4)
        if len(header) != 4:
            return None
        name_length, extra_length = struct.unpack("<HH", header)
        start = info.header_offset + 30 + name_length + extra_length
        return start, start + info.compress_size
    except (OSError, ValueError):
        return None
    finally:
        file_pointer.seek(position)
