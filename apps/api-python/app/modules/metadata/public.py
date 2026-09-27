from app.modules.metadata.application.standard_files import (
    MetadataFileSource,
    StandardFileMetadataReader,
    StandardMetadataError,
    StandardMetadataObservation,
)
from app.modules.metadata.application.standard_writeback import (
    PlannedStandardWrite,
    PreparedStandardFile,
    StandardWriteFile,
    StandardWriteFormat,
    StandardWriteInspectionPort,
    StandardWritePlan,
    StandardWritePlanStore,
    StandardWriteStatus,
)
from app.modules.metadata.domain.source_name import metadata_from_source_name

"""Public metadata capability contracts."""

from app.contracts.metadata_identity import MetadataIdentity
from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.local_metadata import (
    FilesystemLocalMetadataInspector,
    LocalAudioMetadata,
    LocalMetadataCandidate,
    ResolvedLocalMetadata,
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
from app.modules.metadata.infrastructure.generation import complete_missing_metadata
from app.modules.metadata.infrastructure.matching import (
    MetadataMatch,
    candidate_key,
    match_metadata_candidates,
    prepare_matched_metadata,
)
from app.services.metadata_file_writeback import (
    load_metadata_writeback_projection,
    metadata_writeback_enabled,
    persist_metadata_writeback_intents,
)
from app.services.metadata_provider_registry import (
    enabled_metadata_provider_ids,
    recognize_metadata_identity,
    search_with_metadata_provider,
)
from app.services.organize_service import choose_metadata_candidate

__all__ = [
    "BUILTIN_MANIFESTS",
    "MAX_OPF_BYTES",
    "OPF_NAMESPACE",
    "AutomaticMetadataRequestGate",
    "AutomaticRateLimit",
    "FilesystemLocalMetadataInspector",
    "LocalAudioMetadata",
    "LocalMetadataCandidate",
    "MetadataFileSource",
    "MetadataIdentity",
    "MetadataMatch",
    "MetadataWritebackAssetProjection",
    "MetadataWritebackImportProjection",
    "MetadataWritebackProjection",
    "MetadataWritebackResourceProjection",
    "OpfMetadataError",
    "PlannedStandardWrite",
    "PreparedStandardFile",
    "PreparedWritebackIntent",
    "ProviderConfigField",
    "ProviderManifest",
    "PublicationMetadata",
    "ResolvedLocalMetadata",
    "StandardFileMetadataReader",
    "StandardMetadataError",
    "StandardMetadataObservation",
    "StandardWriteFile",
    "StandardWriteFormat",
    "StandardWriteInspectionPort",
    "StandardWritePlan",
    "StandardWritePlanStore",
    "StandardWriteStatus",
    "candidate_key",
    "choose_metadata_candidate",
    "complete_missing_metadata",
    "cover_media_type",
    "enabled_metadata_provider_ids",
    "load_metadata_writeback_projection",
    "match_metadata_candidates",
    "metadata_from_source_name",
    "metadata_writeback_enabled",
    "parse_opf_metadata",
    "persist_metadata_writeback_intents",
    "prepare_matched_metadata",
    "prepare_metadata_writeback_intents",
    "prepare_source_node_metadata_writeback_intent",
    "recognize_metadata_identity",
    "resolve_local_metadata",
    "search_with_metadata_provider",
    "serialize_opf_metadata",
]
