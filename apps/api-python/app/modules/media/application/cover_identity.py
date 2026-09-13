"""Application port for a validated, versioned cover URL."""

from typing import Protocol


class CoverUrlResolver(Protocol):
    def __call__(
        self, endpoint: str, cover_path: str | None, *, size: str | None = None
    ) -> str: ...
