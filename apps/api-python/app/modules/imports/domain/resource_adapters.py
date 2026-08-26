"""File and directory resource adapter identity and suffix matching."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.modules.library.public import AssetRole


class ResourceAdapterId(str, Enum):
    EPUB = "epub"
    PDF = "pdf"
    TXT = "txt"
    KINDLE = "kindle"
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


ADAPTER_SPECS: tuple[ResourceAdapterSpec, ...] = (
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.EPUB,
        adapter_version="1",
        format_label="EPUB",
        file_extensions=frozenset({".epub"}),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.PDF,
        adapter_version="1",
        format_label="PDF",
        file_extensions=frozenset({".pdf"}),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.TXT,
        adapter_version="2",
        format_label="TXT",
        file_extensions=frozenset({".txt", ".fb2"}),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
        format_by_extension=(
            (".txt", "TXT"),
            (".fb2", "FB2"),
        ),
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.KINDLE,
        adapter_version="1",
        format_label="KINDLE",
        file_extensions=frozenset({".mobi", ".azw", ".azw3", ".prc"}),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.COMIC_ARCHIVE,
        adapter_version="1",
        format_label="COMIC",
        file_extensions=frozenset({".cbz", ".cbr", ".zip", ".rar"}),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
        format_by_extension=(
            (".cbz", "CBZ"),
            (".cbr", "CBR"),
            (".zip", "ZIP"),
            (".rar", "RAR"),
        ),
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.AUDIO_FILE,
        adapter_version="1",
        format_label="AUDIO",
        file_extensions=frozenset(
            {
                ".aac",
                ".flac",
                ".m4a",
                ".m4b",
                ".mp3",
                ".ogg",
                ".opus",
                ".wav",
                ".wma",
            }
        ),
        is_directory_adapter=False,
        asset_role=AssetRole.PRIMARY,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.AUDIOBOOK_DIRECTORY,
        adapter_version="1",
        format_label="AUDIOBOOK_DIR",
        file_extensions=frozenset(
            {
                ".aac",
                ".flac",
                ".m4a",
                ".m4b",
                ".mp3",
                ".ogg",
                ".opus",
                ".wav",
                ".wma",
            }
        ),
        is_directory_adapter=True,
        asset_role=AssetRole.TRACK,
        minimum_ready_assets=1,
    ),
    ResourceAdapterSpec(
        adapter_id=ResourceAdapterId.IMAGE_DIRECTORY,
        adapter_version="1",
        format_label="IMAGE_DIR",
        file_extensions=frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}),
        is_directory_adapter=True,
        asset_role=AssetRole.PAGE,
        minimum_ready_assets=1,
    ),
)


def file_extension(name: str) -> str:
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


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
