"""Import-only PDF structure inspection; no page content or repair scans."""

import re
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import Destination

from app.modules.imports.application.pdf_types import PdfChapter, PdfInspection
from app.modules.imports.domain.pdf_content import PdfContentKind, PdfTextEvidence
from app.modules.imports.infrastructure.limited_read import LimitedReader


class _ImportPdfReader(PdfReader):
    def _find_eof_marker(self, stream: BinaryIO) -> None:
        end = stream.seek(0, 2)
        start = max(0, end - 65558)
        stream.seek(start)
        tail = stream.read(end - start)
        matches = list(re.finditer(rb"startxref\s+(\d+)\s+%%EOF", tail))
        if not matches:
            raise PdfReadError("Import PDF trailer unavailable in tail window")
        self._import_startxref = int(matches[-1].group(1))

    def _find_startxref_pos(self, stream: BinaryIO) -> int:
        return self._import_startxref

    def _rebuild_xref_table(self, stream: BinaryIO) -> None:
        raise PdfReadError("Import does not repair PDF cross references")


def inspect_pdf(path: Path, original_name: str | None = None) -> PdfInspection:
    metadata: dict[str, str] = {}
    chapters: list[PdfChapter] = []
    count: int | None = None
    try:
        with LimitedReader(path) as source:
            pdf = _ImportPdfReader(source, strict=True, root_object_recovery_limit=0)
            info = pdf.metadata
            if info:
                metadata = {str(k).lstrip("/"): str(v).strip() for k, v in info.items()}
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
    except (OSError, ValueError, PdfReadError, KeyError, TypeError, RecursionError):
        # Optional metadata inspection cannot turn a readable file into a
        # failed import. Actual reader errors remain owned by the reader.
        pass
    title = metadata.get("Title")
    if title and re.sub(r"[\s._-]+", "", title).casefold() in {
        "cover",
        "frontcover",
        "title",
        "untitled",
        "封面",
        "封皮",
    }:
        title = None
    author = metadata.get("Author")
    return PdfInspection(
        title=title or Path(original_name or path.name).stem,
        author=author or "未知作者",
        embedded_title=title,
        embedded_author=author,
        description=metadata.get("Subject"),
        tags=tuple(filter(None, re.split(r"[,，;]", metadata.get("Keywords", "")))),
        page_count=count,
        chapters=tuple(chapters),
        raw_metadata=metadata,
        content_kind=PdfContentKind.UNKNOWN,
        text_evidence=PdfTextEvidence(0, count or 0, 0, False, "not-inspected", 0),
    )
