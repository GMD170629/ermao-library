"""Pure catalog topology domain contracts."""

from app.modules.catalog.domain.layouts import interpret_layout
from app.modules.catalog.domain.model import (
    AdmissionKind,
    AssetCandidate,
    EntryType,
    LayoutResult,
    LayoutViolation,
    OrganizationMode,
    PathComparison,
    ProbedEntry,
    SourceKind,
    ViolationCode,
    VolumeCandidate,
)

__all__ = [
    "AdmissionKind",
    "AssetCandidate",
    "EntryType",
    "LayoutResult",
    "LayoutViolation",
    "OrganizationMode",
    "PathComparison",
    "ProbedEntry",
    "SourceKind",
    "ViolationCode",
    "VolumeCandidate",
    "interpret_layout",
]
