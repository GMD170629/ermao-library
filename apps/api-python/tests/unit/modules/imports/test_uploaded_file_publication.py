"""Browser saves use the shared standard copy path and retain their size limits."""

from io import BytesIO

import pytest

from app.modules.imports.application.save_uploaded_files import (
    SaveUploadedFiles,
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadSource,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)


def test_browser_save_preserves_existing_name_and_copies_exact_bytes(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"existing")
    result = SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(
        SaveUploadedFilesCommand(
            tmp_path,
            (UploadSource("book.epub", BytesIO(b"new upload"), False, None),),
            audio_bundle_max_bytes=100,
        )
    )
    assert result[0].filename == "book-1.epub"
    assert result[0].size_bytes == len(b"new upload")
    assert result[0].path.read_bytes() == b"new upload"
    assert (tmp_path / "book.epub").read_bytes() == b"existing"
    assert list(tmp_path.glob(".upload-*")) == []


@pytest.mark.parametrize("bundle_limit", [4, 6])
def test_browser_audio_limits_keep_published_files_and_partial_staging(
    tmp_path, bundle_limit
):
    first = UploadSource("1.mp3", BytesIO(b"1234"), True, 4)
    second = UploadSource("2.mp3", BytesIO(b"12345"), True, 4)
    with pytest.raises(UploadFileTooLargeError) as raised:
        SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(
            SaveUploadedFilesCommand(tmp_path, (first, second), bundle_limit)
        )
    assert (tmp_path / "1.mp3").read_bytes() == b"1234"
    assert not (tmp_path / "2.mp3").exists()
    assert len(list(tmp_path.glob(".upload-*.part"))) == 1
    assert raised.value.saved_files[0].path == tmp_path / "1.mp3"
