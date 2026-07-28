"""Pure import filename eligibility rules shared by delivery adapters."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_IMPORT_FILE_EXTENSIONS = frozenset(
    {
        ".azw",
        ".azw3",
        ".cbz",
        ".epub",
        ".fb2",
        ".m4a",
        ".m4b",
        ".mobi",
        ".mp3",
        ".pdf",
        ".prc",
        ".txt",
        ".zip",
    }
)


def is_supported_import_filename(value: str | Path) -> bool:
    return Path(value).suffix.lower() in SUPPORTED_IMPORT_FILE_EXTENSIONS
