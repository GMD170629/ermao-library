"""EPUB navigation parser adapter used by legacy reader recovery."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.public import inspect_epub_navigation
from app.modules.reader.application.dto import ReaderRecoveredEpubChapterDto
from app.modules.reader.application.volume_reader import ReaderEpubNavigationParseError


class FileReaderEpubNavigationParser:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()

    def parse(self, source_path: str) -> tuple[ReaderRecoveredEpubChapterDto, ...]:
        candidate = Path(source_path)
        path = candidate if candidate.is_absolute() else self._storage_root / candidate
        try:
            chapters = inspect_epub_navigation(path.resolve())
        except (KeyError, OSError, ValueError) as error:
            raise ReaderEpubNavigationParseError(str(path)) from error
        return tuple(
            ReaderRecoveredEpubChapterDto(
                title=chapter.title,
                href=chapter.href,
                sort_order=chapter.sort_order,
                idref=chapter.idref,
                media_type=chapter.media_type,
            )
            for chapter in chapters
        )


__all__ = ["FileReaderEpubNavigationParser"]
