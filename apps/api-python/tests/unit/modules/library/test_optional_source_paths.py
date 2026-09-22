import errno
from pathlib import Path

import pytest

from app.core.exception_diagnostics import deferred_exception_persistence
from app.modules.library.infrastructure.source_paths import (
    resolve_existing_library_file,
)


def test_missing_optional_source_path_is_normal(tmp_path):
    with deferred_exception_persistence() as pending:
        assert resolve_existing_library_file(str(tmp_path), "absent.epub") is None
    assert pending == []


@pytest.mark.parametrize("number", [errno.EACCES, errno.EIO])
def test_optional_source_io_failure_retains_actual_errno(tmp_path, monkeypatch, number, caplog):
    def fail(*_args, **_kwargs):
        raise OSError(number, "source resolution failed", "/private/books/book.epub")
    monkeypatch.setattr(Path, "resolve", fail)
    with deferred_exception_persistence() as pending:
        assert resolve_existing_library_file(str(tmp_path), "book.epub") is None
    assert len(pending) == 1
    assert pending[0].metadata["diagnostics"]["rootCause"]["errno"] == number
    assert "source resolution failed" in caplog.text
    assert "/private/books" not in caplog.text
