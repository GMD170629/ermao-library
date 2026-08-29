"""Named public API for cross-capability publication consumers."""

from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
    EnsurePublicationNavigationOutcome,
    EnsurePublicationNavigationResult,
    OpenPublicationNavigationResult,
)
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationResourceTooLargeError,
    PublicationUnsupportedError,
)

__all__ = [
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
    "NormalizedPublication",
    "OpenPublicationNavigationResult",
    "PublicationAccessScope",
    "PublicationCorruptError",
    "PublicationNotFoundError",
    "PublicationResourceTooLargeError",
    "PublicationUnsupportedError",
]
