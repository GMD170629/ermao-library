"""Interpret one publication name, never its parent directories."""

from __future__ import annotations

import re

from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source

_AUTHOR = re.compile(
    r"^(.*?)\s*(?:[\[［(（]\s*)?作者\s*[:：]\s*(.+?)(?:[\]］)）])?\s*$"
)
_SEPARATOR = re.compile(r"\s+-\s+")
_BRACKETED_TITLE_AUTHOR = re.compile(r"\[([^\[\]]+)\]\s*\[([^\[\]]+)\]")
_EXTENSIONS = frozenset(
    {
        "epub",
        "pdf",
        "txt",
        "fb2",
        "mobi",
        "azw",
        "azw3",
        "cbz",
        "cbr",
        "zip",
        "rar",
        "mp3",
        "m4a",
        "m4b",
        "aac",
        "flac",
        "ogg",
        "opus",
        "wav",
        "wma",
        "aiff",
        "aif",
        "jpg",
        "jpeg",
        "png",
        "webp",
        "gif",
    }
)


def metadata_from_source_name(name: str, *, is_directory: bool) -> PublicationMetadata:
    """Explicit author markers win; ambiguous unmarked names remain intact."""
    title = name.strip()
    if not is_directory and title.rpartition(".")[2].lower() in _EXTENSIONS:
        title = title.rpartition(".")[0]
    author = None
    match = _AUTHOR.fullmatch(title)
    bracketed = _BRACKETED_TITLE_AUTHOR.fullmatch(title.strip())
    if match and match[1].strip() and match[2].strip():
        title, author = match[1].strip(), match[2].strip()
    elif bracketed and bracketed[1].strip() and bracketed[2].strip():
        title, author = bracketed[1].strip(), bracketed[2].strip()
    else:
        parts = _SEPARATOR.split(title)
        if len(parts) == 2 and all(part.strip() for part in parts):
            title, author = (part.strip() for part in parts)
    if title.startswith("《") and title.endswith("》"):
        title = title[1:-1].strip()
    titles = titles_from_local_source(title)
    return PublicationMetadata(
        title=titles.work_title,
        volume_title=titles.volume_title,
        volume_index=titles.volume_index,
        authors=(author,) if author else (),
    )
