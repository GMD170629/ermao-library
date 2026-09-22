"""Real system moves across filesystems and independently mounted libraries."""

import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    Library,
    LibraryBook,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.shelf import ShelfBook
from app.modules.library.application.file_move_plans import (
    MoveActor,
    PrepareFileMovePlan,
)
from app.modules.library.domain.file_moves import MoveRequest
from app.modules.library.infrastructure.file_move_io import SystemMovePublication
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from app.modules.reader.infrastructure.persistence.models import (
    ReaderResourceProgressV5,
)
from tests.integration.modules.automation.test_file_reads import add_file, file_access
from tests.integration.modules.automation.test_move_execution import executor


@pytest.fixture
def separate_volume(tmp_path):
    if sys.platform == "darwin":
        image = tmp_path / "move.sparseimage"
        mount = tmp_path / "volume"
        mount.mkdir()
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-size",
                "64m",
                "-fs",
                "APFS",
                "-type",
                "SPARSE",
                "-volname",
                "ErmaoMoveTest",
                str(image),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(image)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        try:
            yield mount
        finally:
            subprocess.run(
                ["hdiutil", "detach", str(mount)],
                check=True,
                capture_output=True,
                timeout=60,
            )
    elif Path("/dev/shm").is_dir():
        with tempfile.TemporaryDirectory(
            prefix="ermao-move-", dir="/dev/shm"
        ) as directory:
            yield Path(directory)
    else:
        pytest.skip("No disposable second filesystem available on this host")


def prepare_cross_library_move(db, tmp_path, destination_root, *, source_root=None):
    access, default_root = file_access(db, tmp_path)
    root = source_root or default_root
    (root / "allowed").mkdir(parents=True, exist_ok=True)
    source_library = db.get(Library, "test-library")
    source_library.root_path = str(root)
    source_library.organization_mode = "VOLUMES"
    destination = db.get(Library, "private-library")
    destination.root_path = str(destination_root)
    destination.organization_mode = "VOLUMES"
    db.commit()
    original = b"original publication bytes" * 100_000
    (root / "allowed/book.epub").write_bytes(original)
    (root / "allowed/metadata.opf").write_bytes(b"sidecar bytes")
    add_file(db, "resource-node", "allowed/book.epub")
    db.add(
        LibraryReadableResource(
            id="move-resource",
            library_id="test-library",
            book_id="allowed",
            source_node_id="resource-node",
            adapter_id="epub",
            adapter_version="1",
            format="EPUB",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db.flush()
    db.add(
        LibraryResourceAsset(
            id="move-asset",
            library_id="test-library",
            resource_id="move-resource",
            source_node_id="resource-node",
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db.add(
        ReaderResourceProgressV5(
            id="move-progress",
            user_id=access.user_id,
            resource_id="move-resource",
            client_id="reader-client",
            mutation_id="original-position",
            locator_json='{"href":"chapter-2.xhtml"}',
            presentation_json="{}",
            captured_at=datetime.now(UTC),
            revision=7,
            display_percent=42,
        )
    )
    db.commit()
    actor = MoveActor(
        access.user_id,
        access.grant_id,
        frozenset({"test-library", "private-library"}),
        True,
    )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(actor, (MoveRequest("allowed-node", "private-library", "renamed"),))
    store = SqlAlchemyFileMoveOperations(db)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db.commit()
    assert store.claim_next(3000) == "operation"
    db.commit()
    return actor, root, store, original


def assert_moved_with_identity(db, actor, root, destination, store, original):
    assert store.progress("operation", actor).status == "COMPLETED"
    assert (destination / "renamed/book.epub").read_bytes() == original
    assert (destination / "renamed/metadata.opf").read_bytes() == b"sidecar bytes"
    assert list(root.iterdir()) == []
    assert {path.name for path in destination.iterdir()} == {"renamed"}
    assert {path.name for path in (destination / "renamed").iterdir()} == {
        "book.epub",
        "metadata.opf",
    }
    db.expire_all()
    assert db.get(LibraryBook, "allowed").library_id == "private-library"
    assert (
        db.get(LibraryReadableResource, "move-resource").library_id == "private-library"
    )
    assert db.get(LibraryResourceAsset, "move-asset").library_id == "private-library"
    assert (
        db.get(LibrarySourceNode, "resource-node").relative_path == "renamed/book.epub"
    )
    assert db.get(LibrarySourceNode, "resource-node").parent_id == "allowed-node"
    assert db.get(ShelfBook, {"shelf_id": "static", "book_id": "allowed"}) is not None
    progress = db.get(ReaderResourceProgressV5, "move-progress")
    assert progress.resource_id == "move-resource"
    assert progress.revision == 7 and progress.display_percent == 42
    assert progress.locator_json == '{"href":"chapter-2.xhtml"}'
    scan = db.scalar(
        select(LibraryImportTask).where(LibraryImportTask.kind == "SCAN_LIBRARY")
    )
    assert scan.library_id == "private-library" and scan.state == "QUEUED"


@pytest.mark.parametrize("interrupted", [False, True])
def test_real_system_cross_device_move_preserves_identity_without_backups(
    db_session, tmp_path, separate_volume, interrupted
):
    actor, root, store, original = prepare_cross_library_move(
        db_session, tmp_path, separate_volume
    )
    assert root.stat().st_dev != separate_volume.stat().st_dev

    class Publication(SystemMovePublication):
        calls = 0
        interruption_raised = False

        def publish(self, move):
            self.calls += 1
            super().publish(move)
            if interrupted:
                self.interruption_raised = True
                raise OSError("simulated interruption after system move")

    files = Publication()
    command = executor(db_session, store, files, lambda current: current)
    command.execute("operation")
    if interrupted:
        assert files.interruption_raised
        assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
        assert (separate_volume / "renamed/book.epub").read_bytes() == original
        assert not (root / "allowed").exists()
        (root / "allowed").mkdir()
        (root / "allowed/new.txt").write_bytes(b"new source after interruption")
        command.execute("operation")
        assert files.calls == 1
        assert (
            root / "allowed/new.txt"
        ).read_bytes() == b"new source after interruption"
        assert (separate_volume / "renamed/book.epub").read_bytes() == original
        assert db_session.get(LibraryBook, "allowed").library_id == "test-library"
        assert list(db_session.scalars(select(LibraryImportTask))) == []
    else:
        assert_moved_with_identity(
            db_session, actor, root, separate_volume, store, original
        )
        command.execute("operation")
        assert files.calls == 1


def test_system_cross_device_move_does_not_clobber_target_or_replay_failure(
    db_session, tmp_path, separate_volume
):
    actor, root, store, original = prepare_cross_library_move(
        db_session, tmp_path, separate_volume
    )

    class Publication(SystemMovePublication):
        calls = 0

        def _move(self, move, source_fd, target_fd, source_name, target_name):
            self.calls += 1
            (separate_volume / "renamed").write_bytes(b"existing target")
            super()._move(move, source_fd, target_fd, source_name, target_name)

    files = Publication()
    command = executor(db_session, store, files, lambda current: current)
    command.execute("operation")
    assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
    assert (root / "allowed/book.epub").read_bytes() == original
    assert (separate_volume / "renamed").read_bytes() == b"existing target"
    assert list(separate_volume.iterdir()) == [separate_volume / "renamed"]
    command.execute("operation")
    assert files.calls == 1


def test_same_device_independent_linux_bind_mounts_move_successfully(
    db_session, tmp_path
):
    source_mount = os.environ.get("ERMAO_MOVE_TEST_SOURCE_MOUNT")
    destination_mount = os.environ.get("ERMAO_MOVE_TEST_DESTINATION_MOUNT")
    if (
        not sys.platform.startswith("linux")
        or not source_mount
        or not destination_mount
    ):
        pytest.skip(
            "Requires two disposable Linux bind mounts supplied by the container test run"
        )

    with (
        tempfile.TemporaryDirectory(prefix="move-source-", dir=source_mount) as source,
        tempfile.TemporaryDirectory(
            prefix="move-target-", dir=destination_mount
        ) as destination,
    ):
        source_root, destination_root = Path(source), Path(destination)
        assert source_root.stat().st_dev == destination_root.stat().st_dev
        mount_ids = []
        for root in (source_root, destination_root):
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                info = Path(f"/proc/self/fdinfo/{descriptor}").read_text()
                mount_ids.append(
                    next(
                        line for line in info.splitlines() if line.startswith("mnt_id:")
                    )
                )
            finally:
                os.close(descriptor)
        assert mount_ids[0] != mount_ids[1]
        actor, root, store, original = prepare_cross_library_move(
            db_session,
            tmp_path,
            destination_root,
            source_root=source_root,
        )
        executor(
            db_session, store, SystemMovePublication(), lambda current: current
        ).execute("operation")
        assert_moved_with_identity(
            db_session, actor, root, destination_root, store, original
        )
