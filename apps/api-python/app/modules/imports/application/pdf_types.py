"""Typed PDF inspection results used by the import application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.modules.imports.domain.pdf_content import PdfContentKind, PdfTextEvidence


@dataclass(frozen=True, slots=True)
class PdfChapter:
    title: str
    page_number: int | None
    level: int

    def metadata(self) -> dict[str, object]:
        return {
            "title": self.title,
            "pageNumber": self.page_number,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class PdfInspection:
    title: str
    author: str
    embedded_title: str | None
    embedded_author: str | None
    description: str | None
    tags: tuple[str, ...]
    page_count: int
    chapters: tuple[PdfChapter, ...]
    raw_metadata: Mapping[str, object]
    content_kind: PdfContentKind
    text_evidence: PdfTextEvidence
