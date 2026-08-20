"""pypdfium2-backed PDF metadata, text-layer, and cover inspection."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from time import monotonic
from typing import Protocol

from app.modules.imports.application.pdf_types import (
    PdfChapter,
    PdfCoverPublication,
    PdfInspection,
)
from app.modules.imports.domain.pdf_content import (
    PdfTextEvidence,
    classify_pdf_content,
)

logger = logging.getLogger(__name__)

PDF_TEXT_BUDGET_SECONDS = 3.0
PDF_TEXT_CHUNK_SIZE = 512
PDF_MAX_CHARACTERS_PER_PAGE = 4096


class _PdfTextPage(Protocol):
    def count_chars(self) -> int: ...

    def get_text_range(self, index: int, count: int) -> str: ...

    def close(self) -> None: ...


class _PdfPage(Protocol):
    def get_textpage(self) -> _PdfTextPage: ...

    def close(self) -> None: ...


class _PdfDestination(Protocol):
    def get_index(self) -> int | None: ...


class _PdfBookmark(Protocol):
    level: int

    def get_title(self) -> str | None: ...

    def get_dest(self) -> _PdfDestination | None: ...


class _PdfDocument(Protocol):
    def __getitem__(self, index: int) -> _PdfPage: ...

    def get_toc(self, max_depth: int) -> Iterable[_PdfBookmark]: ...


def inspect_pdf(
    path: Path,
    original_name: str | None = None,
    *,
    clock: Callable[[], float] = monotonic,
    text_budget_seconds: float = PDF_TEXT_BUDGET_SECONDS,
) -> PdfInspection:
    started = clock()
    page_count = 1
    raw_metadata: dict[str, object] = {
        "sourceFileName": original_name or path.name,
    }
    chapters: list[PdfChapter] = []
    evidence = PdfTextEvidence(
        inspected_pages=0,
        total_pages=page_count,
        maximum_effective_characters=0,
        completed=False,
        reason="inspection-error",
        elapsed_ms=0,
    )
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page_count = max(1, len(pdf))
            raw_metadata.update(pdf.get_metadata_dict() or {})
            chapters.extend(_chapters(pdf))
            evidence = _inspect_text_layer(
                pdf,
                page_count,
                started=started,
                clock=clock,
                budget_seconds=text_budget_seconds,
            )
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001 - PDF backend failures become inspection warnings
        raw_metadata["parseWarning"] = str(exc)
        page_count = max(1, _fallback_pdf_page_count(path))
        evidence = PdfTextEvidence(
            inspected_pages=0,
            total_pages=page_count,
            maximum_effective_characters=0,
            completed=False,
            reason="inspection-error",
            elapsed_ms=_elapsed_ms(started, clock),
        )
        logger.warning(
            "pdf.content-inspection.failed file=%s reason=%s",
            path.name,
            type(exc).__name__,
        )

    raw_metadata.update(_pdf_inline_metadata(path))
    raw_metadata["chapters"] = [chapter.metadata() for chapter in chapters]
    content_kind = classify_pdf_content(evidence)
    raw_metadata["contentClassification"] = {
        "kind": content_kind.value,
        "reason": evidence.reason,
        "inspectedPages": evidence.inspected_pages,
        "totalPages": evidence.total_pages,
        "maximumEffectiveCharacters": evidence.maximum_effective_characters,
        "elapsedMs": evidence.elapsed_ms,
    }
    logger.info(
        "pdf.content-inspection.completed file=%s kind=%s reason=%s "
        "inspected_pages=%s total_pages=%s elapsed_ms=%s",
        path.name,
        content_kind.value,
        evidence.reason,
        evidence.inspected_pages,
        evidence.total_pages,
        evidence.elapsed_ms,
    )
    embedded_title = _usable_pdf_title(raw_metadata.get("Title"))
    embedded_author = _clean_pdf_metadata_text(raw_metadata.get("Author"))
    return PdfInspection(
        title=embedded_title or _title_from_file(Path(original_name or path.name)),
        author=embedded_author or "未知作者",
        embedded_title=embedded_title,
        embedded_author=embedded_author,
        description=_sanitize_description(
            _clean_pdf_metadata_text(raw_metadata.get("Subject")) or ""
        ),
        tags=tuple(
            _split_tags(_clean_pdf_metadata_text(raw_metadata.get("Keywords")) or "")
        ),
        page_count=page_count,
        chapters=tuple(chapters),
        raw_metadata=raw_metadata,
        content_kind=content_kind,
        text_evidence=evidence,
    )


def publish_pdf_cover(
    storage_root: Path,
    source_path: Path,
    work_id: str,
    version_id: str,
    volume_id: str,
) -> PdfCoverPublication:
    target = (
        storage_root / "books" / work_id / version_id / volume_id / "cover.jpg"
    )
    temporary = target.with_suffix(f"{target.suffix}.part")
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(source_path))
        try:
            if len(pdf) < 1:
                return PdfCoverPublication(path=None)
            page = pdf[0]
            try:
                bitmap = page.render(scale=2)
                try:
                    image = bitmap.to_pil().copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.thumbnail((900, 1200))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(temporary, format="JPEG", quality=88, optimize=True)
            os.replace(temporary, target)
            return PdfCoverPublication(path=str(target), rendered_page=1)
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001 - cover adapter contains backend failures
        temporary.unlink(missing_ok=True)
        return PdfCoverPublication(path=None, warning=str(exc))


def _inspect_text_layer(
    pdf: _PdfDocument,
    page_count: int,
    *,
    started: float,
    clock: Callable[[], float],
    budget_seconds: float,
) -> PdfTextEvidence:
    inspected_pages = 0
    maximum_effective_characters = 0
    for page_index in range(page_count):
        if clock() - started >= budget_seconds:
            return _text_evidence(
                inspected_pages,
                page_count,
                maximum_effective_characters,
                False,
                "timeout",
                started,
                clock,
            )
        page = pdf[page_index]
        try:
            text_page = page.get_textpage()
            try:
                page_effective_characters, timed_out = _effective_page_characters(
                    text_page,
                    started=started,
                    clock=clock,
                    budget_seconds=budget_seconds,
                )
            finally:
                text_page.close()
        finally:
            page.close()
        if timed_out:
            return _text_evidence(
                inspected_pages,
                page_count,
                maximum_effective_characters,
                False,
                "timeout",
                started,
                clock,
            )
        inspected_pages += 1
        maximum_effective_characters = max(
            maximum_effective_characters,
            page_effective_characters,
        )
        if page_effective_characters >= 40:
            return _text_evidence(
                inspected_pages,
                page_count,
                maximum_effective_characters,
                False,
                "substantive-text-found",
                started,
                clock,
            )
    return _text_evidence(
        inspected_pages,
        page_count,
        maximum_effective_characters,
        True,
        "no-substantive-text",
        started,
        clock,
    )


def _effective_page_characters(
    text_page: _PdfTextPage,
    *,
    started: float,
    clock: Callable[[], float],
    budget_seconds: float,
) -> tuple[int, bool]:
    available = min(text_page.count_chars(), PDF_MAX_CHARACTERS_PER_PAGE)
    if clock() - started >= budget_seconds:
        return 0, True
    effective = 0
    for offset in range(0, available, PDF_TEXT_CHUNK_SIZE):
        if clock() - started >= budget_seconds:
            return effective, True
        text = text_page.get_text_range(
            offset,
            min(PDF_TEXT_CHUNK_SIZE, available - offset),
        )
        effective += sum(character.isalnum() for character in text)
        if effective >= 40:
            return effective, False
    return effective, False


def _text_evidence(
    inspected_pages: int,
    total_pages: int,
    maximum_effective_characters: int,
    completed: bool,
    reason: str,
    started: float,
    clock: Callable[[], float],
) -> PdfTextEvidence:
    return PdfTextEvidence(
        inspected_pages=inspected_pages,
        total_pages=total_pages,
        maximum_effective_characters=maximum_effective_characters,
        completed=completed,
        reason=reason,
        elapsed_ms=_elapsed_ms(started, clock),
    )


def _elapsed_ms(started: float, clock: Callable[[], float]) -> int:
    return max(0, round((clock() - started) * 1000))


def _chapters(pdf: _PdfDocument) -> list[PdfChapter]:
    chapters: list[PdfChapter] = []
    for bookmark in pdf.get_toc(max_depth=20):
        title = str(bookmark.get_title() or "").strip()
        destination = bookmark.get_dest()
        page_index = destination.get_index() if destination is not None else None
        if title:
            chapters.append(
                PdfChapter(
                    title=title,
                    page_number=page_index + 1 if page_index is not None else None,
                    level=int(bookmark.level),
                )
            )
    return chapters


def _pdf_inline_metadata(path: Path) -> dict[str, str]:
    try:
        content = path.read_bytes()
    except OSError:
        return {}
    metadata: dict[str, str] = {}
    for key in ["Title", "Author", "Subject", "Keywords"]:
        match = re.search(
            rb"/" + key.encode("ascii") + rb"\s*\(([^()]*)\)", content, re.DOTALL
        )
        if match:
            value = _decode_pdf_literal(match.group(1))
            if value:
                metadata[key] = value
    return metadata


def _decode_pdf_literal(value: bytes) -> str | None:
    unescaped = _unescape_pdf_literal(value)
    try:
        if unescaped.startswith(b"\xfe\xff"):
            payload = unescaped[2:]
            if len(payload) % 2:
                return None
            decoded = payload.decode("utf-16-be")
        elif unescaped.startswith(b"\xff\xfe"):
            payload = unescaped[2:]
            if len(payload) % 2:
                return None
            decoded = payload.decode("utf-16-le")
        else:
            decoded = unescaped.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return _clean_pdf_metadata_text(decoded)


def _unescape_pdf_literal(value: bytes) -> bytes:
    decoded = bytearray()
    index = 0
    simple_escapes = {
        ord("n"): ord("\n"),
        ord("r"): ord("\r"),
        ord("t"): ord("\t"),
        ord("b"): ord("\b"),
        ord("f"): ord("\f"),
        ord("("): ord("("),
        ord(")"): ord(")"),
        ord("\\"): ord("\\"),
    }
    while index < len(value):
        current = value[index]
        if current != ord("\\") or index + 1 >= len(value):
            decoded.append(current)
            index += 1
            continue
        escaped = value[index + 1]
        if escaped in simple_escapes:
            decoded.append(simple_escapes[escaped])
            index += 2
            continue
        if escaped in (ord("\r"), ord("\n")):
            index += 2
            if (
                escaped == ord("\r")
                and index < len(value)
                and value[index] == ord("\n")
            ):
                index += 1
            continue
        if ord("0") <= escaped <= ord("7"):
            octal_end = index + 1
            while (
                octal_end < len(value)
                and octal_end < index + 4
                and ord("0") <= value[octal_end] <= ord("7")
            ):
                octal_end += 1
            decoded.append(int(value[index + 1 : octal_end], 8) & 0xFF)
            index = octal_end
            continue
        decoded.append(escaped)
        index += 2
    return bytes(decoded)


def _clean_pdf_metadata_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or "\ufffd" in text:
        return None
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        return None
    return text


def _usable_pdf_title(value: object) -> str | None:
    title = _clean_pdf_metadata_text(value)
    if title is None:
        return None
    normalized = re.sub(r"[\s._-]+", "", title).casefold()
    if normalized in {"cover", "frontcover", "title", "untitled", "封面", "封皮"}:
        return None
    return title


def _fallback_pdf_page_count(path: Path) -> int:
    try:
        content = path.read_bytes()
    except OSError:
        return 1
    matches = re.findall(rb"/Type\s*/Page\b", content)
    return len(matches) or 1


def _title_from_file(path: Path) -> str:
    return re.sub(r"[_-]+", " ", path.stem).strip() or path.name


def _sanitize_description(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()
    return cleaned or None


def _split_tags(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，;]", value) if part.strip()]
