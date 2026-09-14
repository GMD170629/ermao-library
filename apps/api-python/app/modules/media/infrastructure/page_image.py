"""Shared page image rendering for previews and first-page covers."""

from __future__ import annotations

import io
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from PIL import Image, ImageOps, UnidentifiedImageError

from app.infrastructure.comic_archives import ComicArchiveError, open_comic_archive
from app.modules.media.application.resource_preview import (
    ResourcePreviewNotFoundError,
    ResourcePreviewUnavailableError,
)

PREVIEW_MAX_EDGE = 480
PREVIEW_WEBP_QUALITY = 75


@dataclass(frozen=True, slots=True)
class PageImageSource:
    resource_format: str
    path: Path
    page_entry: str | None = None


class _PdfBitmap(Protocol):
    def to_pil(self) -> Image.Image: ...

    def close(self) -> None: ...


class _PdfPage(Protocol):
    def render(self, *, scale: int) -> _PdfBitmap: ...

    def close(self) -> None: ...


class _PdfDocument(Protocol):
    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> _PdfPage: ...

    def close(self) -> None: ...


class _PdfiumModule(Protocol):
    def PdfDocument(self, path: str) -> _PdfDocument: ...


class ResourcePreviewRenderCoordinator:
    """Bound expensive PDFium work so concurrent thumbnail requests stay reliable."""

    def __init__(self, *, max_concurrent_pdf_renders: int = 1) -> None:
        if max_concurrent_pdf_renders < 1:
            raise ValueError("max_concurrent_pdf_renders must be positive")
        self._pdf_slots = threading.BoundedSemaphore(max_concurrent_pdf_renders)

    @contextmanager
    def pdf_render_slot(self) -> Iterator[None]:
        self._pdf_slots.acquire()
        try:
            yield
        finally:
            self._pdf_slots.release()


class PageImageRenderer:
    def __init__(self, coordinator: ResourcePreviewRenderCoordinator) -> None:
        self._render_coordinator = coordinator

    def render(self, source: PageImageSource, page_index: int) -> bytes:
        try:
            if source.resource_format == "PDF":
                with self._render_coordinator.pdf_render_slot():
                    pdfium = cast(_PdfiumModule, import_module("pypdfium2"))
                    document = pdfium.PdfDocument(str(source.path))
                    try:
                        if page_index >= len(document):
                            raise ResourcePreviewNotFoundError
                        page = document[page_index]
                        try:
                            bitmap = page.render(scale=1)
                            try:
                                with bitmap.to_pil() as rendered:
                                    image = rendered.copy()
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
                    finally:
                        document.close()
            elif source.page_entry is not None:
                with open_comic_archive(source.path) as archive:
                    content = archive.read(source.page_entry)
                image = Image.open(io.BytesIO(content))
            else:
                image = Image.open(source.path)
            with image:
                prepared = ImageOps.exif_transpose(image)
                if getattr(prepared, "is_animated", False):
                    prepared.seek(0)
                prepared.thumbnail(
                    (PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE),
                    Image.Resampling.LANCZOS,
                )
                if prepared.mode not in {"RGB", "RGBA"}:
                    prepared = prepared.convert(
                        "RGBA" if "transparency" in prepared.info else "RGB"
                    )
                output = io.BytesIO()
                prepared.save(
                    output,
                    format="WEBP",
                    quality=PREVIEW_WEBP_QUALITY,
                    method=4,
                )
                return output.getvalue()
        except ResourcePreviewNotFoundError:
            raise
        except (
            Image.DecompressionBombError,
            ComicArchiveError,
            KeyError,
            OSError,
            RuntimeError,
            ValueError,
            UnidentifiedImageError,
        ) as exc:
            raise ResourcePreviewUnavailableError from exc
