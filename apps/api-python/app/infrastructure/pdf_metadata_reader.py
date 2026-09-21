"""Bounded PDF cross-reference access without repair or whole-file scanning."""

import re
from typing import IO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class StrictMetadataPdfReader(PdfReader):
    def _find_eof_marker(self, stream: IO[bytes]) -> None:
        end = stream.seek(0, 2)
        start = max(0, end - 65558)
        stream.seek(start)
        tail = stream.read(end - start)
        matches = list(re.finditer(rb"startxref\s+(\d+)\s+%%EOF", tail))
        if not matches:
            raise PdfReadError("Import PDF trailer unavailable in tail window")
        self._import_startxref = int(matches[-1].group(1))

    def _find_startxref_pos(self, stream: IO[bytes]) -> int:
        return self._import_startxref

    def _rebuild_xref_table(self, stream: IO[bytes]) -> None:
        raise PdfReadError("Import does not repair PDF cross references")
