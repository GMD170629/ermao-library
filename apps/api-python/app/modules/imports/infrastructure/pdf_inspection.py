"""Import-only PDF structure inspection; no page content or repair scans."""

import logging
from pathlib import Path

from pypdf.errors import PdfReadError
from pypdf.generic import Destination

from app.contracts.publication_metadata import PublicationMetadata
from app.core.exception_diagnostics import record_exception
from app.infrastructure.bounded_inspection import LimitedReader
from app.infrastructure.pdf_embedded_metadata import read_pdf_embedded_metadata
from app.infrastructure.pdf_metadata_reader import StrictMetadataPdfReader
from app.modules.imports.application.pdf_types import PdfChapter, PdfInspection
from app.modules.imports.domain.pdf_content import PdfContentKind, PdfTextEvidence


def inspect_pdf(path: Path, original_name: str | None = None) -> PdfInspection:
    metadata = None
    chapters: list[PdfChapter] = []
    count: int | None = None
    try:
        with LimitedReader(path) as source:
            pdf = StrictMetadataPdfReader(source, strict=True, root_object_recovery_limit=0)
            metadata = read_pdf_embedded_metadata(pdf)
            count = len(pdf.pages)

            def visit(items: list, level: int = 0) -> None:
                if level >= 20:
                    return
                for item in items:
                    if isinstance(item, list):
                        visit(item, level + 1)
                    elif isinstance(item, Destination):
                        index = pdf.get_destination_page_number(item)
                        chapters.append(
                            PdfChapter(
                                str(item.title),
                                index + 1 if index is not None and index >= 0 else None,
                                level,
                            )
                        )

            visit(pdf.outline)
    except (OSError, ValueError, PdfReadError, KeyError, TypeError, RecursionError) as error:
        # Optional metadata inspection cannot turn a readable file into a
        # failed import. Actual reader errors remain owned by the reader.
        record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.pdf_inspection.inspect_pdf.failed", error,
                         context={"step": "inspect_pdf"})
    return PdfInspection(
        embedded_metadata=metadata or PublicationMetadata(),
        fallback_title=Path(original_name or path.name).stem,
        page_count=count,
        chapters=tuple(chapters),
        content_kind=PdfContentKind.UNKNOWN,
        text_evidence=PdfTextEvidence(0, count or 0, 0, False, "not-inspected", 0),
    )
