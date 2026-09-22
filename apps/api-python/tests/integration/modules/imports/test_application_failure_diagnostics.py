"""Application ports retain filesystem/parser failures in runtime and event logs."""

import errno
import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failure_diagnostics import RuntimeFailureDiagnostics
from app.models import SystemEvent
from app.modules.imports.application.library_paths import library_directory_tree_node
from app.modules.imports.infrastructure.readable_resource.support import (
    StructuredPipelineLog,
)


def events(db, action):
    db.rollback()
    return list(db.scalars(select(SystemEvent).where(SystemEvent.action == action)))


@pytest.mark.parametrize(
    "step", ["resolve_directory", "resolve_child", "list_directory"]
)
def test_directory_browser_preserves_actual_filesystem_failure(
    db_session, tmp_path, monkeypatch, caplog, step
):
    root = tmp_path.resolve()
    child = root / "books"
    child.mkdir()
    actual_resolve = Path.resolve
    actual_iterdir = Path.iterdir

    def resolve(path, *args, **kwargs):
        if (step == "resolve_directory" and path == root) or (
            step == "resolve_child" and path == child
        ):
            raise OSError(errno.EIO, "injected directory I/O failure", str(path))
        return actual_resolve(path, *args, **kwargs)

    def iterdir(path):
        if step == "list_directory" and path == root:
            raise PermissionError(
                errno.EACCES, "injected directory enumeration denial", str(path)
            )
        return actual_iterdir(path)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "iterdir", iterdir)
    result, message, status = library_directory_tree_node(
        str(root),
        mount_root_for_path=lambda _: str(root),
        diagnostics=RuntimeFailureDiagnostics(
            logging.getLogger(__name__),
            "import",
            lambda: Session(db_session.get_bind()),
        ),
    )
    action = {
        "resolve_directory": "resolve_failed",
        "resolve_child": "child_resolve_failed",
        "list_directory": "list_failed",
    }[step]
    observed = events(db_session, f"library.directory.{action}")
    assert len(observed) == 1
    metadata = observed[0].metadata_json
    assert metadata["step"] == step
    assert metadata["diagnostics"]["rootCause"]["errno"] == (
        errno.EACCES if step == "list_directory" else errno.EIO
    )
    assert observed[0].id in caplog.text
    assert str(root) not in json.dumps(metadata)
    if step == "resolve_directory":
        assert status == 404 and result is None and message
    elif step == "list_directory":
        assert status == 200 and result["readable"] is False
    else:
        assert status == 200 and result["children"] == []


def test_pipeline_exception_port_persists_task_context_and_actual_parser_cause(
    db_session, caplog
):
    log = StructuredPipelineLog(lambda: Session(db_session.get_bind()))
    try:
        raise SyntaxError("injected damaged image chunk")
    except SyntaxError as error:
        log.emit(
            "readable_resource.local_cover.rejected",
            error=error,
            task_id="task-damaged-cover",
            resource_id="resource-cover",
            source_node_id="source-cover",
            stage="cover_prepare",
            outcome="invalid",
        )
    observed = events(db_session, "readable_resource.local_cover.rejected")
    assert len(observed) == 1
    metadata = observed[0].metadata_json
    assert metadata["taskId"] == "task-damaged-cover"
    assert metadata["sourceNodeId"] == "source-cover"
    assert metadata["diagnostics"]["exceptionType"] == "SyntaxError"
    assert metadata["diagnostics"]["message"] == "injected damaged image chunk"
    assert observed[0].id in caplog.text
