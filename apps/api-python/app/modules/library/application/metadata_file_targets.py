"""Library-owned identity and format information for explicit standard file writes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class MetadataFileTarget:
    node_id: str
    library_id: str
    root: Path
    relative_path: str
    directory: bool
    book_id: str
    resource_id: str | None
    asset_id: str | None
    format: str | None


class MetadataFileTargetPort(Protocol):
    def get(
        self, node_id: str, library_ids: frozenset[str]
    ) -> MetadataFileTarget | None: ...
