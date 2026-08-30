"""Named public API for cross-capability publication consumers."""

from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
    EnsurePublicationNavigationOutcome,
    EnsurePublicationNavigationResult,
)
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationReadError,
    PublicationResourceTooLargeError,
    PublicationUnsupportedError,
)

__all__ = [
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
    "NormalizedPublication",
    "PublicationAccessScope",
    "PublicationCorruptError",
    "PublicationNotFoundError",
    "PublicationReadError",
    "PublicationResourceTooLargeError",
    "PublicationUnsupportedError",
]
