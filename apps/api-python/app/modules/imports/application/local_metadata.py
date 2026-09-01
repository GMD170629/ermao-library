"""Compatibility exports for the metadata capability's local resolver.

Local metadata is a shared business capability, not an import-only concern.
Keep this module as a thin compatibility surface for existing import ports and
callers while the authoritative contracts and implementation live under
``app.modules.metadata``.
"""

from app.modules.metadata.public import (
    LocalAudioMetadata,
    LocalCoverPayload,
    LocalMetadataCandidate,
    LocalSidecarCandidateReader,
    ResolvedLocalMetadata,
    parse_local_metadata,
    resolve_local_metadata,
)

__all__ = [
    "LocalAudioMetadata",
    "LocalCoverPayload",
    "LocalMetadataCandidate",
    "LocalSidecarCandidateReader",
    "ResolvedLocalMetadata",
    "parse_local_metadata",
    "resolve_local_metadata",
]
