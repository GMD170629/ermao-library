"""Deterministic plain-text to in-memory Readium Publication adapter."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
)
from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.application.safety_policy import (
    publication_parser_limit,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationLink,
    PublicationReadError,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationTxtEmptyError,
    PublicationTxtEncodingError,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.chapter_core import ChapterCore
from app.modules.publications.infrastructure.snapshot_cache import (
    PublicationSnapshotCache,
    publication_snapshot_weight,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)

TXT_PARSER_IDENTIFIER = "ermao-chapters:1"
TXT_NORMALIZATION_IDENTIFIER = "shuku-txt-publication-v3"
MAX_TXT_SOURCE_BYTES = reader_safety_budget(ReaderSafetyBudgetName.TXT_MEMORY_MAX_BYTES)
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
    chapters_by_href: dict[str, _TxtChapter]


def _decode_txt(content: bytes) -> str:
    if len(content) > MAX_TXT_SOURCE_BYTES:
        raise publication_parser_limit(
            ReaderSafetyRuleId.TXT_MEMORY_BUDGET,
            "TXT source exceeds the size limit",
        )
    candidates: tuple[tuple[str, bytes], ...]
    if content.startswith(b"\xef\xbb\xbf"):
        candidates = (("utf-8", content[3:]),)
    elif content.startswith(b"\xff\xfe"):
        candidates = (("utf-16-le", content[2:]),)
    elif content.startswith(b"\xfe\xff"):
        candidates = (("utf-16-be", content[2:]),)
    else:
        candidates = (("utf-8", content), ("gb18030", content))
    last_decode_error: UnicodeDecodeError | None = None
    for encoding, payload in candidates:
        try:
            decoded = payload.decode(encoding, errors="strict")
        except UnicodeDecodeError as error:
            last_decode_error = error
            continue
        return decoded
    raise PublicationTxtEncodingError(
        "TXT source encoding is unsupported"
    ) from last_decode_error


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
        raise PublicationReadError("TXT source is unavailable") from error
    decoded = _decode_txt(content)
    if not decoded.strip():
        raise PublicationTxtEmptyError("TXT source is empty")
    projection = ChapterCore.load().parse_txt(decoded)
    chapters_by_href: dict[str, _TxtChapter] = {}
    reading_order: list[PublicationLink] = []

    def resource(href: str, resource_title: str, body: bytes) -> None:
        chapters_by_href[href] = _TxtChapter(
            resource_title, tuple(body.decode().split("\n"))
        )
        reading_order.append(
            PublicationLink(
                href=href,
                media_type="application/xhtml+xml",
                title=resource_title,
            )
        )

    first_start = (
        projection.entries[0].source_start
        if projection.entries
        else len(projection.text)
    )
    if projection.entries and first_start > 0:
        resource("text/frontmatter.xhtml", title, projection.text[:first_start])
    for entry in projection.entries:
        if entry.href is None:
            continue
        resource(
            entry.href.partition("#")[0],
            entry.title,
            projection.text[entry.content_start : entry.source_end],
        )
    if not reading_order:
        resource("text/body.xhtml", title, projection.text)
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
        toc=projection.table_of_contents(),
    )
    return _TxtSnapshot(
        publication=publication,
        source_mtime=source_path.stat().st_mtime,
        chapters_by_href=chapters_by_href,
    )


class TxtPublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root
        self._cache: PublicationSnapshotCache[_TxtSnapshot] = PublicationSnapshotCache()

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._require_snapshot(source).publication

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        snapshot = self._require_snapshot(source)
        safe_href = _resource_href(href)
        if safe_href == _STYLESHEET_HREF:
            media_type, content = "text/css", _STYLESHEET
        else:
            chapter = snapshot.chapters_by_href.get(safe_href)
            if chapter is None:
                raise PublicationResourceNotFoundError
            media_type, content = "application/xhtml+xml", _chapter_xhtml(chapter)
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
            raise publication_parser_limit(
                ReaderSafetyRuleId.TXT_MEMORY_BUDGET,
                "TXT source exceeds the size limit",
            )
        key = (
            str(source_path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.title,
            source.author,
        )
        return self._cache.get(
            key,
            lambda: _snapshot(*key),
            publication_snapshot_weight(stat_result.st_size),
        )

    def close(self) -> None:
        self._cache.close()


__all__ = [
    "TXT_NORMALIZATION_IDENTIFIER",
    "TXT_PARSER_IDENTIFIER",
    "TxtPublicationAdapter",
]
