"""Prepared publication contract for remotely sourced Library covers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PreparedCoverPublication:
    book_id: str
    temporary_path: Path
    final_path: Path
    stored_path: str


class CoverPublicationGateway(Protocol):
    def prepare(self, *, book_id: str, cover_url: str) -> PreparedCoverPublication:
        """Download and validate a cover without holding a database session."""

    def publish(self, prepared: PreparedCoverPublication) -> None:
        """Atomically publish a prepared cover after the database commit."""

    def discard(self, prepared: PreparedCoverPublication) -> None:
        """Remove an unpublished temporary file after a failed database mutation."""


__all__ = ["CoverPublicationGateway", "PreparedCoverPublication"]
