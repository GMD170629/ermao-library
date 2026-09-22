"""Image I/O/cleanup failures retain their cause instead of becoming bad input."""

import errno
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.core.exception_diagnostics import deferred_exception_persistence
from app.modules.auth.infrastructure import avatar_files
from app.modules.library.infrastructure.resource_cover import (
    FilesystemResourceCoverPublication,
)
from app.modules.library.infrastructure.source_node_cover import (
    FilesystemSourceNodeCoverPublication,
)


@pytest.mark.parametrize("kind", ["resource", "source_node", "avatar"])
def test_staged_image_write_and_cleanup_have_separate_linked_diagnostics(
    tmp_path, monkeypatch, kind, caplog
):
    original = OSError(errno.ENOSPC, "disk full", "/private/library/staged-image")
    cleanup = PermissionError(errno.EACCES, "cleanup denied", "/private/library/staged-image")

    def write_failure(*_args, **_kwargs):
        raise original

    def cleanup_failure(*_args, **_kwargs):
        raise cleanup

    image_bytes = BytesIO()
    Image.new("RGB", (3, 3)).save(image_bytes, format="PNG")
    if kind == "avatar":
        monkeypatch.setattr(Image.Image, "save", write_failure)
        monkeypatch.setattr(avatar_files.PreparedAvatarPublication, "discard", cleanup_failure)
        prepare = lambda: avatar_files.prepare_avatar_publication(image_bytes.getvalue(), target_directory=tmp_path)
    else:
        monkeypatch.setattr(Path, "write_bytes", write_failure)
        monkeypatch.setattr(Path, "unlink", cleanup_failure)
        if kind == "resource":
            prepare = lambda: FilesystemResourceCoverPublication(tmp_path).prepare(resource_id="resource-id", content=image_bytes.getvalue())
        else:
            prepare = lambda: FilesystemSourceNodeCoverPublication(tmp_path).prepare(source_node_id="source-id", content=image_bytes.getvalue())
    with deferred_exception_persistence() as pending, pytest.raises(OSError) as captured:
        prepare()
    assert captured.value is original
    assert len(pending) == 2
    assert pending[0].metadata["diagnostics"]["directException"]["errno"] == errno.ENOSPC
    assert pending[1].metadata["diagnostics"]["directException"]["errno"] == errno.EACCES
    assert pending[1].metadata["parentDiagnosticId"] == pending[0].diagnostic_id
    assert "disk full" in caplog.text and "cleanup denied" in caplog.text
    assert "/private/library" not in caplog.text


@pytest.mark.parametrize("kind", ["resource", "source_node"])
def test_unknown_image_decoder_value_error_is_not_user_validation(tmp_path, monkeypatch, kind):
    original = ValueError("decoder invariant failed")

    def fail(*_args, **_kwargs):
        raise original

    monkeypatch.setattr(Image, "open", fail)
    with deferred_exception_persistence() as pending, pytest.raises(ValueError) as captured:
        if kind == "resource":
            FilesystemResourceCoverPublication(tmp_path).prepare(resource_id="resource-id", content=b"image")
        else:
            FilesystemSourceNodeCoverPublication(tmp_path).prepare(source_node_id="source-id", content=b"image")
    assert captured.value is original
    assert len(pending) == 1
    assert pending[0].metadata["diagnostics"]["directException"]["type"] == "ValueError"
    assert not list(tmp_path.rglob("*.part"))
