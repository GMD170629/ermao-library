"""Named public API for cross-capability publication consumers."""

from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
    EnsurePublicationNavigationOutcome,
    EnsurePublicationNavigationResult,
    OpenPublicationNavigationResult,
    PublicationNavigationSourceChangedError,
)
from app.modules.publications.application.open_publication import OpenPublication
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationUnsupportedError,
)

__all__ = [
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
    "NormalizedPublication",
    "OpenPublication",
    "OpenPublicationNavigationResult",
    "PublicationAccessScope",
    "PublicationCorruptError",
    "PublicationNavigationSourceChangedError",
    "PublicationNotFoundError",
    "PublicationUnsupportedError",
]
