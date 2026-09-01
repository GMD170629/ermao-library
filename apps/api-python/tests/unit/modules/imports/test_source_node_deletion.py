from __future__ import annotations

from typing import cast

import pytest

from app.modules.imports.infrastructure.readable_resource.source_node_deletion import (
    LibrarySourceNodeDeletionAdapter,
)
from app.modules.library.application.commands.manage_source_tree import (
    DeleteSourceNode,
    ManagementResult,
)


class StubDeleteSourceNode:
    def __init__(self, result: ManagementResult) -> None:
        self._result = result
        self.calls: list[str] = []

    def execute(self, source_node_id: str) -> ManagementResult:
        self.calls.append(source_node_id)
        return self._result


def _adapter(
    result: ManagementResult,
) -> tuple[LibrarySourceNodeDeletionAdapter, StubDeleteSourceNode]:
    stub = StubDeleteSourceNode(result)
    return LibrarySourceNodeDeletionAdapter(cast(DeleteSourceNode, stub)), stub


def test_source_node_deletion_adapter_delegates_success() -> None:
    adapter, stub = _adapter(ManagementResult(ok=True))

    adapter.delete_source_node("source-1")

    assert stub.calls == ["source-1"]


def test_source_node_deletion_adapter_treats_already_missing_as_idempotent() -> None:
    adapter, stub = _adapter(ManagementResult(ok=False, code="SOURCE_NODE_NOT_FOUND"))

    adapter.delete_source_node("source-1")

    assert stub.calls == ["source-1"]


def test_source_node_deletion_adapter_propagates_other_failures() -> None:
    adapter, _stub = _adapter(ManagementResult(ok=False, code="DELETE_BLOCKED"))

    with pytest.raises(RuntimeError, match="DELETE_BLOCKED"):
        adapter.delete_source_node("source-1")
