"""Filesystem traversal, path containment, and directory probe adapter."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import (
    DirectoryEntry,
    RegularFileObservation,
    SourceTreeFilesystemPort,
    UnreadableDirectoryEntry,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    ProbeTerminationReason,
    decide_directory_probe,
)
from app.modules.imports.domain.ignore_rules import should_ignore_source_entry
from app.modules.imports.domain.resource_adapters import (
    is_supported_source_tree_filename,
)
from app.modules.library.public import SourceNodePhysicalKind


class OsSourceTreeFilesystem(SourceTreeFilesystemPort):
    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        root_resolved = root.resolve()
        candidate = (root_resolved / relative_path).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as error:
            raise ValueError("path_escapes_library_root") from error
        if candidate.is_symlink():
            real = candidate.parent.resolve() / candidate.name
            try:
                real.relative_to(root_resolved)
            except ValueError as error:
                raise ValueError("symlink_escapes_library_root") from error
        return candidate

    def iter_directory_entries(
        self,
        absolute_directory: Path,
    ) -> Iterator[DirectoryEntry | UnreadableDirectoryEntry]:
        iterator = os.scandir(absolute_directory)
        try:
            for entry in iterator:
                try:
                    kind = self._physical_kind(entry)
                    stat = entry.stat(follow_symlinks=False)
                    mtime_ns = int(stat.st_mtime_ns)
                    size = (
                        None
                        if kind is SourceNodePhysicalKind.DIRECTORY
                        else int(stat.st_size)
                    )
                except OSError:
                    yield UnreadableDirectoryEntry(name=entry.name)
                    continue
                yield (entry.name, kind, size, mtime_ns)
        finally:
            iterator.close()

    def probe_directory(
        self,
        *,
        root: Path,
        directory_relative_path: str,
        ignore_hidden: bool,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
        sample_limit: int,
        max_entries: int,
        max_depth: int,
        time_budget_ms: int,
    ) -> DirectoryProbeDecision:
        started = time.monotonic()
        samples: list[str] = []
        entries_visited = 0
        max_depth_reached = 0
        termination = ProbeTerminationReason.COMPLETE_SUBTREE
        stack: list[tuple[str, int]] = [(directory_relative_path, 0)]
        stop = False

        while stack and not stop:
            if (time.monotonic() - started) * 1000 >= time_budget_ms:
                termination = ProbeTerminationReason.TIME_BUDGET
                break
            if entries_visited >= max_entries:
                termination = ProbeTerminationReason.ENTRY_BUDGET
                break
            relative_dir, depth = stack.pop()
            if depth > max_depth:
                termination = ProbeTerminationReason.DEPTH_BUDGET
                continue
            max_depth_reached = max(max_depth_reached, depth)
            absolute = self.resolve_under_root(root, relative_dir)
            try:
                entries = self.iter_directory_entries(absolute)
            except OSError:
                termination = ProbeTerminationReason.LOCAL_IO_ERROR
                break
            try:
                for observed in entries:
                    if isinstance(observed, UnreadableDirectoryEntry):
                        continue
                    name, kind, _size, _mtime = observed
                    if (time.monotonic() - started) * 1000 >= time_budget_ms:
                        termination = ProbeTerminationReason.TIME_BUDGET
                        stop = True
                        break
                    if entries_visited >= max_entries:
                        termination = ProbeTerminationReason.ENTRY_BUDGET
                        stop = True
                        break
                    entries_visited += 1
                    if ignore_hidden and name.startswith(".") and len(name) > 1:
                        continue
                    child_rel = f"{relative_dir}/{name}"
                    if self._matches_ignore(
                        child_rel,
                        name,
                        kind,
                        ignore_hidden,
                        ignore_patterns,
                        global_ignore_patterns,
                    ):
                        continue
                    if kind is SourceNodePhysicalKind.REGULAR_FILE:
                        if not is_supported_source_tree_filename(name):
                            continue
                        samples.append(child_rel)
                        if len(samples) >= sample_limit:
                            termination = ProbeTerminationReason.SAMPLE_LIMIT
                            stop = True
                            stack.clear()
                            break
                    elif kind is SourceNodePhysicalKind.DIRECTORY:
                        stack.append((child_rel, depth + 1))
            except OSError:
                termination = ProbeTerminationReason.LOCAL_IO_ERROR
                break

        return decide_directory_probe(
            directory_relative_path=directory_relative_path,
            sample_relative_paths=tuple(samples),
            entries_visited=entries_visited,
            max_depth_reached=max_depth_reached,
            termination_reason=termination,
        )

    def path_is_readable_directory(self, path: Path) -> bool:
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_dir():
                return False
            iterator = os.scandir(resolved)
            iterator.close()
            return True
        except OSError:
            return False

    def observe_readable_file(self, path: Path) -> RegularFileObservation | None:
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_file():
                return None
            with resolved.open("rb") as readable:
                observed = os.fstat(readable.fileno())
            return RegularFileObservation(
                observed_size_bytes=int(observed.st_size),
                observed_mtime_ns=int(observed.st_mtime_ns),
            )
        except OSError:
            return None

    def delete_source(
        self,
        *,
        root: Path,
        relative_path: str,
        physical_kind: SourceNodePhysicalKind,
    ) -> None:
        root_resolved = root.expanduser().resolve(strict=True)
        candidate = root_resolved / relative_path
        if candidate.is_symlink():
            raise ValueError("refuse_to_delete_symlink_source")
        target = candidate.resolve(strict=False)
        try:
            target.relative_to(root_resolved)
        except ValueError as error:
            raise ValueError("path_escapes_library_root") from error
        if target == root_resolved:
            raise ValueError("refuse_to_delete_library_root")
        if not target.exists():
            return
        if physical_kind is SourceNodePhysicalKind.DIRECTORY:
            if not target.is_dir():
                raise ValueError("source_kind_changed")
            shutil.rmtree(target)
            return
        if physical_kind is SourceNodePhysicalKind.REGULAR_FILE:
            if not target.is_file():
                raise ValueError("source_kind_changed")
            target.unlink()
            return
        raise ValueError("unsupported_source_kind")

    def _physical_kind(self, entry: os.DirEntry[str]) -> SourceNodePhysicalKind:
        if entry.is_symlink():
            return SourceNodePhysicalKind.SYMLINK
        if entry.is_dir(follow_symlinks=False):
            return SourceNodePhysicalKind.DIRECTORY
        if entry.is_file(follow_symlinks=False):
            return SourceNodePhysicalKind.REGULAR_FILE
        return SourceNodePhysicalKind.OTHER

    def _matches_ignore(
        self,
        relative: str,
        name: str,
        physical_kind: SourceNodePhysicalKind,
        ignore_hidden: bool,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
    ) -> bool:
        return should_ignore_source_entry(
            relative_path=relative,
            name=name,
            is_regular_file=physical_kind is SourceNodePhysicalKind.REGULAR_FILE,
            ignore_hidden=ignore_hidden,
            library_patterns=ignore_patterns,
            global_patterns=global_ignore_patterns,
        )
