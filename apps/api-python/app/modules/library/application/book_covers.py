"""Application contracts for resolving effective Book cover candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

BookCoverSource = Literal["BOOK", "RESOURCE"]


@dataclass(frozen=True, slots=True)
class BookCoverCandidate:
    source: BookCoverSource
    source_id: str
    stored_path: str


class BookCoverQueryPort(Protocol):
    def list_candidates(self, book_id: str) -> tuple[BookCoverCandidate, ...]: ...

    def preferred_paths(self, book_ids: tuple[str, ...]) -> Mapping[str, str]: ...


class ResolveBookCoverCandidates:
    def __init__(self, queries: BookCoverQueryPort) -> None:
        self._queries = queries

    def execute(self, book_id: str) -> tuple[BookCoverCandidate, ...]:
        return self._queries.list_candidates(book_id)


__all__ = [
    "BookCoverCandidate",
    "BookCoverQueryPort",
    "BookCoverSource",
    "ResolveBookCoverCandidates",
]
