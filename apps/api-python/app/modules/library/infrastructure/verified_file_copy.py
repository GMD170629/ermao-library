"""Bounded copies into exclusive staging slots; source deletion is never performed."""

import hashlib
import os
from pathlib import Path

from app.infrastructure.copied_file_attributes import (
    apply_copy_attributes,
    read_copy_attributes,
)
from app.modules.library.application.file_move_plans import CopiedContent
from app.modules.library.domain.file_moves import (
    FileMoveError,
    MoveInventory,
    validate_portable_file_path,
)
from app.modules.library.infrastructure.move_inventory import (
    file_identity,
    inspect_move_source,
)
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)

COPY_CHUNK_BYTES = 1024 * 1024


def copy_verified_tree(
    source_root: Path,
    source_relative: str,
    destination_root: Path,
    staging_relative: str,
    inventory: MoveInventory,
) -> tuple[CopiedContent, ...]:
    """The caller journals the server-chosen staging name before entering here."""
    validate_portable_file_path(staging_relative)
    if inspect_move_source(source_root, source_relative) != inventory:
        raise FileMoveError("SOURCE_CHANGED")
    copied: list[CopiedContent] = []
    directory_attributes = []
    for item in inventory.entries:
        destination = staging_relative + item.relative_path[len(source_relative) :]
        parent, _, name = destination.rpartition("/")
        if item.directory:
            with open_library_directory(source_root, item.relative_path) as source_fd:
                if file_identity(os.fstat(source_fd)) != item.identity:
                    raise FileMoveError("SOURCE_CHANGED")
                attributes = read_copy_attributes(source_fd)
            directory_attributes.append(
                (item.relative_path, destination, item.identity)
            )
            with open_library_directory(destination_root, parent) as parent_fd:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
            continue
        with open_library_file(source_root, item.relative_path) as source_fd:
            if file_identity(os.fstat(source_fd)) != item.identity:
                raise FileMoveError("SOURCE_CHANGED")
            attributes = read_copy_attributes(source_fd)
            with open_library_directory(destination_root, parent) as parent_fd:
                target_fd = os.open(
                    name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        block = os.read(source_fd, COPY_CHUNK_BYTES)
                        if not block:
                            break
                        size += len(block)
                        if size > item.identity.size:
                            raise FileMoveError("SOURCE_CHANGED")
                        digest.update(block)
                        pending = memoryview(block)
                        while pending:
                            count = os.write(target_fd, pending)
                            if count <= 0:
                                raise FileMoveError("COPY_WRITE_FAILED")
                            pending = pending[count:]
                    if (
                        size != item.identity.size
                        or file_identity(os.fstat(source_fd)) != item.identity
                        or read_copy_attributes(source_fd) != attributes
                    ):
                        raise FileMoveError("SOURCE_CHANGED")
                    os.fsync(target_fd)
                    os.lseek(target_fd, 0, os.SEEK_SET)
                    verification = hashlib.sha256()
                    verified_size = 0
                    while True:
                        block = os.read(target_fd, COPY_CHUNK_BYTES)
                        if not block:
                            break
                        verified_size += len(block)
                        if verified_size > size:
                            raise FileMoveError("COPY_VERIFICATION_FAILED")
                        verification.update(block)
                    if (
                        verified_size != size
                        or verification.digest() != digest.digest()
                    ):
                        raise FileMoveError("COPY_VERIFICATION_FAILED")
                    apply_copy_attributes(target_fd, attributes)
                    os.fsync(target_fd)
                    copied.append(CopiedContent(destination, size, digest.hexdigest()))
                finally:
                    os.close(target_fd)
                os.fsync(parent_fd)
    for source, destination, identity in reversed(directory_attributes):
        with open_library_directory(source_root, source) as source_fd:
            if file_identity(os.fstat(source_fd)) != identity:
                raise FileMoveError("SOURCE_ATTRIBUTES_CHANGED")
            attributes = read_copy_attributes(source_fd)
        with open_library_directory(destination_root, destination) as target_fd:
            apply_copy_attributes(target_fd, attributes)
            os.fsync(target_fd)
    # Detect additions, removals and external changes across the entire copy.
    if inspect_move_source(source_root, source_relative) != inventory:
        raise FileMoveError("SOURCE_CHANGED")
    return tuple(copied)
