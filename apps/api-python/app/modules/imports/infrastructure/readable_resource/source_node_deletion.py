"""Adapter from import reconciliation to the Library source deletion use case."""

from __future__ import annotations

from app.modules.imports.application.readable_resource.ports import (
    SourceNodeDeletionPort,
)
from app.modules.library.public import DeleteSourceNode


class LibrarySourceNodeDeletionAdapter(SourceNodeDeletionPort):
    """Keep the Library capability as the sole owner of subtree cleanup."""

    def __init__(self, delete_source_node: DeleteSourceNode) -> None:
        self._delete_source_node = delete_source_node

    def delete_source_node(self, source_node_id: str) -> None:
        result = self._delete_source_node.execute(source_node_id)
        if not result.ok and result.code != "SOURCE_NODE_NOT_FOUND":
            raise RuntimeError(result.code or "SOURCE_NODE_DELETE_FAILED")


__all__ = ["LibrarySourceNodeDeletionAdapter"]
