"""Read-only, paginated browsing of the canonical source tree."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.modules.library.application.source_tree_ports import SourceNodeRecord
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind


class SourceAccessError(ValueError):
    """Stable rejection without private filesystem information."""


@dataclass(frozen=True)
class SourceLocation:
    node: SourceNodeRecord
    root_path: Path


@dataclass(frozen=True)
class SourceNodePage:
    nodes: tuple[SourceNodeRecord, ...]
    total: int
    page: int
    page_size: int


class SourceBrowserPort(Protocol):
    def location(
        self, node_id: str, library_ids: frozenset[str]
    ) -> SourceLocation | None: ...
    def page_children(
        self, library_id: str, parent_id: str | None, page: int, page_size: int
    ) -> SourceNodePage: ...


@dataclass(frozen=True)
class BrowseSourceNodes:
    port: SourceBrowserPort

    def execute(
        self,
        *,
        library_ids: frozenset[str],
        library_id: str,
        parent_id: str | None,
        page: int,
        page_size: int,
    ) -> SourceNodePage:
        if library_id not in library_ids:
            raise SourceAccessError("RESOURCE_NOT_FOUND")
        if (
            type(page) is not int
            or page < 1
            or type(page_size) is not int
            or not 1 <= page_size <= 50
        ):
            raise SourceAccessError("INVALID_PAGINATION")
        if parent_id is not None:
            parent = self.port.location(parent_id, frozenset({library_id}))
            if (
                parent is None
                or parent.node.physical_kind is not SourceNodePhysicalKind.DIRECTORY
            ):
                raise SourceAccessError("RESOURCE_NOT_FOUND")
        return self.port.page_children(library_id, parent_id, page, page_size)
