"""Deterministic plain-text to in-memory Readium Publication adapter."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)

TXT_PARSER_IDENTIFIER = "shuku-txt-parser-v1"
TXT_NORMALIZATION_IDENTIFIER = "shuku-txt-publication-v2"
MAX_TXT_SOURCE_BYTES = 64 * 1024 * 1024
_CHINESE_CHAPTER = re.compile(
    r"^\u7b2c[0-9\u3007\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03"
    r"\u516b\u4e5d\u5341\u767e\u5343\u4e07\u4e24]+"
    r"[\u7ae0\u8282\u56de\u5377\u7bc7\u90e8](?:[ \u3000:：].*)?$"
)
_LATIN_CHAPTER = re.compile(
    r"^(?:chapter|part|book)[ \t]+[0-9ivxlcdm]+(?:[ .:：-].*)?$",
    re.IGNORECASE,
)
_STYLESHEET_HREF = "text/reader.css"
_STYLESHEET = b"""html { color-scheme: light dark; }
body { margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere; }
h1 { font-size: 1.35em; margin: 1.5em 0 1em; }
p { margin: 0 0 1em; white-space: normal; }
"""


@dataclass(frozen=True, slots=True)
class _TxtChapter:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TxtSnapshot:
    publication: NormalizedPublication
    source_mtime: float
    resources_by_href: dict[str, tuple[str, bytes]]


def _decode_txt(content: bytes) -> str:
    if len(content) > MAX_TXT_SOURCE_BYTES:
        raise PublicationCorruptError("TXT source exceeds the size limit")
    candidates: tuple[tuple[str, bytes], ...]
    if content.startswith(b"\xef\xbb\xbf"):
        candidates = (("utf-8", content[3:]),)
    elif content.startswith(b"\xff\xfe"):
        candidates = (("utf-16-le", content[2:]),)
    elif content.startswith(b"\xfe\xff"):
        candidates = (("utf-16-be", content[2:]),)
    else:
        candidates = (("utf-8", content), ("gb18030", content))
    for encoding, payload in candidates:
        try:
            decoded = payload.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        if "\x00" in decoded:
            raise PublicationCorruptError("TXT source contains NUL characters")
        return decoded
    raise PublicationCorruptError("TXT source encoding is unsupported")


def _normalized_lines(content: str) -> tuple[str, ...]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u2028", "\n").replace("\u2029", "\n")
    if not normalized.strip():
        raise PublicationCorruptError("TXT source is empty")
    return tuple(line.rstrip() for line in normalized.split("\n"))


def _is_chapter_heading(line: str) -> bool:
    value = line.strip()
    return 2 <= len(value) <= 96 and bool(
        _CHINESE_CHAPTER.fullmatch(value) or _LATIN_CHAPTER.fullmatch(value)
    )


def _chapters(
    lines: tuple[str, ...], publication_title: str
) -> tuple[_TxtChapter, ...]:
    starts = [index for index, line in enumerate(lines) if _is_chapter_heading(line)]
    if not starts:
        ranges = [(0, len(lines))]
    else:
        effective_starts = starts
        if any(line.strip() for line in lines[: starts[0]]):
            effective_starts = [0, *starts]
        ranges = [
            (
                start,
                effective_starts[index + 1]
                if index + 1 < len(effective_starts)
                else len(lines),
            )
            for index, start in enumerate(effective_starts)
        ]
    chapters: list[_TxtChapter] = []
    for chapter_index, (start, end) in enumerate(ranges, start=1):
        chapter_lines = lines[start:end]
        first = chapter_lines[0] if chapter_lines else ""
        has_heading = _is_chapter_heading(first)
        title = (
            first.strip()
            if has_heading
            else publication_title
            if len(ranges) == 1
            else f"{publication_title} {chapter_index}"
        )
        chapters.append(
            _TxtChapter(
                title=title,
                lines=chapter_lines[1:] if has_heading else chapter_lines,
            )
        )
    return tuple(chapters)


def _escape_xml(value: str) -> str:
    return html.escape(value, quote=True).replace("&#x27;", "&apos;")


def _chapter_xhtml(chapter: _TxtChapter) -> bytes:
    paragraph_lines: list[list[str]] = []
    current: list[str] = []
    for line in chapter.lines:
        if not line.strip():
            if current:
                paragraph_lines.append(current)
                current = []
        else:
            current.append(line)
    if current:
        paragraph_lines.append(current)
    paragraphs = "\n".join(
        f'<p id="block-{index:06d}">'
        + "<br/>".join(_escape_xml(line) for line in block)
        + "</p>"
        for index, block in enumerate(paragraph_lines, start=1)
    )
    document = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="und">
<head><meta charset="utf-8"/><title>{_escape_xml(chapter.title)}</title>
<link rel="stylesheet" type="text/css" href="reader.css"/></head>
<body><h1 id="heading-000001">{_escape_xml(chapter.title)}</h1>
{paragraphs}
</body></html>"""
    return document.encode()


def _resource_href(raw_href: str) -> str:
    split = urlsplit(raw_href)
    decoded = unquote(split.path)
    if (
        split.scheme
        or split.netloc
        or split.query
        or split.fragment
        or not decoded
        or decoded.startswith("/")
        or "\\" in decoded
        or ".." in decoded.split("/")
    ):
        raise PublicationResourceNotFoundError
    return decoded


@lru_cache(maxsize=64)
def _snapshot(
    source_path_value: str,
    source_size: int,
    source_mtime_ns: int,
    title: str,
    author: str | None,
) -> _TxtSnapshot:
    source_path = Path(source_path_value)
    try:
        content = source_path.read_bytes()
    except OSError as error:
        raise PublicationCorruptError("TXT source is unavailable") from error
    chapters = _chapters(_normalized_lines(_decode_txt(content)), title)
    resources: dict[str, tuple[str, bytes]] = {
        _STYLESHEET_HREF: ("text/css", _STYLESHEET)
    }
    reading_order: list[PublicationLink] = []
    toc: list[PublicationTocEntry] = []
    for chapter_index, chapter in enumerate(chapters, start=1):
        href = f"text/chapter-{chapter_index:04d}.xhtml"
        resources[href] = (
            "application/xhtml+xml",
            _chapter_xhtml(chapter),
        )
        reading_order.append(
            PublicationLink(
                href=href,
                media_type="application/xhtml+xml",
                title=chapter.title,
            )
        )
        toc.append(
            PublicationTocEntry(
                href=f"{href}#heading-000001",
                title=chapter.title,
            )
        )
    publication = NormalizedPublication(
        identifier=f"urn:shuku:txt:{source_size}:{source_mtime_ns}",
        title=title,
        author=author,
        language=None,
        reading_progression="ltr",
        revision=PublicationRevision(
            source_size_bytes=source_size,
            source_mtime_ms=source_mtime_ns // 1_000_000,
            parser=TXT_PARSER_IDENTIFIER,
            normalization=TXT_NORMALIZATION_IDENTIFIER,
        ),
        reading_order=tuple(reading_order),
        resources=(PublicationLink(href=_STYLESHEET_HREF, media_type="text/css"),),
        toc=tuple(toc),
    )
    return _TxtSnapshot(
        publication=publication,
        source_mtime=source_path.stat().st_mtime,
        resources_by_href=resources,
    )


class TxtPublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._require_snapshot(source).publication

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        snapshot = self._require_snapshot(source)
        safe_href = _resource_href(href)
        indexed = snapshot.resources_by_href.get(safe_href)
        if indexed is None:
            raise PublicationResourceNotFoundError
        media_type, content = indexed
        return PublicationResource(
            href=safe_href,
            media_type=media_type,
            content=content,
            source_mtime=snapshot.source_mtime,
        )

    def _require_snapshot(self, source: PublicationSource) -> _TxtSnapshot:
        if source.source_format != "txt":
            raise PublicationUnsupportedError(source.source_format)
        source_path = resolve_publication_source(
            source.path,
            select_publication_source_root(source.library_root, self._storage_root),
        )
        stat_result = source_path.stat()
        if stat_result.st_size > MAX_TXT_SOURCE_BYTES:
            raise PublicationCorruptError("TXT source exceeds the size limit")
        return _snapshot(
            str(source_path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.title,
            source.author,
        )


__all__ = [
    "TXT_NORMALIZATION_IDENTIFIER",
    "TXT_PARSER_IDENTIFIER",
    "TxtPublicationAdapter",
]
