import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.models import Library, LibraryBook
from app.modules.library.application.file_move_plans import (
    MoveActor,
    PrepareFileMovePlan,
)
from app.modules.library.domain.file_moves import MoveRequest
from app.modules.library.infrastructure.file_move_copy_publication import (
    VerifiedMovePublication,
)
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from tests.integration.modules.automation.test_file_reads import file_access
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
        import tempfile

        with tempfile.TemporaryDirectory(
            prefix="ermao-move-", dir="/dev/shm"
        ) as directory:
            yield Path(directory)
    else:
        pytest.skip("No disposable second filesystem available on this host")


@pytest.mark.parametrize("interruption", [None, "publish", "backup"])
def test_real_cross_device_operation_verifies_copy_and_retains_recovery_source(
    db_session, tmp_path, separate_volume, interruption
):
    access, root = file_access(db_session, tmp_path)
    assert os.stat(root).st_dev != os.stat(separate_volume).st_dev
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    destination = db_session.get(Library, "private-library")
    destination.root_path = str(separate_volume)
    destination.organization_mode = "VOLUMES"
    db_session.commit()
    original = b"original publication bytes" * 100_000
    (root / "allowed/publication.epub").write_bytes(original)
    (root / "allowed/metadata.opf").write_bytes(b"sidecar bytes")
    if sys.platform == "darwin":
        subprocess.run(
            [
                "xattr",
                "-w",
                "com.ermao.move-test",
                "preserved",
                str(root / "allowed/publication.epub"),
            ],
            check=True,
        )
        subprocess.run(
            [
                "chmod",
                "+a",
                "everyone allow read",
                str(root / "allowed/publication.epub"),
            ],
            check=True,
        )
    actor = MoveActor(
        access.user_id,
        access.grant_id,
        frozenset({"test-library", "private-library"}),
        True,
    )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(actor, (MoveRequest("allowed-node", "private-library", "renamed"),))
    assert plan.moves[0].cross_device
    store = SqlAlchemyFileMoveOperations(db_session)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db_session.commit()
    assert store.claim_next(3000) == "operation"
    db_session.commit()

    class Publication(VerifiedMovePublication):
        copies = 0
        interrupted = False

        def prepare_copy(self, move):
            self.copies += 1
            return super().prepare_copy(move)

        def publish(self, move, copy=None):
            super().publish(move, copy)
            if interruption == "publish" and not self.interrupted:
                self.interrupted = True
                raise OSError("simulated interruption after publication")

        def finish_source(self, move, copy=None):
            result = super().finish_source(move, copy)
            if interruption == "backup" and not self.interrupted:
                self.interrupted = True
                raise OSError("simulated interruption after staging source")
            return result

    files = Publication()
    command = executor(db_session, store, files, lambda actor: actor)
    if interruption:
        with pytest.raises(OSError, match="simulated interruption"):
            command.execute("operation")
        assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
        store.prepare_recovery("operation", 5000)
        db_session.commit()
    command.execute("operation")
    assert files.copies == 1
    assert store.progress("operation", actor).status == "COMPLETED"
    assert (separate_volume / "renamed/publication.epub").read_bytes() == original
    assert (separate_volume / "renamed/metadata.opf").read_bytes() == b"sidecar bytes"
    assert not (root / "allowed").exists()
    assert (
        root / plan.moves[0].backup_relative_path / "publication.epub"
    ).read_bytes() == original
    assert not (separate_volume / plan.moves[0].staging_relative_path).exists()
    db_session.expire_all()
    assert db_session.get(LibraryBook, "allowed").library_id == "private-library"

    from app.infrastructure.copied_file_attributes import (
        read_copy_attributes,
    )

    with (
        (root / plan.moves[0].backup_relative_path / "publication.epub").open(
            "rb"
        ) as source,
        (separate_volume / "renamed/publication.epub").open("rb") as target,
    ):
        assert read_copy_attributes(source.fileno()) == read_copy_attributes(
            target.fileno()
        )

    from app.modules.library.application.file_move_recovery_cleanup import (
        CleanExpiredMoveBackups,
    )
    from app.modules.library.domain.file_moves import RECOVERY_RETENTION_MS

    assert (
        CleanExpiredMoveBackups(store, files, db_session, lambda: 5000).execute() == 0
    )
    retained = root / plan.moves[0].backup_relative_path
    if interruption == "publish":
        (separate_volume / "renamed/publication.epub").write_bytes(b"new user content")
    elif interruption == "backup":
        (retained / "publication.epub").write_bytes(b"changed recovery copy")
    cleaned = CleanExpiredMoveBackups(
        store, files, db_session, lambda: RECOVERY_RETENTION_MS + 5000
    ).execute()
    assert cleaned == (1 if interruption is None else 0)
    if interruption is None:
        assert not retained.exists()
        assert (separate_volume / "renamed/publication.epub").read_bytes() == original
    else:
        assert retained.exists()
    assert store.expired_backups(RECOVERY_RETENTION_MS + 6000, 5) == ()
