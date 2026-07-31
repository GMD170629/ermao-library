"""Bounded, streaming directory discovery for very large monitor trees."""

from __future__ import annotations

import os
from collections import Counter, deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from app.modules.imports.application.audio_types import (
    DISC_DIRECTORY_PATTERN,
    MAX_AUDIO_BUNDLE_TRACKS,
    is_supported_audio_file,
)
from app.modules.imports.application.work_queue_dto import ScanErrorDTO
from app.modules.imports.infrastructure.directory_scan import (
    ImportIgnoreReason,
    MonitorFolderConfig,
    audio_track_name_proves_membership,
    import_source_ignore_reason,
    is_supported_import_filename,
    should_ignore_path,
)
from app.services.book_identity import (
    normalize_identity_part,
    recognize_book_identity_with_regex,
)

SCAN_ENTRY_LIMIT = 5_000
SCAN_CANDIDATE_LIMIT = 500
SCAN_TIME_BUDGET_SECONDS = 0.250
SCAN_ERROR_SAMPLE_LIMIT = 100


@dataclass
class _AudioGroup:
    root: Path
    title_key: str
    paths: list[Path] = field(default_factory=list)
    track_count: int = 0
    overflowed: bool = False
    all_tracks_named: bool = True
    has_sibling_book: bool = False
    has_root_tracks: bool = False
    has_volume_tracks: bool = False
    read_failed: bool = False

    def add(self, path: Path, *, from_volume: bool) -> None:
        self.track_count += 1
        self.all_tracks_named = (
            self.all_tracks_named and audio_track_name_proves_membership(path)
        )
        if from_volume:
            self.has_volume_tracks = True
        else:
            self.has_root_tracks = True
        if self.track_count <= MAX_AUDIO_BUNDLE_TRACKS:
            self.paths.append(path)
            return
        if not self.overflowed:
            self.paths.clear()
            self.overflowed = True


@dataclass
class _Frame:
    path: Path
    entries: Iterator[os.DirEntry[str]]
    audio_group: _AudioGroup
    owns_audio_group: bool
    audio_volume_path: Path
    is_group_root: bool


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

    def __init__(self, root_path: Path, folder: MonitorFolderConfig) -> None:
        self._root_path = root_path.expanduser().resolve()
        self._folder = folder
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
                frame.audio_group.read_failed = True
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
                if is_supported_audio_file(path):
                    reason = import_source_ignore_reason(path, self._folder)
                    if reason is not None:
                        self._record_ignored(reason)
                        continue
                    frame.audio_group.add(
                        path.resolve(),
                        from_volume=frame.audio_volume_path != frame.audio_group.root,
                    )
                    continue
                reason = import_source_ignore_reason(path, self._folder)
                if reason is not None:
                    self._record_ignored(reason)
                    continue
                if frame.is_group_root and is_supported_import_filename(path):
                    frame.audio_group.has_sibling_book = True
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

    @property
    def buffered_audio_path_count(self) -> int:
        return sum(len(frame.audio_group.paths) for frame in self._owned_frames())

    def _owned_frames(self) -> Iterator[_Frame]:
        return (frame for frame in self._stack if frame.owns_audio_group)

    def _enter_directory(self, path: Path, *, parent: _Frame | None = None) -> None:
        self._directories_delta += 1
        try:
            entries = os.scandir(path)
        except (OSError, ValueError) as exc:
            self._record_error(path, exc)
            return
        if parent is None:
            group = _new_audio_group(path)
            owns_group = True
            volume_path = path
            is_group_root = True
        elif DISC_DIRECTORY_PATTERN.match(path.name.strip()):
            group = parent.audio_group
            owns_group = False
            volume_path = parent.audio_volume_path
            is_group_root = False
        elif parent.is_group_root and _is_audio_volume_child(parent.audio_group, path):
            group = parent.audio_group
            owns_group = False
            volume_path = path
            is_group_root = False
        else:
            group = _new_audio_group(path)
            owns_group = True
            volume_path = path
            is_group_root = True
        self._stack.append(
            _Frame(
                path=path,
                entries=entries,
                audio_group=group,
                owns_audio_group=owns_group,
                audio_volume_path=volume_path,
                is_group_root=is_group_root,
            )
        )

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
        if frame.owns_audio_group:
            self._finalize_audio_group(frame.audio_group)

    def _finalize_audio_group(self, group: _AudioGroup) -> None:
        if not group.track_count:
            return
        if group.read_failed:
            self._skipped_delta += group.track_count
            return
        if group.overflowed:
            self._skipped_delta += group.track_count
            self._reasons["audio_track_limit_exceeded"] += group.track_count
            if len(self._errors) < SCAN_ERROR_SAMPLE_LIMIT:
                self._errors.append(
                    ScanErrorDTO(
                        path=str(group.root),
                        error=(
                            f"有声书音轨超过 {MAX_AUDIO_BUNDLE_TRACKS} 条，"
                            "请拆分目录后重新导入"
                        ),
                        code="AUDIO_TRACK_LIMIT_EXCEEDED",
                        limit=MAX_AUDIO_BUNDLE_TRACKS,
                        observed_count=group.track_count,
                    )
                )
            return
        if group.has_root_tracks and group.has_volume_tracks:
            self._skipped_delta += group.track_count
            self._record_error(
                group.root,
                ValueError(
                    "有声书书名目录不能同时包含直属音轨和卷目录，"
                    "请整理为单卷或多卷结构后重试"
                ),
            )
            return
        proven_bundle = group.track_count >= 2 and (
            not group.has_sibling_book or group.all_tracks_named
        )
        if proven_bundle:
            self._queue_candidate(group.root)
            return
        for path in group.paths:
            self._queue_candidate(path)

    def _reset_delta(self) -> None:
        self._pending_candidates = []
        self._directories_delta = 0
        self._files_delta = 0
        self._candidates_delta = 0
        self._skipped_delta = 0
        self._reasons = Counter()
        self._errors = []


def _new_audio_group(path: Path) -> _AudioGroup:
    identity = recognize_book_identity_with_regex(f"{path.name}.epub")
    return _AudioGroup(
        root=path,
        title_key=normalize_identity_part(identity.title.strip() or path.name),
    )


def _is_audio_volume_child(group: _AudioGroup, child: Path) -> bool:
    identity = recognize_book_identity_with_regex(f"{child.name}.epub")
    child_key = normalize_identity_part(identity.title.strip() or child.name)
    return identity.volume_index is not None or bool(
        group.title_key
        and child_key
        and child_key != group.title_key
        and group.title_key in child_key
    )
