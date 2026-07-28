from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ClaimClientSequenceCommand:
    user_id: str
    work_id: str
    client_id: str
    client_sequence: int
    mutation_id: str
    now: datetime


class ReaderProgressCursorPort(Protocol):
    def claim(self, command: ClaimClientSequenceCommand) -> bool: ...


class ClaimClientSequence:
    """Atomically advance one reader client's durable high-water mark."""

    def __init__(self, cursor: ReaderProgressCursorPort):
        self._cursor = cursor

    def execute(self, command: ClaimClientSequenceCommand) -> bool:
        return self._cursor.claim(command)
