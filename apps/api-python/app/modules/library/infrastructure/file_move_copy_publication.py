"""Publish verified cross-device copies, then retain the original as a recovery copy."""

import hashlib
import os
import shutil
import stat

from app.contracts.controlled_file_slots import is_controlled_file_slot
from app.modules.library.application.file_move_plans import (
    PlannedMove,
    PreparedMoveCopy,
    StagedMoveSource,
)
from app.modules.library.application.file_move_recovery_cleanup import ExpiredMoveBackup
from app.modules.library.domain.file_moves import FileMoveError
from app.modules.library.infrastructure.file_move_io import (
    SameDeviceMovePublication,
    exclusive_rename,
    published_same_device_identity,
)
from app.modules.library.infrastructure.move_inventory import (
    file_identity,
    inspect_move_destination,
    inspect_move_source,
    require_writable_move_directory,
)
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)
from app.modules.library.infrastructure.verified_file_copy import (
    COPY_CHUNK_BYTES,
    copy_verified_tree,
)


def _slots(move: PlannedMove) -> tuple[str, str]:
    staging, backup = move.staging_relative_path, move.backup_relative_path
    if (
        staging is None
        or backup is None
        or not is_controlled_file_slot(staging)
        or not is_controlled_file_slot(backup)
    ):
        raise FileMoveError("COPY_SLOT_NOT_PLANNED")
    return staging, backup


class VerifiedMovePublication(SameDeviceMovePublication):
    def validate(self, move: PlannedMove) -> None:
        require_writable_move_directory(
            move.source.root, move.source.relative_path.rpartition("/")[0]
        )
        require_writable_move_directory(
            move.destination.root, move.destination_inspection.parent_relative_path
        )
        if not move.cross_device:
            return super().validate(move)
        _slots(move)
        if (
            inspect_move_source(move.source.root, move.source.relative_path)
            != move.inventory
        ):
            raise FileMoveError("SOURCE_CHANGED")
        if (
            inspect_move_destination(
                move.destination.root, move.destination.relative_path
            )
            != move.destination_inspection
        ):
            raise FileMoveError("DESTINATION_CHANGED")

    def prepare_copy(self, move: PlannedMove) -> PreparedMoveCopy | None:
        if not move.cross_device:
            return None
        staging, _ = _slots(move)
        self.validate(move)
        contents = copy_verified_tree(
            move.source.root,
            move.source.relative_path,
            move.destination.root,
            staging,
            move.inventory,
        )
        return PreparedMoveCopy(
            inspect_move_source(move.destination.root, staging), contents
        )

    def publish(self, move: PlannedMove, copy: PreparedMoveCopy | None = None) -> None:
        if not move.cross_device:
            return super().publish(move, copy)
        if copy is None:
            raise FileMoveError("COPY_PROOF_MISSING")
        staging, _ = _slots(move)
        self.validate(move)
        if inspect_move_source(move.destination.root, staging) != copy.inventory:
            raise FileMoveError("STAGED_COPY_CHANGED")
        parent, _, name = move.destination.relative_path.rpartition("/")
        with (
            open_library_directory(move.destination.root) as staging_fd,
            open_library_directory(move.destination.root, parent) as destination_fd,
        ):
            observed = os.fstat(destination_fd)
            expected = move.destination_inspection
            if (observed.st_dev, observed.st_ino) != (
                expected.device,
                expected.parent_inode,
            ):
                raise FileMoveError("DESTINATION_CHANGED")
            exclusive_rename(staging_fd, staging, destination_fd, name)
            os.fsync(destination_fd)
            os.fsync(staging_fd)

    def is_published(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> bool:
        if not move.cross_device:
            return super().is_published(move, copy)
        if copy is None:
            raise FileMoveError("COPY_PROOF_MISSING")
        staging, _ = _slots(move)
        observed = published_same_device_identity(
            move.destination.root,
            move.destination.relative_path,
            copy.inventory.entries[0].identity,
        )
        if observed is None:
            return False
        inventory = inspect_move_source(
            move.destination.root, move.destination.relative_path
        )
        if len(inventory.entries) != len(copy.inventory.entries):
            raise FileMoveError("PUBLISHED_COPY_CHANGED")
        for index, (before, after) in enumerate(
            zip(copy.inventory.entries, inventory.entries, strict=True)
        ):
            expected_path = (
                move.destination.relative_path + before.relative_path[len(staging) :]
            )
            if (
                after.relative_path != expected_path
                or before.directory != after.directory
                or (index and before.identity != after.identity)
            ):
                raise FileMoveError("PUBLISHED_COPY_CHANGED")
        for content in copy.contents:
            path = (
                move.destination.relative_path + content.relative_path[len(staging) :]
            )
            with open_library_file(move.destination.root, path) as descriptor:
                before_identity = file_identity(os.fstat(descriptor))
                digest = hashlib.sha256()
                size = 0
                while True:
                    block = os.read(descriptor, COPY_CHUNK_BYTES)
                    if not block:
                        break
                    size += len(block)
                    if size > content.size:
                        raise FileMoveError("PUBLISHED_COPY_CHANGED")
                    digest.update(block)
                if (
                    size != content.size
                    or digest.hexdigest() != content.sha256
                    or file_identity(os.fstat(descriptor)) != before_identity
                ):
                    raise FileMoveError("PUBLISHED_COPY_CHANGED")
        return True

    def finish_source(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> StagedMoveSource | None:
        if not move.cross_device:
            return None
        if not self.is_published(move, copy):
            raise FileMoveError("PUBLISHED_FILE_MISSING")
        _, backup = _slots(move)
        expected = move.inventory.entries[0].identity
        existing = published_same_device_identity(move.source.root, backup, expected)
        parent, _, name = move.source.relative_path.rpartition("/")
        if existing is not None:
            with open_library_directory(move.source.root, parent) as descriptor:
                try:
                    os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    return StagedMoveSource(backup, existing)
            raise FileMoveError("RECOVERY_SOURCE_STILL_EXISTS")
        if (
            inspect_move_source(move.source.root, move.source.relative_path)
            != move.inventory
        ):
            raise FileMoveError("SOURCE_CHANGED")
        with (
            open_library_directory(move.source.root, parent) as source_fd,
            open_library_directory(move.source.root) as backup_fd,
        ):
            if (
                file_identity(os.stat(name, dir_fd=source_fd, follow_symlinks=False))
                != expected
            ):
                raise FileMoveError("SOURCE_CHANGED")
            exclusive_rename(source_fd, name, backup_fd, backup)
            os.fsync(source_fd)
            os.fsync(backup_fd)
            observed = published_same_device_identity(
                move.source.root, backup, expected
            )
            if observed is None:
                raise FileMoveError("RECOVERY_SOURCE_MISSING")
        return StagedMoveSource(backup, observed)

    def remove_backup(self, backup: ExpiredMoveBackup) -> None:
        move = backup.move
        _, planned_backup = _slots(move)
        if backup.backup.relative_path != planned_backup:
            raise FileMoveError("BACKUP_SLOT_CHANGED")
        with open_library_directory(move.source.root) as root_fd:
            try:
                current = file_identity(
                    os.stat(planned_backup, dir_fd=root_fd, follow_symlinks=False)
                )
            except FileNotFoundError:
                return  # Retry acknowledgement of an already removed, verified copy.
            if not self.is_published(move, backup.copy):
                raise FileMoveError("PUBLISHED_FILE_MISSING")
            if current != backup.backup.identity:
                raise FileMoveError("BACKUP_CHANGED")
            inventory = inspect_move_source(move.source.root, planned_backup)
            if len(inventory.entries) != len(move.inventory.entries):
                raise FileMoveError("BACKUP_CHANGED")
            for index, (before, after) in enumerate(
                zip(move.inventory.entries, inventory.entries, strict=True)
            ):
                expected_path = (
                    planned_backup
                    + before.relative_path[len(move.source.relative_path) :]
                )
                if (
                    expected_path != after.relative_path
                    or before.directory != after.directory
                    or (index and before.identity != after.identity)
                ):
                    raise FileMoveError("BACKUP_CHANGED")
            if (
                file_identity(
                    os.stat(planned_backup, dir_fd=root_fd, follow_symlinks=False)
                )
                != current
            ):
                raise FileMoveError("BACKUP_CHANGED")
            if stat.S_ISDIR(current.mode):
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise FileMoveError("SAFE_BACKUP_CLEANUP_UNSUPPORTED")
                shutil.rmtree(planned_backup, dir_fd=root_fd)
            else:
                os.unlink(planned_backup, dir_fd=root_fd)
            os.fsync(root_fd)
