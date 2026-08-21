"""Format adapters: suffix match at discovery; content parse only in worker I/O."""

from __future__ import annotations

import re
from pathlib import Path
from posixpath import normpath
from zipfile import BadZipFile, ZipFile

from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
)
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterId,
    ResourceAdapterSpec,
)
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.metadata.public import parse_opf_metadata


class RegistryResourceAdapterExecutor(ResourceAdapterExecutorPort):
    """Wraps existing inspection helpers behind the target adapter port."""

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
    ) -> FileParseResult:
        if not absolute_path.is_file():
            return FileParseResult(
                ok=False,
                adapter=adapter,
                resource_title=None,
                asset=None,
                error_code="FILE_MISSING",
                error_summary="source file is not a regular file",
            )
        title = absolute_path.stem
        if adapter.adapter_id is ResourceAdapterId.EPUB:
            title = self._inspect_epub_title(absolute_path) or title
        elif adapter.adapter_id is ResourceAdapterId.PDF:
            title = self._inspect_pdf_title(absolute_path) or title
        elif adapter.adapter_id in {ResourceAdapterId.TXT, ResourceAdapterId.KINDLE}:
            title = (
                self._inspect_reflowable_title(absolute_path, adapter.format_label)
                or title
            )
        elif adapter.adapter_id is ResourceAdapterId.COMIC_ARCHIVE:
            title = self._inspect_comic_title(absolute_path) or title
        elif adapter.adapter_id in {
            ResourceAdapterId.AUDIO_FILE,
            ResourceAdapterId.AUDIOBOOK_DIRECTORY,
        }:
            title = self._inspect_audio_title(absolute_path) or title
        # IMAGE_DIRECTORY pages: filename stem is enough; no archive unpack.
        asset = ParsedAssetPayload(
            title=title,
            role=role,
            sequence_index=None,
            sort_key=absolute_path.name,
            mime_type=None,
            duration_ms=None,
            failure_reason=None,
            technical=AssetTechnicalMetadata(),
        )
        return FileParseResult(
            ok=True,
            adapter=adapter,
            resource_title=title,
            asset=asset,
            error_code=None,
            error_summary=None,
        )

    def _inspect_epub_title(self, path: Path) -> str | None:
        try:
            with ZipFile(path) as archive:
                container = archive.read("META-INF/container.xml")
                match = re.search(
                    rb"full-path\s*=\s*['\"]([^'\"]+)['\"]",
                    container,
                )
                if match is None:
                    return None
                opf_name = normpath(match.group(1).decode("utf-8"))
                if opf_name.startswith(("../", "/")):
                    return None
                metadata = parse_opf_metadata(archive.read(opf_name))
        except (BadZipFile, KeyError, OSError, ValueError):
            return None
        return metadata.title

    def _inspect_pdf_title(self, path: Path) -> str | None:
        from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf

        try:
            inspection = inspect_pdf(path)
        except (OSError, RuntimeError, ValueError):
            return None
        return getattr(inspection, "title", None)

    def _inspect_reflowable_title(
        self, path: Path, source_format: str
    ) -> str | None:
        from app.modules.imports.infrastructure.reflowable_metadata import (
            inspect_reflowable_book,
        )

        try:
            inspection = inspect_reflowable_book(path, source_format)
        except (OSError, ValueError):
            return None
        return getattr(inspection, "title", None)

    def _inspect_comic_title(self, path: Path) -> str | None:
        # Archive metadata is optional for the target identity.  The source
        # filename remains the deterministic fallback; media delivery owns
        # archive inspection separately.
        return path.stem

    def _inspect_audio_title(self, path: Path) -> str | None:
        from app.services.audio_metadata import parse_audio_metadata

        try:
            metadata = parse_audio_metadata(path)
        except (OSError, ValueError):
            return None
        if metadata is None:
            return path.stem
        return getattr(metadata, "title", None) or path.stem
