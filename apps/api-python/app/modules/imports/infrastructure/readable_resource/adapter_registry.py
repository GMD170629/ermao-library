"""Format adapters: suffix match at discovery; content parse only in worker I/O."""

from __future__ import annotations

import re
from pathlib import Path
from posixpath import dirname, join, normpath
from zipfile import BadZipFile, ZipFile

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.modules.imports.application.local_metadata import (
    LocalCoverPayload,
    LocalMetadataCandidate,
    resolve_local_metadata,
)
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
from app.modules.imports.infrastructure.sidecar_opf import discover_sidecar_opf
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.metadata.public import parse_opf_metadata

_MAX_COVER_BYTES = 20 * 1024 * 1024


class RegistryResourceAdapterExecutor(ResourceAdapterExecutorPort):
    """Wraps existing inspection helpers behind the target adapter port."""

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        local_metadata_priority: tuple[
            LocalMetadataSource, ...
        ] = DEFAULT_LOCAL_METADATA_PRIORITY,
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
        embedded = self._inspect_embedded(absolute_path, adapter)
        sidecar = discover_sidecar_opf(absolute_path)
        path_titles = titles_from_local_source(absolute_path.stem)
        candidates = [
            LocalMetadataCandidate(
                source="PATH",
                metadata=PublicationMetadata(
                    title=path_titles.work_title,
                    volume_title=path_titles.volume_title,
                    volume_index=path_titles.volume_index,
                ),
            )
        ]
        if embedded is not None:
            candidates.append(embedded)
        if sidecar is not None:
            candidates.append(
                LocalMetadataCandidate(
                    source="SIDECAR_OPF",
                    metadata=sidecar.metadata,
                    cover=(
                        LocalCoverPayload(sidecar.cover_content)
                        if sidecar.cover_content is not None
                        else None
                    ),
                )
            )
        resolved = resolve_local_metadata(tuple(candidates), local_metadata_priority)
        title = (
            resolved.metadata.volume_title
            or resolved.metadata.title
            or absolute_path.stem
        )
        if adapter.adapter_id is ResourceAdapterId.COMIC_ARCHIVE:
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
            local_metadata=resolved,
        )

    def _inspect_embedded(
        self, path: Path, adapter: ResourceAdapterSpec
    ) -> LocalMetadataCandidate | None:
        if adapter.adapter_id is ResourceAdapterId.EPUB:
            return self._inspect_epub(path)
        if adapter.adapter_id is ResourceAdapterId.PDF:
            return self._inspect_pdf(path)
        if adapter.adapter_id in {ResourceAdapterId.TXT, ResourceAdapterId.KINDLE}:
            return self._inspect_reflowable(path, adapter.format_label)
        return None

    def _inspect_epub(self, path: Path) -> LocalMetadataCandidate | None:
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
                cover = self._epub_cover(archive, opf_name, metadata.cover_href)
        except (BadZipFile, KeyError, OSError, ValueError):
            return None
        return LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=metadata,
            cover=LocalCoverPayload(cover) if cover is not None else None,
        )

    def _inspect_pdf(self, path: Path) -> LocalMetadataCandidate | None:
        from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf

        try:
            inspection = inspect_pdf(path)
        except (OSError, RuntimeError, ValueError):
            return None
        return LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=PublicationMetadata(
                title=inspection.embedded_title,
                authors=(inspection.embedded_author,)
                if inspection.embedded_author
                else (),
                description=inspection.description,
                subjects=inspection.tags,
            ),
        )

    def _inspect_reflowable(
        self, path: Path, source_format: str
    ) -> LocalMetadataCandidate | None:
        from app.modules.imports.infrastructure.reflowable_metadata import (
            inspect_reflowable_book,
        )

        try:
            inspection = inspect_reflowable_book(path, source_format)
        except (OSError, ValueError):
            return None
        titles = titles_from_local_source(
            inspection.title,
            series_name=inspection.series_name,
            volume_index=inspection.series_index,
        )
        return LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=PublicationMetadata(
                title=titles.work_title,
                volume_title=titles.volume_title,
                authors=inspection.authors,
                description=inspection.description,
                subjects=inspection.subjects,
                series_name=inspection.series_name,
                series_index=inspection.series_index,
                volume_index=titles.volume_index,
                language=inspection.language,
                publisher=inspection.publisher,
                published_at=inspection.published_at,
                identifier=inspection.identifier,
                isbn=inspection.isbn,
            ),
            cover=(
                LocalCoverPayload(inspection.cover.content)
                if inspection.cover is not None
                else None
            ),
        )

    def _epub_cover(
        self, archive: ZipFile, opf_name: str, href: str | None
    ) -> bytes | None:
        if not href:
            return None
        member = normpath(join(dirname(opf_name), href.replace("\\", "/")))
        if member.startswith(("../", "/")):
            return None
        try:
            info = archive.getinfo(member)
            if not 0 < info.file_size <= _MAX_COVER_BYTES:
                return None
            content = archive.read(info)
        except (KeyError, OSError, BadZipFile):
            return None
        prefix = content[:16]
        valid = prefix.startswith(
            (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")
        ) or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP")
        return content if valid else None

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
