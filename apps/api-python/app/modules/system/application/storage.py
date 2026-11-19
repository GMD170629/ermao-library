"""System directory usage and file-only maintenance."""

from dataclasses import dataclass
from typing import Literal, Protocol

StorageCategory = Literal[
    "program",
    "database",
    "images",
    "cache",
    "logs",
    "backups",
    "updates",
    "uploads",
    "other",
]
CATEGORIES: tuple[StorageCategory, ...] = (
    "program",
    "database",
    "images",
    "cache",
    "logs",
    "backups",
    "updates",
    "uploads",
    "other",
)
CLEANABLE = frozenset({"cache", "logs", "backups", "updates", "uploads"})


@dataclass(frozen=True)
class StorageUsage:
    root: str
    sizes: dict[StorageCategory, int]


class StorageFiles(Protocol):
    def usage(self, category: StorageCategory | None = None) -> StorageUsage: ...
    def clear(self, category: StorageCategory) -> None: ...


class StorageManagement:
    def __init__(self, files: StorageFiles) -> None:
        self.files = files

    def usage(
        self, *, authorized: bool, category: StorageCategory | None = None
    ) -> StorageUsage:
        if not authorized:
            raise PermissionError("SYSTEM_MANAGER_REQUIRED")
        return self.files.usage(category)

    def clear(self, category: StorageCategory, *, authorized: bool) -> StorageUsage:
        if not authorized:
            raise PermissionError("SYSTEM_MANAGER_REQUIRED")
        if category not in CLEANABLE:
            raise ValueError("STORAGE_CATEGORY_READ_ONLY")
        self.files.clear(category)
        return self.files.usage(category)
