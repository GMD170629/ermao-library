"""Uploads share admission, preserve completed files, and clean staging."""

from io import BytesIO

import pytest

from app.modules.imports.application import import_file_size
from app.modules.imports.application.errors import ImportFileTooLargeError
from app.modules.imports.application.save_uploaded_files import (
    SaveUploadedFiles,
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadSource,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)


@pytest.mark.parametrize("size", [2**31 - 1, 2**31])
def test_import_admission_accepts_two_gib_boundary(size):
    import_file_size.validate_import_file_size(size)


def test_import_admission_rejects_one_byte_over_two_gib():
    with pytest.raises(ImportFileTooLargeError, match="IMPORT_FILE_TOO_LARGE"):
        import_file_size.validate_import_file_size(2**31 + 1)


def test_browser_save_preserves_existing_name_and_copies_exact_bytes(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"existing")
    result = SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(
        SaveUploadedFilesCommand(
            tmp_path, (UploadSource("book.epub", BytesIO(b"new upload")),)
        )
    )
    assert result[0].filename == "book-1.epub"
    assert result[0].size_bytes == len(b"new upload")
    assert result[0].path.read_bytes() == b"new upload"
    assert (tmp_path / "book.epub").read_bytes() == b"existing"
    assert list(tmp_path.glob(".upload-*")) == []


@pytest.mark.parametrize("extension", ["mp3", "epub", "txt", "cbz"])
@pytest.mark.parametrize("declared_size", [None, 5, 1])
def test_browser_import_limits_each_file_and_cleans_failed_staging(
    tmp_path, monkeypatch, extension, declared_size
):
    monkeypatch.setattr(import_file_size, "reader_safety_budget", lambda _: 4)
    first = UploadSource(f"1.{extension}", BytesIO(b"1234"))
    second = UploadSource(f"2.{extension}", BytesIO(b"12345"), declared_size)
    with pytest.raises(UploadFileTooLargeError) as raised:
        SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(
            SaveUploadedFilesCommand(tmp_path, (first, second))
        )
    assert raised.value.code == "IMPORT_FILE_TOO_LARGE"
    assert (tmp_path / f"1.{extension}").read_bytes() == b"1234"
    assert not (tmp_path / f"2.{extension}").exists()
    assert list(tmp_path.glob(".upload-*.part")) == []
    assert raised.value.saved_files[0].path == tmp_path / f"1.{extension}"


def test_browser_audio_batch_has_no_aggregate_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(import_file_size, "reader_safety_budget", lambda _: 4)
    files = tuple(UploadSource(f"{n}.mp3", BytesIO(b"1234")) for n in range(3))
    result = SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(
        SaveUploadedFilesCommand(tmp_path, files)
    )
    assert sum(file.size_bytes for file in result) == 12
    assert len(result) == 3


def test_interrupted_upload_removes_staging_and_keeps_prior_files(tmp_path):
    class CancelledStream(BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise KeyboardInterrupt()
            return super().read(1)

    sources = (
        UploadSource("first.txt", BytesIO(b"complete")),
        UploadSource("cancelled.txt", CancelledStream(b"cancelled")),
    )
    with pytest.raises(KeyboardInterrupt):
        SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(
            SaveUploadedFilesCommand(tmp_path, sources)
        )
    assert (tmp_path / "first.txt").read_bytes() == b"complete"
    assert not (tmp_path / "cancelled.txt").exists()
    assert list(tmp_path.glob(".upload-*.part")) == []
