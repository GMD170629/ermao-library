"""Named package-building API, shared by CLI and preparation validation."""

from .application.dependency_release import (
    CodePackage,
    DependencySet,
    ProgramIdentity,
    ReleaseManifest,
)
from .application.models import (
    ApplicationIdentity,
    Environment,
    Package,
    ReleaseReference,
)
from .infrastructure.archive import program_path, validate_layout
from .infrastructure.dependency_preparation import verify_dependency_artifact

__all__ = [
    "ApplicationIdentity",
    "CodePackage",
    "DependencySet",
    "Environment",
    "Package",
    "ProgramIdentity",
    "ReleaseManifest",
    "ReleaseReference",
    "program_path",
    "validate_layout",
    "verify_dependency_artifact",
]
