from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path
from typing import BinaryIO, NoReturn, Self

import pytest

from app.modules.catalog.application.content_dto import (
    SourceDigestProgress,
    SourceDigestRequest,
)
from app.modules.catalog.application.content_ports import (
    ContentLeaseLost,
    InvalidSourceDigestRelativePath,
    SourceDigestIoError,
    SourceDigestPermissionDenied,
    SourceDigestRootIdentityChanged,
    SourceDigestUnavailable,
)
from app.modules.catalog.application.source_admission_ports import (
    InvalidSourceRelativePath,
    SourceProbeIoError,
    SourceProbePermissionDenied,
    SourceProbeUnavailable,
    SourceStatExpectation,
)
from app.modules.catalog.domain.content import Sha256Digest
from app.modules.catalog.domain.model import EntryType
from app.modules.catalog.infrastructure.admission.source_file import OpenedSource
from app.modules.catalog.infrastructure.content import LocalSourceDigestAdapter
from app.modules.catalog.infrastructure.content import (
    local_source_digest as digest_module,
)


def _root_identity(root: Path) -> str:
    root_stat = root.stat()
    return f"{root_stat.st_dev}:{root_stat.st_ino}"


def _expected(source: Path) -> SourceStatExpectation:
    source_stat = source.stat()
    return SourceStatExpectation(
        device_id=source_stat.st_dev,
        file_id=source_stat.st_ino,
        size_bytes=source_stat.st_size,
        modified_ns=source_stat.st_mtime_ns,
    )


def _request(root: Path, source: Path) -> SourceDigestRequest:
    return SourceDigestRequest(
        library_id="library-security",
        source_entry_id="source-security",
        input_revision=1,
        canonical_root=str(root.resolve()),
        expected_root_identity=_root_identity(root),
        relative_path=(source.name,),
        expected_stat=_expected(source),
    )


class _ReadSizeSpy:
    def __init__(self, stream: BinaryIO, observed_sizes: list[int]) -> None:
        self._stream = stream
        self._observed_sizes = observed_sizes

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stream.close()

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise AssertionError("unbounded read is forbidden")
        self._observed_sizes.append(size)
        return self._stream.read(size)


class _RecordingCheckpoint:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.progress: list[SourceDigestProgress] = []
        self._fail_after = fail_after

    def checkpoint(self, progress: SourceDigestProgress) -> None:
        self.progress.append(progress)
        if self._fail_after == len(self.progress):
            raise ContentLeaseLost()


def test_digest_never_uses_an_unbounded_or_oversized_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-library"
    root.mkdir()
    source = root / "large.bin"
    source.write_bytes((b"x" * (1024 * 1024 * 2)) + b"tail")
    observed_sizes: list[int] = []
    original_duplicate = OpenedSource.duplicate_binary

    def duplicate_with_spy(opened: OpenedSource) -> _ReadSizeSpy:
        return _ReadSizeSpy(original_duplicate(opened), observed_sizes)

    monkeypatch.setattr(OpenedSource, "duplicate_binary", duplicate_with_spy)

    checkpoint = _RecordingCheckpoint()
    result = LocalSourceDigestAdapter().digest(
        _request(root, source),
        checkpoint,
    )

    assert result.content_digest == Sha256Digest.from_bytes(source.read_bytes())
    assert observed_sizes
    assert set(observed_sizes) == {1024 * 1024}
    assert [progress.bytes_hashed for progress in checkpoint.progress] == [
        1024 * 1024,
        1024 * 1024 * 2,
        (1024 * 1024 * 2) + 4,
    ]


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="requires procfs")
def test_lease_loss_stops_before_the_next_chunk_and_closes_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-library"
    root.mkdir()
    source = root / "large.bin"
    source.write_bytes(b"x" * (1024 * 1024 * 8))
    observed_sizes: list[int] = []
    original_duplicate = OpenedSource.duplicate_binary

    def duplicate_with_spy(opened: OpenedSource) -> _ReadSizeSpy:
        return _ReadSizeSpy(original_duplicate(opened), observed_sizes)

    monkeypatch.setattr(OpenedSource, "duplicate_binary", duplicate_with_spy)
    checkpoint = _RecordingCheckpoint(fail_after=2)
    descriptor_baseline = len(os.listdir("/proc/self/fd"))

    with pytest.raises(ContentLeaseLost):
        LocalSourceDigestAdapter().digest(
            _request(root, source),
            checkpoint,
        )

    assert observed_sizes == [1024 * 1024, 1024 * 1024]
    assert [progress.bytes_hashed for progress in checkpoint.progress] == [
        1024 * 1024,
        1024 * 1024 * 2,
    ]
    assert len(os.listdir("/proc/self/fd")) == descriptor_baseline


@pytest.mark.parametrize(
    "relative_path",
    [
        (),
        (".",),
        ("..",),
        ("shelf/book.epub",),
        ("shelf\\book.epub",),
        ("/absolute.epub",),
        ("C:drive.epub",),
        ("nul\x00name.epub",),
        ("surrogate\ud800.epub",),
    ],
)
def test_digest_request_rejects_path_injection(
    tmp_path: Path,
    relative_path: tuple[str, ...],
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"book")

    with pytest.raises((ValueError, UnicodeEncodeError)):
        SourceDigestRequest(
            library_id="library-security",
            source_entry_id="source-security",
            input_revision=1,
            canonical_root=str(root.resolve()),
            expected_root_identity=_root_identity(root),
            relative_path=relative_path,
            expected_stat=_expected(source),
        )


def test_adapter_maps_defensive_invalid_path_to_its_stable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"book")
    request = _request(root, source)

    def invalid_path(**_kwargs: object) -> NoReturn:
        raise InvalidSourceRelativePath()

    monkeypatch.setattr(digest_module, "open_source", invalid_path)

    with pytest.raises(InvalidSourceDigestRelativePath) as caught:
        LocalSourceDigestAdapter().digest(request, _RecordingCheckpoint())

    assert str(caught.value) == "INVALID_SOURCE_DIGEST_RELATIVE_PATH"
    assert isinstance(caught.value.__cause__, InvalidSourceRelativePath)


def test_permission_error_is_typed_path_free_and_preserves_the_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"book")

    def permission_denied(**_kwargs: object) -> NoReturn:
        try:
            raise PermissionError(f"cannot read {source}")
        except PermissionError as error:
            raise SourceProbePermissionDenied() from error

    monkeypatch.setattr(digest_module, "open_source", permission_denied)

    with pytest.raises(SourceDigestPermissionDenied) as caught:
        LocalSourceDigestAdapter().digest(
            _request(root, source),
            _RecordingCheckpoint(),
        )

    assert str(caught.value) == "SOURCE_DIGEST_PERMISSION_DENIED"
    assert str(root) not in str(caught.value)
    assert isinstance(caught.value.__cause__, SourceProbePermissionDenied)
    assert isinstance(caught.value.__cause__.__cause__, PermissionError)


def test_io_and_platform_failures_keep_stable_codes_and_causes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"book")
    request = _request(root, source)

    def io_failure(**_kwargs: object) -> NoReturn:
        try:
            raise OSError(f"failed under {root}")
        except OSError as error:
            raise SourceProbeIoError() from error

    monkeypatch.setattr(digest_module, "open_source", io_failure)
    with pytest.raises(SourceDigestIoError) as io_caught:
        LocalSourceDigestAdapter().digest(request, _RecordingCheckpoint())
    assert str(io_caught.value) == "SOURCE_DIGEST_IO_ERROR"
    assert str(root) not in str(io_caught.value)
    assert isinstance(io_caught.value.__cause__, SourceProbeIoError)
    assert isinstance(io_caught.value.__cause__.__cause__, OSError)

    def platform_unavailable(**_kwargs: object) -> NoReturn:
        raise SourceProbeUnavailable()

    monkeypatch.setattr(digest_module, "open_source", platform_unavailable)
    with pytest.raises(SourceDigestUnavailable) as unavailable_caught:
        LocalSourceDigestAdapter().digest(request, _RecordingCheckpoint())
    assert str(unavailable_caught.value) == "SOURCE_DIGEST_UNAVAILABLE"
    assert isinstance(unavailable_caught.value.__cause__, SourceProbeUnavailable)


def test_missing_and_rebound_roots_do_not_leak_the_canonical_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"book")
    request = _request(root, source)
    root.rename(tmp_path / "moved-private-library")

    with pytest.raises(SourceDigestUnavailable) as missing:
        LocalSourceDigestAdapter().digest(request, _RecordingCheckpoint())
    assert str(root) not in str(missing.value)

    replacement = root
    replacement.mkdir()
    (replacement / source.name).write_bytes(b"book")
    with pytest.raises(SourceDigestRootIdentityChanged) as rebound:
        LocalSourceDigestAdapter().digest(request, _RecordingCheckpoint())
    assert str(root) not in str(rebound.value)


def test_junction_observation_fails_closed_and_closes_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "junction"
    source.write_bytes(b"must not be read")
    request = _request(root, source)
    opened = OpenedSource(
        relative_path=(source.name,),
        observed_path=(source.name,),
        observed_name=source.name,
        root_fd=os.open(root, os.O_RDONLY),
        parent_fd=os.open(root, os.O_RDONLY),
        source_fd=None,
        initial_stat=source.stat(),
        entry_type=EntryType.JUNCTION,
    )

    def junction(**_kwargs: object) -> OpenedSource:
        return opened

    monkeypatch.setattr(digest_module, "open_source", junction)

    with pytest.raises(SourceDigestUnavailable):
        LocalSourceDigestAdapter().digest(request, _RecordingCheckpoint())

    with pytest.raises(OSError):
        os.fstat(opened.root_fd)
    with pytest.raises(OSError):
        os.fstat(opened.parent_fd)
    assert source.read_bytes() == b"must not be read"


def test_evidence_and_errors_never_expose_root_or_relative_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-library-root"
    root.mkdir()
    source = root / "secret-book.epub"
    source.write_bytes(b"book")

    evidence = LocalSourceDigestAdapter().digest(
        _request(root, source),
        _RecordingCheckpoint(),
    )

    assert str(root.resolve()) not in repr(evidence)
    assert source.name not in repr(evidence)
    assert not any(
        "root" in field.name.casefold() or "path" in field.name.casefold()
        for field in fields(type(evidence))
    )
