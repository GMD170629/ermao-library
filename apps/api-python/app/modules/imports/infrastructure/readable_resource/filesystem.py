"""Filesystem traversal, path containment, and directory probe adapter."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import (
    DirectoryEntry,
    SourceTreeFilesystemPort,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    ProbeTerminationReason,
    decide_directory_probe,
)
from app.modules.imports.domain.ignore_rules import should_ignore_source_entry
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind


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
    ) -> Iterator[DirectoryEntry]:
        iterator = os.scandir(absolute_directory)
        try:
            for entry in iterator:
                kind = self._physical_kind(entry)
                try:
                    stat = entry.stat(follow_symlinks=False)
                    mtime_ns = int(stat.st_mtime_ns)
                    size = (
                        None
                        if kind is SourceNodePhysicalKind.DIRECTORY
                        else int(stat.st_size)
                    )
                except OSError:
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
    ) -> tuple[DirectoryProbeDecision, ProbeTerminationReason]:
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
                for name, kind, _size, _mtime in entries:
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

        decision = decide_directory_probe(
            sample_relative_paths=tuple(samples),
            entries_visited=entries_visited,
            max_depth_reached=max_depth_reached,
            termination_reason=termination,
        )
        return decision, termination

    def path_is_readable_directory(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            return resolved.is_dir() and os.access(resolved, os.R_OK | os.X_OK)
        except OSError:
            return False

    def _physical_kind(self, entry: os.DirEntry[str]) -> SourceNodePhysicalKind:
        try:
            if entry.is_symlink():
                return SourceNodePhysicalKind.SYMLINK
            if entry.is_dir(follow_symlinks=False):
                return SourceNodePhysicalKind.DIRECTORY
            if entry.is_file(follow_symlinks=False):
                return SourceNodePhysicalKind.REGULAR_FILE
        except OSError:
            return SourceNodePhysicalKind.OTHER
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
