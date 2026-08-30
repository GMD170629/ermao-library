"""Generated Reader safety policy. Do not edit by hand."""
# fmt: off
# Generated layout is contract-digest checked; do not reformat.

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class ReaderSafetyAction(StrEnum):
    ALLOW = 'ALLOW'
    BLOCK_RESOURCE = 'BLOCK_RESOURCE'
    REJECT_PUBLICATION = 'REJECT_PUBLICATION'
    SANITIZE = 'SANITIZE'

class ReaderSafetyAlgorithmId(StrEnum):
    ARCHIVE_STRUCTURE = 'ARCHIVE_STRUCTURE'
    AUDIO_CONTAINER_MIME = 'AUDIO_CONTAINER_MIME'
    AUDIO_ENGINE_CODEC = 'AUDIO_ENGINE_CODEC'
    AUDIO_METADATA_BUDGET = 'AUDIO_METADATA_BUDGET'
    AUDIO_REDIRECT_POLICY = 'AUDIO_REDIRECT_POLICY'
    AUDIO_TRACK_CHAPTER_BOUNDS = 'AUDIO_TRACK_CHAPTER_BOUNDS'
    BLOCK_MISSING_OPTIONAL_RESOURCE = 'BLOCK_MISSING_OPTIONAL_RESOURCE'
    BOUNDED_TXT_CHUNK = 'BOUNDED_TXT_CHUNK'
    COMIC_ARCHIVE_BUDGET = 'COMIC_ARCHIVE_BUDGET'
    COMIC_ARCHIVE_STRUCTURE = 'COMIC_ARCHIVE_STRUCTURE'
    COMIC_MANIFEST_REVISION = 'COMIC_MANIFEST_REVISION'
    COMIC_PAGE_FAILURE = 'COMIC_PAGE_FAILURE'
    COMIC_PAGE_MIME = 'COMIC_PAGE_MIME'
    DOCTYPE_ALLOWLIST = 'DOCTYPE_ALLOWLIST'
    DRM_REJECTION = 'DRM_REJECTION'
    EXACT_FORMAT_MIME = 'EXACT_FORMAT_MIME'
    MAX_ARCHIVE_ENTRIES = 'MAX_ARCHIVE_ENTRIES'
    MAX_ARCHIVE_ENTRY_BYTES = 'MAX_ARCHIVE_ENTRY_BYTES'
    MAX_ARCHIVE_EXPANDED_BYTES = 'MAX_ARCHIVE_EXPANDED_BYTES'
    MAX_BINARY_RESOURCE_BYTES = 'MAX_BINARY_RESOURCE_BYTES'
    MAX_COMIC_MANIFEST_BYTES = 'MAX_COMIC_MANIFEST_BYTES'
    MAX_COMIC_PAGE_BYTES = 'MAX_COMIC_PAGE_BYTES'
    MAX_COMIC_PAGE_COUNT = 'MAX_COMIC_PAGE_COUNT'
    MAX_COMPRESSION_RATIO = 'MAX_COMPRESSION_RATIO'
    MAX_FB2_IMAGE_BYTES = 'MAX_FB2_IMAGE_BYTES'
    MAX_FB2_STRUCTURE = 'MAX_FB2_STRUCTURE'
    MAX_MARKUP_BYTES = 'MAX_MARKUP_BYTES'
    MAX_ORIGINAL_BYTES = 'MAX_ORIGINAL_BYTES'
    MAX_TXT_MEMORY = 'MAX_TXT_MEMORY'
    MAX_XML_BYTES = 'MAX_XML_BYTES'
    PDF_ACTIVE_CONTENT = 'PDF_ACTIVE_CONTENT'
    PDF_PAGE_GEOMETRY = 'PDF_PAGE_GEOMETRY'
    PDF_RANGE_PROTOCOL = 'PDF_RANGE_PROTOCOL'
    PDF_RENDER_BUDGET = 'PDF_RENDER_BUDGET'
    REJECT_XML_ENTITY = 'REJECT_XML_ENTITY'
    REQUIRE_READING_ORDER_MARKUP = 'REQUIRE_READING_ORDER_MARKUP'
    SANITIZE_CSS = 'SANITIZE_CSS'
    SANITIZE_MARKUP = 'SANITIZE_MARKUP'
    SANITIZE_SVG = 'SANITIZE_SVG'
    SANITIZE_URI = 'SANITIZE_URI'

class ReaderSafetyErrorCode(StrEnum):
    AUDIO_DURATION_INVALID = 'AUDIO_DURATION_INVALID'
    AUDIO_METADATA_LIMIT = 'AUDIO_METADATA_LIMIT'
    AUDIO_MIME_MISMATCH = 'AUDIO_MIME_MISMATCH'
    AUDIO_SECURITY_REJECTED = 'AUDIO_SECURITY_REJECTED'
    COMIC_MIME_MISMATCH = 'COMIC_MIME_MISMATCH'
    COMIC_PAGE_BLOCKED = 'COMIC_PAGE_BLOCKED'
    COMIC_RESOURCE_CHANGED = 'COMIC_RESOURCE_CHANGED'
    COMIC_SECURITY_REJECTED = 'COMIC_SECURITY_REJECTED'
    ENGINE_CODEC_UNSUPPORTED = 'ENGINE_CODEC_UNSUPPORTED'
    ENGINE_POLICY_ALGORITHM_UNSUPPORTED = 'ENGINE_POLICY_ALGORITHM_UNSUPPORTED'
    PDF_PAGE_LIMIT = 'PDF_PAGE_LIMIT'
    PDF_RANGE_INVALID = 'PDF_RANGE_INVALID'
    PDF_RENDER_LIMIT = 'PDF_RENDER_LIMIT'
    PLATFORM_POLICY_ALGORITHM_UNSUPPORTED = 'PLATFORM_POLICY_ALGORITHM_UNSUPPORTED'
    PUBLICATION_CORRUPT = 'PUBLICATION_CORRUPT'
    PUBLICATION_DRM_UNSUPPORTED = 'PUBLICATION_DRM_UNSUPPORTED'
    PUBLICATION_MIME_MISMATCH = 'PUBLICATION_MIME_MISMATCH'
    PUBLICATION_PARSER_LIMIT = 'PUBLICATION_PARSER_LIMIT'
    PUBLICATION_RESOURCE_BLOCKED = 'PUBLICATION_RESOURCE_BLOCKED'
    PUBLICATION_SECURITY_REJECTED = 'PUBLICATION_SECURITY_REJECTED'
    PUBLICATION_TOO_LARGE = 'PUBLICATION_TOO_LARGE'

class ReaderSafetyConsumer(StrEnum):
    BACKEND = 'BACKEND'
    WEB = 'WEB'
    ANDROID = 'ANDROID'
    IOS = 'IOS'

class ReaderSafetyStage(StrEnum):
    ADMISSION = 'ADMISSION'
    PARSE = 'PARSE'
    SANITIZE = 'SANITIZE'
    RESOURCE = 'RESOURCE'
    RENDER = 'RENDER'
    DELIVERY = 'DELIVERY'
    PLAYBACK = 'PLAYBACK'

class ReaderSafetyMorphology(StrEnum):
    REFLOWABLE = 'REFLOWABLE'
    PDF = 'PDF'
    COMIC = 'COMIC'
    AUDIO = 'AUDIO'

class ReaderSafetyDeliveryMode(StrEnum):
    DOWNLOAD_ORIGINAL = 'DOWNLOAD_ORIGINAL'
    STREAM = 'STREAM'
    PLAYER = 'PLAYER'

class ReaderSafetyFormatLifecycle(StrEnum):
    ACTIVE = 'ACTIVE'
    RECEIVE_ONLY = 'RECEIVE_ONLY'

class ReaderSafetyUriSyntax(StrEnum):
    SCALAR = 'SCALAR'
    SRCSET = 'SRCSET'
    SPACE_SEPARATED = 'SPACE_SEPARATED'
    CSS = 'CSS'

class ReaderSafetyUriPurpose(StrEnum):
    SUBRESOURCE = 'SUBRESOURCE'
    USER_NAVIGATION = 'USER_NAVIGATION'
    ALWAYS_REMOVE = 'ALWAYS_REMOVE'

class ReaderSafetyFormat(StrEnum):
    EPUB = 'EPUB'
    FB2 = 'FB2'
    TXT = 'TXT'
    MOBI = 'MOBI'
    AZW = 'AZW'
    AZW3 = 'AZW3'
    PRC = 'PRC'
    PDF = 'PDF'
    CBZ = 'CBZ'
    ZIP = 'ZIP'
    CBR = 'CBR'
    RAR = 'RAR'
    IMAGE_DIR = 'IMAGE_DIR'
    AUDIO = 'AUDIO'
    AUDIOBOOK_DIR = 'AUDIOBOOK_DIR'
    AUDIOBOOK = 'AUDIOBOOK'
    M4B = 'M4B'
    M4A = 'M4A'
    MP3 = 'MP3'

class ReaderSafetyBudgetName(StrEnum):
    ORIGINAL_MAX_BYTES = 'originalMaxBytes'
    BINARY_RESOURCE_MAX_BYTES = 'binaryResourceMaxBytes'
    ARCHIVE_ENTRY_MAX_COUNT = 'archiveEntryMaxCount'
    ARCHIVE_EXPANDED_MAX_BYTES = 'archiveExpandedMaxBytes'
    ARCHIVE_ENTRY_MAX_BYTES = 'archiveEntryMaxBytes'
    ARCHIVE_COMPRESSION_RATIO_MAX = 'archiveCompressionRatioMax'
    XML_CONTROL_DOCUMENT_MAX_BYTES = 'xmlControlDocumentMaxBytes'
    REFLOWABLE_MARKUP_MAX_BYTES = 'reflowableMarkupMaxBytes'
    FB2_TEXT_MAX_BYTES = 'fb2TextMaxBytes'
    FB2_MAX_DEPTH = 'fb2MaxDepth'
    FB2_MAX_NODES = 'fb2MaxNodes'
    FB2_TEXT_MAX_CHARACTERS = 'fb2TextMaxCharacters'
    FB2_ENCODED_IMAGE_MAX_BYTES = 'fb2EncodedImageMaxBytes'
    FB2_DECODED_IMAGE_MAX_BYTES = 'fb2DecodedImageMaxBytes'
    FB2_DECODED_IMAGES_TOTAL_MAX_BYTES = 'fb2DecodedImagesTotalMaxBytes'
    TXT_MEMORY_MAX_BYTES = 'txtMemoryMaxBytes'
    TXT_CHUNK_MAX_CHARACTERS = 'txtChunkMaxCharacters'
    PDF_PAGE_MAX_COUNT = 'pdfPageMaxCount'
    PDF_RENDER_MAX_PIXELS = 'pdfRenderMaxPixels'
    PDF_CANVAS_MAX_DIMENSION = 'pdfCanvasMaxDimension'
    PDF_RANGE_CHUNK_BYTES = 'pdfRangeChunkBytes'
    PDF_RANGE_REQUEST_MAX_BYTES = 'pdfRangeRequestMaxBytes'
    PDF_RANGE_MAX_CONCURRENT = 'pdfRangeMaxConcurrent'
    PDF_RANGE_MEMORY_CACHE_MAX_BYTES = 'pdfRangeMemoryCacheMaxBytes'
    COMIC_PAGE_MAX_COUNT = 'comicPageMaxCount'
    COMIC_PAGE_MAX_BYTES = 'comicPageMaxBytes'
    COMIC_MANIFEST_MAX_BYTES = 'comicManifestMaxBytes'
    COMIC_EXPANDED_MAX_BYTES = 'comicExpandedMaxBytes'
    COMIC_COMPRESSION_RATIO_MAX = 'comicCompressionRatioMax'
    AUDIO_TRACK_MAX_COUNT = 'audioTrackMaxCount'
    AUDIO_CHAPTER_MAX_COUNT = 'audioChapterMaxCount'
    AUDIO_METADATA_MAX_BYTES = 'audioMetadataMaxBytes'
    AUDIO_ARTWORK_MAX_BYTES = 'audioArtworkMaxBytes'

class ReaderSafetyRuleId(StrEnum):
    COMMON_EXACT_FORMAT_MIME = 'COMMON.EXACT_FORMAT_MIME'
    COMMON_ORIGINAL_MAX_BYTES = 'COMMON.ORIGINAL_MAX_BYTES'
    COMMON_BINARY_RESOURCE_MAX_BYTES = 'COMMON.BINARY_RESOURCE_MAX_BYTES'
    COMMON_DRM_REJECTED = 'COMMON.DRM_REJECTED'
    REFLOWABLE_SAFE_STANDARD_DOCTYPE = 'REFLOWABLE.SAFE_STANDARD_DOCTYPE'
    REFLOWABLE_REJECT_XML_ENTITY = 'REFLOWABLE.REJECT_XML_ENTITY'
    REFLOWABLE_SANITIZE_MARKUP = 'REFLOWABLE.SANITIZE_MARKUP'
    REFLOWABLE_SANITIZE_URI = 'REFLOWABLE.SANITIZE_URI'
    REFLOWABLE_SANITIZE_SVG = 'REFLOWABLE.SANITIZE_SVG'
    REFLOWABLE_SANITIZE_CSS = 'REFLOWABLE.SANITIZE_CSS'
    REFLOWABLE_OPTIONAL_RESOURCE_FAILURE = 'REFLOWABLE.OPTIONAL_RESOURCE_FAILURE'
    REFLOWABLE_REQUIRED_READING_ORDER_MARKUP = 'REFLOWABLE.REQUIRED_READING_ORDER_MARKUP'
    REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES = 'REFLOWABLE.XML_CONTROL_DOCUMENT_MAX_BYTES'
    REFLOWABLE_MARKUP_MAX_BYTES = 'REFLOWABLE.MARKUP_MAX_BYTES'
    EPUB_ARCHIVE_STRUCTURE = 'EPUB.ARCHIVE_STRUCTURE'
    EPUB_ARCHIVE_ENTRY_MAX_COUNT = 'EPUB.ARCHIVE_ENTRY_MAX_COUNT'
    EPUB_ARCHIVE_EXPANDED_MAX_BYTES = 'EPUB.ARCHIVE_EXPANDED_MAX_BYTES'
    EPUB_ARCHIVE_ENTRY_MAX_BYTES = 'EPUB.ARCHIVE_ENTRY_MAX_BYTES'
    EPUB_ARCHIVE_COMPRESSION_RATIO = 'EPUB.ARCHIVE_COMPRESSION_RATIO'
    FB2_STRUCTURE_BUDGET = 'FB2.STRUCTURE_BUDGET'
    FB2_IMAGE_BUDGET = 'FB2.IMAGE_BUDGET'
    TXT_MEMORY_BUDGET = 'TXT.MEMORY_BUDGET'
    TXT_BOUNDED_CHUNK = 'TXT.BOUNDED_CHUNK'
    PDF_DISABLE_ACTIVE_CONTENT = 'PDF.DISABLE_ACTIVE_CONTENT'
    PDF_PAGE_GEOMETRY = 'PDF.PAGE_GEOMETRY'
    PDF_RENDER_BUDGET = 'PDF.RENDER_BUDGET'
    PDF_RANGE_PROTOCOL = 'PDF.RANGE_PROTOCOL'
    COMIC_PAGE_MIME = 'COMIC.PAGE_MIME'
    COMIC_ARCHIVE_STRUCTURE = 'COMIC.ARCHIVE_STRUCTURE'
    COMIC_PAGE_MAX_COUNT = 'COMIC.PAGE_MAX_COUNT'
    COMIC_ARCHIVE_BUDGET = 'COMIC.ARCHIVE_BUDGET'
    COMIC_PAGE_MAX_BYTES = 'COMIC.PAGE_MAX_BYTES'
    COMIC_MANIFEST_MAX_BYTES = 'COMIC.MANIFEST_MAX_BYTES'
    COMIC_PAGE_DECODE_FAILURE = 'COMIC.PAGE_DECODE_FAILURE'
    COMIC_MANIFEST_REVISION = 'COMIC.MANIFEST_REVISION'
    AUDIO_CONTAINER_MIME = 'AUDIO.CONTAINER_MIME'
    AUDIO_ORIGINAL_MAX_BYTES = 'AUDIO.ORIGINAL_MAX_BYTES'
    AUDIO_ENGINE_CODEC = 'AUDIO.ENGINE_CODEC'
    AUDIO_TRACK_AND_CHAPTER_BOUNDS = 'AUDIO.TRACK_AND_CHAPTER_BOUNDS'
    AUDIO_METADATA_BUDGET = 'AUDIO.METADATA_BUDGET'
    AUDIO_REDIRECT_POLICY = 'AUDIO.REDIRECT_POLICY'

class ReaderSafetyPlatformDefenseId(StrEnum):
    XML_EXTERNAL_ENTITY_RESOLUTION_DISABLED = 'XML_EXTERNAL_ENTITY_RESOLUTION_DISABLED'
    DOCUMENT_SCRIPT_EXECUTION_DISABLED = 'DOCUMENT_SCRIPT_EXECUTION_DISABLED'
    DOCUMENT_INITIATED_NETWORK_DISABLED = 'DOCUMENT_INITIATED_NETWORK_DISABLED'
    TRUSTED_RUNTIME_URI_PROVENANCE = 'TRUSTED_RUNTIME_URI_PROVENANCE'
    PDF_ACTIVE_ACTIONS_DISABLED = 'PDF_ACTIVE_ACTIONS_DISABLED'
    ORIGINAL_ARTIFACT_IMMUTABLE = 'ORIGINAL_ARTIFACT_IMMUTABLE'
    NO_SECURITY_FAILURE_PARSER_FALLBACK = 'NO_SECURITY_FAILURE_PARSER_FALLBACK'

@dataclass(frozen=True, slots=True)
class ReaderSafetyFormatDefinition:
    id: ReaderSafetyFormat
    morphology: ReaderSafetyMorphology
    delivery_mode: ReaderSafetyDeliveryMode
    lifecycle: ReaderSafetyFormatLifecycle
    extension: str | None
    canonical_mime_type: str | None
    accepted_mime_types: tuple[str, ...]
    required_consumers: tuple[ReaderSafetyConsumer, ...]

@dataclass(frozen=True, slots=True)
class ReaderSafetyRule:
    id: ReaderSafetyRuleId
    formats: tuple[ReaderSafetyFormat, ...]
    stage: ReaderSafetyStage
    algorithm: ReaderSafetyAlgorithmId
    parameter_refs: tuple[str, ...]
    action: ReaderSafetyAction
    error_code: ReaderSafetyErrorCode | None
    required_consumers: tuple[ReaderSafetyConsumer, ...]

@dataclass(frozen=True, slots=True)
class ReaderSafetyPlatformDefense:
    id: ReaderSafetyPlatformDefenseId
    formats: tuple[ReaderSafetyFormat, ...]
    stage: ReaderSafetyStage
    required_consumers: tuple[ReaderSafetyConsumer, ...]

@dataclass(frozen=True, slots=True)
class ReaderSafetyDoctype:
    name: str
    public_id: str
    system_id: str

@dataclass(frozen=True, slots=True)
class ReaderSafetyUriAttributePolicy:
    elements: tuple[str, ...]
    attribute: str
    syntax: ReaderSafetyUriSyntax
    purpose: ReaderSafetyUriPurpose

@dataclass(frozen=True, slots=True)
class ReaderSafetyReflowableProfile:
    safe_doctypes: tuple[ReaderSafetyDoctype, ...]
    external_dtd_resolution: bool
    reject_internal_subset: bool
    reject_custom_entities: bool
    named_entity_codepoints: Mapping[str, int]
    reading_order_markup_mime_types: tuple[str, ...]
    embedded_image_extensions_by_mime_type: Mapping[str, str]
    sanitized_elements: tuple[str, ...]
    sanitized_attributes: tuple[str, ...]
    sanitized_attribute_prefixes: tuple[str, ...]
    sanitized_meta_http_equiv_values: tuple[str, ...]
    blocked_author_schemes: tuple[str, ...]
    remote_subresource_schemes: tuple[str, ...]
    user_navigation_schemes: tuple[str, ...]
    trusted_runtime_schemes: tuple[str, ...]
    uri_attribute_policies: tuple[ReaderSafetyUriAttributePolicy, ...]
    allowed_font_obfuscation_algorithms: tuple[str, ...]
    svg_sanitized_elements: tuple[str, ...]
    css_text_elements: tuple[str, ...]
    css_sanitized_constructs: tuple[str, ...]
    archive_fatal_findings: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ReaderSafetyPdfProfile:
    blocked_actions: tuple[str, ...]
    require_finite_page_geometry: bool
    require_identity_content_encoding: bool
    require_strong_revision: bool
    allow_whole_response_fallback: bool

@dataclass(frozen=True, slots=True)
class ReaderSafetyComicProfile:
    allowed_page_mime_types: tuple[str, ...]
    page_mime_types_by_extension: Mapping[str, str]
    archive_fatal_findings: tuple[str, ...]
    single_page_decode_failure_action: ReaderSafetyAction
    manifest_revision_required: bool

@dataclass(frozen=True, slots=True)
class ReaderSafetyAudioProfile:
    container_mime_types: Mapping[str, str]
    codec_decision: str
    blocked_redirect_schemes: tuple[str, ...]
    require_finite_non_negative_duration: bool
    require_ordered_track_identity: bool

READER_SAFETY_POLICY_SCHEMA_VERSION: Final = 1
READER_SAFETY_POLICY_VERSION: Final = 1
READER_SAFETY_POLICY_ID: Final = 'shuku.reader-safety'
READER_SAFETY_POLICY_DIGEST: Final = '12f3e2ba610d907fa4ca5eefd0ab2319e000a8b5348c45549c9e2bc721579a46'
READER_SAFETY_IMPLEMENTATION_FAILURE_CODES: Final = (ReaderSafetyErrorCode.ENGINE_POLICY_ALGORITHM_UNSUPPORTED, ReaderSafetyErrorCode.PLATFORM_POLICY_ALGORITHM_UNSUPPORTED)

READER_SAFETY_FORMATS = MappingProxyType({
    ReaderSafetyFormat.EPUB: ReaderSafetyFormatDefinition(ReaderSafetyFormat.EPUB, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.epub', 'application/epub+zip', ('application/epub+zip',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.FB2: ReaderSafetyFormatDefinition(ReaderSafetyFormat.FB2, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.fb2', 'application/x-fictionbook+xml', ('application/x-fictionbook+xml', 'text/xml', 'application/xml'), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.TXT: ReaderSafetyFormatDefinition(ReaderSafetyFormat.TXT, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.txt', 'text/plain', ('text/plain',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.MOBI: ReaderSafetyFormatDefinition(ReaderSafetyFormat.MOBI, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.mobi', 'application/x-mobipocket-ebook', ('application/x-mobipocket-ebook',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.AZW: ReaderSafetyFormatDefinition(ReaderSafetyFormat.AZW, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.azw', 'application/vnd.amazon.ebook', ('application/vnd.amazon.ebook',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.AZW3: ReaderSafetyFormatDefinition(ReaderSafetyFormat.AZW3, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.azw3', 'application/vnd.amazon.ebook', ('application/vnd.amazon.ebook', 'application/x-mobipocket-ebook'), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.PRC: ReaderSafetyFormatDefinition(ReaderSafetyFormat.PRC, ReaderSafetyMorphology.REFLOWABLE, ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL, ReaderSafetyFormatLifecycle.ACTIVE, '.prc', 'application/x-mobipocket-ebook', ('application/x-mobipocket-ebook',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.PDF: ReaderSafetyFormatDefinition(ReaderSafetyFormat.PDF, ReaderSafetyMorphology.PDF, ReaderSafetyDeliveryMode.STREAM, ReaderSafetyFormatLifecycle.ACTIVE, '.pdf', 'application/pdf', ('application/pdf',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.CBZ: ReaderSafetyFormatDefinition(ReaderSafetyFormat.CBZ, ReaderSafetyMorphology.COMIC, ReaderSafetyDeliveryMode.STREAM, ReaderSafetyFormatLifecycle.ACTIVE, '.cbz', 'application/vnd.comicbook+zip', ('application/vnd.comicbook+zip', 'application/x-cbz'), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.ZIP: ReaderSafetyFormatDefinition(ReaderSafetyFormat.ZIP, ReaderSafetyMorphology.COMIC, ReaderSafetyDeliveryMode.STREAM, ReaderSafetyFormatLifecycle.ACTIVE, '.zip', 'application/zip', ('application/zip',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.CBR: ReaderSafetyFormatDefinition(ReaderSafetyFormat.CBR, ReaderSafetyMorphology.COMIC, ReaderSafetyDeliveryMode.STREAM, ReaderSafetyFormatLifecycle.ACTIVE, '.cbr', 'application/vnd.comicbook-rar', ('application/vnd.comicbook-rar', 'application/x-cbr'), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.RAR: ReaderSafetyFormatDefinition(ReaderSafetyFormat.RAR, ReaderSafetyMorphology.COMIC, ReaderSafetyDeliveryMode.STREAM, ReaderSafetyFormatLifecycle.ACTIVE, '.rar', 'application/vnd.rar', ('application/vnd.rar', 'application/x-rar-compressed'), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.IMAGE_DIR: ReaderSafetyFormatDefinition(ReaderSafetyFormat.IMAGE_DIR, ReaderSafetyMorphology.COMIC, ReaderSafetyDeliveryMode.STREAM, ReaderSafetyFormatLifecycle.ACTIVE, None, None, (), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyFormat.AUDIO: ReaderSafetyFormatDefinition(ReaderSafetyFormat.AUDIO, ReaderSafetyMorphology.AUDIO, ReaderSafetyDeliveryMode.PLAYER, ReaderSafetyFormatLifecycle.ACTIVE, None, None, (), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyFormat.AUDIOBOOK_DIR: ReaderSafetyFormatDefinition(ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyMorphology.AUDIO, ReaderSafetyDeliveryMode.PLAYER, ReaderSafetyFormatLifecycle.ACTIVE, None, None, (), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyFormat.AUDIOBOOK: ReaderSafetyFormatDefinition(ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyMorphology.AUDIO, ReaderSafetyDeliveryMode.PLAYER, ReaderSafetyFormatLifecycle.RECEIVE_ONLY, None, None, (), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyFormat.M4B: ReaderSafetyFormatDefinition(ReaderSafetyFormat.M4B, ReaderSafetyMorphology.AUDIO, ReaderSafetyDeliveryMode.PLAYER, ReaderSafetyFormatLifecycle.RECEIVE_ONLY, '.m4b', 'audio/mp4', ('audio/mp4',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyFormat.M4A: ReaderSafetyFormatDefinition(ReaderSafetyFormat.M4A, ReaderSafetyMorphology.AUDIO, ReaderSafetyDeliveryMode.PLAYER, ReaderSafetyFormatLifecycle.RECEIVE_ONLY, '.m4a', 'audio/mp4', ('audio/mp4',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyFormat.MP3: ReaderSafetyFormatDefinition(ReaderSafetyFormat.MP3, ReaderSafetyMorphology.AUDIO, ReaderSafetyDeliveryMode.PLAYER, ReaderSafetyFormatLifecycle.RECEIVE_ONLY, '.mp3', 'audio/mpeg', ('audio/mpeg',), (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
})
READER_SAFETY_BUDGETS = MappingProxyType({
    ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES: 2147483648,
    ReaderSafetyBudgetName.BINARY_RESOURCE_MAX_BYTES: 268435456,
    ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_COUNT: 10000,
    ReaderSafetyBudgetName.ARCHIVE_EXPANDED_MAX_BYTES: 2147483648,
    ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_BYTES: 268435456,
    ReaderSafetyBudgetName.ARCHIVE_COMPRESSION_RATIO_MAX: 200,
    ReaderSafetyBudgetName.XML_CONTROL_DOCUMENT_MAX_BYTES: 16777216,
    ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES: 67108864,
    ReaderSafetyBudgetName.FB2_TEXT_MAX_BYTES: 67108864,
    ReaderSafetyBudgetName.FB2_MAX_DEPTH: 128,
    ReaderSafetyBudgetName.FB2_MAX_NODES: 500000,
    ReaderSafetyBudgetName.FB2_TEXT_MAX_CHARACTERS: 67108864,
    ReaderSafetyBudgetName.FB2_ENCODED_IMAGE_MAX_BYTES: 29360128,
    ReaderSafetyBudgetName.FB2_DECODED_IMAGE_MAX_BYTES: 20971520,
    ReaderSafetyBudgetName.FB2_DECODED_IMAGES_TOTAL_MAX_BYTES: 134217728,
    ReaderSafetyBudgetName.TXT_MEMORY_MAX_BYTES: 67108864,
    ReaderSafetyBudgetName.TXT_CHUNK_MAX_CHARACTERS: 65536,
    ReaderSafetyBudgetName.PDF_PAGE_MAX_COUNT: 20000,
    ReaderSafetyBudgetName.PDF_RENDER_MAX_PIXELS: 12000000,
    ReaderSafetyBudgetName.PDF_CANVAS_MAX_DIMENSION: 4096,
    ReaderSafetyBudgetName.PDF_RANGE_CHUNK_BYTES: 262144,
    ReaderSafetyBudgetName.PDF_RANGE_REQUEST_MAX_BYTES: 1048576,
    ReaderSafetyBudgetName.PDF_RANGE_MAX_CONCURRENT: 2,
    ReaderSafetyBudgetName.PDF_RANGE_MEMORY_CACHE_MAX_BYTES: 8388608,
    ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT: 10000,
    ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES: 33554432,
    ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES: 2097152,
    ReaderSafetyBudgetName.COMIC_EXPANDED_MAX_BYTES: 2147483648,
    ReaderSafetyBudgetName.COMIC_COMPRESSION_RATIO_MAX: 200,
    ReaderSafetyBudgetName.AUDIO_TRACK_MAX_COUNT: 10000,
    ReaderSafetyBudgetName.AUDIO_CHAPTER_MAX_COUNT: 10000,
    ReaderSafetyBudgetName.AUDIO_METADATA_MAX_BYTES: 1048576,
    ReaderSafetyBudgetName.AUDIO_ARTWORK_MAX_BYTES: 20971520,
})
READER_SAFETY_RULES = MappingProxyType({
    ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME: ReaderSafetyRule(ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC, ReaderSafetyFormat.PDF, ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR), ReaderSafetyStage.ADMISSION, ReaderSafetyAlgorithmId.EXACT_FORMAT_MIME, ('formats',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_MIME_MISMATCH, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMMON_ORIGINAL_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.COMMON_ORIGINAL_MAX_BYTES, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC, ReaderSafetyFormat.PDF, ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR), ReaderSafetyStage.ADMISSION, ReaderSafetyAlgorithmId.MAX_ORIGINAL_BYTES, ('budgets.originalMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_TOO_LARGE, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMMON_BINARY_RESOURCE_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.COMMON_BINARY_RESOURCE_MAX_BYTES, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.RESOURCE, ReaderSafetyAlgorithmId.MAX_BINARY_RESOURCE_BYTES, ('budgets.binaryResourceMaxBytes',), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.PUBLICATION_RESOURCE_BLOCKED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMMON_DRM_REJECTED: ReaderSafetyRule(ReaderSafetyRuleId.COMMON_DRM_REJECTED, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC, ReaderSafetyFormat.PDF), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.DRM_REJECTION, ('profiles.reflowable.allowedFontObfuscationAlgorithms',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_DRM_UNSUPPORTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_SAFE_STANDARD_DOCTYPE: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_SAFE_STANDARD_DOCTYPE, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.DOCTYPE_ALLOWLIST, ('profiles.reflowable.safeDoctypes', 'profiles.reflowable.externalDtdResolution'), ReaderSafetyAction.ALLOW, None, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.REJECT_XML_ENTITY, ('profiles.reflowable.rejectInternalSubset', 'profiles.reflowable.rejectCustomEntities', 'profiles.reflowable.externalDtdResolution', 'profiles.reflowable.namedEntityCodepoints'), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_SANITIZE_MARKUP: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_SANITIZE_MARKUP, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.SANITIZE, ReaderSafetyAlgorithmId.SANITIZE_MARKUP, ('profiles.reflowable.sanitizedElements', 'profiles.reflowable.sanitizedAttributes', 'profiles.reflowable.sanitizedAttributePrefixes', 'profiles.reflowable.sanitizedMetaHttpEquivValues'), ReaderSafetyAction.SANITIZE, None, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_SANITIZE_URI: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_SANITIZE_URI, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.SANITIZE, ReaderSafetyAlgorithmId.SANITIZE_URI, ('profiles.reflowable.blockedAuthorSchemes', 'profiles.reflowable.remoteSubresourceSchemes', 'profiles.reflowable.userNavigationSchemes', 'profiles.reflowable.trustedRuntimeSchemes', 'profiles.reflowable.uriAttributePolicies'), ReaderSafetyAction.SANITIZE, None, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_SANITIZE_SVG: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_SANITIZE_SVG, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2), ReaderSafetyStage.SANITIZE, ReaderSafetyAlgorithmId.SANITIZE_SVG, ('profiles.reflowable.svgSanitizedElements', 'profiles.reflowable.sanitizedAttributePrefixes', 'profiles.reflowable.blockedAuthorSchemes', 'profiles.reflowable.remoteSubresourceSchemes'), ReaderSafetyAction.SANITIZE, None, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.SANITIZE, ReaderSafetyAlgorithmId.SANITIZE_CSS, ('profiles.reflowable.cssTextElements', 'profiles.reflowable.cssSanitizedConstructs', 'profiles.reflowable.remoteSubresourceSchemes', 'profiles.reflowable.blockedAuthorSchemes'), ReaderSafetyAction.SANITIZE, None, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.RESOURCE, ReaderSafetyAlgorithmId.BLOCK_MISSING_OPTIONAL_RESOURCE, (), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.PUBLICATION_RESOURCE_BLOCKED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.REQUIRE_READING_ORDER_MARKUP, ('profiles.reflowable.readingOrderMarkupMimeTypes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_CORRUPT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_XML_BYTES, ('budgets.xmlControlDocumentMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_MARKUP_BYTES, ('budgets.reflowableMarkupMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE: ReaderSafetyRule(ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE, (ReaderSafetyFormat.EPUB,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.ARCHIVE_STRUCTURE, ('profiles.reflowable.archiveFatalFindings',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_COUNT: ReaderSafetyRule(ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_COUNT, (ReaderSafetyFormat.EPUB,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_ARCHIVE_ENTRIES, ('budgets.archiveEntryMaxCount',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.EPUB_ARCHIVE_EXPANDED_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.EPUB_ARCHIVE_EXPANDED_MAX_BYTES, (ReaderSafetyFormat.EPUB,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_ARCHIVE_EXPANDED_BYTES, ('budgets.archiveExpandedMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_BYTES, (ReaderSafetyFormat.EPUB,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_ARCHIVE_ENTRY_BYTES, ('budgets.archiveEntryMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.EPUB_ARCHIVE_COMPRESSION_RATIO: ReaderSafetyRule(ReaderSafetyRuleId.EPUB_ARCHIVE_COMPRESSION_RATIO, (ReaderSafetyFormat.EPUB,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_COMPRESSION_RATIO, ('budgets.archiveCompressionRatioMax',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET: ReaderSafetyRule(ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET, (ReaderSafetyFormat.FB2,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_FB2_STRUCTURE, ('budgets.fb2MaxDepth', 'budgets.fb2MaxNodes', 'budgets.fb2TextMaxBytes', 'budgets.fb2TextMaxCharacters'), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.FB2_IMAGE_BUDGET: ReaderSafetyRule(ReaderSafetyRuleId.FB2_IMAGE_BUDGET, (ReaderSafetyFormat.FB2,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_FB2_IMAGE_BYTES, ('budgets.fb2EncodedImageMaxBytes', 'budgets.fb2DecodedImageMaxBytes', 'budgets.fb2DecodedImagesTotalMaxBytes', 'profiles.reflowable.embeddedImageExtensionsByMimeType'), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.PUBLICATION_RESOURCE_BLOCKED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.TXT_MEMORY_BUDGET: ReaderSafetyRule(ReaderSafetyRuleId.TXT_MEMORY_BUDGET, (ReaderSafetyFormat.TXT,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_TXT_MEMORY, ('budgets.txtMemoryMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.TXT_BOUNDED_CHUNK: ReaderSafetyRule(ReaderSafetyRuleId.TXT_BOUNDED_CHUNK, (ReaderSafetyFormat.TXT,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.BOUNDED_TXT_CHUNK, ('budgets.txtChunkMaxCharacters',), ReaderSafetyAction.ALLOW, None, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.PDF_DISABLE_ACTIVE_CONTENT: ReaderSafetyRule(ReaderSafetyRuleId.PDF_DISABLE_ACTIVE_CONTENT, (ReaderSafetyFormat.PDF,), ReaderSafetyStage.SANITIZE, ReaderSafetyAlgorithmId.PDF_ACTIVE_CONTENT, ('profiles.pdf.blockedActions',), ReaderSafetyAction.SANITIZE, None, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.PDF_PAGE_GEOMETRY: ReaderSafetyRule(ReaderSafetyRuleId.PDF_PAGE_GEOMETRY, (ReaderSafetyFormat.PDF,), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.PDF_PAGE_GEOMETRY, ('budgets.pdfPageMaxCount', 'profiles.pdf.requireFinitePageGeometry'), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PDF_PAGE_LIMIT, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.PDF_RENDER_BUDGET: ReaderSafetyRule(ReaderSafetyRuleId.PDF_RENDER_BUDGET, (ReaderSafetyFormat.PDF,), ReaderSafetyStage.RENDER, ReaderSafetyAlgorithmId.PDF_RENDER_BUDGET, ('budgets.pdfRenderMaxPixels', 'budgets.pdfCanvasMaxDimension'), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.PDF_RENDER_LIMIT, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.PDF_RANGE_PROTOCOL: ReaderSafetyRule(ReaderSafetyRuleId.PDF_RANGE_PROTOCOL, (ReaderSafetyFormat.PDF,), ReaderSafetyStage.DELIVERY, ReaderSafetyAlgorithmId.PDF_RANGE_PROTOCOL, ('budgets.pdfRangeChunkBytes', 'budgets.pdfRangeRequestMaxBytes', 'budgets.pdfRangeMaxConcurrent', 'budgets.pdfRangeMemoryCacheMaxBytes', 'profiles.pdf.requireIdentityContentEncoding', 'profiles.pdf.requireStrongRevision', 'profiles.pdf.allowWholeResponseFallback'), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PDF_RANGE_INVALID, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_PAGE_MIME: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_PAGE_MIME, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.RESOURCE, ReaderSafetyAlgorithmId.COMIC_PAGE_MIME, ('profiles.comic.allowedPageMimeTypes', 'profiles.comic.pageMimeTypesByExtension'), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.COMIC_MIME_MISMATCH, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.COMIC_ARCHIVE_STRUCTURE, ('profiles.comic.archiveFatalFindings',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.COMIC_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.MAX_COMIC_PAGE_COUNT, ('budgets.comicPageMaxCount',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.COMIC_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.COMIC_ARCHIVE_BUDGET, ('budgets.comicExpandedMaxBytes', 'budgets.comicCompressionRatioMax'), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.COMIC_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.RESOURCE, ReaderSafetyAlgorithmId.MAX_COMIC_PAGE_BYTES, ('budgets.comicPageMaxBytes',), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.COMIC_PAGE_BLOCKED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_MANIFEST_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_MANIFEST_MAX_BYTES, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.DELIVERY, ReaderSafetyAlgorithmId.MAX_COMIC_MANIFEST_BYTES, ('budgets.comicManifestMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.COMIC_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_PAGE_DECODE_FAILURE: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_PAGE_DECODE_FAILURE, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.RENDER, ReaderSafetyAlgorithmId.COMIC_PAGE_FAILURE, ('profiles.comic.singlePageDecodeFailureAction',), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.COMIC_PAGE_BLOCKED, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.COMIC_MANIFEST_REVISION: ReaderSafetyRule(ReaderSafetyRuleId.COMIC_MANIFEST_REVISION, (ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR), ReaderSafetyStage.DELIVERY, ReaderSafetyAlgorithmId.COMIC_MANIFEST_REVISION, ('profiles.comic.manifestRevisionRequired',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.COMIC_RESOURCE_CHANGED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyRuleId.AUDIO_CONTAINER_MIME: ReaderSafetyRule(ReaderSafetyRuleId.AUDIO_CONTAINER_MIME, (ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyFormat.M4B, ReaderSafetyFormat.M4A, ReaderSafetyFormat.MP3), ReaderSafetyStage.ADMISSION, ReaderSafetyAlgorithmId.AUDIO_CONTAINER_MIME, ('profiles.audio.containerMimeTypes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.AUDIO_MIME_MISMATCH, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyRuleId.AUDIO_ORIGINAL_MAX_BYTES: ReaderSafetyRule(ReaderSafetyRuleId.AUDIO_ORIGINAL_MAX_BYTES, (ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyFormat.M4B, ReaderSafetyFormat.M4A, ReaderSafetyFormat.MP3), ReaderSafetyStage.ADMISSION, ReaderSafetyAlgorithmId.MAX_ORIGINAL_BYTES, ('budgets.originalMaxBytes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.PUBLICATION_TOO_LARGE, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyRuleId.AUDIO_ENGINE_CODEC: ReaderSafetyRule(ReaderSafetyRuleId.AUDIO_ENGINE_CODEC, (ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyFormat.M4B, ReaderSafetyFormat.M4A, ReaderSafetyFormat.MP3), ReaderSafetyStage.PLAYBACK, ReaderSafetyAlgorithmId.AUDIO_ENGINE_CODEC, ('profiles.audio.codecDecision',), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.ENGINE_CODEC_UNSUPPORTED, (ReaderSafetyConsumer.WEB,)),
    ReaderSafetyRuleId.AUDIO_TRACK_AND_CHAPTER_BOUNDS: ReaderSafetyRule(ReaderSafetyRuleId.AUDIO_TRACK_AND_CHAPTER_BOUNDS, (ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyFormat.M4B, ReaderSafetyFormat.M4A, ReaderSafetyFormat.MP3), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.AUDIO_TRACK_CHAPTER_BOUNDS, ('budgets.audioTrackMaxCount', 'budgets.audioChapterMaxCount', 'profiles.audio.requireOrderedTrackIdentity', 'profiles.audio.requireFiniteNonNegativeDuration'), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.AUDIO_DURATION_INVALID, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyRuleId.AUDIO_METADATA_BUDGET: ReaderSafetyRule(ReaderSafetyRuleId.AUDIO_METADATA_BUDGET, (ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyFormat.M4B, ReaderSafetyFormat.M4A, ReaderSafetyFormat.MP3), ReaderSafetyStage.PARSE, ReaderSafetyAlgorithmId.AUDIO_METADATA_BUDGET, ('budgets.audioMetadataMaxBytes', 'budgets.audioArtworkMaxBytes'), ReaderSafetyAction.BLOCK_RESOURCE, ReaderSafetyErrorCode.AUDIO_METADATA_LIMIT, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
    ReaderSafetyRuleId.AUDIO_REDIRECT_POLICY: ReaderSafetyRule(ReaderSafetyRuleId.AUDIO_REDIRECT_POLICY, (ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR, ReaderSafetyFormat.AUDIOBOOK, ReaderSafetyFormat.M4B, ReaderSafetyFormat.M4A, ReaderSafetyFormat.MP3), ReaderSafetyStage.DELIVERY, ReaderSafetyAlgorithmId.AUDIO_REDIRECT_POLICY, ('profiles.audio.blockedRedirectSchemes',), ReaderSafetyAction.REJECT_PUBLICATION, ReaderSafetyErrorCode.AUDIO_SECURITY_REJECTED, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB)),
})
READER_SAFETY_PLATFORM_DEFENSES = MappingProxyType({
    ReaderSafetyPlatformDefenseId.XML_EXTERNAL_ENTITY_RESOLUTION_DISABLED: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.XML_EXTERNAL_ENTITY_RESOLUTION_DISABLED, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2), ReaderSafetyStage.PARSE, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyPlatformDefenseId.DOCUMENT_SCRIPT_EXECUTION_DISABLED: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.DOCUMENT_SCRIPT_EXECUTION_DISABLED, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.RENDER, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyPlatformDefenseId.DOCUMENT_INITIATED_NETWORK_DISABLED: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.DOCUMENT_INITIATED_NETWORK_DISABLED, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC, ReaderSafetyFormat.PDF), ReaderSafetyStage.RENDER, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyPlatformDefenseId.TRUSTED_RUNTIME_URI_PROVENANCE: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.TRUSTED_RUNTIME_URI_PROVENANCE, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC), ReaderSafetyStage.RESOURCE, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyPlatformDefenseId.PDF_ACTIVE_ACTIONS_DISABLED: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.PDF_ACTIVE_ACTIONS_DISABLED, (ReaderSafetyFormat.PDF,), ReaderSafetyStage.RENDER, (ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyPlatformDefenseId.ORIGINAL_ARTIFACT_IMMUTABLE: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.ORIGINAL_ARTIFACT_IMMUTABLE, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC, ReaderSafetyFormat.PDF, ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR, ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR), ReaderSafetyStage.ADMISSION, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
    ReaderSafetyPlatformDefenseId.NO_SECURITY_FAILURE_PARSER_FALLBACK: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.NO_SECURITY_FAILURE_PARSER_FALLBACK, (ReaderSafetyFormat.EPUB, ReaderSafetyFormat.FB2, ReaderSafetyFormat.TXT, ReaderSafetyFormat.MOBI, ReaderSafetyFormat.AZW, ReaderSafetyFormat.AZW3, ReaderSafetyFormat.PRC, ReaderSafetyFormat.PDF, ReaderSafetyFormat.CBZ, ReaderSafetyFormat.ZIP, ReaderSafetyFormat.CBR, ReaderSafetyFormat.RAR, ReaderSafetyFormat.IMAGE_DIR, ReaderSafetyFormat.AUDIO, ReaderSafetyFormat.AUDIOBOOK_DIR), ReaderSafetyStage.PARSE, (ReaderSafetyConsumer.BACKEND, ReaderSafetyConsumer.WEB, ReaderSafetyConsumer.ANDROID, ReaderSafetyConsumer.IOS)),
})

READER_SAFETY_REFLOWABLE_PROFILE: Final = ReaderSafetyReflowableProfile(
    safe_doctypes=(
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.0 Strict//EN', 'http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.0 Transitional//EN', 'http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.0 Frameset//EN', 'http://www.w3.org/TR/xhtml1/DTD/xhtml1-frameset.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.1//EN', 'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.0 Strict//EN', 'https://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.0 Transitional//EN', 'https://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.0 Frameset//EN', 'https://www.w3.org/TR/xhtml1/DTD/xhtml1-frameset.dtd'),
        ReaderSafetyDoctype('html', '-//W3C//DTD XHTML 1.1//EN', 'https://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'),
    ),
    external_dtd_resolution=False,
    reject_internal_subset=True,
    reject_custom_entities=True,
    named_entity_codepoints=MappingProxyType({
        'AElig': 198,
        'Aacute': 193,
        'Acirc': 194,
        'Agrave': 192,
        'Alpha': 913,
        'Aring': 197,
        'Atilde': 195,
        'Auml': 196,
        'Beta': 914,
        'Ccedil': 199,
        'Chi': 935,
        'Dagger': 8225,
        'Delta': 916,
        'ETH': 208,
        'Eacute': 201,
        'Ecirc': 202,
        'Egrave': 200,
        'Epsilon': 917,
        'Eta': 919,
        'Euml': 203,
        'Gamma': 915,
        'Iacute': 205,
        'Icirc': 206,
        'Igrave': 204,
        'Iota': 921,
        'Iuml': 207,
        'Kappa': 922,
        'Lambda': 923,
        'Mu': 924,
        'Ntilde': 209,
        'Nu': 925,
        'OElig': 338,
        'Oacute': 211,
        'Ocirc': 212,
        'Ograve': 210,
        'Omega': 937,
        'Omicron': 927,
        'Oslash': 216,
        'Otilde': 213,
        'Ouml': 214,
        'Phi': 934,
        'Pi': 928,
        'Prime': 8243,
        'Psi': 936,
        'Rho': 929,
        'Scaron': 352,
        'Sigma': 931,
        'THORN': 222,
        'Tau': 932,
        'Theta': 920,
        'Uacute': 218,
        'Ucirc': 219,
        'Ugrave': 217,
        'Upsilon': 933,
        'Uuml': 220,
        'Xi': 926,
        'Yacute': 221,
        'Yuml': 376,
        'Zeta': 918,
        'aacute': 225,
        'acirc': 226,
        'acute': 180,
        'aelig': 230,
        'agrave': 224,
        'alefsym': 8501,
        'alpha': 945,
        'amp': 38,
        'and': 8743,
        'ang': 8736,
        'apos': 39,
        'aring': 229,
        'asymp': 8776,
        'atilde': 227,
        'auml': 228,
        'bdquo': 8222,
        'beta': 946,
        'brvbar': 166,
        'bull': 8226,
        'cap': 8745,
        'ccedil': 231,
        'cedil': 184,
        'cent': 162,
        'chi': 967,
        'circ': 710,
        'clubs': 9827,
        'cong': 8773,
        'copy': 169,
        'crarr': 8629,
        'cup': 8746,
        'curren': 164,
        'dArr': 8659,
        'dagger': 8224,
        'darr': 8595,
        'deg': 176,
        'delta': 948,
        'diams': 9830,
        'divide': 247,
        'eacute': 233,
        'ecirc': 234,
        'egrave': 232,
        'empty': 8709,
        'emsp': 8195,
        'ensp': 8194,
        'epsilon': 949,
        'equiv': 8801,
        'eta': 951,
        'eth': 240,
        'euml': 235,
        'euro': 8364,
        'exist': 8707,
        'fnof': 402,
        'forall': 8704,
        'frac12': 189,
        'frac14': 188,
        'frac34': 190,
        'frasl': 8260,
        'gamma': 947,
        'ge': 8805,
        'gt': 62,
        'hArr': 8660,
        'harr': 8596,
        'hearts': 9829,
        'hellip': 8230,
        'iacute': 237,
        'icirc': 238,
        'iexcl': 161,
        'igrave': 236,
        'image': 8465,
        'infin': 8734,
        'int': 8747,
        'iota': 953,
        'iquest': 191,
        'isin': 8712,
        'iuml': 239,
        'kappa': 954,
        'lArr': 8656,
        'lambda': 955,
        'lang': 9001,
        'laquo': 171,
        'larr': 8592,
        'lceil': 8968,
        'ldquo': 8220,
        'le': 8804,
        'lfloor': 8970,
        'lowast': 8727,
        'loz': 9674,
        'lrm': 8206,
        'lsaquo': 8249,
        'lsquo': 8216,
        'lt': 60,
        'macr': 175,
        'mdash': 8212,
        'micro': 181,
        'middot': 183,
        'minus': 8722,
        'mu': 956,
        'nabla': 8711,
        'nbsp': 160,
        'ndash': 8211,
        'ne': 8800,
        'ni': 8715,
        'not': 172,
        'notin': 8713,
        'nsub': 8836,
        'ntilde': 241,
        'nu': 957,
        'oacute': 243,
        'ocirc': 244,
        'oelig': 339,
        'ograve': 242,
        'oline': 8254,
        'omega': 969,
        'omicron': 959,
        'oplus': 8853,
        'or': 8744,
        'ordf': 170,
        'ordm': 186,
        'oslash': 248,
        'otilde': 245,
        'otimes': 8855,
        'ouml': 246,
        'para': 182,
        'part': 8706,
        'permil': 8240,
        'perp': 8869,
        'phi': 966,
        'pi': 960,
        'piv': 982,
        'plusmn': 177,
        'pound': 163,
        'prime': 8242,
        'prod': 8719,
        'prop': 8733,
        'psi': 968,
        'quot': 34,
        'rArr': 8658,
        'radic': 8730,
        'rang': 9002,
        'raquo': 187,
        'rarr': 8594,
        'rceil': 8969,
        'rdquo': 8221,
        'real': 8476,
        'reg': 174,
        'rfloor': 8971,
        'rho': 961,
        'rlm': 8207,
        'rsaquo': 8250,
        'rsquo': 8217,
        'sbquo': 8218,
        'scaron': 353,
        'sdot': 8901,
        'sect': 167,
        'shy': 173,
        'sigma': 963,
        'sigmaf': 962,
        'sim': 8764,
        'spades': 9824,
        'sub': 8834,
        'sube': 8838,
        'sum': 8721,
        'sup': 8835,
        'sup1': 185,
        'sup2': 178,
        'sup3': 179,
        'supe': 8839,
        'szlig': 223,
        'tau': 964,
        'there4': 8756,
        'theta': 952,
        'thetasym': 977,
        'thinsp': 8201,
        'thorn': 254,
        'tilde': 732,
        'times': 215,
        'trade': 8482,
        'uArr': 8657,
        'uacute': 250,
        'uarr': 8593,
        'ucirc': 251,
        'ugrave': 249,
        'uml': 168,
        'upsih': 978,
        'upsilon': 965,
        'uuml': 252,
        'weierp': 8472,
        'xi': 958,
        'yacute': 253,
        'yen': 165,
        'yuml': 255,
        'zeta': 950,
        'zwj': 8205,
        'zwnj': 8204,
    }),
    reading_order_markup_mime_types=('application/xhtml+xml', 'text/html'),
    embedded_image_extensions_by_mime_type=MappingProxyType({
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
    }),
    sanitized_elements=('script', 'iframe', 'object', 'embed', 'form', 'base'),
    sanitized_attributes=('srcdoc',),
    sanitized_attribute_prefixes=('on',),
    sanitized_meta_http_equiv_values=('refresh', 'content-security-policy'),
    blocked_author_schemes=('javascript', 'file', 'data', 'blob'),
    remote_subresource_schemes=('http', 'https'),
    user_navigation_schemes=('http', 'https', 'mailto', 'tel'),
    trusted_runtime_schemes=('blob', 'data'),
    allowed_font_obfuscation_algorithms=('http://www.idpf.org/2008/embedding', 'http://ns.adobe.com/pdf/enc#RC'),
    svg_sanitized_elements=('script', 'foreignObject', 'iframe', 'object', 'embed'),
    css_text_elements=('style',),
    css_sanitized_constructs=('REMOTE_IMPORT', 'REMOTE_URL', 'EXPRESSION', 'BEHAVIOR', 'MOZ_BINDING'),
    archive_fatal_findings=('PATH_ESCAPE', 'ABSOLUTE_PATH', 'BACKSLASH_PATH', 'NUL_PATH', 'DOT_SEGMENT', 'DUPLICATE_CANONICAL_ENTRY', 'SYMLINK', 'ENCRYPTED_ENTRY', 'OVERLAPPING_ENTRY', 'CRC_MISMATCH'),
    uri_attribute_policies=(
        ReaderSafetyUriAttributePolicy(('*',), 'src', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('*',), 'srcset', ReaderSafetyUriSyntax.SRCSET, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('*',), 'style', ReaderSafetyUriSyntax.CSS, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('*',), 'xml:base', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('link',), 'href', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('video',), 'poster', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('*',), 'background', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('html',), 'manifest', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('img', 'input'), 'usemap', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('object',), 'data', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('object', 'applet'), 'codebase', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('applet',), 'code', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('applet',), 'archive', ReaderSafetyUriSyntax.SPACE_SEPARATED, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('image', 'use', 'feimage'), 'href', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('image', 'use', 'feimage'), 'xlink:href', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.SUBRESOURCE),
        ReaderSafetyUriAttributePolicy(('a', 'area'), 'href', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.USER_NAVIGATION),
        ReaderSafetyUriAttributePolicy(('a',), 'xlink:href', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.USER_NAVIGATION),
        ReaderSafetyUriAttributePolicy(('blockquote', 'q', 'ins', 'del'), 'cite', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.USER_NAVIGATION),
        ReaderSafetyUriAttributePolicy(('a', 'area'), 'ping', ReaderSafetyUriSyntax.SPACE_SEPARATED, ReaderSafetyUriPurpose.ALWAYS_REMOVE),
        ReaderSafetyUriAttributePolicy(('form',), 'action', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.ALWAYS_REMOVE),
        ReaderSafetyUriAttributePolicy(('button', 'input'), 'formaction', ReaderSafetyUriSyntax.SCALAR, ReaderSafetyUriPurpose.ALWAYS_REMOVE),
    ),
)

READER_SAFETY_PDF_PROFILE: Final = ReaderSafetyPdfProfile(
    blocked_actions=('JAVASCRIPT', 'XFA', 'FORM_ACTION', 'LAUNCH', 'EXTERNAL_DOCUMENT', 'DOCUMENT_NETWORK'),
    require_finite_page_geometry=True,
    require_identity_content_encoding=True,
    require_strong_revision=True,
    allow_whole_response_fallback=False,
)

READER_SAFETY_COMIC_PROFILE: Final = ReaderSafetyComicProfile(
    allowed_page_mime_types=('image/jpeg', 'image/png', 'image/gif', 'image/webp'),
    page_mime_types_by_extension=MappingProxyType({
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }),
    archive_fatal_findings=('PATH_ESCAPE', 'ABSOLUTE_PATH', 'BACKSLASH_PATH', 'NUL_PATH', 'DOT_SEGMENT', 'DUPLICATE_CANONICAL_ENTRY', 'SYMLINK', 'HARDLINK', 'ENCRYPTED_ENTRY', 'OVERLAPPING_ENTRY', 'CRC_MISMATCH'),
    single_page_decode_failure_action=ReaderSafetyAction.BLOCK_RESOURCE,
    manifest_revision_required=True,
)

READER_SAFETY_AUDIO_PROFILE: Final = ReaderSafetyAudioProfile(
    container_mime_types=MappingProxyType({
        '.aac': 'audio/aac',
        '.ac3': 'audio/ac3',
        '.adx': 'audio/x-adx',
        '.aif': 'audio/aiff',
        '.aifc': 'audio/aiff',
        '.aiff': 'audio/aiff',
        '.amr': 'audio/amr',
        '.ape': 'audio/x-ape',
        '.aptx': 'audio/x-aptx',
        '.aptxhd': 'audio/x-aptxhd',
        '.au': 'audio/basic',
        '.caf': 'audio/x-caf',
        '.dff': 'audio/x-dff',
        '.dsf': 'audio/x-dsf',
        '.dts': 'audio/vnd.dts',
        '.eac3': 'audio/eac3',
        '.flac': 'audio/flac',
        '.g722': 'audio/x-g722',
        '.g726': 'audio/x-g726',
        '.gsm': 'audio/x-gsm',
        '.lbc': 'audio/x-lbc',
        '.m4a': 'audio/mp4',
        '.m4b': 'audio/mp4',
        '.m4r': 'audio/mp4',
        '.mka': 'audio/x-matroska',
        '.mlp': 'audio/x-mlp',
        '.mp2': 'audio/mpeg',
        '.mp3': 'audio/mpeg',
        '.mpc': 'audio/x-mpc',
        '.oga': 'audio/ogg',
        '.ogg': 'audio/ogg',
        '.oma': 'audio/x-oma',
        '.opus': 'audio/ogg',
        '.qcp': 'audio/x-qcp',
        '.ra': 'audio/vnd.rn-realaudio',
        '.rf64': 'audio/wav',
        '.shn': 'audio/x-shn',
        '.snd': 'audio/basic',
        '.sph': 'audio/x-sph',
        '.spx': 'audio/ogg',
        '.tak': 'audio/x-tak',
        '.thd': 'audio/x-thd',
        '.tta': 'audio/x-tta',
        '.voc': 'audio/x-voc',
        '.w64': 'audio/wav',
        '.wav': 'audio/wav',
        '.wave': 'audio/wav',
        '.weba': 'audio/webm',
        '.wma': 'audio/x-ms-wma',
        '.wv': 'audio/x-wv',
        '.xma': 'audio/x-xma',
    }),
    codec_decision='ENGINE_CAPABILITY',
    blocked_redirect_schemes=('file', 'data', 'blob', 'javascript'),
    require_finite_non_negative_duration=True,
    require_ordered_track_identity=True,
)

def reader_safety_format_policy(source_format: str) -> ReaderSafetyFormatDefinition | None:
    try:
        format_id = ReaderSafetyFormat(source_format.strip().upper())
    except ValueError:
        return None
    return READER_SAFETY_FORMATS[format_id]

def require_reader_safety_format_policy(source_format: str) -> ReaderSafetyFormatDefinition:
    policy = reader_safety_format_policy(source_format)
    if policy is None:
        raise ValueError(f"unsupported Reader safety format: {source_format}")
    return policy

def reader_safety_budget(name: ReaderSafetyBudgetName) -> int:
    return READER_SAFETY_BUDGETS[name]

def reader_safety_rule(rule_id: ReaderSafetyRuleId) -> ReaderSafetyRule:
    return READER_SAFETY_RULES[rule_id]

def reader_safety_comic_page_mime_type(extension: str) -> str | None:
    return READER_SAFETY_COMIC_PROFILE.page_mime_types_by_extension.get(
        extension.strip().lower()
    )

def reader_safety_fb2_embedded_image_extension(media_type: str) -> str | None:
    return READER_SAFETY_REFLOWABLE_PROFILE.embedded_image_extensions_by_mime_type.get(
        media_type.strip().lower()
    )

# fmt: on
