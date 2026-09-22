"""A moved regular file must finish scanning before replacement can complete."""

import hashlib
from dataclasses import replace

from sqlalchemy import select

from app.bootstrap.automation import (
    build_automation_file_moves,
    build_automation_settings,
    build_automation_uploads,
    build_grant_manager,
)
from app.bootstrap.file_moves import build_file_move_worker
from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.contracts.automation_upload import UploadSpec
from app.models import Library, LibraryImportScanGap, LibrarySourceNode
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import Scope
from app.modules.library.public import MoveRequest
from tests.integration.modules.automation.test_uploads import (
    spec,
    transmit,
    upload_access,
)


def test_moved_file_replacement_reaches_completed(
    db_session, tmp_path, monkeypatch, test_settings
):
    access, root = upload_access(db_session, tmp_path, monkeypatch, test_settings)
    permissions = replace(
        access.permissions, scopes=access.permissions.scopes | {Scope.FILES_MODIFY}
    )
    grant = build_grant_manager(db_session).create(
        user_id=access.user_id, name="move and replace", permissions=permissions
    )
    access = replace(access, grant_id=grant.grant.id, permissions=permissions)
    build_automation_settings(db_session).update(
        access.user_id,
        AutomationServiceSettings(True, permissions.scopes, "http://localhost"),
    )
    library = db_session.get(Library, "test-library")
    library.organization_mode = "FLAT"
    library.min_file_size_bytes = 0
    db_session.commit()
    uploads = build_automation_uploads(db_session)
    worker = build_readable_resource_worker(
        build_readable_resource_pipeline(db_session, test_settings)
    )
    original = b"Original readable text.\n"
    upload_id = transmit(uploads, access, spec(original, "original.txt"), original)
    uploads.complete(access, upload_id)
    for _ in range(30):
        if worker.process_once() == "idle":
            break
    initial = uploads.progress(access, upload_id)
    assert initial["status"] == "COMPLETED", initial
    node = db_session.scalar(
        select(LibrarySourceNode).where(
            LibrarySourceNode.library_id == "test-library",
            LibrarySourceNode.relative_path == "original.txt",
        )
    )
    node_id = node.id
    moves = build_automation_file_moves(db_session)
    plan = moves.plan(access, (MoveRequest(node_id, "test-library", "moved.txt"),))
    operation = moves.execute(access, plan["plan_id"], "move")
    build_file_move_worker(db_session).process_once()
    assert moves.progress(access, operation["operation_id"])["status"] == "COMPLETED"
    for _ in range(30):
        if worker.process_once() == "idle":
            break
    db_session.expire_all()
    gap = db_session.get(LibraryImportScanGap, "test-library")
    assert gap is None or not gap.scopes

    replacement = b"Replacement readable text with a different length.\n"
    source = root / "moved.txt"
    info = source.stat()
    version = hashlib.sha256(f"{info.st_size}:{info.st_mtime_ns}".encode()).hexdigest()
    replacement_id = transmit(
        uploads,
        access,
        UploadSpec(
            "replace",
            "moved.txt",
            len(replacement),
            hashlib.sha256(replacement).hexdigest(),
            library_id="test-library",
            source_node_id=node_id,
            expected_source_version=version,
        ),
        replacement,
        "replace",
    )
    assert uploads.complete(access, replacement_id)["status"] == "QUEUED"
    for _ in range(30):
        if worker.process_once() == "idle":
            break
    final = uploads.progress(access, replacement_id)
    assert final["status"] == "COMPLETED", final
    assert final["result"]["book_ids"] == initial["result"]["book_ids"]
    assert final["result"]["resource_ids"] == initial["result"]["resource_ids"]
    assert source.read_bytes() == replacement
