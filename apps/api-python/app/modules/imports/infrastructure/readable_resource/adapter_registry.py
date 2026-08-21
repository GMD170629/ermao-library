"""Format adapters: suffix match at discovery; content parse only in worker I/O."""

from __future__ import annotations

from pathlib import Path

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


class RegistryResourceAdapterExecutor(ResourceAdapterExecutorPort):
    """Wraps existing inspection helpers behind the target adapter port."""

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
    ) -> FileParseResult:
        try:
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
            try:
                if adapter.adapter_id is ResourceAdapterId.EPUB:
                    title = self._inspect_epub_title(absolute_path) or title
                elif adapter.adapter_id is ResourceAdapterId.PDF:
                    title = self._inspect_pdf_title(absolute_path) or title
                elif adapter.adapter_id in {
                    ResourceAdapterId.TXT,
                    ResourceAdapterId.KINDLE,
                }:
                    title = self._inspect_reflowable_title(absolute_path) or title
                elif adapter.adapter_id is ResourceAdapterId.COMIC_ARCHIVE:
                    title = self._inspect_comic_title(absolute_path) or title
                elif adapter.adapter_id in {
                    ResourceAdapterId.AUDIO_FILE,
                    ResourceAdapterId.AUDIOBOOK_DIRECTORY,
                }:
                    title = self._inspect_audio_title(absolute_path) or title
            except Exception:
                title = absolute_path.stem
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
        except Exception as error:
            return FileParseResult(
                ok=False,
                adapter=adapter,
                resource_title=None,
                asset=None,
                error_code="PARSE_FAILED",
                error_summary=str(error.__class__.__name__),
            )

    def _inspect_epub_title(self, path: Path) -> str | None:
        from app.modules.imports.application.import_epub import parse_epub_metadata

        metadata = parse_epub_metadata(path)
        title = metadata.get("title")
        return title if isinstance(title, str) else None

    def _inspect_pdf_title(self, path: Path) -> str | None:
        from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf

        inspection = inspect_pdf(path)
        return getattr(inspection, "title", None)

    def _inspect_reflowable_title(self, path: Path) -> str | None:
        from app.modules.imports.infrastructure.reflowable_metadata import (
            inspect_reflowable_book,
        )

        inspection = inspect_reflowable_book(path)
        return getattr(inspection, "title", None)

    def _inspect_comic_title(self, path: Path) -> str | None:
        from app.infrastructure.comic_archives import inspect_comic_archive

        inspection = inspect_comic_archive(path)
        title = inspection.get("title")
        return title if isinstance(title, str) else path.stem

    def _inspect_audio_title(self, path: Path) -> str | None:
        from app.services.audio_metadata import parse_audio_metadata

        metadata = parse_audio_metadata(path)
        if metadata is None:
            return path.stem
        return getattr(metadata, "title", None) or path.stem
