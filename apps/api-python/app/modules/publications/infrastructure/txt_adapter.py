"""Deterministic plain-text to EPUB-profile Readium Publication adapter."""

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
    PublicationFingerprint,
    PublicationLink,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.source_files import (
    publication_sha256,
    resolve_publication_source,
)

TXT_PARSER_IDENTIFIER = "shuku-txt-parser-v1"
TXT_NORMALIZATION_IDENTIFIER = "shuku-txt-publication-v1"
MAX_TXT_SOURCE_BYTES = 64 * 1024 * 1024
_CHAPTER_HEADING = re.compile(
    r"^(?:\u7b2c[0-9\uff10-\uff19\u4e00\u4e8c\u4e09\u56db\u4e94\u516d"
    r"\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07\u96f6\u3007\u4e24]+"
    r"[\u7ae0\u56de\u5377\u8282\u90e8\u7bc7]"
    r"(?:\s*[:：.、-]?\s+.+)?|"
    r"(?:chapter|part|book|section)\s+[0-9ivxlcdm]+"
    r"(?:\s*[:：.、-]?\s+.+)?)$",
    re.IGNORECASE,
)
_STYLESHEET_HREF = "styles/book.css"
_DEFAULT_CHAPTER_TITLE = "\u6b63\u6587"
_STYLESHEET = b"""html { writing-mode: horizontal-tb; }\nbody { margin: 0; padding: 1em; }\nh1 { break-before: page; }\np { margin: 0 0 1em; white-space: pre-wrap; }\n"""


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
    return tuple(normalized.split("\n"))


def _chapters(lines: tuple[str, ...]) -> tuple[_TxtChapter, ...]:
    chapters: list[_TxtChapter] = []
    current_title = _DEFAULT_CHAPTER_TITLE
    current_lines: list[str] = []
    for line in lines:
        heading = line.strip()
        if heading and _CHAPTER_HEADING.fullmatch(heading):
            if current_lines or chapters:
                chapters.append(
                    _TxtChapter(title=current_title, lines=tuple(current_lines))
                )
            current_title = heading
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines or not chapters:
        chapters.append(_TxtChapter(title=current_title, lines=tuple(current_lines)))
    return tuple(chapters)


def _chapter_xhtml(chapter: _TxtChapter, chapter_index: int) -> bytes:
    blocks: list[str] = []
    block_index = 0
    if chapter.title != _DEFAULT_CHAPTER_TITLE:
        blocks.append(
            f'<h1 id="heading-{chapter_index:04d}">{html.escape(chapter.title)}</h1>'
        )
    for line in chapter.lines:
        if not line.strip():
            continue
        block_index += 1
        block_id = f"block-{chapter_index:04d}-{block_index:06d}"
        blocks.append(f'<p id="{block_id}">{html.escape(line)}</p>')
    if not blocks:
        blocks.append(f'<p id="block-{chapter_index:04d}-000001"></p>')
    body = "\n".join(blocks)
    document = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="und">\n'
        "<head>\n"
        f"<title>{html.escape(chapter.title)}</title>\n"
        '<link rel="stylesheet" type="text/css" href="../styles/book.css"/>\n'
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )
    return document.encode("utf-8")


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
    known_hash: str | None,
    title: str,
    author: str | None,
) -> _TxtSnapshot:
    del source_size, source_mtime_ns
    source_path = Path(source_path_value)
    try:
        content = source_path.read_bytes()
    except OSError as error:
        raise PublicationCorruptError("TXT source is unavailable") from error
    chapters = _chapters(_normalized_lines(_decode_txt(content)))
    resources: dict[str, tuple[str, bytes]] = {
        _STYLESHEET_HREF: ("text/css", _STYLESHEET)
    }
    reading_order: list[PublicationLink] = []
    toc: list[PublicationTocEntry] = []
    for chapter_index, chapter in enumerate(chapters, start=1):
        href = f"text/chapter-{chapter_index:04d}.xhtml"
        resources[href] = (
            "application/xhtml+xml",
            _chapter_xhtml(chapter, chapter_index),
        )
        reading_order.append(
            PublicationLink(
                href=href,
                media_type="application/xhtml+xml",
                title=chapter.title,
            )
        )
        fragment = (
            f"heading-{chapter_index:04d}"
            if chapter.title != _DEFAULT_CHAPTER_TITLE
            else f"block-{chapter_index:04d}-000001"
        )
        toc.append(
            PublicationTocEntry(
                href=f"{href}#{fragment}",
                title=chapter.title,
            )
        )
    original_hash = (known_hash or publication_sha256(source_path)).removeprefix(
        "sha256:"
    )
    if len(original_hash) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in original_hash
    ):
        original_hash = publication_sha256(source_path)
    publication = NormalizedPublication(
        identifier=f"urn:shuku:txt:{original_hash.lower()}",
        title=title,
        author=author,
        language=None,
        reading_progression="ltr",
        fingerprint=PublicationFingerprint(
            original_file_hash=f"sha256:{original_hash.lower()}",
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
        source_path = resolve_publication_source(source.path, self._storage_root)
        stat_result = source_path.stat()
        if stat_result.st_size > MAX_TXT_SOURCE_BYTES:
            raise PublicationCorruptError("TXT source exceeds the size limit")
        return _snapshot(
            str(source_path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.full_hash,
            source.title,
            source.author,
        )


__all__ = [
    "TXT_NORMALIZATION_IDENTIFIER",
    "TXT_PARSER_IDENTIFIER",
    "TxtPublicationAdapter",
]
