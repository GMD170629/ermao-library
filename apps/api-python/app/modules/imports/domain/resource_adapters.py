"""File and directory resource adapter identity and suffix matching."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_COMIC_PROFILE,
    READER_SAFETY_FORMATS,
    ReaderSafetyFormat,
    ReaderSafetyMorphology,
)
from app.modules.imports.application.audio_types import SUPPORTED_AUDIO_EXTS
from app.modules.library.public import AssetRole


class ResourceAdapterId(str, Enum):
    EPUB = "epub"
    PDF = "pdf"
    TXT = "txt"
    MOBI_FAMILY = "mobi-family"
    COMIC_ARCHIVE = "comic-archive"
    AUDIO_FILE = "audio-file"
    AUDIOBOOK_DIRECTORY = "audiobook-directory"
    IMAGE_DIRECTORY = "image-directory"


@dataclass(frozen=True, slots=True)
class ResourceAdapterSpec:
    adapter_id: ResourceAdapterId
    adapter_version: str
    format_label: str
    file_extensions: frozenset[str]
    is_directory_adapter: bool
    asset_role: AssetRole
    minimum_ready_assets: int
    # Most adapters have one stable format label. Adapters that accept
    # multiple concrete source containers can opt into an explicit
    # suffix-to-format mapping.
    format_by_extension: tuple[tuple[str, str], ...] = ()


def _format_mapping(
    *formats: ReaderSafetyFormat,
) -> tuple[tuple[str, str], ...]:
    mappings: list[tuple[str, str]] = []
    for source_format in formats:
        extension = READER_SAFETY_FORMATS[source_format].extension
        if extension is None:
            raise RuntimeError(
                f"generated Reader safety format {source_format.value} has no extension"
            )
        mappings.append((extension, source_format.value))
    return tuple(mappings)


def _format_extensions(
    mappings: tuple[tuple[str, str], ...],
) -> frozenset[str]:
    return frozenset(extension for extension, _source_format in mappings)


_EPUB_FORMATS = _format_mapping(ReaderSafetyFormat.EPUB)
_PDF_FORMATS = _format_mapping(ReaderSafetyFormat.PDF)
_TEXT_FORMATS = _format_mapping(ReaderSafetyFormat.TXT, ReaderSafetyFormat.FB2)
_MOBI_FAMILY_FORMATS = _format_mapping(
    ReaderSafetyFormat.MOBI,
    ReaderSafetyFormat.AZW,
    ReaderSafetyFormat.AZW3,
    ReaderSafetyFormat.PRC,
)
_COMIC_ARCHIVE_FORMATS = _format_mapping(
    ReaderSafetyFormat.CBZ,
    ReaderSafetyFormat.CBR,
    ReaderSafetyFormat.ZIP,
    ReaderSafetyFormat.RAR,
)


ADAPTER_SPECS: tuple[ResourceAdapterSpec, ...] = (
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.EPUB,
        adapter_version="1",
        format_label=ReaderSafetyFormat.EPUB.value,
        file_extensions=_format_extensions(_EPUB_FORMATS),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.PDF,
        adapter_version="1",
        format_label=ReaderSafetyFormat.PDF.value,
        file_extensions=_format_extensions(_PDF_FORMATS),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.TXT,
        adapter_version="2",
        format_label=ReaderSafetyFormat.TXT.value,
        file_extensions=_format_extensions(_TEXT_FORMATS),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
        format_by_extension=_TEXT_FORMATS,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.MOBI_FAMILY,
        adapter_version="2",
        format_label=ReaderSafetyFormat.MOBI.value,
        file_extensions=_format_extensions(_MOBI_FAMILY_FORMATS),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
        format_by_extension=_MOBI_FAMILY_FORMATS,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.COMIC_ARCHIVE,
        adapter_version="1",
        format_label=ReaderSafetyMorphology.COMIC.value.upper(),
        file_extensions=_format_extensions(_COMIC_ARCHIVE_FORMATS),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
        format_by_extension=_COMIC_ARCHIVE_FORMATS,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.AUDIO_FILE,
        adapter_version="1",
        format_label=ReaderSafetyFormat.AUDIO.value,
        file_extensions=SUPPORTED_AUDIO_EXTS,
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.AUDIOBOOK_DIRECTORY,
        adapter_version="1",
        format_label=ReaderSafetyFormat.AUDIOBOOK_DIR.value,
        file_extensions=SUPPORTED_AUDIO_EXTS,
        is_directory_adapter=True,
        asset_role=AssetRole.TRACK,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.IMAGE_DIRECTORY,
        adapter_version="1",
        format_label=ReaderSafetyFormat.IMAGE_DIR.value,
        file_extensions=frozenset(
            READER_SAFETY_COMIC_PROFILE.page_mime_types_by_extension
        ),
        is_directory_adapter=True,
        asset_role=AssetRole.PAGE,
        minimum_ready_assets=1,
    ),
)


def file_extension(name: str) -> str:
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def is_supported_source_tree_filename(filename: str) -> bool:
    """Return whether any enabled file or directory adapter consumes the suffix."""

    extension = file_extension(filename)
    return bool(extension) and any(
        extension in spec.file_extensions for spec in ADAPTER_SPECS
    )


def match_file_adapters(filename: str) -> tuple[ResourceAdapterSpec, ...]:
    extension = file_extension(filename)
    if not extension:
        return ()
    return tuple(
        spec
        for spec in ADAPTER_SPECS
        if not spec.is_directory_adapter and extension in spec.file_extensions
    )


def source_format_for_filename(spec: ResourceAdapterSpec, filename: str) -> str:
    """Resolve the concrete stored format for one accepted source filename.

    ``format`` describes the actual source container consumed by the
    Reader (for example ``CBZ``).  A spec without an explicit mapping keeps
    its stable format label; this makes the few intentional generic labels
    explicit instead of deriving arbitrary values from every suffix.
    """

    extension = file_extension(filename)
    if extension not in spec.file_extensions:
        raise ValueError(
            f"source filename extension {extension!r} is not accepted by "
            f"adapter {spec.adapter_id.value}"
        )
    for mapped_extension, source_format in spec.format_by_extension:
        if mapped_extension == extension:
            return source_format
    return spec.format_label


def match_directory_adapters_for_samples(
    sample_filenames: tuple[str, ...],
) -> tuple[ResourceAdapterSpec, ...]:
    if not sample_filenames:
        return ()
    matched: list[ResourceAdapterSpec] = []
    for spec in ADAPTER_SPECS:
        if not spec.is_directory_adapter:
            continue
        if all(
            file_extension(name) in spec.file_extensions for name in sample_filenames
        ):
            matched.append(spec)
    return tuple(matched)


def unique_adapter_or_none(
    matches: tuple[ResourceAdapterSpec, ...],
) -> ResourceAdapterSpec | None:
    if len(matches) == 1:
        return matches[0]
    return None
