from __future__ import annotations

from typing import Protocol


class ImportUnitOfWork(Protocol):
    """Transaction boundary used by recoverable import checkpoints."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
