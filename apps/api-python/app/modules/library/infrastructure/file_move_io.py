"""Descriptor-relative exclusive publication for journalled file moves."""

import os
from pathlib import Path

from app.contracts.controlled_file_slots import is_controlled_file_slot
from app.infrastructure.exclusive_rename import exclusive_rename
from app.modules.library.application.file_move_plans import (
    DestinationInspection,
    PlannedMove,
    PreparedMoveCopy,
    StagedMoveSource,
)
from app.modules.library.domain.file_moves import FileIdentity, FileMoveError
from app.modules.library.infrastructure.move_inventory import (
    file_identity,
    inspect_move_destination,
    inspect_move_source,
    require_writable_move_directory,
)
from app.modules.library.infrastructure.source_file_access import open_library_directory


def publish_same_device_move(move: PlannedMove) -> FileIdentity:
    """The caller must persist intent and own the conflict boundary first."""
    if move.cross_device:
        raise FileMoveError("CROSS_DEVICE_COPY_REQUIRED")
    if (
        inspect_move_source(move.source.root, move.source.relative_path)
        != move.inventory
    ):
        raise FileMoveError("SOURCE_CHANGED")
    target = inspect_move_destination(
        move.destination.root, move.destination.relative_path
    )
    if target != move.destination_inspection:
        raise FileMoveError("DESTINATION_CHANGED")
    if target.missing_directories:
        raise FileMoveError("DESTINATION_DIRECTORIES_NOT_PREPARED")
    source_parent, _, source_name = move.source.relative_path.rpartition("/")
    target_parent, _, target_name = move.destination.relative_path.rpartition("/")
    with (
        open_library_directory(move.source.root, source_parent) as source_fd,
        open_library_directory(move.destination.root, target_parent) as target_fd,
    ):
        expected = move.inventory.entries[0].identity
        if (
            file_identity(os.stat(source_name, dir_fd=source_fd, follow_symlinks=False))
            != expected
        ):
            raise FileMoveError("SOURCE_CHANGED")
        target_stat = os.fstat(target_fd)
        if (target_stat.st_dev, target_stat.st_ino) != (
            target.device,
            target.parent_inode,
        ):
            raise FileMoveError("DESTINATION_CHANGED")
        exclusive_rename(source_fd, source_name, target_fd, target_name)
        # Publication may have happened even if fsync or observation fails. The
        # owning use case must keep the intent and require recovery on any error.
        os.fsync(target_fd)
        os.fsync(source_fd)
        published = file_identity(
            os.stat(target_name, dir_fd=target_fd, follow_symlinks=False)
        )
        if (published.device, published.inode) != (expected.device, expected.inode):
            raise FileMoveError("PUBLISHED_IDENTITY_CHANGED")
        return published


def published_same_device_identity(
    root: Path, relative_path: str, expected: FileIdentity
) -> FileIdentity | None:
    """Inspect only the journal's precise target when recovering an uncertain rename."""
    parent, _, name = relative_path.rpartition("/")
    try:
        with open_library_directory(root, parent) as descriptor:
            observed = file_identity(
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            )
    except FileNotFoundError:
        return None
    if (
        observed.device,
        observed.inode,
        observed.mode,
        observed.size,
        observed.mtime_ns,
    ) != (
        expected.device,
        expected.inode,
        expected.mode,
        expected.size,
        expected.mtime_ns,
    ):
        raise FileMoveError("RECOVERY_TARGET_CHANGED")
    return observed


class SameDeviceMovePublication:
    def create_directory(
        self, root: Path, relative_path: str, parent: DestinationInspection
    ) -> FileIdentity:
        parent_path, _, name = relative_path.rpartition("/")
        if parent_path != parent.parent_relative_path:
            raise FileMoveError("DESTINATION_CHANGED")
        with open_library_directory(root, parent_path) as descriptor:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != (parent.device, parent.parent_inode):
                raise FileMoveError("DESTINATION_CHANGED")
            os.mkdir(name, 0o755, dir_fd=descriptor)
            os.fsync(descriptor)
            return file_identity(
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            )

    def validate(self, move: PlannedMove) -> None:
        require_writable_move_directory(
            move.source.root, move.source.relative_path.rpartition("/")[0]
        )
        require_writable_move_directory(
            move.destination.root, move.destination_inspection.parent_relative_path
        )
        if move.cross_device:
            raise FileMoveError("CROSS_DEVICE_COPY_REQUIRED")
        if (
            inspect_move_source(move.source.root, move.source.relative_path)
            != move.inventory
        ):
            raise FileMoveError("SOURCE_CHANGED")
        destination = inspect_move_destination(
            move.destination.root,
            move.destination.relative_path,
            existing_source=move.source.relative_path if move.case_only else None,
        )
        if destination != move.destination_inspection:
            raise FileMoveError("DESTINATION_CHANGED")

    def prepare_copy(self, move: PlannedMove) -> PreparedMoveCopy | None:
        return None

    def finish_source(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> StagedMoveSource | None:
        return None

    def publish(self, move: PlannedMove, copy: PreparedMoveCopy | None = None) -> None:
        if move.case_only:
            publish_case_only_move(move)
            return
        publish_same_device_move(move)

    def is_published(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> bool:
        if move.case_only:
            state = case_only_move_state(move)
            if state == "published":
                return True
            if state == "source":
                self.validate(move)
            return False
        target = published_same_device_identity(
            move.destination.root,
            move.destination.relative_path,
            move.inventory.entries[0].identity,
        )
        if target is None:
            self.validate(move)
            return False
        inventory = inspect_move_source(
            move.destination.root, move.destination.relative_path
        )
        if len(inventory.entries) != len(move.inventory.entries):
            raise FileMoveError("RECOVERY_TARGET_CHANGED")
        for index, (before, after) in enumerate(
            zip(move.inventory.entries, inventory.entries, strict=True)
        ):
            expected_path = (
                move.destination.relative_path
                + before.relative_path[len(move.source.relative_path) :]
            )
            if (
                after.relative_path != expected_path
                or after.directory != before.directory
            ):
                raise FileMoveError("RECOVERY_TARGET_CHANGED")
            if index and after.identity != before.identity:
                raise FileMoveError("RECOVERY_TARGET_CHANGED")
        parent, _, name = move.source.relative_path.rpartition("/")
        with open_library_directory(move.source.root, parent) as descriptor:
            try:
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                return True
        raise FileMoveError("RECOVERY_SOURCE_STILL_EXISTS")


def verify_relocated_move(move: PlannedMove, relative_path: str) -> None:
    if (
        published_same_device_identity(
            move.source.root, relative_path, move.inventory.entries[0].identity
        )
        is None
    ):
        raise FileMoveError("RECOVERY_TARGET_MISSING")
    inventory = inspect_move_source(move.source.root, relative_path)
    if len(inventory.entries) != len(move.inventory.entries):
        raise FileMoveError("RECOVERY_TARGET_CHANGED")
    for index, (before, after) in enumerate(
        zip(move.inventory.entries, inventory.entries, strict=True)
    ):
        if (
            after.relative_path
            != relative_path + before.relative_path[len(move.source.relative_path) :]
            or after.directory != before.directory
            or (index and after.identity != before.identity)
        ):
            raise FileMoveError("RECOVERY_TARGET_CHANGED")


def case_only_move_state(move: PlannedMove) -> str:
    slot = move.staging_relative_path
    if slot is None or not is_controlled_file_slot(slot):
        raise FileMoveError("CASE_RENAME_SLOT_MISSING")
    parent, _, source_name = move.source.relative_path.rpartition("/")
    target_name = move.destination.relative_path.rpartition("/")[2]
    with (
        open_library_directory(move.source.root) as root_fd,
        open_library_directory(move.source.root, parent) as parent_fd,
    ):
        names = os.listdir(parent_fd)
        staged = slot in os.listdir(root_fd)
    if staged:
        if source_name in names or target_name in names:
            raise FileMoveError("CASE_RENAME_COLLISION")
        verify_relocated_move(move, slot)
        return "staged"
    if target_name in names and source_name not in names:
        verify_relocated_move(move, move.destination.relative_path)
        return "published"
    if source_name in names and target_name not in names:
        return "source"
    raise FileMoveError("CASE_RENAME_COLLISION")


def publish_case_only_move(move: PlannedMove) -> None:
    state = case_only_move_state(move)
    if state == "published":
        return
    parent, _, source_name = move.source.relative_path.rpartition("/")
    target_name = move.destination.relative_path.rpartition("/")[2]
    slot = move.staging_relative_path
    if slot is None:
        raise FileMoveError("CASE_RENAME_SLOT_MISSING")
    with (
        open_library_directory(move.source.root) as root_fd,
        open_library_directory(move.source.root, parent) as parent_fd,
    ):
        parent_identity = os.fstat(parent_fd)
        if (parent_identity.st_dev, parent_identity.st_ino) != (
            move.destination_inspection.device,
            move.destination_inspection.parent_inode,
        ):
            raise FileMoveError("DESTINATION_CHANGED")
        if state == "source":
            SameDeviceMovePublication().validate(move)
            exclusive_rename(parent_fd, source_name, root_fd, slot)
            os.fsync(parent_fd)
            os.fsync(root_fd)
        verify_relocated_move(move, slot)
        inspect_move_destination(move.destination.root, move.destination.relative_path)
        exclusive_rename(root_fd, slot, parent_fd, target_name)
        os.fsync(parent_fd)
        os.fsync(root_fd)
    verify_relocated_move(move, move.destination.relative_path)
