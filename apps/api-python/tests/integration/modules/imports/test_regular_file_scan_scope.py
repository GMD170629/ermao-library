"""File scopes clear only after successful observation or confirmed absence."""

import pytest

from app.models import LibraryImportScanGap, LibraryImportTask, LibrarySourceNode
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScanCommand,
)
from app.modules.imports.domain.scan_policy import ScanScope, decode_scan_scopes
from app.modules.imports.infrastructure.readable_resource.scan_gating import (
    record_scan_gaps,
)
from tests.integration.modules.imports.test_scan_failure_recovery import (
    _drain,
    _node_for,
    _pipeline,
)


@pytest.mark.parametrize("missing", [False, True])
def test_file_scope_preserves_failure_and_resolves_confirmed_result(
    tmp_path, monkeypatch, missing
):
    root = tmp_path / "library"
    db, _settings, pipeline = _pipeline(tmp_path, {"lib": root})
    try:
        source = root / "book.txt"
        source.write_text("original readable text")
        (root / "keep.txt").write_text("unrelated readable text")
        pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "MANUAL")
        )
        _drain(pipeline)
        node_id = _node_for(db, "lib", "book.txt").id
        scopes = (ScanScope("book.txt", True), ScanScope("unrelated", True))
        record_scan_gaps(db, "lib", scopes)
        db.commit()
        observe = pipeline.filesystem.observe_readable_file
        if missing:
            source.unlink()
        else:
            source.write_text("updated readable text with changed size")
            monkeypatch.setattr(
                pipeline.filesystem,
                "observe_readable_file",
                lambda path: None if path == source else observe(path),
            )
        scan = pipeline.request_library_scan.execute(
            RequestLibraryScanCommand("lib", "MANUAL", (scopes[0],))
        )
        _drain(pipeline)
        db.expire_all()
        if not missing:
            assert db.get(LibraryImportTask, scan.task_id).state == "FAILED"
            assert (
                decode_scan_scopes(db.get(LibraryImportScanGap, "lib").scopes) == scopes
            )
            monkeypatch.setattr(pipeline.filesystem, "observe_readable_file", observe)
            pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("lib", "MANUAL", (scopes[0],))
            )
            _drain(pipeline)
            db.expire_all()
            assert (
                db.get(LibrarySourceNode, node_id).observed_size_bytes
                == source.stat().st_size
            )
        else:
            assert db.get(LibrarySourceNode, node_id) is None
        assert decode_scan_scopes(db.get(LibraryImportScanGap, "lib").scopes) == (
            scopes[1],
        )
        assert (root / "keep.txt").read_text() == "unrelated readable text"
    finally:
        db.close()
