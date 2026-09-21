"""Read-only, descriptor-anchored inventory; never follows special files."""

import os
import stat
from pathlib import Path

from app.modules.library.application.file_move_plans import DestinationInspection
from app.modules.library.domain.file_moves import (
    MAX_BYTES,
    MAX_FILES,
    FileIdentity,
    FileMoveError,
    MoveInventory,
    MoveInventoryEntry,
    collision_key,
    validate_portable_file_path,
)
from app.modules.library.infrastructure.source_file_access import open_library_directory


def file_identity(value: os.stat_result) -> FileIdentity:
    return FileIdentity(
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def inspect_move_source(root: Path, relative_path: str) -> MoveInventory:
    validate_portable_file_path(relative_path)
    parent, _, name = relative_path.rpartition("/")
    entries: list[MoveInventoryEntry] = []
    files = byte_count = 0

    def visit(directory_fd: int, name: str, path: str, device: int, depth: int) -> None:
        nonlocal files, byte_count
        if depth > 128 or len(entries) >= MAX_FILES * 2:
            raise FileMoveError("INVENTORY_LIMIT")
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        is_directory = stat.S_ISDIR(before.st_mode)
        if before.st_dev != device:
            raise FileMoveError("NESTED_MOUNT_UNSUPPORTED")
        if not is_directory and not stat.S_ISREG(before.st_mode):
            raise FileMoveError("SPECIAL_FILE_UNSUPPORTED")
        identity = file_identity(before)
        entries.append(MoveInventoryEntry(path, is_directory, identity))
        if is_directory:
            descriptor = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
            )
            try:
                if file_identity(os.fstat(descriptor)) != identity:
                    raise FileMoveError("SOURCE_CHANGED")
                names = os.listdir(descriptor)
                if len(names) > MAX_FILES * 2 - len(entries):
                    raise FileMoveError("INVENTORY_LIMIT")
                seen: set[str] = set()
                for child in sorted(names):
                    child_path = path + "/" + child
                    validate_portable_file_path(child_path)
                    key = collision_key(child)
                    if key in seen:
                        raise FileMoveError("PORTABLE_NAME_COLLISION")
                    seen.add(key)
                    visit(descriptor, child, child_path, device, depth + 1)
                if file_identity(os.fstat(descriptor)) != identity:
                    raise FileMoveError("SOURCE_CHANGED")
            finally:
                os.close(descriptor)
        else:
            files += 1
            byte_count += before.st_size
            if files > MAX_FILES or byte_count > MAX_BYTES:
                raise FileMoveError("INVENTORY_LIMIT")
            if before.st_nlink != 1:
                raise FileMoveError("HARDLINK_MOVE_UNSUPPORTED")
        if (
            file_identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False))
            != identity
        ):
            raise FileMoveError("SOURCE_CHANGED")

    try:
        with open_library_directory(root, parent) as descriptor:
            visit(descriptor, name, relative_path, os.fstat(descriptor).st_dev, 0)
    except OSError as error:
        raise FileMoveError("SOURCE_UNAVAILABLE") from error
    return MoveInventory(tuple(entries), files, byte_count)


def inspect_move_destination(root: Path, relative_path: str) -> DestinationInspection:
    validate_portable_file_path(relative_path)
    parts = relative_path.split("/")
    with open_library_directory(root) as root_fd:
        directory = root_fd
        descriptors: list[int] = []
        parent_parts: list[str] = []
        try:
            for index, name in enumerate(parts):
                names = os.listdir(directory)
                matches = [
                    existing
                    for existing in names
                    if collision_key(existing) == collision_key(name)
                ]
                if not matches:
                    missing = tuple(
                        "/".join(parts[:end]) for end in range(index + 1, len(parts))
                    )
                    parent_stat = os.fstat(directory)
                    return DestinationInspection(
                        missing,
                        parent_stat.st_dev,
                        parent_stat.st_ino,
                        "/".join(parent_parts),
                    )
                if matches != [name] or index == len(parts) - 1:
                    raise FileMoveError("DESTINATION_EXISTS")
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                descriptors.append(descriptor)
                if os.fstat(descriptor).st_dev != os.fstat(root_fd).st_dev:
                    raise FileMoveError("NESTED_MOUNT_UNSUPPORTED")
                directory = descriptor
                parent_parts.append(name)
        except OSError as error:
            raise FileMoveError("DESTINATION_UNAVAILABLE") from error
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
    raise FileMoveError("DESTINATION_EXISTS")


def require_writable_move_directory(root: Path, relative_path: str) -> None:
    with open_library_directory(root, relative_path) as descriptor:
        if os.fstatvfs(descriptor).f_flag & os.ST_RDONLY:
            raise FileMoveError("READ_ONLY_FILESYSTEM")
        if not os.access(".", os.W_OK | os.X_OK, dir_fd=descriptor, effective_ids=True):
            raise FileMoveError("DIRECTORY_NOT_WRITABLE")


class AnchoredMoveInspection:
    def source(self, root: Path, relative_path: str) -> MoveInventory:
        require_writable_move_directory(root, relative_path.rpartition("/")[0])
        return inspect_move_source(root, relative_path)

    def destination(self, root: Path, relative_path: str) -> DestinationInspection:
        result = inspect_move_destination(root, relative_path)
        require_writable_move_directory(root, result.parent_relative_path)
        return result
