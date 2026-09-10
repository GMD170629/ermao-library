"""Format adapters: suffix match at discovery; content parse only in worker I/O."""

from __future__ import annotations

import re
from pathlib import Path
from posixpath import dirname, join, normpath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
)
from app.contracts.media_capabilities import resolve_asset_mime_type
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.core.safe_errors import safe_error_message
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
    source_format_for_filename,
)
from app.modules.imports.infrastructure.limited_read import (
    COVER_BYTES,
    METADATA_BYTES,
    InspectionLimitReached,
    ZipInspectionReader,
)
from app.modules.imports.infrastructure.sidecar_opf import (
    discover_directory_sidecar_opf,
    discover_sidecar_opf,
)
from app.modules.library.public import (
    AssetRole,
    is_transparent_audiobook_directory_name,
)
from app.modules.metadata.public import (
    FilesystemLocalMetadataInspector,
    LocalAudioMetadata,
    LocalMetadataCandidate,
    parse_opf_metadata,
)

_MAX_COVER_BYTES = 20 * 1024 * 1024


class RegistryResourceAdapterExecutor(ResourceAdapterExecutorPort):
    """Wraps existing inspection helpers behind the target adapter port."""

    def __init__(
        self, audio_metadata: AudioMetadataInspectorPort | None = None
    ) -> None:
        if audio_metadata is None:
            from app.modules.imports.infrastructure.audio_metadata_inspector import (
                BoundedAudioMetadataInspector,
            )

            audio_metadata = BoundedAudioMetadataInspector()
        self._audio_metadata = audio_metadata
        self._directory_metadata = None
        self._directory_metadata_key: tuple[object, ...] | None = None
        self._local_metadata_inspector = FilesystemLocalMetadataInspector(
            embedded_reader=self.inspect_embedded_local_metadata,
            audio_reader=self.inspect_audio_local_metadata,
            sidecar_reader=self.inspect_sidecar_local_metadata,
        )

    def reset_inspection_cache(self) -> None:
        self._directory_metadata = None
        self._directory_metadata_key = None

    @property
    def local_metadata_inspector(self) -> FilesystemLocalMetadataInspector:
        """Return the shared local metadata inspector used by import parsing."""

        return self._local_metadata_inspector

    def inspect_audio_local_metadata(self, source: Path) -> LocalAudioMetadata:
        """Map the imports audio inspection DTO to the metadata DTO."""

        return self._map_audio_metadata(self._audio_metadata.inspect(source))

    @staticmethod
    def _map_audio_metadata(audio: AudioFileMetadata) -> LocalAudioMetadata:
        return LocalAudioMetadata(
            album=audio.album,
            author=audio.author,
            narrator=audio.narrator,
            series_name=audio.series_name,
            volume_index=audio.volume_index,
            cover_data=audio.cover_data,
        )

    def inspect_sidecar_local_metadata(
        self,
        metadata_source: Path,
        *,
        directory: bool,
    ) -> LocalMetadataCandidate | None:
        """Discover one safe sidecar and map it to a metadata candidate."""

        result = (
            discover_directory_sidecar_opf(metadata_source)
            if directory
            else discover_sidecar_opf(metadata_source)
        )
        if result is None:
            return None
        return LocalMetadataCandidate(
            source="SIDECAR_OPF",
            metadata=result.metadata,
            cover=result.cover_content,
        )

    def inspect_embedded_local_metadata(
        self,
        source: Path,
        source_format: str,
    ) -> LocalMetadataCandidate | None:
        """Inspect format-owned metadata without composing source priority."""

        normalized_format = source_format.strip().upper()
        if normalized_format == "EPUB":
            return self._inspect_epub(source)
        if normalized_format == "PDF":
            inspection = self._inspect_pdf(source)
            return inspection[0] if inspection is not None else None
        if normalized_format in {"TXT", "FB2", "MOBI", "AZW", "AZW3", "PRC"}:
            return self._inspect_reflowable(source, normalized_format)
        return None

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
        with absolute_path.open("rb"):
            pass  # Verify access without consuming source contents.
        navigation_units: tuple[ResourceNavigationUnitInput, ...] = ()
        pdf_page_count: int | None = None
        # OS exceptions quote/escape filenames; parser errors may use the plain path.
        private_path_forms = [str(absolute_path), repr(str(absolute_path))[1:-1]]
        audio_metadata: AudioFileMetadata | None = None
        local_audio_metadata: LocalAudioMetadata | None = None
        embedded: LocalMetadataCandidate | None = None
        if adapter.adapter_id is ResourceAdapterId.PDF:
            pdf_inspection = self._inspect_pdf(absolute_path)
            embedded = pdf_inspection[0] if pdf_inspection is not None else None
            pdf_page_count = pdf_inspection[1] if pdf_inspection is not None else None
            navigation_units = pdf_inspection[2] if pdf_inspection is not None else ()
        elif adapter.adapter_id is ResourceAdapterId.EPUB:
            embedded, navigation_units = self._inspect_epub_details(absolute_path)
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
                    error_summary=safe_error_message(exc, private_path_forms),
                )
            except (OSError, ValueError) as exc:
                return FileParseResult(
                    ok=False,
                    adapter=adapter,
                    resource_title=None,
                    asset=None,
                    error_code="AUDIO_METADATA_INVALID",
                    error_summary=safe_error_message(exc, private_path_forms),
                )
            local_audio_metadata = self._map_audio_metadata(audio_metadata)
        effective_resource_path = resource_absolute_path or (
            absolute_path.parent if adapter.is_directory_adapter else absolute_path
        )
        # Cache only the current image resource within a scan round. A single
        # slot bounds memory; source revisions invalidate it even within a round.
        directory_key: tuple[object, ...] | None = None
        if adapter.adapter_id is ResourceAdapterId.IMAGE_DIRECTORY:
            candidates = (
                effective_resource_path,
                effective_resource_path / "metadata.opf",
                effective_resource_path / f"{effective_resource_path.name}.opf",
                effective_resource_path.with_suffix(".opf"),
            )
            directory_key = (
                effective_resource_path,
                local_metadata_priority,
                tuple(
                    (item.stat().st_mtime_ns, item.stat().st_size)
                    if item.exists()
                    else None
                    for item in candidates
                ),
            )
        if (
            directory_key is not None
            and directory_key == self._directory_metadata_key
            and self._directory_metadata is not None
        ):
            resolved = self._directory_metadata
        else:
            resolved = self._local_metadata_inspector.inspect(
                absolute_path,
                source_format=(
                    "AUDIOBOOK_DIRECTORY"
                    if adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
                    else source_format_for_filename(adapter, absolute_path.name)
                ),
                resource_path=effective_resource_path,
                embedded=embedded,
                audio=local_audio_metadata,
                source_order=local_metadata_priority,
            )
            if directory_key is not None:
                self._directory_metadata_key = directory_key
                self._directory_metadata = resolved
        title = (
            resolved.metadata.volume_title
            or resolved.metadata.title
            or absolute_path.stem
        )
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
            except InspectionLimitReached:
                inspection = None
            except (ComicArchiveError, OSError, ValueError) as exc:
                return FileParseResult(
                    ok=False,
                    adapter=adapter,
                    resource_title=None,
                    asset=None,
                    error_code="COMIC_ARCHIVE_INVALID",
                    error_summary=safe_error_message(exc, private_path_forms),
                    local_metadata=resolved,
                )
            if inspection is not None:
                comic_info = inspection["comicInfo"] or {}
                resolved = self._local_metadata_inspector.inspect(
                    absolute_path,
                    source_format=source_format_for_filename(
                        adapter, absolute_path.name
                    ),
                    resource_path=effective_resource_path,
                    source_order=local_metadata_priority,
                    embedded=LocalMetadataCandidate(
                        source="EMBEDDED",
                        metadata=PublicationMetadata(
                            title=comic_info.get("title"),
                            authors=tuple(
                                value
                                for value in (
                                    comic_info.get("writer")
                                    or comic_info.get("penciller"),
                                )
                                if value
                            ),
                            description=comic_info.get("summary"),
                            publisher=comic_info.get("publisher"),
                            series_name=comic_info.get("series"),
                            subjects=tuple(comic_info.get("tags", [])),
                        ),
                        cover=inspection.get("coverContent"),
                    ),
                )
                title = (
                    resolved.metadata.volume_title or resolved.metadata.title or title
                )
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
            title=(
                absolute_path.stem
                if role is AssetRole.PAGE
                else asset_title
                if audio_metadata is not None
                else title
            ),
            role=role,
            sequence_index=None,
            sort_key=absolute_path.name,
            mime_type=resolve_asset_mime_type(
                resource_format=source_format_for_filename(adapter, absolute_path.name),
                asset_role=role.value,
                filename=absolute_path.name,
                stored_mime_type=mime_type,
            ),
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

    @staticmethod
    def _read_zip_metadata(archive: ZipFile, name: str) -> bytes:
        if archive.getinfo(name).file_size > METADATA_BYTES:
            raise ValueError("metadata inspection limit")
        with archive.open(name) as source:
            content = source.read(METADATA_BYTES + 1)
        if len(content) > METADATA_BYTES:
            raise ValueError("metadata inspection limit")
        return content

    def _inspect_epub(self, path: Path) -> LocalMetadataCandidate | None:
        return self._inspect_epub_details(path)[0]

    def _inspect_epub_details(
        self, path: Path
    ) -> tuple[LocalMetadataCandidate | None, tuple[ResourceNavigationUnitInput, ...]]:
        candidate = None
        units: tuple[ResourceNavigationUnitInput, ...] = ()
        try:
            with ZipInspectionReader(path) as source, ZipFile(source) as archive:
                container = self._read_zip_metadata(archive, "META-INF/container.xml")
                match = re.search(
                    rb"full-path\s*=\s*['\"]([^'\"]+)['\"]",
                    container,
                )
                if match is None:
                    return None, ()
                opf_name = normpath(match.group(1).decode("utf-8"))
                if opf_name.startswith(("../", "/")):
                    return None, ()
                opf_content = self._read_zip_metadata(archive, opf_name)
                metadata = parse_opf_metadata(opf_content)
                candidate = LocalMetadataCandidate(
                    source="EMBEDDED", metadata=metadata, cover=None
                )
                with source.independent_read(METADATA_BYTES + 65558):
                    units = self._epub_navigation(archive, opf_name, opf_content)
                with source.independent_read(COVER_BYTES + 65558):
                    cover = self._epub_cover(archive, opf_name, metadata.cover_href)
        except (BadZipFile, KeyError, OSError, ValueError, ElementTree.ParseError):
            return candidate, units
        return LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=metadata,
            cover=cover,
        ), units

    def _epub_navigation(
        self, archive: ZipFile, opf_name: str, content: bytes
    ) -> tuple[ResourceNavigationUnitInput, ...]:
        root = ElementTree.fromstring(content)
        items = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "item"]
        nav = next(
            (node for node in items if "nav" in node.get("properties", "").split()),
            None,
        )
        if nav is None:
            nav = next(
                (
                    node
                    for node in items
                    if node.get("media-type") == "application/x-dtbncx+xml"
                ),
                None,
            )
        if nav is None:
            return ()
        name = normpath(join(dirname(opf_name), nav.get("href", "")))
        if name.startswith(("../", "/")):
            return ()
        document = ElementTree.fromstring(self._read_zip_metadata(archive, name))
        units: list[ResourceNavigationUnitInput] = []
        entries: list[tuple[str, str]] = []
        if nav.get("media-type") == "application/x-dtbncx+xml":
            for point in document.iter():
                if point.tag.rsplit("}", 1)[-1] != "navPoint":
                    continue
                content_node = next(
                    (
                        child
                        for child in point
                        if child.tag.rsplit("}", 1)[-1] == "content"
                    ),
                    None,
                )
                label = next(
                    (
                        child
                        for child in point
                        if child.tag.rsplit("}", 1)[-1] == "navLabel"
                    ),
                    None,
                )
                if content_node is not None:
                    href = content_node.get("src", "")
                    entries.append(
                        (
                            href,
                            "".join(label.itertext()).strip()
                            if label is not None
                            else href,
                        )
                    )
        else:
            toc = next(
                (
                    node
                    for node in document.iter()
                    if node.tag.rsplit("}", 1)[-1] == "nav"
                    and "toc"
                    in node.get("{http://www.idpf.org/2007/ops}type", "").split()
                ),
                None,
            )
            if toc is None:
                return ()
            entries = [
                (node.get("href", ""), "".join(node.itertext()).strip())
                for node in toc.iter()
                if node.tag.rsplit("}", 1)[-1] == "a"
            ]
        for href, title in entries:
            if not href or ":" in href.split("/", 1)[0]:
                continue
            target = normpath(join(dirname(name), href))
            if target.startswith(("../", "/")):
                continue
            units.append(
                ResourceNavigationUnitInput(
                    unit_type="chapter",
                    title=title or href,
                    href=target,
                    media_type="application/xhtml+xml",
                    sort_order=len(units),
                )
            )
        return tuple(units)

    def _inspect_pdf(
        self, path: Path
    ) -> (
        tuple[
            LocalMetadataCandidate, int | None, tuple[ResourceNavigationUnitInput, ...]
        ]
        | None
    ):
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
            tuple(
                ResourceNavigationUnitInput(
                    unit_type="chapter",
                    title=chapter.title,
                    href=f"#page={chapter.page_number}",
                    media_type="application/pdf",
                    sort_order=index,
                )
                for index, chapter in enumerate(inspection.chapters)
                if chapter.page_number is not None
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
            cover=(inspection.cover.content if inspection.cover is not None else None),
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
        return ()
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
