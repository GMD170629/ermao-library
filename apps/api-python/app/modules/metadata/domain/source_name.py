"""Interpret one publication name, never its parent directories."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source

_AUTHOR = re.compile(r"(?:作者|(?<![A-Za-z])author)\s*[:：]", re.IGNORECASE)
_BRACKETS = dict(zip("[［【(（《〈", "]］】)）》〉", strict=True))
_CLOSERS = frozenset(_BRACKETS.values())
_SEPARATORS = frozenset("-－–—_＿|｜")


@dataclass(frozen=True, slots=True)
class _NamePart:
    start: int
    text: str
    wrapped: bool = False


def _name_parts(name: str) -> list[_NamePart] | None:
    """Split only at top-level boundaries, validating every bracket group."""
    parts: list[_NamePart] = []
    start = 0
    index = 0
    while index < len(name):
        char = name[index]
        if char in _CLOSERS:
            return None
        if char in _SEPARATORS or char in _BRACKETS:
            if name[start:index].strip():
                parts.append(_NamePart(start, name[start:index]))
            if char in _BRACKETS:
                group_start = index
                stack = [(char, index)]
                index += 1
                while index < len(name) and stack:
                    current = name[index]
                    if current in _BRACKETS:
                        stack.append((current, index))
                    elif current in _CLOSERS:
                        opener, opening_index = stack.pop()
                        if _BRACKETS[opener] != current or not name[opening_index + 1:index].strip():
                            return None
                    index += 1
                if stack:
                    return None
                parts.append(_NamePart(group_start, name[group_start + 1:index - 1], True))
                start = index
                continue
            start = index + 1
        index += 1
    if name[start:].strip():
        parts.append(_NamePart(start, name[start:]))
    return parts


def _title_author(name: str) -> tuple[str, str | None] | None:
    parts = _name_parts(name)
    if parts is None:
        return None
    if not parts:
        return name, None
    for part in parts:
        marker = _AUTHOR.search(part.text)
        if marker is None:
            continue
        author = part.text[marker.end():].strip()
        prefix = name[:part.start] + part.text[:marker.start()]
        title = prefix.strip().rstrip("".join(_SEPARATORS)).strip()
        if not title or not author:
            continue
        title_parts = _name_parts(title)
        if title_parts is None:
            continue
        if len(title_parts) == 1 and title_parts[0].wrapped:
            title = title_parts[0].text.strip()
        return title, author
    return parts[0].text.strip(), parts[1].text.strip() if len(parts) > 1 else None


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
    """Prefer explicit authors, otherwise use the first two structural parts."""
    title = name.strip()
    if not is_directory and title.rpartition(".")[2].lower() in _EXTENSIONS:
        title = title.rpartition(".")[0]
    parsed = _title_author(title)
    if parsed is None:
        return PublicationMetadata(title=title)
    title, author = parsed
    titles = titles_from_local_source(title)
    return PublicationMetadata(
        title=titles.work_title,
        volume_title=titles.volume_title,
        volume_index=titles.volume_index,
        authors=(author,) if author else (),
    )
