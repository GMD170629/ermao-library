"""Atomic filesystem publisher for browser-uploaded import sources."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.contracts.automation_upload import UploadError, UploadPublication, UploadTarget
from app.contracts.file_operation import FileOperationError
from app.infrastructure.copied_file_attributes import (
    apply_copy_attributes,
    read_copy_attributes,
)
from app.infrastructure.exclusive_rename import exclusive_rename
from app.infrastructure.file_identity import file_identity
from app.modules.imports.application.save_uploaded_files import (
    SavedUploadFile,
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadPublicationError,
    safe_upload_filename,
)


class AtomicUploadedFilePublisher:
    """Publish a complete batch via hidden temporary files and atomic renames."""

    def __init__(
        self,
        *,
        nonce_factory: Callable[[], str] | None = None,
        open_directory: Callable[[Path, str], AbstractContextManager[int]]
        | None = None,
    ) -> None:
        self._directories = open_directory
        self._nonce_factory = nonce_factory or (lambda: uuid4().hex)

    def publish(self, command: SaveUploadedFilesCommand) -> tuple[SavedUploadFile, ...]:
        directory = command.target_directory.expanduser().resolve()
        if not directory.is_dir():
            raise UploadPublicationError("target directory is not available")

        reserved_paths: set[Path] = set()
        staged_paths: list[Path] = []
        published_paths: list[Path] = []
        saved_files: list[SavedUploadFile] = []
        remaining_audio_bytes = command.audio_bundle_max_bytes
        nonce = self._nonce_factory()

        try:
            for index, source in enumerate(command.sources):
                target = self._unique_target(directory, source.filename, reserved_paths)
                reserved_paths.add(target)
                staged = directory / f".upload-{nonce}-{index}.part"
                staged_paths.append(staged)
                copied = self._copy_stream(
                    source.stream,
                    staged,
                    max_bytes=(
                        min(source.max_bytes, remaining_audio_bytes)
                        if source.is_audio and source.max_bytes is not None
                        else remaining_audio_bytes
                        if source.is_audio
                        else source.max_bytes
                    ),
                )
                if source.is_audio:
                    remaining_audio_bytes -= copied
                    if remaining_audio_bytes < 0:
                        raise UploadFileTooLargeError(
                            "audio batch exceeds configured size"
                        )
                staged.replace(target)
                staged_paths.remove(staged)
                published_paths.append(target)
                saved_files.append(
                    SavedUploadFile(
                        filename=target.name,
                        path=target,
                        size_bytes=copied,
                    )
                )
        except OSError as exc:
            self._cleanup(staged_paths, published_paths)
            raise UploadPublicationError("unable to save upload files") from exc
        except UploadPublicationError:
            self._cleanup(staged_paths, published_paths)
            raise
        return tuple(saved_files)

    def prepare_strict(
        self, upload_id: str, target: UploadTarget, source: Path, size: int, digest: str
    ) -> UploadPublication:
        """Stage one exact name without changing the browser's auto-rename policy."""
        if self._directories is None:
            raise RuntimeError("anchored upload directories are required")
        parent, _, name = target.relative_path.rpartition("/")
        staged = f".upload-{upload_id}.part"
        with self._directories(target.root, parent) as directory:
            self._check_parent(directory, target)
            try:
                existing = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                if target.original is not None:
                    raise UploadError("SOURCE_CHANGED") from None
            else:
                if target.original is None:
                    raise UploadError("UPLOAD_NAME_CONFLICT")
                if file_identity(existing) != target.original:
                    raise UploadError("SOURCE_CHANGED")
            try:
                descriptor = os.open(
                    staged,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
            except FileExistsError:
                descriptor = os.open(
                    staged, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory
                )
            with os.fdopen(descriptor, "r+b") as output:
                if (
                    not stat.S_ISREG(os.fstat(output.fileno()).st_mode)
                    or os.fstat(output.fileno()).st_nlink != 1
                ):
                    raise UploadError("UPLOAD_STAGING_CONFLICT")
                # No publication checkpoint exists yet; recopy a interrupted prepare.
                output.truncate(0)
                source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(source_fd, "rb") as input_file:
                    copied = 0
                    while block := input_file.read(1024 * 1024):
                        copied += len(block)
                        if copied > size:
                            raise UploadError("UPLOAD_SIZE_MISMATCH")
                        output.write(block)
                output.flush()
                if target.original is not None:
                    original_fd = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory
                    )
                    try:
                        if file_identity(os.fstat(original_fd)) != target.original:
                            raise UploadError("SOURCE_CHANGED")
                        apply_copy_attributes(
                            output.fileno(), read_copy_attributes(original_fd)
                        )
                    finally:
                        os.close(original_fd)
                    os.utime(output.fileno(), None)
                os.fsync(output.fileno())
                output.seek(0)
                observed = hashlib.file_digest(output, "sha256").hexdigest()
                identity = file_identity(os.fstat(output.fileno()))
                if identity.size != size or observed != digest:
                    raise UploadError("UPLOAD_STAGING_CONFLICT")
            os.fsync(directory)
        return UploadPublication(
            target,
            staged,
            identity,
            backup_name=f".ermao-mcp-{upload_id}-source"
            if target.original is not None
            else None,
        )

    @staticmethod
    def _check_parent(directory: int, target: UploadTarget) -> None:
        observed = os.fstat(directory)
        if (observed.st_dev, observed.st_ino) != (
            target.parent_device,
            target.parent_inode,
        ):
            raise UploadError("UPLOAD_TARGET_CHANGED")

    def publish_strict(self, publication: UploadPublication) -> None:
        if self._directories is None:
            raise RuntimeError("anchored upload directories are required")
        target = publication.target
        parent, _, name = target.relative_path.rpartition("/")
        with self._directories(target.root, parent) as directory:
            self._check_parent(directory, target)
            try:
                observed = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                observed = None
            if observed is not None:
                identity = publication.identity
                if (
                    observed.st_dev,
                    observed.st_ino,
                    observed.st_size,
                    observed.st_mtime_ns,
                ) == (
                    identity.device,
                    identity.inode,
                    identity.size,
                    identity.mtime_ns,
                ):
                    return  # Publication completed before its database checkpoint.
                if (
                    file_identity(
                        os.stat(
                            publication.staged_name,
                            dir_fd=directory,
                            follow_symlinks=False,
                        )
                    )
                    != publication.identity
                ):
                    raise UploadError("UPLOAD_STAGING_CHANGED")
                if (
                    target.original is None
                    or file_identity(observed) != target.original
                    or publication.backup_name is None
                ):
                    raise UploadError("UPLOAD_NAME_CONFLICT")
                exclusive_rename(directory, name, directory, publication.backup_name)
                os.fsync(directory)
            elif target.original is not None:
                if publication.backup_name is None:
                    raise UploadError("SOURCE_CHANGED")
                backup = os.stat(
                    publication.backup_name, dir_fd=directory, follow_symlinks=False
                )
                original = target.original
                if (
                    backup.st_dev,
                    backup.st_ino,
                    backup.st_size,
                    backup.st_mtime_ns,
                ) != (
                    original.device,
                    original.inode,
                    original.size,
                    original.mtime_ns,
                ):
                    raise UploadError("SOURCE_CHANGED")
            if (
                file_identity(
                    os.stat(
                        publication.staged_name, dir_fd=directory, follow_symlinks=False
                    )
                )
                != publication.identity
            ):
                raise UploadError("UPLOAD_STAGING_CHANGED")
            try:
                exclusive_rename(directory, publication.staged_name, directory, name)
            except FileOperationError as error:
                raise UploadError(
                    "UPLOAD_NAME_CONFLICT"
                    if str(error) == "DESTINATION_EXISTS"
                    else str(error)
                ) from error
            os.fsync(directory)

    @staticmethod
    def _unique_target(
        directory: Path, filename: str, reserved_paths: set[Path]
    ) -> Path:
        safe_name = safe_upload_filename(filename)
        parsed = Path(safe_name)
        stem = parsed.stem or "upload"
        suffix = parsed.suffix
        index = 0
        while True:
            candidate = directory / (
                safe_name if index == 0 else f"{stem}-{index}{suffix}"
            )
            resolved = candidate.resolve()
            if directory != resolved.parent:
                raise UploadPublicationError("target path escapes directory")
            if not resolved.exists() and resolved not in reserved_paths:
                return resolved
            index += 1

    @staticmethod
    def _copy_stream(source: BinaryIO, target: Path, *, max_bytes: int | None) -> int:
        copied = 0
        with target.open("xb") as handle:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if max_bytes is not None and copied > max_bytes:
                    raise UploadFileTooLargeError("upload exceeds configured size")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        return copied

    @staticmethod
    def _cleanup(staged_paths: list[Path], published_paths: list[Path]) -> None:
        for path in reversed(staged_paths):
            path.unlink(missing_ok=True)
        for path in reversed(published_paths):
            path.unlink(missing_ok=True)
