"""Public metadata capability contracts."""

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.commands import (
    MetadataUnitOfWork,
    execute_metadata_transaction,
)
from app.modules.metadata.application.opf import (
    MAX_OPF_BYTES,
    OpfMetadataError,
    parse_opf_metadata,
    serialize_opf_metadata,
)
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.domain.providers import (
    BUILTIN_MANIFESTS,
    AutomaticRateLimit,
    ProviderConfigField,
    ProviderManifest,
)

__all__ = [
    "BUILTIN_MANIFESTS",
    "MAX_OPF_BYTES",
    "AutomaticMetadataRequestGate",
    "AutomaticRateLimit",
    "MetadataUnitOfWork",
    "OpfMetadataError",
    "ProviderConfigField",
    "ProviderManifest",
    "PublicationMetadata",
    "execute_metadata_transaction",
    "parse_opf_metadata",
    "serialize_opf_metadata",
]
