"""Bounded, streaming directory discovery for large library roots."""

from __future__ import annotations

import os
from collections import Counter, deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from app.contracts.library_layout import LibraryOrganizationMode
from app.modules.imports.application.audio_types import MAX_AUDIO_BUNDLE_TRACKS
from app.modules.imports.application.work_queue_dto import ScanErrorDTO
from app.modules.imports.infrastructure.directory_scan import (
    ImportIgnoreReason,
    LibraryConfig,
    import_source_ignore_reason,
    should_ignore_path,
)
from app.services.audio_metadata import is_supported_audio_file

SCAN_ENTRY_LIMIT = 5_000
SCAN_CANDIDATE_LIMIT = 500
SCAN_TIME_BUDGET_SECONDS = 0.250
SCAN_ERROR_SAMPLE_LIMIT = 100


@dataclass
class _Frame:
    path: Path
    entries: Iterator[os.DirEntry[str]]
    depth: int
    audio_track_count: int = 0
    read_failed: bool = False


@dataclass(frozen=True)
class ScanSlice:
    candidates: tuple[Path, ...]
    directories_scanned: int
    files_scanned: int
    candidates_found: int
    skipped_count: int
    ignored_reason_counts: dict[str, int]
    errors: tuple[ScanErrorDTO, ...]
    completed: bool


class StreamingDirectoryScanner:
    """Keep only iterator stack and one bounded candidate batch in memory."""

    def __init__(self, root_path: Path, folder: LibraryConfig) -> None:
        self._root_path = root_path.expanduser().resolve()
        self._folder = folder
        self._organization_mode = LibraryOrganizationMode(folder.organization_mode)
        self._stack: list[_Frame] = []
        self._pending_candidates: list[Path] = []
        self._candidate_backlog: deque[Path] = deque()
        self._directories_delta = 0
        self._files_delta = 0
        self._candidates_delta = 0
        self._skipped_delta = 0
        self._reasons: Counter[str] = Counter()
        self._errors: list[ScanErrorDTO] = []
        self._started = False
        self._completed = False

    def close(self) -> None:
        while self._stack:
            frame = self._stack.pop()
            close = getattr(frame.entries, "close", None)
            if callable(close):
                close()
        self._completed = True

    def next_slice(self, *, candidate_limit: int = SCAN_CANDIDATE_LIMIT) -> ScanSlice:
        if not 1 <= candidate_limit <= SCAN_CANDIDATE_LIMIT:
            raise ValueError(
                f"candidate_limit must be between 1 and {SCAN_CANDIDATE_LIMIT}"
            )
        self._reset_delta()
        if not self._started:
            self._started = True
            self._enter_directory(self._root_path)
        deadline = monotonic() + SCAN_TIME_BUDGET_SECONDS
        entries_seen = 0
        while (
            (self._stack or self._candidate_backlog)
            and entries_seen < SCAN_ENTRY_LIMIT
            and len(self._pending_candidates) < candidate_limit
            and monotonic() < deadline
        ):
            if self._candidate_backlog:
                self._pending_candidates.append(self._candidate_backlog.popleft())
                continue
            frame = self._stack[-1]
            try:
                entry = next(frame.entries)
            except StopIteration:
                self._close_top_frame()
                continue
            except OSError as exc:
                self._record_error(frame.path, exc)
                frame.read_failed = True
                self._close_top_frame()
                continue
            entries_seen += 1
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if should_ignore_path(path, self._folder):
                        self._skipped_delta += 1
                        continue
                    self._enter_directory(path, parent=frame)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                self._files_delta += 1
                reason = import_source_ignore_reason(path, self._folder)
                if reason is not None:
                    self._record_ignored(reason)
                    continue
                if is_supported_audio_file(path):
                    self._accept_audio_file(path, frame)
                elif self._organization_mode is LibraryOrganizationMode.AUDIOBOOK:
                    self._record_ignored("unsupported_file_type")
                else:
                    self._queue_candidate(path)
            except (OSError, ValueError) as exc:
                self._record_error(path, exc)
        if not self._stack and not self._candidate_backlog:
            self._completed = True
        result = ScanSlice(
            candidates=tuple(self._pending_candidates),
            directories_scanned=self._directories_delta,
            files_scanned=self._files_delta,
            candidates_found=self._candidates_delta,
            skipped_count=self._skipped_delta,
            ignored_reason_counts=dict(self._reasons),
            errors=tuple(self._errors),
            completed=self._completed,
        )
        self._pending_candidates = []
        return result

    def _enter_directory(self, path: Path, *, parent: _Frame | None = None) -> None:
        self._directories_delta += 1
        try:
            entries = os.scandir(path)
        except (OSError, ValueError) as exc:
            self._record_error(path, exc)
            return
        self._stack.append(
            _Frame(
                path=path,
                entries=entries,
                depth=0 if parent is None else parent.depth + 1,
            )
        )

    def _accept_audio_file(self, path: Path, frame: _Frame) -> None:
        if self._organization_mode is not LibraryOrganizationMode.AUDIOBOOK:
            self._record_ignored("unsupported_file_type")
            return
        if frame.depth == 0:
            self._queue_candidate(path)
            return
        frame.audio_track_count += 1

    def _queue_candidate(self, path: Path) -> None:
        self._candidate_backlog.append(path)
        self._candidates_delta += 1

    def _record_ignored(self, reason: ImportIgnoreReason) -> None:
        self._skipped_delta += 1
        self._reasons[reason] += 1

    def _record_error(self, path: Path, error: BaseException) -> None:
        if len(self._errors) < SCAN_ERROR_SAMPLE_LIMIT:
            self._errors.append(ScanErrorDTO(path=str(path), error=str(error)))

    def _close_top_frame(self) -> None:
        frame = self._stack.pop()
        close = getattr(frame.entries, "close", None)
        if callable(close):
            close()
        if self._stack:
            self._stack[-1].audio_track_count += frame.audio_track_count
            self._stack[-1].read_failed = (
                self._stack[-1].read_failed or frame.read_failed
            )
        if (
            self._organization_mode is LibraryOrganizationMode.AUDIOBOOK
            and frame.depth == 1
            and frame.audio_track_count
        ):
            self._finalize_audiobook_work(frame)

    def _finalize_audiobook_work(self, frame: _Frame) -> None:
        if frame.read_failed:
            self._skipped_delta += frame.audio_track_count
            return
        if frame.audio_track_count > MAX_AUDIO_BUNDLE_TRACKS:
            self._skipped_delta += frame.audio_track_count
            self._reasons["audio_track_limit_exceeded"] += frame.audio_track_count
            if len(self._errors) < SCAN_ERROR_SAMPLE_LIMIT:
                self._errors.append(
                    ScanErrorDTO(
                        path=str(frame.path),
                        error=(
                            f"有声书音轨超过 {MAX_AUDIO_BUNDLE_TRACKS} 条，"
                            "请拆分目录后重新导入"
                        ),
                        code="AUDIO_TRACK_LIMIT_EXCEEDED",
                        limit=MAX_AUDIO_BUNDLE_TRACKS,
                        observed_count=frame.audio_track_count,
                    )
                )
            return
        self._queue_candidate(frame.path)

    def _reset_delta(self) -> None:
        self._pending_candidates = []
        self._directories_delta = 0
        self._files_delta = 0
        self._candidates_delta = 0
        self._skipped_delta = 0
        self._reasons = Counter()
        self._errors = []
