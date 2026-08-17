from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

import pytest

from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryIssue,
    DiscoveryIssueCode,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryChangedDuringDiscovery,
    DirectoryPermissionDenied,
    DirectoryRootUnavailable,
    InvalidDiscoveryRelativePath,
)
from app.modules.catalog.infrastructure.discovery import (
    LocalDirectoryDiscoveryAdapter,
)
from app.modules.catalog.infrastructure.discovery import (
    local_directory_discovery as discovery_module,
)


def _observations(
    root: Path, relative_directory: tuple[str, ...] = ()
) -> list[DiscoveredSource | DiscoveryIssue]:
    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=str(root.resolve())
    ) as session:
        return list(session.iter_directory(relative_directory))


def _descriptor_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_discovery_streams_direct_children_and_preserves_host_names(
    tmp_path: Path,
) -> None:
    preserved_name = "Café 01.epub"
    source = tmp_path / preserved_name
    source.write_bytes(b"source bytes are not part of discovery")
    nested = tmp_path / "Shelf"
    nested.mkdir()
    (nested / "nested.pdf").write_bytes(b"nested")

    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=str(tmp_path.resolve())
    ) as session:
        root_identity = session.root_identity
        root_entries = list(session.iter_directory(()))
        nested_entries = list(session.iter_directory(("Shelf",)))
        assert session.revalidate_root_identity() == root_identity

    by_path = {
        observation.relative_path: observation
        for observation in root_entries
        if isinstance(observation, DiscoveredSource)
    }
    file_observation = by_path[(preserved_name,)]
    observed_stat = source.stat()
    assert file_observation.entry_type is DiscoveryEntryType.FILE
    assert file_observation.expected_stat is not None
    assert file_observation.expected_stat.device_id == observed_stat.st_dev
    assert file_observation.expected_stat.file_id == observed_stat.st_ino
    assert file_observation.expected_stat.size_bytes == observed_stat.st_size
    assert file_observation.expected_stat.modified_ns == observed_stat.st_mtime_ns
    assert file_observation.filesystem_identity == (
        f"{observed_stat.st_dev}:{observed_stat.st_ino}"
    )
    assert by_path[("Shelf",)].entry_type is DiscoveryEntryType.DIRECTORY
    assert by_path[("Shelf",)].expected_stat is None
    assert ("Shelf", "nested.pdf") not in by_path
    assert [entry.relative_path for entry in nested_entries] == [
        ("Shelf", "nested.pdf")
    ]


@pytest.mark.parametrize(
    "relative_directory",
    [
        ("",),
        (".",),
        ("..",),
        ("/absolute",),
        ("nested/path",),
        ("nested\\path",),
        ("C:escape",),
        ("name\x00suffix",),
        ("invalid-\udcff",),
    ],
)
def test_relative_directory_rejects_injectable_components(
    tmp_path: Path,
    relative_directory: tuple[str, ...],
) -> None:
    with (
        LocalDirectoryDiscoveryAdapter().open(
            canonical_root=str(tmp_path.resolve())
        ) as session,
        pytest.raises(InvalidDiscoveryRelativePath) as caught,
    ):
        session.iter_directory(relative_directory)

    assert str(caught.value) == "INVALID_DISCOVERY_RELATIVE_PATH"
    assert str(tmp_path) not in str(caught.value)


def test_invalid_or_linked_root_is_path_free_and_never_followed(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    for canonical_root in (str(linked_root), "/private/library\x00suffix"):
        with (
            pytest.raises(DirectoryRootUnavailable) as caught,
            LocalDirectoryDiscoveryAdapter().open(canonical_root=canonical_root),
        ):
            pass
        assert str(caught.value) == "DIRECTORY_ROOT_UNAVAILABLE"
        assert "private" not in str(caught.value)
        assert "linked-root" not in str(caught.value)


def test_canonical_root_preserves_real_host_spelling_instead_of_normalizing(
    tmp_path: Path,
) -> None:
    decomposed_root_name = unicodedata.normalize("NFD", "Café")
    root = tmp_path / decomposed_root_name
    root.mkdir()
    (root / "book.epub").write_bytes(b"book")
    canonical_root = str(root.resolve())

    assert unicodedata.normalize("NFC", canonical_root) != canonical_root
    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=canonical_root
    ) as session:
        observations = list(session.iter_directory(()))
        assert session.revalidate_root_identity() == session.root_identity

    assert [entry.relative_path for entry in observations] == [("book.epub",)]


def test_symlink_and_special_children_are_typed_without_following(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"outside bytes")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    fifo = tmp_path / "event.pipe"
    os.mkfifo(fifo)

    observations = _observations(tmp_path)
    by_path = {
        observation.relative_path: observation
        for observation in observations
        if isinstance(observation, DiscoveredSource)
    }

    assert by_path[("linked",)].entry_type is DiscoveryEntryType.SYMLINK
    assert by_path[("linked",)].expected_stat is None
    assert by_path[("event.pipe",)].entry_type is DiscoveryEntryType.SPECIAL
    assert by_path[("event.pipe",)].expected_stat is None
    assert all("secret.txt" not in entry.relative_path for entry in by_path.values())
    assert secret.read_bytes() == b"outside bytes"


def test_host_names_preserve_nfd_and_unsafe_names_emit_path_free_issues(
    tmp_path: Path,
) -> None:
    decomposed_name = unicodedata.normalize("NFD", "café.epub")
    (tmp_path / decomposed_name).write_bytes(b"book")
    decomposed_directory = unicodedata.normalize("NFD", "Édition")
    nested = tmp_path / decomposed_directory
    nested.mkdir()
    (nested / decomposed_name).write_bytes(b"nested book")
    undecodable_path = os.fsencode(tmp_path) + b"/invalid-\xff.epub"
    descriptor = os.open(undecodable_path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(descriptor)

    observations = _observations(tmp_path)
    nested_observations = _observations(tmp_path, (decomposed_directory,))
    issues = [
        observation
        for observation in observations
        if isinstance(observation, DiscoveryIssue)
    ]
    sources = [
        observation
        for observation in observations
        if isinstance(observation, DiscoveredSource)
    ]

    assert issues == [
        DiscoveryIssue(parent_path=(), code=DiscoveryIssueCode.PATH_NAME_UNSUPPORTED),
    ]
    assert {source.relative_path for source in sources} == {
        (decomposed_name,),
        (decomposed_directory,),
    }
    assert [source.relative_path for source in nested_observations] == [
        (decomposed_directory, decomposed_name)
    ]
    issue_text = repr(issues)
    assert "invalid" not in issue_text


def test_discovery_does_not_read_bytes_or_open_for_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"immutable source content")
    child = tmp_path / "Shelf"
    child.mkdir()
    before_source = source.stat()
    before_child = child.stat()
    before_root = tmp_path.stat()
    real_open = discovery_module.os.open

    def guarded_open(
        path: str | bytes | int,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        assert flags & write_flags == 0
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def unexpected_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("directory discovery must not read source bytes")

    monkeypatch.setattr(discovery_module.os, "open", guarded_open)
    monkeypatch.setattr(discovery_module.os, "read", unexpected_read)
    monkeypatch.setattr(discovery_module.os, "pread", unexpected_read)

    observations = _observations(tmp_path)

    assert len(observations) == 2
    after_source = source.stat()
    after_child = child.stat()
    after_root = tmp_path.stat()
    assert source.read_bytes() == b"immutable source content"
    for before, after in (
        (before_source, after_source),
        (before_child, after_child),
        (before_root, after_root),
    ):
        assert (
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )


def test_session_closes_directory_iterators_on_completion_and_early_exit(
    tmp_path: Path,
) -> None:
    for index in range(20):
        (tmp_path / f"book-{index:02}.epub").write_bytes(b"book")
    baseline = _descriptor_count()

    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=str(tmp_path.resolve())
    ) as session:
        root_only = _descriptor_count()
        assert root_only == baseline + 1
        assert len(list(session.iter_directory(()))) == 20
        assert _descriptor_count() == root_only

        stream = session.iter_directory(())
        next(stream)
        assert _descriptor_count() > root_only

    assert _descriptor_count() == baseline
    assert list(stream) == []


def test_iterator_error_closes_all_owned_descriptors(tmp_path: Path) -> None:
    (tmp_path / "first.epub").write_bytes(b"book")
    baseline = _descriptor_count()

    with (
        pytest.raises(DirectoryChangedDuringDiscovery) as caught,
        LocalDirectoryDiscoveryAdapter().open(
            canonical_root=str(tmp_path.resolve())
        ) as session,
    ):
        stream = session.iter_directory(())
        next(stream)
        initial_directory_stat = tmp_path.stat()
        (tmp_path / "added.epub").write_bytes(b"changed during enumeration")
        os.utime(
            tmp_path,
            ns=(
                initial_directory_stat.st_atime_ns,
                initial_directory_stat.st_mtime_ns + 1_000_000_000,
            ),
        )
        list(stream)

    assert str(caught.value) == "DIRECTORY_CHANGED_DURING_DISCOVERY"
    assert str(tmp_path) not in str(caught.value)
    assert _descriptor_count() == baseline


class _ConsumerCancellation(BaseException):
    pass


@pytest.mark.parametrize("error_type", [RuntimeError, _ConsumerCancellation])
def test_consumer_exception_or_cancellation_closes_stream_and_session(
    tmp_path: Path,
    error_type: type[BaseException],
) -> None:
    (tmp_path / "book.epub").write_bytes(b"book")
    baseline = _descriptor_count()

    with (
        pytest.raises(error_type),
        LocalDirectoryDiscoveryAdapter().open(
            canonical_root=str(tmp_path.resolve())
        ) as session,
    ):
        stream = session.iter_directory(())
        next(stream)
        raise error_type()

    assert _descriptor_count() == baseline


def test_revalidate_freshly_walks_canonical_root_after_ancestor_rebind(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "anchor"
    root = anchor / "library"
    root.mkdir(parents=True)
    displaced = tmp_path / "displaced-anchor"

    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=str(root.resolve())
    ) as session:
        initial_identity = session.root_identity
        anchor.rename(displaced)
        root.mkdir(parents=True)
        rebound_identity = session.revalidate_root_identity()

    assert rebound_identity != initial_identity


def test_directory_stream_detects_relative_ancestor_rebind(tmp_path: Path) -> None:
    observed = tmp_path / "shelf" / "volume"
    observed.mkdir(parents=True)
    (observed / "book.epub").write_bytes(b"book")
    displaced = tmp_path / "displaced-shelf"

    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=str(tmp_path.resolve())
    ) as session:
        stream = session.iter_directory(("shelf", "volume"))
        next(stream)
        (tmp_path / "shelf").rename(displaced)
        observed.mkdir(parents=True)
        (observed / "book.epub").write_bytes(b"book")

        with pytest.raises(DirectoryChangedDuringDiscovery):
            list(stream)


def test_permission_denial_is_typed_path_free_and_preserves_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    real_open = discovery_module.os.open

    def denied_child_open(
        path: str | bytes | int,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "restricted":
            raise PermissionError("denied /private/library")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(discovery_module.os, "open", denied_child_open)

    with (
        LocalDirectoryDiscoveryAdapter().open(
            canonical_root=str(tmp_path.resolve())
        ) as session,
        pytest.raises(DirectoryPermissionDenied) as caught,
    ):
        session.iter_directory(("restricted",))

    assert str(caught.value) == "DIRECTORY_PERMISSION_DENIED"
    assert isinstance(caught.value.__cause__, PermissionError)
    assert str(restricted) not in str(caught.value)


class _FakeDirectoryEntry:
    def __init__(self, name: str, source_stat: os.stat_result) -> None:
        self.name = name
        self._source_stat = source_stat

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        assert not follow_symlinks
        return self._source_stat


class _MillionEntryIterator(Iterator[_FakeDirectoryEntry]):
    def __init__(self, source_stat: os.stat_result) -> None:
        self._source_stat = source_stat
        self.observed_count = 0
        self.closed = False

    def __next__(self) -> _FakeDirectoryEntry:
        if self.observed_count >= 1_000_000:
            raise StopIteration
        self.observed_count += 1
        return _FakeDirectoryEntry(
            f"book-{self.observed_count}.epub",
            self._source_stat,
        )

    def close(self) -> None:
        self.closed = True


def test_million_entry_source_is_lazy_and_only_consumes_requested_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = tmp_path / "template.epub"
    template.write_bytes(b"book")
    entries = _MillionEntryIterator(template.stat())
    monkeypatch.setattr(discovery_module.os, "scandir", lambda _fd: entries)

    with LocalDirectoryDiscoveryAdapter().open(
        canonical_root=str(tmp_path.resolve())
    ) as session:
        stream = session.iter_directory(())
        prefix = tuple(islice(stream, 7))
        assert len(prefix) == 7
        assert entries.observed_count == 7
        assert not entries.closed

    assert entries.closed
    assert entries.observed_count == 7
