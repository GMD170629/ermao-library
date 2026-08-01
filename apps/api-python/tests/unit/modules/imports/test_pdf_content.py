from app.modules.imports.domain.pdf_content import (
    PdfContentKind,
    PdfTextEvidence,
    classify_pdf_content,
)


def evidence(
    *,
    maximum_effective_characters: int,
    completed: bool = True,
    inspected_pages: int = 1,
    total_pages: int = 1,
) -> PdfTextEvidence:
    return PdfTextEvidence(
        inspected_pages=inspected_pages,
        total_pages=total_pages,
        maximum_effective_characters=maximum_effective_characters,
        completed=completed,
        reason="test",
        elapsed_ms=0,
    )


def test_pdf_requires_forty_effective_characters_on_one_page() -> None:
    assert (
        classify_pdf_content(evidence(maximum_effective_characters=39))
        is PdfContentKind.IMAGE_ONLY
    )
    assert (
        classify_pdf_content(evidence(maximum_effective_characters=40))
        is PdfContentKind.TEXTUAL
    )


def test_incomplete_pdf_inspection_is_unknown() -> None:
    assert (
        classify_pdf_content(
            evidence(
                maximum_effective_characters=0,
                completed=False,
                inspected_pages=3,
                total_pages=10,
            )
        )
        is PdfContentKind.UNKNOWN
    )
