"""Committed source-tree relocation shared with dependent file queues."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRelocation:
    source_library_id: str
    source_relative_path: str
    destination_library_id: str
    destination_relative_path: str
    node_ids: tuple[str, ...]
    book_ids: tuple[str, ...]
    reimport: bool = False
