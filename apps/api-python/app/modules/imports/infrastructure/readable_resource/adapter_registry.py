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
from app.infrastructure.comic_archives import (
    ComicArchiveError,
    inspect_comic_archive,
)
from app.modules.imports.application.audio_types import (
    AudioFileMetadata,
    audio_episode_number,
    audio_mime_type,
)
from app.modules.imports.application.errors import AudioInspectionError
from app.modules.imports.application.local_metadata import (
    LocalCoverPayload,
    LocalMetadataCandidate,
    resolve_local_metadata,
)
from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    AudioMetadataInspectorPort,
    FileParseResult,
    ParsedAssetPayload,
    ResourceAdapterExecutorPort,
    ResourceNavigationUnitInput,
)
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterId,
    ResourceAdapterSpec,
)
from app.modules.imports.infrastructure.sidecar_opf import discover_sidecar_opf
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.public import is_transparent_audiobook_directory_name
from app.modules.metadata.public import parse_opf_metadata

_MAX_COVER_BYTES = 20 * 1024 * 1024


class RegistryResourceAdapterExecutor(ResourceAdapterExecutorPort):
    """Wraps existing inspection helpers behind the target adapter port."""

    def __init__(
        self, audio_metadata: AudioMetadataInspectorPort | None = None
    ) -> None:
        if audio_metadata is None:
            from app.modules.imports.infrastructure.audio_metadata_inspector import (
                MutagenFfprobeAudioMetadataInspector,
            )

            audio_metadata = MutagenFfprobeAudioMetadataInspector()
        self._audio_metadata = audio_metadata

    def parse_file(
        self,
        *,
        absolute_path: Path,
        resource_absolute_path: Path | None = None,
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
        pdf_page_count: int | None = None
        audio_metadata: AudioFileMetadata | None = None
        if adapter.adapter_id is ResourceAdapterId.PDF:
            pdf_inspection = self._inspect_pdf(absolute_path)
            embedded = pdf_inspection[0] if pdf_inspection is not None else None
            pdf_page_count = pdf_inspection[1] if pdf_inspection is not None else None
        elif adapter.adapter_id in {
            ResourceAdapterId.AUDIO_FILE,
            ResourceAdapterId.AUDIOBOOK_DIRECTORY,
        }:
            try:
                audio_metadata = self._audio_metadata.inspect(absolute_path)
            except AudioInspectionError as exc:
                return FileParseResult(
                    ok=False,
                    adapter=adapter,
                    resource_title=None,
                    asset=None,
                    error_code=exc.code,
                    error_summary=str(exc),
                )
            except (OSError, ValueError) as exc:
                return FileParseResult(
                    ok=False,
                    adapter=adapter,
                    resource_title=None,
                    asset=None,
                    error_code="AUDIO_METADATA_INVALID",
                    error_summary=str(exc),
                )
            embedded = LocalMetadataCandidate(
                source="EMBEDDED",
                metadata=PublicationMetadata(
                    title=(
                        audio_metadata.album
                        if adapter.adapter_id is ResourceAdapterId.AUDIO_FILE
                        else None
                    ),
                    authors=(audio_metadata.author,) if audio_metadata.author else (),
                    narrators=(audio_metadata.narrator,)
                    if audio_metadata.narrator
                    else (),
                    series_name=audio_metadata.series_name,
                    volume_index=audio_metadata.volume_index,
                ),
                cover=(
                    LocalCoverPayload(audio_metadata.cover_data)
                    if audio_metadata.cover_data is not None
                    else None
                ),
            )
        else:
            embedded = self._inspect_embedded(absolute_path, adapter)
        effective_resource_path = resource_absolute_path or (
            absolute_path.parent
            if adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
            else absolute_path
        )
        metadata_source = (
            effective_resource_path
            if adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
            else absolute_path
        )
        sidecar = discover_sidecar_opf(metadata_source)
        if (
            sidecar is None
            and adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
        ):
            sidecar = discover_sidecar_opf(absolute_path)
        path_titles = titles_from_local_source(
            metadata_source.name if metadata_source.is_dir() else metadata_source.stem
        )
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
        navigation_units: tuple[ResourceNavigationUnitInput, ...] = ()
        asset_title: str | None = title
        mime_type: str | None = None
        disc_number: int | None = None
        track_number: int | None = None
        if adapter.adapter_id is ResourceAdapterId.COMIC_ARCHIVE:
            try:
                inspection = inspect_comic_archive(
                    absolute_path,
                    original_name=absolute_path.name,
                )
            except (ComicArchiveError, OSError, ValueError) as exc:
                return FileParseResult(
                    ok=False,
                    adapter=adapter,
                    resource_title=None,
                    asset=None,
                    error_code="COMIC_ARCHIVE_INVALID",
                    error_summary=str(exc),
                    local_metadata=resolved,
                )
            title = str(inspection["title"]) or title
            navigation_units = tuple(
                ResourceNavigationUnitInput(
                    unit_type="page",
                    title=str(page["title"]),
                    href=str(page["entryPath"]),
                    media_type=str(page["mediaType"]),
                    sort_order=int(page["index"]) - 1,
                    size=int(page["size"]),
                )
                for page in inspection["pages"]
            )
        elif audio_metadata is not None:
            asset_title = _clean_track_title(audio_metadata.title)
            mime_type = audio_mime_type(absolute_path)
            disc_number = audio_metadata.disc_number or _disc_number_from_path(
                absolute_path, effective_resource_path
            )
            track_number = audio_metadata.track_number or audio_episode_number(
                absolute_path
            )
            navigation_units = _audio_navigation_units(
                audio_metadata,
                title=asset_title or absolute_path.name,
                mime_type=mime_type,
            )
        # IMAGE_DIRECTORY pages: filename stem is enough; no archive unpack.
        asset = ParsedAssetPayload(
            title=asset_title if audio_metadata is not None else title,
            role=role,
            sequence_index=None,
            sort_key=absolute_path.name,
            mime_type=mime_type if audio_metadata is not None else None,
            duration_ms=(
                audio_metadata.duration_ms if audio_metadata is not None else None
            ),
            failure_reason=None,
            technical=AssetTechnicalMetadata(
                codec=audio_metadata.codec if audio_metadata is not None else None,
                bitrate=audio_metadata.bitrate if audio_metadata is not None else None,
                sample_rate=(
                    audio_metadata.sample_rate if audio_metadata is not None else None
                ),
                channels=audio_metadata.channels
                if audio_metadata is not None
                else None,
                disc_number=disc_number,
                track_number=track_number,
                page_count=pdf_page_count,
            ),
            navigation_units=navigation_units,
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

    def _inspect_pdf(self, path: Path) -> tuple[LocalMetadataCandidate, int] | None:
        from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf

        try:
            inspection = inspect_pdf(path)
        except (OSError, RuntimeError, ValueError):
            return None
        return (
            LocalMetadataCandidate(
                source="EMBEDDED",
                metadata=PublicationMetadata(
                    title=inspection.embedded_title,
                    authors=(inspection.embedded_author,)
                    if inspection.embedded_author
                    else (),
                    description=inspection.description,
                    subjects=inspection.tags,
                ),
            ),
            inspection.page_count,
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


def _clean_track_title(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _disc_number_from_path(path: Path, resource_root: Path) -> int | None:
    try:
        parents = path.relative_to(resource_root).parts[:-1]
    except ValueError:
        return None
    for name in reversed(parents):
        if not is_transparent_audiobook_directory_name(name):
            continue
        match = re.search(r"\d{1,6}", name)
        return int(match.group()) if match else 1
    return None


def _audio_navigation_units(
    metadata: AudioFileMetadata,
    *,
    title: str,
    mime_type: str,
) -> tuple[ResourceNavigationUnitInput, ...]:
    chapters = metadata.chapters
    if not chapters:
        return (
            ResourceNavigationUnitInput(
                unit_type="audio_chapter",
                title=title,
                href=f"#t=0,{metadata.duration_ms / 1000:g}",
                media_type=mime_type,
                sort_order=0,
                start_ms=0,
                end_ms=metadata.duration_ms,
                duration_ms=metadata.duration_ms,
            ),
        )
    return tuple(
        ResourceNavigationUnitInput(
            unit_type="audio_chapter",
            title=_clean_track_title(chapter.title) or title,
            href=f"#t={chapter.start_ms / 1000:g},{chapter.end_ms / 1000:g}",
            media_type=mime_type,
            sort_order=index,
            start_ms=chapter.start_ms,
            end_ms=chapter.end_ms,
            duration_ms=chapter.end_ms - chapter.start_ms,
        )
        for index, chapter in enumerate(chapters)
    )
