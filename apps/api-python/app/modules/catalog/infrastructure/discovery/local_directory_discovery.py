"""Read-only, no-follow discovery for one directory at a time."""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NoReturn, Protocol, Self

from app.modules.catalog.application.scan_dto import (
    DiscoveredSource,
    DiscoveryEntryType,
    DiscoveryIssue,
    DiscoveryIssueCode,
    DiscoveryObservation,
)
from app.modules.catalog.application.scan_ports import (
    DirectoryChangedDuringDiscovery,
    DirectoryDiscoveryOperationalError,
    DirectoryIoError,
    DirectoryPermissionDenied,
    DirectoryRootUnavailable,
    InvalidDiscoveryRelativePath,
)
from app.modules.catalog.application.source_admission_ports import (
    SourceStatExpectation,
)

_O_DIRECTORY = int(getattr(os, "O_DIRECTORY", 0))
_O_CLOEXEC = int(getattr(os, "O_CLOEXEC", 0))
_O_NOFOLLOW = int(getattr(os, "O_NOFOLLOW", 0))
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC | _O_NOFOLLOW
_REPARSE_POINT = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
_PLATFORM_SUPPORTED = (
    _O_DIRECTORY != 0
    and _O_NOFOLLOW != 0
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.scandir in os.supports_fd
)
_CHANGED_ERRNOS = {
    errno.ENOENT,
    errno.ENOTDIR,
    errno.ELOOP,
    getattr(errno, "ESTALE", -1),
}
_ROOT_UNAVAILABLE_ERRNOS = _CHANGED_ERRNOS | {errno.ENODEV}


class _DirectoryEntries(Protocol):
    def __next__(self) -> os.DirEntry[str]: ...

    def close(self) -> None: ...


def _identity(source_stat: os.stat_result) -> str:
    return f"{source_stat.st_dev}:{source_stat.st_ino}"


def _identity_signature(source_stat: os.stat_result) -> tuple[int, int, int]:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        stat.S_IFMT(source_stat.st_mode),
    )


def _directory_signature(source_stat: os.stat_result) -> tuple[int, ...]:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        stat.S_IFMT(source_stat.st_mode),
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
    )


def _entry_type(source_stat: os.stat_result) -> DiscoveryEntryType:
    if stat.S_ISLNK(source_stat.st_mode):
        return DiscoveryEntryType.SYMLINK
    attributes = int(getattr(source_stat, "st_file_attributes", 0))
    if attributes & _REPARSE_POINT:
        return DiscoveryEntryType.JUNCTION
    if stat.S_ISDIR(source_stat.st_mode):
        return DiscoveryEntryType.DIRECTORY
    if stat.S_ISREG(source_stat.st_mode):
        return DiscoveryEntryType.FILE
    return DiscoveryEntryType.SPECIAL


def _raise_root_error(error: OSError) -> NoReturn:
    if isinstance(error, PermissionError):
        raise DirectoryPermissionDenied() from error
    if error.errno in _ROOT_UNAVAILABLE_ERRNOS:
        raise DirectoryRootUnavailable() from error
    raise DirectoryIoError() from error


def _raise_directory_error(error: OSError) -> NoReturn:
    if isinstance(error, PermissionError):
        raise DirectoryPermissionDenied() from error
    if error.errno in _CHANGED_ERRNOS:
        raise DirectoryChangedDuringDiscovery() from error
    raise DirectoryIoError() from error


def _canonical_components(canonical_root: str) -> tuple[str, ...]:
    if (
        not isinstance(canonical_root, str)
        or not canonical_root
        or "\x00" in canonical_root
        or not os.path.isabs(canonical_root)
    ):
        raise DirectoryRootUnavailable()
    try:
        canonical_root.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise DirectoryRootUnavailable() from error
    components = tuple(
        component for component in canonical_root.split(os.sep) if component
    )
    rebuilt = os.sep + os.sep.join(components) if components else os.sep
    if rebuilt != canonical_root or any(
        component in {".", ".."} for component in components
    ):
        raise DirectoryRootUnavailable()
    return components


def _valid_relative_component(component: object) -> bool:
    if not isinstance(component, str):
        return False
    try:
        component.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return not (
        not component
        or component in {".", ".."}
        or "\x00" in component
        or "/" in component
        or "\\" in component
        or os.path.isabs(component)
        or (len(component) >= 2 and component[0].isalpha() and component[1] == ":")
    )


def _validate_relative_directory(relative_directory: tuple[str, ...]) -> None:
    if not isinstance(relative_directory, tuple) or any(
        not _valid_relative_component(component) for component in relative_directory
    ):
        raise InvalidDiscoveryRelativePath()


def _open_canonical_root(canonical_root: str) -> tuple[int, os.stat_result]:
    if not _PLATFORM_SUPPORTED:
        raise DirectoryRootUnavailable()
    components = _canonical_components(canonical_root)
    current_fd: int | None = None
    try:
        current_fd = os.open(os.sep, _DIRECTORY_OPEN_FLAGS)
        for component in components:
            path_stat = os.stat(
                component,
                dir_fd=current_fd,
                follow_symlinks=False,
            )
            if _entry_type(path_stat) is not DiscoveryEntryType.DIRECTORY:
                raise DirectoryRootUnavailable()
            next_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            try:
                opened_stat = os.fstat(next_fd)
            except BaseException:
                os.close(next_fd)
                raise
            if _identity_signature(path_stat) != _identity_signature(opened_stat):
                os.close(next_fd)
                raise DirectoryChangedDuringDiscovery()
            os.close(current_fd)
            current_fd = next_fd
        root_stat = os.fstat(current_fd)
        if _entry_type(root_stat) is not DiscoveryEntryType.DIRECTORY:
            raise DirectoryRootUnavailable()
        return current_fd, root_stat
    except DirectoryDiscoveryOperationalError:
        if current_fd is not None:
            os.close(current_fd)
        raise
    except OSError as error:
        if current_fd is not None:
            os.close(current_fd)
        _raise_root_error(error)


@dataclass(frozen=True, slots=True)
class _OpenedDirectory:
    descriptor: int
    initial_stat: os.stat_result
    lineage: tuple[tuple[int, int, int], ...]


class _LocalDirectoryDiscoverySession:
    def __init__(self, canonical_root: str) -> None:
        self._canonical_root = canonical_root
        self._root_fd: int | None = None
        self._root_stat: os.stat_result | None = None
        self._streams: set[_DirectoryObservationIterator] = set()
        self._closed = False

    def __enter__(self) -> Self:
        if self._closed or self._root_fd is not None:
            raise RuntimeError("directory discovery session is not reusable")
        self._root_fd, self._root_stat = _open_canonical_root(self._canonical_root)
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def root_identity(self) -> str:
        root_stat = self._active_root_stat()
        return _identity(root_stat)

    def iter_directory(
        self, relative_directory: tuple[str, ...]
    ) -> Iterator[DiscoveryObservation]:
        _validate_relative_directory(relative_directory)
        opened = self._open_relative_directory(relative_directory)
        try:
            entries = os.scandir(opened.descriptor)
        except OSError as error:
            os.close(opened.descriptor)
            _raise_directory_error(error)
        stream = _DirectoryObservationIterator(
            session=self,
            relative_directory=relative_directory,
            opened=opened,
            entries=entries,
        )
        self._streams.add(stream)
        return stream

    def revalidate_root_identity(self) -> str:
        self._active_root_stat()
        root_fd, root_stat = _open_canonical_root(self._canonical_root)
        try:
            return _identity(root_stat)
        finally:
            os.close(root_fd)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for stream in tuple(self._streams):
            stream.close()
        self._streams.clear()
        if self._root_fd is not None:
            os.close(self._root_fd)
            self._root_fd = None
            self._root_stat = None

    def _active_root_stat(self) -> os.stat_result:
        if self._closed or self._root_fd is None or self._root_stat is None:
            raise RuntimeError("directory discovery session is not active")
        return self._root_stat

    def _active_root_fd(self) -> int:
        self._active_root_stat()
        assert self._root_fd is not None
        return self._root_fd

    def _open_relative_directory(
        self, relative_directory: tuple[str, ...]
    ) -> _OpenedDirectory:
        current_fd: int | None = None
        try:
            current_fd = os.dup(self._active_root_fd())
            current_stat = os.fstat(current_fd)
            lineage = [_identity_signature(current_stat)]
            for component in relative_directory:
                path_stat = os.stat(
                    component,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
                if _entry_type(path_stat) is not DiscoveryEntryType.DIRECTORY:
                    raise DirectoryChangedDuringDiscovery()
                next_fd = os.open(
                    component,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=current_fd,
                )
                try:
                    opened_stat = os.fstat(next_fd)
                except BaseException:
                    os.close(next_fd)
                    raise
                if _identity_signature(path_stat) != _identity_signature(opened_stat):
                    os.close(next_fd)
                    raise DirectoryChangedDuringDiscovery()
                os.close(current_fd)
                current_fd = next_fd
                current_stat = opened_stat
                lineage.append(_identity_signature(opened_stat))
            return _OpenedDirectory(
                descriptor=current_fd,
                initial_stat=current_stat,
                lineage=tuple(lineage),
            )
        except DirectoryDiscoveryOperationalError:
            if current_fd is not None:
                os.close(current_fd)
            raise
        except OSError as error:
            if current_fd is not None:
                os.close(current_fd)
            _raise_directory_error(error)

    def _verify_directory(
        self,
        relative_directory: tuple[str, ...],
        opened: _OpenedDirectory,
    ) -> None:
        try:
            final_stat = os.fstat(opened.descriptor)
        except OSError as error:
            _raise_directory_error(error)
        if _directory_signature(final_stat) != _directory_signature(
            opened.initial_stat
        ):
            raise DirectoryChangedDuringDiscovery()
        rebound = self._open_relative_directory(relative_directory)
        try:
            if rebound.lineage != opened.lineage:
                raise DirectoryChangedDuringDiscovery()
        finally:
            os.close(rebound.descriptor)

    def _forget(self, stream: _DirectoryObservationIterator) -> None:
        self._streams.discard(stream)


class _DirectoryObservationIterator(Iterator[DiscoveryObservation]):
    def __init__(
        self,
        *,
        session: _LocalDirectoryDiscoverySession,
        relative_directory: tuple[str, ...],
        opened: _OpenedDirectory,
        entries: _DirectoryEntries,
    ) -> None:
        self._session = session
        self._relative_directory = relative_directory
        self._opened = opened
        self._entries = entries
        self._closed = False

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> DiscoveryObservation:
        if self._closed:
            raise StopIteration
        try:
            entry = next(self._entries)
        except StopIteration:
            self._finish()
            raise
        except OSError as error:
            self.close()
            _raise_directory_error(error)
        try:
            return self._observation(entry)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._entries.close()
        finally:
            try:
                os.close(self._opened.descriptor)
            finally:
                self._session._forget(self)

    def _finish(self) -> None:
        try:
            self._entries.close()
            self._session._verify_directory(
                self._relative_directory,
                self._opened,
            )
        finally:
            if not self._closed:
                self._closed = True
                try:
                    os.close(self._opened.descriptor)
                finally:
                    self._session._forget(self)

    def _observation(self, entry: os.DirEntry[str]) -> DiscoveryObservation:
        if not _valid_relative_component(entry.name):
            return DiscoveryIssue(
                parent_path=self._relative_directory,
                code=DiscoveryIssueCode.PATH_NAME_UNSUPPORTED,
            )
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError as error:
            _raise_directory_error(error)
        entry_type = _entry_type(entry_stat)
        expected_stat = None
        if entry_type is DiscoveryEntryType.FILE:
            expected_stat = SourceStatExpectation(
                device_id=entry_stat.st_dev,
                file_id=entry_stat.st_ino,
                size_bytes=entry_stat.st_size,
                modified_ns=entry_stat.st_mtime_ns,
            )
        return DiscoveredSource(
            relative_path=(*self._relative_directory, entry.name),
            entry_type=entry_type,
            filesystem_identity=_identity(entry_stat),
            expected_stat=expected_stat,
        )


class LocalDirectoryDiscoveryAdapter:
    """Open a read-only discovery session bound to a canonical library root."""

    def open(self, *, canonical_root: str) -> _LocalDirectoryDiscoverySession:
        return _LocalDirectoryDiscoverySession(canonical_root)


__all__ = ["LocalDirectoryDiscoveryAdapter"]
