"""No-follow, root-relative source access for admission probes."""

from __future__ import annotations

import errno
import os
import stat
import unicodedata
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import BinaryIO, NoReturn, Self

from app.modules.catalog.application.source_admission_ports import (
    InvalidSourceRelativePath,
    SourceAdmissionOperationalError,
    SourceChangedDuringProbe,
    SourceProbeIoError,
    SourceProbePermissionDenied,
    SourceProbeUnavailable,
    SourceStatExpectation,
)
from app.modules.catalog.domain.model import EntryType

_O_DIRECTORY = int(getattr(os, "O_DIRECTORY", 0))
_O_CLOEXEC = int(getattr(os, "O_CLOEXEC", 0))
_O_NOFOLLOW = int(getattr(os, "O_NOFOLLOW", 0))
_O_NONBLOCK = int(getattr(os, "O_NONBLOCK", 0))
_PLATFORM_SUPPORTED = (
    _O_DIRECTORY != 0
    and _O_NOFOLLOW != 0
    and hasattr(os, "pread")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW
_FILE_OPEN_FLAGS = os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def validate_relative_path(relative_path: tuple[str, ...]) -> None:
    """Reject any component that could change root-relative interpretation."""

    if not isinstance(relative_path, tuple) or not relative_path:
        raise InvalidSourceRelativePath()
    for component in relative_path:
        if (
            not isinstance(component, str)
            or not component
            or component in {".", ".."}
            or "\x00" in component
            or "/" in component
            or "\\" in component
            or unicodedata.normalize("NFC", component) != component
            or os.path.isabs(component)
            or (len(component) >= 2 and component[0].isalpha() and component[1] == ":")
        ):
            raise InvalidSourceRelativePath()


def _entry_type(source_stat: os.stat_result) -> EntryType:
    if stat.S_ISLNK(source_stat.st_mode):
        return EntryType.SYMLINK
    file_attributes = int(getattr(source_stat, "st_file_attributes", 0))
    if file_attributes & _REPARSE_POINT:
        return EntryType.JUNCTION
    if stat.S_ISDIR(source_stat.st_mode):
        return EntryType.DIRECTORY
    return EntryType.FILE


def _stat_signature(source_stat: os.stat_result) -> tuple[int, ...]:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        stat.S_IFMT(source_stat.st_mode),
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
    )


def _identity_signature(source_stat: os.stat_result) -> tuple[int, ...]:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        stat.S_IFMT(source_stat.st_mode),
    )


def _matches_expected(
    source_stat: os.stat_result, expected: SourceStatExpectation
) -> bool:
    return (
        source_stat.st_dev == expected.device_id
        and source_stat.st_ino == expected.file_id
        and source_stat.st_size == expected.size_bytes
        and source_stat.st_mtime_ns == expected.modified_ns
    )


def _raise_operational(error: OSError) -> NoReturn:
    if isinstance(error, PermissionError):
        raise SourceProbePermissionDenied() from error
    raise SourceProbeIoError() from error


@dataclass(slots=True)
class OpenedSource(AbstractContextManager["OpenedSource"]):
    """An opened entry plus the parent handle required for final revalidation."""

    relative_path: tuple[str, ...]
    observed_path: tuple[str, ...]
    observed_name: str
    root_fd: int
    parent_fd: int
    source_fd: int | None
    initial_stat: os.stat_result
    entry_type: EntryType
    _closed: bool = False

    @property
    def filename(self) -> str:
        return self.relative_path[-1]

    @property
    def size_bytes(self) -> int:
        return self.initial_stat.st_size

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            try:
                if self.source_fd is not None:
                    os.close(self.source_fd)
            finally:
                os.close(self.parent_fd)
        finally:
            os.close(self.root_fd)

    def read_prefix(self, maximum_bytes: int) -> bytes:
        if self.source_fd is None or maximum_bytes <= 0:
            return b""
        try:
            return os.pread(self.source_fd, maximum_bytes, 0)
        except OSError as error:
            _raise_operational(error)

    def read_at(self, offset: int, maximum_bytes: int) -> bytes:
        if self.source_fd is None or maximum_bytes <= 0:
            return b""
        try:
            return os.pread(self.source_fd, maximum_bytes, offset)
        except OSError as error:
            _raise_operational(error)

    def read_tail(self, maximum_bytes: int) -> bytes:
        if self.source_fd is None or maximum_bytes <= 0:
            return b""
        offset = max(0, self.size_bytes - maximum_bytes)
        try:
            return os.pread(self.source_fd, min(maximum_bytes, self.size_bytes), offset)
        except OSError as error:
            _raise_operational(error)

    def duplicate_binary(self) -> BinaryIO:
        if self.source_fd is None:
            raise RuntimeError("source is not an opened regular file")
        try:
            duplicate_fd = os.dup(self.source_fd)
            return os.fdopen(duplicate_fd, "rb", closefd=True)
        except OSError as error:
            _raise_operational(error)

    def verify_unchanged(self) -> None:
        verification_parent: int | None = None
        try:
            verification_parent = os.dup(self.root_fd)
            for component in self.observed_path[:-1]:
                component_stat = os.stat(
                    component,
                    dir_fd=verification_parent,
                    follow_symlinks=False,
                )
                if _entry_type(component_stat) is not EntryType.DIRECTORY:
                    raise SourceChangedDuringProbe()
                next_fd = os.open(
                    component,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=verification_parent,
                )
                try:
                    opened_stat = os.fstat(next_fd)
                except OSError:
                    os.close(next_fd)
                    raise
                if _identity_signature(opened_stat) != _identity_signature(
                    component_stat
                ):
                    os.close(next_fd)
                    raise SourceChangedDuringProbe()
                os.close(verification_parent)
                verification_parent = next_fd

            if _identity_signature(
                os.fstat(verification_parent)
            ) != _identity_signature(os.fstat(self.parent_fd)):
                raise SourceChangedDuringProbe()
            final_path_stat = os.stat(
                self.observed_name,
                dir_fd=verification_parent,
                follow_symlinks=False,
            )
            if _stat_signature(final_path_stat) != _stat_signature(self.initial_stat):
                raise SourceChangedDuringProbe()
            if self.source_fd is not None:
                final_fd_stat = os.fstat(self.source_fd)
                if _stat_signature(final_fd_stat) != _stat_signature(self.initial_stat):
                    raise SourceChangedDuringProbe()
        except (FileNotFoundError, NotADirectoryError) as error:
            raise SourceChangedDuringProbe() from error
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise SourceChangedDuringProbe() from error
            if isinstance(error, PermissionError):
                raise SourceProbePermissionDenied() from error
            raise SourceProbeIoError() from error
        finally:
            if verification_parent is not None:
                os.close(verification_parent)


def open_source(
    *,
    canonical_root: str,
    relative_path: tuple[str, ...],
    expected_stat: SourceStatExpectation | None,
) -> OpenedSource:
    """Open an entry beneath ``canonical_root`` without following child links."""

    validate_relative_path(relative_path)
    if not _PLATFORM_SUPPORTED:
        raise SourceProbeUnavailable()
    if (
        not isinstance(canonical_root, str)
        or "\x00" in canonical_root
        or not os.path.isabs(canonical_root)
    ):
        raise SourceProbeIoError()

    try:
        root_fd = os.open(canonical_root, _DIRECTORY_OPEN_FLAGS)
    except OSError as error:
        _raise_operational(error)
    try:
        parent_fd = os.dup(root_fd)
    except OSError as error:
        os.close(root_fd)
        _raise_operational(error)

    try:
        for component_index, component in enumerate(relative_path[:-1]):
            component_stat = os.stat(
                component,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            component_type = _entry_type(component_stat)
            if component_type in {EntryType.SYMLINK, EntryType.JUNCTION}:
                return OpenedSource(
                    relative_path=relative_path,
                    observed_path=relative_path[: component_index + 1],
                    observed_name=component,
                    root_fd=root_fd,
                    parent_fd=parent_fd,
                    source_fd=None,
                    initial_stat=component_stat,
                    entry_type=component_type,
                )
            if component_type is not EntryType.DIRECTORY:
                raise NotADirectoryError
            try:
                next_fd = os.open(
                    component,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=parent_fd,
                )
            except OSError as error:
                if error.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                    raise SourceChangedDuringProbe() from error
                raise
            try:
                opened_stat = os.fstat(next_fd)
            except OSError:
                os.close(next_fd)
                raise
            if _stat_signature(opened_stat) != _stat_signature(component_stat):
                os.close(next_fd)
                raise SourceChangedDuringProbe()
            os.close(parent_fd)
            parent_fd = next_fd

        observed_name = relative_path[-1]
        initial_stat = os.stat(
            observed_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if expected_stat is not None and not _matches_expected(
            initial_stat, expected_stat
        ):
            raise SourceChangedDuringProbe()
        entry_type = _entry_type(initial_stat)
        if entry_type in {EntryType.SYMLINK, EntryType.JUNCTION}:
            return OpenedSource(
                relative_path=relative_path,
                observed_path=relative_path,
                observed_name=observed_name,
                root_fd=root_fd,
                parent_fd=parent_fd,
                source_fd=None,
                initial_stat=initial_stat,
                entry_type=entry_type,
            )
        if entry_type is EntryType.FILE and not stat.S_ISREG(initial_stat.st_mode):
            raise SourceProbeIoError()
        open_flags = (
            _DIRECTORY_OPEN_FLAGS
            if entry_type is EntryType.DIRECTORY
            else _FILE_OPEN_FLAGS
        )
        try:
            source_fd = os.open(observed_name, open_flags, dir_fd=parent_fd)
        except OSError as error:
            if error.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                raise SourceChangedDuringProbe() from error
            raise
        try:
            opened_stat = os.fstat(source_fd)
        except OSError:
            os.close(source_fd)
            raise
        if _stat_signature(opened_stat) != _stat_signature(initial_stat):
            os.close(source_fd)
            raise SourceChangedDuringProbe()
        return OpenedSource(
            relative_path=relative_path,
            observed_path=relative_path,
            observed_name=observed_name,
            root_fd=root_fd,
            parent_fd=parent_fd,
            source_fd=source_fd,
            initial_stat=initial_stat,
            entry_type=entry_type,
        )
    except SourceAdmissionOperationalError:
        os.close(parent_fd)
        os.close(root_fd)
        raise
    except OSError as error:
        os.close(parent_fd)
        os.close(root_fd)
        _raise_operational(error)


__all__ = ["OpenedSource", "open_source", "validate_relative_path"]
