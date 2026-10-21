"""Named public API for cross-capability publication consumers."""

from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
    EnsurePublicationNavigationOutcome,
    EnsurePublicationNavigationResult,
)
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.application.txt_decoding import (
    DecodedTxt,
    decode_txt_bytes,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationReadError,
    PublicationResourceNotFoundError,
    PublicationResourceTooLargeError,
    PublicationUnsupportedError,
)

__all__ = [
    "DecodedTxt",
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
    "NormalizedPublication",
    "PublicationAccessScope",
    "PublicationCorruptError",
    "PublicationNotFoundError",
    "PublicationReadError",
    "PublicationResourceNotFoundError",
    "PublicationResourceTooLargeError",
    "PublicationUnsupportedError",
    "decode_txt_bytes",
]
