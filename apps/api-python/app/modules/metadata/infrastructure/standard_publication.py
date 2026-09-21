"""Prepare standard metadata separately, then publish through verified recovery slots."""

import hashlib
import os
import stat
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

from app.contracts.controlled_file_slots import is_controlled_file_slot
from app.contracts.file_operation import FileIdentity, FileOperationError
from app.contracts.publication_metadata import PublicationMetadata
from app.infrastructure.copied_file_attributes import (
    apply_copy_attributes,
    read_copy_attributes,
)
from app.infrastructure.epub_metadata import read_epub_package, read_zip_metadata
from app.infrastructure.exclusive_rename import exclusive_rename
from app.infrastructure.file_identity import file_identity
from app.infrastructure.sidecar_paths import same_stem_source_names, sidecar_opf_paths
from app.modules.metadata.application.opf import MAX_OPF_BYTES, parse_opf_metadata
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.application.standard_writeback import (
    PreparedStandardFile,
    StandardPreparationError,
    StandardWriteFile,
    StandardWriteFormat,
    StandardWriteInspection,
)
from app.modules.metadata.infrastructure.archive_writeback import (
    BoundedArchiveStream,
    inspect_archive_entries,
    preview_archive_metadata,
    write_archive_metadata,
)
from app.modules.metadata.infrastructure.selective_comicinfo import patch_comicinfo
from app.modules.metadata.infrastructure.selective_opf import patch_opf_metadata
from app.modules.metadata.infrastructure.standard_files import read_comic_metadata

DirectoryOpener = Callable[[Path, str], AbstractContextManager[int]]
FileOpener = Callable[[Path, str], AbstractContextManager[int]]


def _same_identity(
    actual: FileIdentity | None,
    expected: FileIdentity | None,
    *,
    relocated: bool = False,
) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return (
        replace(actual, ctime_ns=expected.ctime_ns) if relocated else actual
    ) == expected


def _identity(directory: int, name: str) -> FileIdentity | None:
    try:
        return file_identity(os.stat(name, dir_fd=directory, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _digest(descriptor: int, expected_size: int) -> str:
    if os.fstat(descriptor).st_size != expected_size:
        raise StandardMetadataError("SOURCE_CHANGED")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = expected_size
    while remaining:
        chunk = os.read(descriptor, min(1024**2, remaining))
        if not chunk:
            raise StandardMetadataError("SOURCE_CHANGED")
        remaining -= len(chunk)
        digest.update(chunk)
    if os.read(descriptor, 1):
        raise StandardMetadataError("SOURCE_CHANGED")
    return digest.hexdigest()


class StandardMetadataPublication:
    def __init__(self, open_directory: DirectoryOpener, open_file: FileOpener) -> None:
        self._directory = open_directory
        self._file = open_file

    def require_unshared_opf(
        self, root: Path, source_relative_path: str, *, directory: bool
    ) -> None:
        if directory:
            return
        source = Path(source_relative_path)
        parent = source.parent.as_posix()
        with self._directory(root, "" if parent == "." else parent) as descriptor:
            names = tuple(os.listdir(descriptor))
        if len(names) > 10_000:
            raise StandardMetadataError("DIRECTORY_INSPECTION_LIMIT")
        if same_stem_source_names(names, source.name) != (source.name,):
            raise StandardMetadataError("SHARED_SIDECAR_TARGET")
        own = source.with_suffix(".opf")
        for candidate in sidecar_opf_paths(source, directory=False):
            if candidate != own and candidate.name in names:
                raise StandardMetadataError("SHARED_SIDECAR_TARGET")

    def inspect(
        self,
        root: Path,
        relative_path: str,
        format: StandardWriteFormat,
        values: PublicationMetadata,
        fields: frozenset[str],
    ) -> StandardWriteInspection:
        parent, _, name = relative_path.rpartition("/")
        with self._directory(root, parent) as directory:
            parent_stat = os.fstat(directory)
            original = _identity(directory, name)
            before = PublicationMetadata()
            if original is None:
                if format == "OPF":
                    patch_opf_metadata(None, values, fields)
                elif format == "ComicInfo":
                    patch_comicinfo(None, values, fields)
                else:
                    raise StandardMetadataError("SOURCE_REQUIRED")
            else:
                if not stat.S_ISREG(original.mode) or original.link_count != 1:
                    raise StandardMetadataError("SOURCE_CHANGED_OR_HARDLINK")
                with self._file(root, relative_path) as descriptor:
                    if file_identity(os.fstat(descriptor)) != original:
                        raise StandardMetadataError("SOURCE_CHANGED")
                    with os.fdopen(os.dup(descriptor), "rb") as source:
                        if format in {"OPF", "ComicInfo"}:
                            content = source.read(MAX_OPF_BYTES + 1)
                            if format == "OPF":
                                patch_opf_metadata(content, values, fields)
                                before = parse_opf_metadata(content)
                            else:
                                patch_comicinfo(content, values, fields)
                                before = read_comic_metadata(content)
                        elif format in {"EPUB", "CBZ", "ZIP"}:
                            with ZipFile(BoundedArchiveStream(source)) as archive:
                                inspect_archive_entries(archive)
                                member, _ = preview_archive_metadata(
                                    archive, format, values, fields
                                )
                                if format == "EPUB":
                                    _, content = read_epub_package(archive)
                                    before = parse_opf_metadata(content)
                                elif member in archive.namelist():
                                    before = read_comic_metadata(
                                        read_zip_metadata(archive, member)
                                    )
                        else:
                            raise StandardMetadataError("WRITER_NOT_AVAILABLE")
                    if file_identity(os.fstat(descriptor)) != original:
                        raise StandardMetadataError("SOURCE_CHANGED")
                if not _same_identity(_identity(directory, name), original):
                    raise StandardMetadataError("SOURCE_CHANGED")
            return StandardWriteInspection(
                original,
                parent_stat.st_dev,
                parent_stat.st_ino,
                replace(before, cover_href=None, unparsed_values=()),
            )

    def _validate_slots(self, target: StandardWriteFile) -> None:
        if (
            not all(
                is_controlled_file_slot(name)
                for name in (target.prepared_name, target.backup_name)
            )
            or target.prepared_name == target.backup_name
        ):
            raise StandardMetadataError("INVALID_RECOVERY_SLOT")

    def _validate_parent(self, directory: int, target: StandardWriteFile) -> None:
        observed = os.fstat(directory)
        if (observed.st_dev, observed.st_ino) != (
            target.parent_device,
            target.parent_inode,
        ):
            raise StandardMetadataError("DESTINATION_CHANGED")

    def prepare(self, target: StandardWriteFile) -> PreparedStandardFile:
        self._validate_slots(target)
        if target.format not in {"OPF", "ComicInfo", "EPUB", "CBZ", "ZIP"}:
            raise StandardMetadataError("WRITER_NOT_AVAILABLE")
        if target.original and (
            target.original.link_count != 1 or not stat.S_ISREG(target.original.mode)
        ):
            raise StandardMetadataError("SOURCE_CHANGED_OR_HARDLINK")
        original_sha256 = None
        parent, _, name = target.relative_path.rpartition("/")
        with self._directory(target.root, parent) as directory:
            self._validate_parent(directory, target)
            if not _same_identity(_identity(directory, name), target.original):
                raise StandardMetadataError("SOURCE_CHANGED")
            available = os.fstatvfs(directory)
            required = (target.original.size if target.original else 0) + MAX_OPF_BYTES
            if (
                available.f_flag & os.ST_RDONLY
                or available.f_bavail * available.f_frsize < required
            ):
                raise StandardMetadataError("PREPARATION_SPACE_UNAVAILABLE")
            prepared_fd = os.open(
                target.prepared_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                if target.original is None:
                    if target.format not in {"OPF", "ComicInfo"}:
                        raise StandardMetadataError("SOURCE_REQUIRED")
                    content = (
                        patch_opf_metadata(None, target.values, target.fields)
                        if target.format == "OPF"
                        else patch_comicinfo(None, target.values, target.fields)
                    )
                    with os.fdopen(os.dup(prepared_fd), "wb") as output:
                        output.write(content)
                else:
                    with self._file(target.root, target.relative_path) as source_fd:
                        if (
                            file_identity(os.fstat(source_fd)) != target.original
                            or target.original.link_count != 1
                        ):
                            raise StandardMetadataError("SOURCE_CHANGED_OR_HARDLINK")
                        attributes = read_copy_attributes(source_fd)
                        original_sha256 = _digest(source_fd, target.original.size)
                        os.lseek(source_fd, 0, os.SEEK_SET)
                        with (
                            os.fdopen(os.dup(source_fd), "rb") as source,
                            os.fdopen(os.dup(prepared_fd), "w+b") as output,
                        ):
                            if target.format in {"OPF", "ComicInfo"}:
                                original = source.read(MAX_OPF_BYTES + 1)
                                content = (
                                    patch_opf_metadata(
                                        original, target.values, target.fields
                                    )
                                    if target.format == "OPF"
                                    else patch_comicinfo(
                                        original, target.values, target.fields
                                    )
                                )
                                output.write(content)
                            elif target.format in {"EPUB", "CBZ", "ZIP"}:
                                write_archive_metadata(
                                    source,
                                    output,
                                    format=target.format,
                                    values=target.values,
                                    fields=target.fields,
                                )
                            else:
                                raise StandardMetadataError("WRITER_NOT_AVAILABLE")
                        if file_identity(os.fstat(source_fd)) != target.original:
                            raise StandardMetadataError("SOURCE_CHANGED")
                        apply_copy_attributes(prepared_fd, attributes)
                os.fsync(prepared_fd)
                identity = file_identity(os.fstat(prepared_fd))
                digest = _digest(prepared_fd, identity.size)
                if file_identity(
                    os.fstat(prepared_fd)
                ) != identity or not _same_identity(
                    _identity(directory, name), target.original
                ):
                    raise StandardMetadataError("SOURCE_CHANGED")
                os.fsync(directory)
                return PreparedStandardFile(identity, digest, original_sha256)
            except Exception as error:
                code = (
                    str(error)
                    if isinstance(error, (StandardMetadataError, FileOperationError))
                    else "FILE_PREPARATION_FAILED"
                )
                raise StandardPreparationError(
                    code, file_identity(os.fstat(prepared_fd))
                ) from error
            finally:
                os.close(prepared_fd)

    def _verify_prepared(
        self, target: StandardWriteFile, relative_path: str, proof: PreparedStandardFile
    ) -> None:
        with self._file(target.root, relative_path) as descriptor:
            observed = file_identity(os.fstat(descriptor))
            if (
                not _same_identity(observed, proof.identity, relocated=True)
                or _digest(descriptor, proof.identity.size) != proof.sha256
                or file_identity(os.fstat(descriptor)) != observed
            ):
                raise StandardMetadataError("PREPARED_CONTENT_CHANGED")

    def published(self, target: StandardWriteFile, proof: PreparedStandardFile) -> bool:
        parent, _, name = target.relative_path.rpartition("/")
        with self._directory(target.root, parent) as directory:
            self._validate_parent(directory, target)
            observed = _identity(directory, name)
            if _same_identity(observed, proof.identity, relocated=True):
                self._verify_prepared(target, target.relative_path, proof)
                return True
            if not _same_identity(observed, target.original):
                backup = _identity(directory, target.backup_name)
                if (
                    observed is not None
                    or target.original is None
                    or not _same_identity(backup, target.original, relocated=True)
                ):
                    raise StandardMetadataError("SOURCE_CHANGED")
        return False

    def publish(self, target: StandardWriteFile, proof: PreparedStandardFile) -> None:
        self._validate_slots(target)
        if self.published(target, proof):
            return
        parent, _, name = target.relative_path.rpartition("/")
        staged_relative = (
            f"{parent}/{target.prepared_name}" if parent else target.prepared_name
        )
        self._verify_prepared(target, staged_relative, proof)
        with self._directory(target.root, parent) as directory:
            self._validate_parent(directory, target)
            observed = _identity(directory, name)
            if observed is not None:
                if not _same_identity(observed, target.original):
                    raise StandardMetadataError("SOURCE_CHANGED")
                exclusive_rename(directory, name, directory, target.backup_name)
                os.fsync(directory)
            if target.original is not None and not _same_identity(
                _identity(directory, target.backup_name),
                target.original,
                relocated=True,
            ):
                raise StandardMetadataError("RECOVERY_SOURCE_CHANGED")
            if target.original is not None:
                backup_relative = (
                    f"{parent}/{target.backup_name}" if parent else target.backup_name
                )
                with self._file(target.root, backup_relative) as backup_fd:
                    if (
                        _digest(backup_fd, target.original.size)
                        != proof.original_sha256
                    ):
                        raise StandardMetadataError("RECOVERY_SOURCE_CHANGED")
            exclusive_rename(directory, target.prepared_name, directory, name)
            os.fsync(directory)
        self._verify_prepared(target, target.relative_path, proof)

    def clear_backup(
        self, target: StandardWriteFile, proof: PreparedStandardFile
    ) -> None:
        """Remove only the verified old file after its retention window has expired."""
        self._validate_slots(target)
        if target.original is None:
            return
        if not self.published(target, proof):
            raise StandardMetadataError("PUBLISHED_FILE_CHANGED")
        parent, _, _ = target.relative_path.rpartition("/")
        relative = f"{parent}/{target.backup_name}" if parent else target.backup_name
        with self._directory(target.root, parent) as directory:
            self._validate_parent(directory, target)
            observed = _identity(directory, target.backup_name)
            if observed is None:
                return
            if not _same_identity(observed, target.original, relocated=True):
                raise StandardMetadataError("RECOVERY_SOURCE_CHANGED")
            with self._file(target.root, relative) as descriptor:
                if (
                    file_identity(os.fstat(descriptor)) != observed
                    or _digest(descriptor, observed.size) != proof.original_sha256
                    or file_identity(os.fstat(descriptor)) != observed
                    or _identity(directory, target.backup_name) != observed
                ):
                    raise StandardMetadataError("RECOVERY_SOURCE_CHANGED")
                os.unlink(target.backup_name, dir_fd=directory)
                os.fsync(directory)

    def discard_prepared(
        self, target: StandardWriteFile, proof: PreparedStandardFile
    ) -> None:
        """Cancel a verified preparation, restoring a staged original when necessary."""
        self._validate_slots(target)
        if self.published(target, proof):
            raise StandardMetadataError("FILE_ALREADY_PUBLISHED")
        parent, _, name = target.relative_path.rpartition("/")
        relative = (
            f"{parent}/{target.prepared_name}" if parent else target.prepared_name
        )
        self._verify_prepared(target, relative, proof)
        with self._directory(target.root, parent) as directory:
            self._validate_parent(directory, target)
            original = _identity(directory, name)
            backup = _identity(directory, target.backup_name)
            if backup is not None:
                if (
                    original is not None
                    or target.original is None
                    or not _same_identity(backup, target.original, relocated=True)
                ):
                    raise StandardMetadataError("RECOVERY_SOURCE_CHANGED")
                backup_relative = (
                    f"{parent}/{target.backup_name}" if parent else target.backup_name
                )
                with self._file(target.root, backup_relative) as descriptor:
                    if (
                        _digest(descriptor, target.original.size)
                        != proof.original_sha256
                    ):
                        raise StandardMetadataError("RECOVERY_SOURCE_CHANGED")
                exclusive_rename(directory, target.backup_name, directory, name)
                os.fsync(directory)
            elif not _same_identity(original, target.original):
                raise StandardMetadataError("SOURCE_CHANGED")
            if not _same_identity(
                _identity(directory, target.prepared_name),
                proof.identity,
                relocated=True,
            ):
                raise StandardMetadataError("PREPARED_CONTENT_CHANGED")
            os.unlink(target.prepared_name, dir_fd=directory)
            os.fsync(directory)
