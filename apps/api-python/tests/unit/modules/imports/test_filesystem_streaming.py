from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.modules.imports.application.readable_resource.ports import (
    DirectoryEntry,
    UnreadableDirectoryEntry,
)
from app.modules.imports.domain.directory_probe import ProbeTerminationReason
from app.modules.imports.domain.resource_adapters import ResourceAdapterId
from app.modules.imports.infrastructure.readable_resource.filesystem import (
    OsSourceTreeFilesystem,
)
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind


class BudgetedFilesystem(OsSourceTreeFilesystem):
    """Instrument directory iteration so over-consumption is detectable."""

    def __init__(self, *, budget: int, names: Iterator[str]) -> None:
        self._budget = budget
        self._names = names
        self.yielded = 0
        self.exhausted = False

    def iter_directory_entries(
        self, absolute_directory: Path
    ) -> Iterator[DirectoryEntry | UnreadableDirectoryEntry]:
        try:
            for name in self._names:
                self.yielded += 1
                if self.yielded > self._budget:
                    raise AssertionError(
                        f"directory iterator consumed beyond budget "
                        f"({self.yielded} > {self._budget})"
                    )
                yield (name, SourceNodePhysicalKind.REGULAR_FILE, 1, self.yielded)
        except StopIteration:
            self.exhausted = True
            return
        else:
            # Generator finished naturally.
            self.exhausted = True


def test_probe_does_not_materialize_full_directory_listing(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    target = root / "book"
    target.mkdir()

    def names() -> Iterator[str]:
        for i in range(10_000):
            yield f"track-{i:05d}.mp3"
        raise AssertionError("generator fully exhausted unexpectedly")

    fs = BudgetedFilesystem(budget=150, names=names())
    decision, termination = fs.probe_directory(
        root=root,
        directory_relative_path="book",
        ignore_hidden=True,
        ignore_patterns=None,
        global_ignore_patterns="",
        sample_limit=100,
        max_entries=10_000,
        max_depth=4,
        time_budget_ms=60_000,
    )
    assert termination is ProbeTerminationReason.SAMPLE_LIMIT
    assert decision.evidence.sample_count == 100
    assert fs.yielded == 100
    assert fs.exhausted is False


def test_million_entry_generator_stops_at_sample_limit(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    (root / "huge").mkdir()

    class CountingNames:
        def __init__(self) -> None:
            self.count = 0

        def __iter__(self) -> Iterator[str]:
            return self

        def __next__(self) -> str:
            if self.count >= 1_000_000:
                raise StopIteration
            self.count += 1
            return f"{self.count:07d}.mp3"

    counter = CountingNames()
    fs = BudgetedFilesystem(budget=200, names=iter(counter))
    decision, termination = fs.probe_directory(
        root=root,
        directory_relative_path="huge",
        ignore_hidden=True,
        ignore_patterns=None,
        global_ignore_patterns="",
        sample_limit=100,
        max_entries=50_000,
        max_depth=2,
        time_budget_ms=60_000,
    )
    assert termination is ProbeTerminationReason.SAMPLE_LIMIT
    assert decision.evidence.sample_count == 100
    assert counter.count == 100
    assert counter.count < 1_000_000


def test_probe_ignores_cover_and_opf_sidecars_before_adapter_matching(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lib"
    target = root / "audiobook"
    target.mkdir(parents=True)
    (target / "01.mp3").write_bytes(b"audio")
    (target / "01.opf").write_text("<package />", encoding="utf-8")
    (target / "01.cover.jpg").write_bytes(b"cover")
    (target / "cover.webp").write_bytes(b"cover")
    (target / "download.tmp").write_bytes(b"temporary")
    (target / "metadata.json").write_text("{}", encoding="utf-8")
    cache = target / "cache"
    cache.mkdir()
    (cache / "bonus.mp3").write_bytes(b"ignored audio")

    decision, termination = OsSourceTreeFilesystem().probe_directory(
        root=root,
        directory_relative_path="audiobook",
        ignore_hidden=True,
        ignore_patterns="**/cache/**",
        global_ignore_patterns="*.tmp",
        sample_limit=100,
        max_entries=100,
        max_depth=4,
        time_budget_ms=60_000,
    )

    assert termination is ProbeTerminationReason.COMPLETE_SUBTREE
    assert decision.adapter is not None
    assert decision.adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
    assert decision.evidence.sample_relative_paths == ("audiobook/01.mp3",)


def test_visible_entry_with_unreadable_stat_returns_protection_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class UnreadableEntry:
        name = "keep.epub"

        def is_symlink(self) -> bool:
            return False

        def is_dir(self, *, follow_symlinks: bool) -> bool:
            del follow_symlinks
            return False

        def is_file(self, *, follow_symlinks: bool) -> bool:
            del follow_symlinks
            return True

        def stat(self, *, follow_symlinks: bool) -> object:
            del follow_symlinks
            raise OSError("temporarily unavailable")

    class ScandirIterator:
        def __iter__(self) -> Iterator[UnreadableEntry]:
            yield UnreadableEntry()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.modules.imports.infrastructure.readable_resource.filesystem.os.scandir",
        lambda _path: ScandirIterator(),
    )
    observed = list(OsSourceTreeFilesystem().iter_directory_entries(tmp_path))
    assert observed == [UnreadableDirectoryEntry(name="keep.epub")]


def test_path_traversal_raises(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    fs = OsSourceTreeFilesystem()
    with pytest.raises(ValueError, match="path_escapes_library_root"):
        fs.resolve_under_root(root, "../outside/secret.epub")


def test_symlink_escape_raises(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.epub"
    secret.write_text("x", encoding="utf-8")
    link = root / "escape.epub"
    link.symlink_to(secret)
    fs = OsSourceTreeFilesystem()
    # resolve() follows the symlink first; either escape message is acceptable.
    with pytest.raises(ValueError, match="escapes_library_root"):
        fs.resolve_under_root(root, "escape.epub")
