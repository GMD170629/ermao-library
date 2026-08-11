"""Filesystem quarantine used by recoverable library deletion commands."""

from __future__ import annotations

import logging
from pathlib import Path

from app.modules.library.application.work_deletion import (
    IsolatedLibraryFiles,
    PreparedFileQuarantineEntry,
)

LOGGER = logging.getLogger(__name__)


class LocalLibraryFileQuarantine:
    def isolate(
        self, entries: tuple[PreparedFileQuarantineEntry, ...]
    ) -> IsolatedLibraryFiles:
        isolated: list[PreparedFileQuarantineEntry] = []
        missing: list[str] = []
        failures: list[dict[str, str]] = []
        for entry in entries:
            original = Path(entry.original_path)
            quarantine = Path(entry.quarantine_path)
            try:
                if not original.exists() and not original.is_symlink():
                    if entry.source_file:
                        missing.append(entry.original_path)
                    continue
                if not original.is_file() and not original.is_symlink():
                    failures.append(
                        {"path": entry.original_path, "message": "目标不是文件"}
                    )
                    continue
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                original.replace(quarantine)
                isolated.append(entry)
            except OSError as error:
                failures.append({"path": entry.original_path, "message": str(error)})
                LOGGER.warning(
                    "library_file_quarantine outcome=failed path=%s",
                    entry.original_path,
                    exc_info=error,
                )
        return IsolatedLibraryFiles(
            entries=tuple(isolated),
            missing_source_paths=tuple(missing),
            failures=tuple(failures),
        )

    def restore(self, isolated: IsolatedLibraryFiles) -> None:
        for entry in reversed(isolated.entries):
            original = Path(entry.original_path)
            quarantine = Path(entry.quarantine_path)
            try:
                if not quarantine.exists() and not quarantine.is_symlink():
                    continue
                original.parent.mkdir(parents=True, exist_ok=True)
                quarantine.replace(original)
                self._remove_empty_quarantine_dirs(entry)
            except OSError as error:
                LOGGER.error(
                    "library_file_quarantine_restore outcome=failed path=%s quarantine=%s",
                    entry.original_path,
                    entry.quarantine_path,
                    exc_info=error,
                )

    def finalize(self, isolated: IsolatedLibraryFiles) -> tuple[dict[str, str], ...]:
        failures: list[dict[str, str]] = []
        for entry in isolated.entries:
            quarantine = Path(entry.quarantine_path)
            try:
                if quarantine.is_file() or quarantine.is_symlink():
                    quarantine.unlink()
                self._remove_empty_quarantine_dirs(entry)
            except OSError as error:
                # The active library/source path is already isolated. Leaving
                # the file in quarantine is recoverable by a later sweeper.
                failures.append({"path": entry.quarantine_path, "message": str(error)})
                LOGGER.warning(
                    "library_file_quarantine_finalize outcome=deferred path=%s",
                    entry.quarantine_path,
                    exc_info=error,
                )
        return tuple(failures)

    @staticmethod
    def _remove_empty_quarantine_dirs(
        entry: PreparedFileQuarantineEntry,
    ) -> None:
        root = Path(entry.quarantine_root)
        current = Path(entry.quarantine_path).parent
        while current != root.parent and (current == root or root in current.parents):
            try:
                current.rmdir()
            except OSError:
                break
            if current == root:
                break
            current = current.parent
