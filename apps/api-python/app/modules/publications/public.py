"""Named public API for cross-capability publication consumers."""

from app.modules.publications.application.open_publication import OpenPublication
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationUnsupportedError,
)

__all__ = [
    "NormalizedPublication",
    "OpenPublication",
    "PublicationAccessScope",
    "PublicationCorruptError",
    "PublicationNotFoundError",
    "PublicationUnsupportedError",
]
