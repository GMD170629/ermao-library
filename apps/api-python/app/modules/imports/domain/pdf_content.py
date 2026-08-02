"""Pure PDF content classification policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PdfContentKind(StrEnum):
    TEXTUAL = "TEXTUAL"
    IMAGE_ONLY = "IMAGE_ONLY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PdfTextEvidence:
    inspected_pages: int
    total_pages: int
    maximum_effective_characters: int
    completed: bool
    reason: str
    elapsed_ms: int


def classify_pdf_content(evidence: PdfTextEvidence) -> PdfContentKind:
    """Classify using extracted page text without depending on PDF tooling."""

    if evidence.maximum_effective_characters >= 40:
        return PdfContentKind.TEXTUAL
    if evidence.completed and evidence.inspected_pages >= evidence.total_pages:
        return PdfContentKind.IMAGE_ONLY
    return PdfContentKind.UNKNOWN
