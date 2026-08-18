from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path

import pytest

from app.modules.catalog.application.content_dto import (
    SourceDigestProgress,
    SourceDigestRequest,
)
from app.modules.catalog.application.content_ports import (
    SourceChangedDuringDigest,
    SourceDigestIoError,
    SourceDigestRootIdentityChanged,
    SourceDigestUnavailable,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)
from app.modules.catalog.domain.content import Sha256Digest
from app.modules.catalog.infrastructure.content import LocalSourceDigestAdapter


class _Checkpoint:
    def checkpoint(self, progress: SourceDigestProgress) -> None:
        assert progress.bytes_hashed > 0


def _root_identity(root: Path) -> str:
    root_stat = root.stat()
    return f"{root_stat.st_dev}:{root_stat.st_ino}"


def _expected(path: Path, *, follow_symlinks: bool = True) -> SourceStatExpectation:
    source_stat = path.stat(follow_symlinks=follow_symlinks)
    return SourceStatExpectation(
        device_id=source_stat.st_dev,
        file_id=source_stat.st_ino,
        size_bytes=source_stat.st_size,
        modified_ns=source_stat.st_mtime_ns,
    )


def _request(
    root: Path,
    relative_path: tuple[str, ...],
    *,
    expected_stat: SourceStatExpectation | None = None,
    expected_root_identity: str | None = None,
    input_revision: int = 1,
) -> SourceDigestRequest:
    source = root.joinpath(*relative_path)
    return SourceDigestRequest(
        library_id="library-digest",
        source_entry_id="source-digest",
        input_revision=input_revision,
        canonical_root=str(root.resolve()),
        expected_root_identity=expected_root_identity or _root_identity(root),
        relative_path=relative_path,
        expected_stat=expected_stat or _expected(source),
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes | str], ...]:
    snapshot: list[tuple[str, str, bytes | str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            snapshot.append((relative, "directory", b""))
        else:
            snapshot.append((relative, "file", path.read_bytes()))
    return tuple(snapshot)


def _descriptor_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_digest_streams_all_bytes_and_preserves_nfd_paths_without_writes(
    tmp_path: Path,
) -> None:
    root_name = unicodedata.normalize("NFD", "Café-library")
    source_name = unicodedata.normalize("NFD", "Résumé.epub")
    root = tmp_path / root_name
    root.mkdir()
    payload = (b"a" * (1024 * 1024)) + (b"b" * (1024 * 1024)) + b"tail"
    source = root / source_name
    source.write_bytes(payload)
    before = _tree_snapshot(root)

    result = LocalSourceDigestAdapter().digest(
        _request(root, (source_name,)),
        _Checkpoint(),
    )

    assert result.source_entry_id == "source-digest"
    assert result.input_revision == 1
    assert result.bytes_hashed == len(payload)
    assert result.observed_stat == _expected(source)
    assert result.content_digest == Sha256Digest(
        f"sha256:{hashlib.sha256(payload).hexdigest()}"
    )
    assert result.observed_stat.size_bytes == len(payload)
    assert _tree_snapshot(root) == before
    assert source_name != unicodedata.normalize("NFC", source_name)


def test_nfd_source_is_not_confused_with_its_nfc_sibling(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    nfd_name = unicodedata.normalize("NFD", "Café.txt")
    nfc_name = unicodedata.normalize("NFC", "Café.txt")
    assert nfd_name != nfc_name
    nfd_source = root / nfd_name
    nfc_source = root / nfc_name
    nfd_source.write_bytes(b"nfd bytes")
    nfc_source.write_bytes(b"nfc sibling bytes")
    if nfd_source.samefile(nfc_source):
        pytest.skip("host filesystem aliases NFC and NFD names")

    result = LocalSourceDigestAdapter().digest(
        _request(root, (nfd_name,)),
        _Checkpoint(),
    )

    assert result.content_digest == Sha256Digest.from_bytes(b"nfd bytes")
    assert nfd_source.read_bytes() == b"nfd bytes"
    assert nfc_source.read_bytes() == b"nfc sibling bytes"


def test_same_inode_size_and_restored_mtime_still_produce_a_new_full_digest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"a" * 4096)
    original_stat = source.stat()
    expected = _expected(source)
    request = _request(root, (source.name,), expected_stat=expected)

    first = LocalSourceDigestAdapter().digest(request, _Checkpoint())
    source.write_bytes(b"b" * 4096)
    os.utime(
        source,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    rewritten_stat = source.stat()
    assert rewritten_stat.st_ino == original_stat.st_ino
    assert rewritten_stat.st_size == original_stat.st_size
    assert rewritten_stat.st_mtime_ns == original_stat.st_mtime_ns

    second = LocalSourceDigestAdapter().digest(request, _Checkpoint())

    assert second.observed_stat == expected
    assert second.content_digest != first.content_digest
    assert second.content_digest == Sha256Digest.from_bytes(b"b" * 4096)


def test_expected_root_identity_is_checked_before_reading(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.txt"
    source.write_text("content", encoding="utf-8")
    request = _request(
        root,
        (source.name,),
        expected_root_identity="malformed-or-stale-root-identity",
    )

    with pytest.raises(SourceDigestRootIdentityChanged) as caught:
        LocalSourceDigestAdapter().digest(request, _Checkpoint())

    assert str(caught.value) == "SOURCE_DIGEST_ROOT_IDENTITY_CHANGED"
    assert str(root) not in str(caught.value)


def test_expected_source_stat_is_checked_before_reading(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.txt"
    source.write_bytes(b"original")
    request = _request(root, (source.name,))
    source.write_bytes(b"changed before digest")

    with pytest.raises(SourceChangedDuringDigest) as caught:
        LocalSourceDigestAdapter().digest(request, _Checkpoint())

    assert str(caught.value) == "SOURCE_CHANGED_DURING_DIGEST"
    assert str(root) not in str(caught.value)


def test_post_digest_fence_detects_leaf_replacement(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.txt"
    source.write_bytes(b"original")
    displaced = root / "old-book.txt"

    def replace_after_digest() -> None:
        source.rename(displaced)
        source.write_bytes(b"replaced")

    adapter = LocalSourceDigestAdapter(digest_completion_hook=replace_after_digest)

    with pytest.raises(SourceChangedDuringDigest):
        adapter.digest(_request(root, (source.name,)), _Checkpoint())


def test_post_digest_fence_detects_ancestor_rebind(tmp_path: Path) -> None:
    root = tmp_path / "library"
    shelf = root / "shelf"
    shelf.mkdir(parents=True)
    source = shelf / "book.txt"
    source.write_bytes(b"original")
    displaced = root / "old-shelf"

    def rebind_after_digest() -> None:
        shelf.rename(displaced)
        shelf.mkdir()
        (shelf / source.name).write_bytes(b"original")

    adapter = LocalSourceDigestAdapter(digest_completion_hook=rebind_after_digest)

    with pytest.raises(SourceChangedDuringDigest):
        adapter.digest(_request(root, ("shelf", source.name)), _Checkpoint())


def test_post_digest_fence_detects_canonical_root_rebind(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.txt"
    source.write_bytes(b"original")
    displaced = tmp_path / "old-library"

    def rebind_after_digest() -> None:
        root.rename(displaced)
        root.mkdir()
        (root / source.name).write_bytes(b"original")

    adapter = LocalSourceDigestAdapter(digest_completion_hook=rebind_after_digest)

    with pytest.raises(SourceDigestRootIdentityChanged):
        adapter.digest(_request(root, (source.name,)), _Checkpoint())


@pytest.mark.parametrize("intermediate", [False, True])
def test_symlink_sources_are_never_followed(tmp_path: Path, intermediate: bool) -> None:
    root = tmp_path / "library"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    outside_source = outside / "secret.txt"
    outside_source.write_bytes(b"outside secret")
    relative_path: tuple[str, ...]
    if intermediate:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        relative_path = ("linked", outside_source.name)
        expected = _expected(outside_source)
    else:
        linked = root / "linked.txt"
        linked.symlink_to(outside_source)
        relative_path = (linked.name,)
        expected = _expected(linked, follow_symlinks=False)

    with pytest.raises(SourceDigestUnavailable) as caught:
        LocalSourceDigestAdapter().digest(
            _request(root, relative_path, expected_stat=expected),
            _Checkpoint(),
        )

    assert str(caught.value) == "SOURCE_DIGEST_UNAVAILABLE"
    assert str(root) not in str(caught.value)
    assert outside_source.read_bytes() == b"outside secret"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX special files")
def test_special_files_fail_closed_without_being_opened(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    special = root / "named-pipe"
    os.mkfifo(special)

    with pytest.raises(SourceDigestIoError) as caught:
        LocalSourceDigestAdapter().digest(
            _request(
                root,
                (special.name,),
                expected_stat=_expected(special, follow_symlinks=False),
            ),
            _Checkpoint(),
        )

    assert str(caught.value) == "SOURCE_DIGEST_IO_ERROR"


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="requires procfs")
def test_success_and_failure_close_every_source_descriptor(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.txt"
    source.write_bytes(b"content")
    request = _request(root, (source.name,))
    baseline = _descriptor_count()

    adapter = LocalSourceDigestAdapter()
    for _ in range(32):
        adapter.digest(request, _Checkpoint())
    assert _descriptor_count() == baseline

    def fail_after_digest() -> None:
        raise OSError("private failure detail")

    with pytest.raises(SourceDigestIoError) as caught:
        LocalSourceDigestAdapter(digest_completion_hook=fail_after_digest).digest(
            request,
            _Checkpoint(),
        )
    assert str(caught.value) == "SOURCE_DIGEST_IO_ERROR"
    assert "private" not in str(caught.value)
    assert _descriptor_count() == baseline


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="requires procfs")
def test_cancellation_closes_every_source_descriptor(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.txt"
    source.write_bytes(b"content")
    request = _request(root, (source.name,))
    baseline = _descriptor_count()

    def cancel_after_digest() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        LocalSourceDigestAdapter(digest_completion_hook=cancel_after_digest).digest(
            request,
            _Checkpoint(),
        )

    assert _descriptor_count() == baseline
