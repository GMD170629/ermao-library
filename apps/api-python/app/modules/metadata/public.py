"""Public metadata capability contracts."""

from app.contracts.publication_metadata import PublicationMetadata
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
)
from app.modules.metadata.domain.providers import (
    BUILTIN_MANIFESTS,
    AutomaticRateLimit,
    ProviderConfigField,
    ProviderManifest,
)
from app.services.metadata_file_writeback import (
    load_metadata_writeback_projection,
    persist_metadata_writeback_intents,
)

__all__ = [
    "BUILTIN_MANIFESTS",
    "MAX_OPF_BYTES",
    "OPF_NAMESPACE",
    "AutomaticMetadataRequestGate",
    "AutomaticRateLimit",
    "MetadataWritebackAssetProjection",
    "MetadataWritebackImportProjection",
    "MetadataWritebackProjection",
    "MetadataWritebackResourceProjection",
    "OpfMetadataError",
    "PreparedWritebackIntent",
    "ProviderConfigField",
    "ProviderManifest",
    "PublicationMetadata",
    "cover_media_type",
    "load_metadata_writeback_projection",
    "parse_opf_metadata",
    "persist_metadata_writeback_intents",
    "prepare_metadata_writeback_intents",
    "serialize_opf_metadata",
]
