"""One metadata-only traversal of the configured application storage."""

import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.exception_diagnostics import capture_exception
from app.modules.system.application.storage import (
    CATEGORIES,
    StorageCategory,
    StorageUsage,
)


@contextmanager
def directory_entries(directory: Path) -> Iterator[Iterator[os.DirEntry[str]]]:
    try:
        entries = os.scandir(directory)
    except FileNotFoundError as error:
        capture_exception(error, level="debug")
        yield iter(())
        return
    with entries:
        yield entries


def category_for(parts: tuple[str, ...]) -> StorageCategory:
    if parts[0] in {"runtime", "dependencies"}:
        return "program"
    if parts[0] == "database":
        return "database"
    if parts[0] in {"covers", "profiles", "books"}:
        return "images"
    if parts[0] == "cache":
        return "cache"
    directories: dict[str, StorageCategory] = {
        "logs": "logs",
        "backups": "backups",
        "update-tmp": "updates",
        "automation-uploads": "uploads",
    }
    return directories.get(parts[0], "other")


class FileSystemStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def clear(self, category: StorageCategory) -> None:
        targets = {
            "cache": "cache",
            "logs": "logs",
            "backups": "backups",
            "updates": "update-tmp/prepared",
            "uploads": "automation-uploads",
        }
        target = self.root / targets[category]
        current = self.root
        for component in target.relative_to(self.root).parts:
            current /= component
            if current.is_symlink() or not current.resolve().is_relative_to(
                self.root.resolve()
            ):
                raise ValueError("UNSAFE_STORAGE")
        if target.exists():
            shutil.rmtree(target)

    def usage(self, category: StorageCategory | None = None) -> StorageUsage:
        sizes: dict[StorageCategory, int] = {
            key: 0 for key in CATEGORIES if category is None or key == category
        }
        pending = [(self.root, ())]
        while pending:
            directory, prefix = pending.pop()
            with directory_entries(directory) as entries:
                for entry in entries:
                    parts = (*prefix, entry.name)
                    key = category_for(parts)
                    if category is not None and key != category:
                        continue
                    try:
                        observed = entry.stat(follow_symlinks=False)
                    except FileNotFoundError as error:
                        capture_exception(error, level="debug")
                        continue
                    if stat.S_ISLNK(observed.st_mode) or getattr(
                        observed, "st_file_attributes", 0
                    ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                        continue
                    if stat.S_ISDIR(observed.st_mode):
                        pending.append((Path(entry.path), parts))
                    elif stat.S_ISREG(observed.st_mode):
                        sizes[key] += observed.st_size
        return StorageUsage(str(self.root), sizes)
