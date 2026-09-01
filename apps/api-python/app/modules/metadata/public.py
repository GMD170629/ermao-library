"""Public metadata capability contracts."""

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.local_metadata import (
    FilesystemLocalMetadataInspector,
    LocalAudioMetadata,
    LocalAudioMetadataReader,
    LocalCoverPayload,
    LocalEmbeddedCandidateReader,
    LocalMetadataCandidate,
    LocalSidecarCandidateReader,
    ResolvedLocalMetadata,
    parse_local_metadata,
    resolve_local_metadata,
)
from app.modules.metadata.application.opf import (
    MAX_OPF_BYTES,
    OPF_NAMESPACE,
    OpfMetadataError,
    cover_media_type,
    parse_opf_metadata,
    serialize_opf_metadata,
)
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.application.writeback import (
    MetadataWritebackAssetProjection,
    MetadataWritebackImportProjection,
    MetadataWritebackProjection,
    MetadataWritebackResourceProjection,
    PreparedWritebackIntent,
    prepare_metadata_writeback_intents,
    prepare_source_node_metadata_writeback_intent,
)
from app.modules.metadata.domain.providers import (
    BUILTIN_MANIFESTS,
    AutomaticRateLimit,
    ProviderConfigField,
    ProviderManifest,
)
from app.services.metadata_file_writeback import (
    load_metadata_writeback_projection,
    metadata_writeback_enabled,
    persist_metadata_writeback_intents,
)
from app.services.metadata_provider_registry import search_with_metadata_provider

__all__ = [
    "BUILTIN_MANIFESTS",
    "MAX_OPF_BYTES",
    "OPF_NAMESPACE",
    "AutomaticMetadataRequestGate",
    "AutomaticRateLimit",
    "FilesystemLocalMetadataInspector",
    "LocalAudioMetadata",
    "LocalAudioMetadataReader",
    "LocalCoverPayload",
    "LocalEmbeddedCandidateReader",
    "LocalMetadataCandidate",
    "LocalSidecarCandidateReader",
    "MetadataWritebackAssetProjection",
    "MetadataWritebackImportProjection",
    "MetadataWritebackProjection",
    "MetadataWritebackResourceProjection",
    "OpfMetadataError",
    "PreparedWritebackIntent",
    "ProviderConfigField",
    "ProviderManifest",
    "PublicationMetadata",
    "ResolvedLocalMetadata",
    "cover_media_type",
    "load_metadata_writeback_projection",
    "metadata_writeback_enabled",
    "parse_local_metadata",
    "parse_opf_metadata",
    "persist_metadata_writeback_intents",
    "prepare_metadata_writeback_intents",
    "prepare_source_node_metadata_writeback_intent",
    "resolve_local_metadata",
    "search_with_metadata_provider",
    "serialize_opf_metadata",
]
