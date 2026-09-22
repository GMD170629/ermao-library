"""System file moves behind the existing library publication boundary."""

import os
import stat
import subprocess
import sys
from pathlib import Path

from app.modules.library.application.file_move_plans import (
    DestinationInspection,
    PlannedMove,
)
from app.modules.library.domain.file_moves import FileIdentity, FileMoveError
from app.modules.library.infrastructure.move_inventory import (
    file_identity,
    inspect_move_destination,
    require_writable_move_directory,
)
from app.modules.library.infrastructure.source_file_access import open_library_directory


class SystemMovePublication:
    """The system owns rename/copy/remove; the task owns ordering and results."""

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
            return file_identity(
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            )

    def validate(self, move: PlannedMove) -> None:
        parent, _, name = move.source.relative_path.rpartition("/")
        require_writable_move_directory(move.source.root, parent)
        require_writable_move_directory(
            move.destination.root, move.destination_inspection.parent_relative_path
        )
        with open_library_directory(move.source.root, parent) as descriptor:
            observed = file_identity(
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            )
        if observed != move.inventory.entries[0].identity:
            raise FileMoveError("SOURCE_CHANGED")
        destination = inspect_move_destination(
            move.destination.root,
            move.destination.relative_path,
            existing_source=move.source.relative_path if move.case_only else None,
        )
        if destination != move.destination_inspection:
            raise FileMoveError("DESTINATION_CHANGED")

    def publish(self, move: PlannedMove) -> None:
        self.validate(move)
        if move.destination_inspection.missing_directories:
            raise FileMoveError("DESTINATION_DIRECTORIES_NOT_PREPARED")
        source_parent, _, source_name = move.source.relative_path.rpartition("/")
        target_parent, _, target_name = move.destination.relative_path.rpartition("/")
        with (
            open_library_directory(move.source.root, source_parent) as source_fd,
            open_library_directory(move.destination.root, target_parent) as target_fd,
        ):
            try:
                if move.case_only:
                    # Native rename changes spelling on case-insensitive filesystems.
                    os.rename(
                        source_name,
                        target_name,
                        src_dir_fd=source_fd,
                        dst_dir_fd=target_fd,
                    )
                else:
                    self._move(move, source_fd, target_fd, source_name, target_name)
            except subprocess.CalledProcessError as error:
                # mv implementations differ on the exit status for -n skips.
                # Inspect the actual outcome while retaining the native failure.
                try:
                    self.is_published(move)
                except FileMoveError as outcome:
                    raise outcome from error
                raise FileMoveError("FILE_MOVE_FAILED") from error
            except OSError as error:
                raise FileMoveError("FILE_MOVE_FAILED") from error
        if not self.is_published(move):
            raise FileMoveError("FILE_MOVE_INCOMPLETE")

    @staticmethod
    def _move(
        move: PlannedMove,
        source_fd: int,
        target_fd: int,
        source_name: str,
        target_name: str,
    ) -> None:
        if sys.platform.startswith("linux"):
            # The authorized parents stay anchored throughout the system move.
            arguments = [
                "/usr/bin/mv",
                "-n",
                "-T",
                "--",
                f"/proc/self/fd/{source_fd}/{source_name}",
                f"/proc/self/fd/{target_fd}/{target_name}",
            ]
        elif sys.platform == "darwin":
            arguments = [
                "/bin/mv",
                "-n",
                "-h",
                "-v",
                str(move.source.root / move.source.relative_path),
                str(move.destination.root / move.destination.relative_path),
            ]
        else:
            raise FileMoveError("SYSTEM_MOVE_UNSUPPORTED")
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            pass_fds=(source_fd, target_fd),
        )
        if sys.platform == "darwin":
            # BSD mv lacks -T. Its verbose result names the actual destination;
            # a concurrently created directory must not turn nesting into success.
            expected = os.fsencode(f"{arguments[-2]} -> {arguments[-1]}\n")
            # Cross-volume directories report their root first, with a trailing
            # slash, followed by cp's per-entry verbose output.
            directory = os.fsencode(f"{arguments[-2]} -> {arguments[-1]}/\n")
            if not result.stdout.startswith((expected, directory)):
                raise FileMoveError("FILE_MOVE_INCOMPLETE")

    def is_published(self, move: PlannedMove) -> bool:
        source_parent, _, source_name = move.source.relative_path.rpartition("/")
        target_parent, _, target_name = move.destination.relative_path.rpartition("/")
        with (
            open_library_directory(move.source.root, source_parent) as source_fd,
            open_library_directory(move.destination.root, target_parent) as target_fd,
        ):
            # Exact names distinguish a case-only rename on APFS as well.
            source_exists = source_name in os.listdir(source_fd)
            target_exists = target_name in os.listdir(target_fd)
            if source_exists:
                if target_exists:
                    # mv -n may return zero when skipping an existing destination.
                    raise FileMoveError("DESTINATION_EXISTS")
                return False
            if not target_exists:
                raise FileMoveError("FILE_MOVE_INCOMPLETE")
            observed = os.stat(target_name, dir_fd=target_fd, follow_symlinks=False)
            expected = move.inventory.entries[0]
            if (
                stat.S_ISDIR(observed.st_mode) != expected.directory
                or not (
                    stat.S_ISDIR(observed.st_mode) or stat.S_ISREG(observed.st_mode)
                )
                or (
                    not expected.directory
                    and observed.st_size != expected.identity.size
                )
            ):
                raise FileMoveError("FILE_MOVE_INCOMPLETE")
        return True
