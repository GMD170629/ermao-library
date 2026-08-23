"""Filesystem and PDFium implementation of resource page previews."""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import false, select, true
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.natural_sort import natural_sort_key
from app.infrastructure.comic_archives import ComicArchiveError, open_comic_archive
from app.models import (
    Library,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
)
from app.modules.media.application.resource_preview import (
    ResourcePreviewAccessScope,
    ResourcePreviewData,
    ResourcePreviewNotFoundError,
    ResourcePreviewUnavailableError,
)

PREVIEW_MAX_EDGE = 480
PREVIEW_WEBP_QUALITY = 75
PREVIEW_CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class _PreviewSource:
    resource_format: str
    path: Path
    page_entry: str | None


class _PdfBitmap(Protocol):
    def to_pil(self) -> Image.Image: ...


class _PdfPage(Protocol):
    def render(self, *, scale: int) -> _PdfBitmap: ...

    def close(self) -> None: ...


class _PdfDocument(Protocol):
    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> _PdfPage: ...

    def close(self) -> None: ...


class _PdfiumModule(Protocol):
    def PdfDocument(self, path: str) -> _PdfDocument: ...


class FilesystemResourcePreview:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def load(
        self,
        *,
        scope: ResourcePreviewAccessScope,
        resource_id: str,
        page_index: int,
    ) -> ResourcePreviewData:
        source = self._source(scope, resource_id, page_index)
        stat = source.path.stat()
        identity = (
            f"resource-preview-v{PREVIEW_CACHE_VERSION}:{source.resource_format}:"
            f"{source.path}:{stat.st_size}:{stat.st_mtime_ns}:"
            f"{source.page_entry or ''}:{page_index}:edge-{PREVIEW_MAX_EDGE}:"
            f"quality-{PREVIEW_WEBP_QUALITY}"
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        cache_path = (
            self._settings.resolved_storage_root
            / "cache"
            / "resource-previews"
            / digest[:2]
            / f"{digest}.webp"
        )
        content = cache_path.read_bytes() if cache_path.is_file() else None
        if content is None:
            content = self._render(source, page_index)
            self._publish(cache_path, content)
        return ResourcePreviewData(
            content=content,
            media_type="image/webp",
            etag=f'"resource-preview-{digest[:32]}"',
        )

    def _source(
        self,
        scope: ResourcePreviewAccessScope,
        resource_id: str,
        page_index: int,
    ) -> _PreviewSource:
        resource = self._db.scalar(
            select(LibraryReadableResource).where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                (
                    true()
                    if scope.is_admin
                    else LibraryReadableResource.library_id.in_(scope.library_ids)
                    if scope.library_ids
                    else false()
                ),
            )
        )
        if resource is None:
            raise ResourcePreviewNotFoundError
        resource_format = resource.format.strip().upper()
        if resource_format == "PDF":
            asset = self._asset_source(resource_id, roles={"PRIMARY"})
            if asset is None:
                raise ResourcePreviewNotFoundError
            return _PreviewSource(resource_format, asset[0], None)
        if resource_format in {"CBZ", "ZIP", "CBR", "RAR"}:
            unit = self._db.scalar(
                select(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.resource_id == resource_id,
                    ReadableResourceNavigationUnit.unit_type == "page",
                    ReadableResourceNavigationUnit.sort_order == page_index,
                )
            )
            if unit is None:
                raise ResourcePreviewNotFoundError
            asset = self._asset_source(resource_id, roles={"PRIMARY"})
            if asset is None:
                raise ResourcePreviewNotFoundError
            return _PreviewSource(resource_format, asset[0], unit.href)
        if resource_format == "IMAGE_DIR":
            assets = self._asset_sources(resource_id, roles={"PAGE"})
            if page_index >= len(assets):
                raise ResourcePreviewNotFoundError
            return _PreviewSource(resource_format, assets[page_index][0], None)
        raise ResourcePreviewNotFoundError

    def _asset_source(
        self, resource_id: str, *, roles: set[str]
    ) -> tuple[Path, str] | None:
        assets = self._asset_sources(resource_id, roles=roles)
        return assets[0] if assets else None

    def _asset_sources(
        self, resource_id: str, *, roles: set[str]
    ) -> list[tuple[Path, str]]:
        rows = self._db.execute(
            select(
                LibrarySourceNode.relative_path,
                LibrarySourceNode.name,
                LibraryResourceAsset.sort_key,
                Library.root_path,
                LibraryResourceAsset.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .join(Library, Library.id == LibraryResourceAsset.library_id)
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.role.in_(roles),
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
        ).all()
        ordered = sorted(
            rows,
            key=lambda row: (
                natural_sort_key(str(row.sort_key or row.name)),
                str(row.id),
            ),
        )
        sources: list[tuple[Path, str]] = []
        for row in ordered:
            path = self._safe_source_path(str(row.root_path), str(row.relative_path))
            if path is not None:
                sources.append((path, str(row.name)))
        return sources

    @staticmethod
    def _safe_source_path(root_value: str, relative_value: str) -> Path | None:
        try:
            root = Path(root_value).expanduser().resolve(strict=True)
            candidate = root.joinpath(*Path(relative_value).parts)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        if resolved != candidate or not resolved.is_file():
            return None
        return resolved

    @staticmethod
    def _render(source: _PreviewSource, page_index: int) -> bytes:
        try:
            if source.resource_format == "PDF":
                pdfium = cast(_PdfiumModule, import_module("pypdfium2"))
                document = pdfium.PdfDocument(str(source.path))
                try:
                    if page_index >= len(document):
                        raise ResourcePreviewNotFoundError
                    page = document[page_index]
                    try:
                        image = page.render(scale=1).to_pil()
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
            ComicArchiveError,
            KeyError,
            OSError,
            RuntimeError,
            ValueError,
            UnidentifiedImageError,
        ) as exc:
            raise ResourcePreviewUnavailableError from exc

    @staticmethod
    def _publish(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


__all__ = ["FilesystemResourcePreview"]
