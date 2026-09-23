"""Typed PDF inspection results used by the import application."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.publication_metadata import PublicationMetadata
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
    embedded_metadata: PublicationMetadata
    fallback_title: str
    page_count: int | None
    chapters: tuple[PdfChapter, ...]
    content_kind: PdfContentKind
    text_evidence: PdfTextEvidence

    @property
    def title(self) -> str:
        return self.embedded_metadata.title or self.fallback_title

    @property
    def author(self) -> str:
        return self.embedded_metadata.author or "未知作者"
