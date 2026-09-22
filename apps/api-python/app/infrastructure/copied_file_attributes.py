"""Best-effort attribute preservation; content publication owns success checks."""

import ctypes
import errno
import logging
import os
import stat
import sys
from dataclasses import dataclass

from app.contracts.file_operation import FileOperationError
from app.core.exception_diagnostics import record_exception

MAX_ATTRIBUTE_BYTES = 2 * 1024 * 1024


def _system_call_failure(number: int) -> OSError:
    # A failing libc operation without errno must never be reported as Success.
    return OSError(number, os.strerror(number)) if number else OSError("System call failed; errno not provided")



@dataclass(frozen=True)
class CopiedFileAttributes:
    uid: int
    gid: int
    mode: int
    mtime_ns: int
    flags: int
    attributes: tuple[tuple[str, bytes], ...]
    acl: bytes | None


def _get_attribute(descriptor: int, name: str) -> bytes:
    library = ctypes.CDLL(None, use_errno=True)
    getter = library.fgetxattr
    getter.restype = ctypes.c_ssize_t
    arguments: list[object] = [descriptor, os.fsencode(name)]
    if sys.platform == "darwin":
        getter.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        suffix: list[object] = [0, 0]
    elif sys.platform.startswith("linux"):
        getter.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        suffix = []
    else:
        raise FileOperationError("COPY_ATTRIBUTES_UNSUPPORTED")
    size = getter(*arguments, None, 0, *suffix)
    if size < 0:
        number = ctypes.get_errno()
        raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE") from _system_call_failure(number)
    if size > MAX_ATTRIBUTE_BYTES:
        raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
    buffer = ctypes.create_string_buffer(size)
    observed = getter(*arguments, buffer, size, *suffix)
    if observed < 0:
        number = ctypes.get_errno()
        raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE") from _system_call_failure(number)
    if observed != size:
        raise FileOperationError("SOURCE_ATTRIBUTES_CHANGED")
    return buffer.raw


def _list_attributes(descriptor: int) -> tuple[str, ...]:
    library = ctypes.CDLL(None, use_errno=True)
    function = library.flistxattr
    function.restype = ctypes.c_ssize_t
    if sys.platform == "darwin":
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        suffix: list[int] = [0]
    else:
        function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        suffix = []
    size = function(descriptor, None, 0, *suffix)
    if size < 0:
        number = ctypes.get_errno()
        raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE") from _system_call_failure(number)
    if size > MAX_ATTRIBUTE_BYTES:
        raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
    buffer = ctypes.create_string_buffer(size)
    observed = function(descriptor, buffer, size, *suffix)
    if observed < 0:
        number = ctypes.get_errno()
        raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE") from _system_call_failure(number)
    if observed != size:
        raise FileOperationError("SOURCE_ATTRIBUTES_CHANGED")
    return tuple(sorted(os.fsdecode(name) for name in buffer.raw.split(b"\0") if name))


def _set_attribute(descriptor: int, name: str, value: bytes | None) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if value is None:
        remover = library.fremovexattr
        remover.restype = ctypes.c_int
        if sys.platform == "darwin":
            remover.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
            result = remover(descriptor, os.fsencode(name), 0)
        else:
            remover.argtypes = [ctypes.c_int, ctypes.c_char_p]
            result = remover(descriptor, os.fsencode(name))
    else:
        setter = library.fsetxattr
        setter.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(value)
        if sys.platform == "darwin":
            setter.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_uint32,
                ctypes.c_int,
            ]
            result = setter(descriptor, os.fsencode(name), buffer, len(value), 0, 0)
        else:
            setter.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_int,
            ]
            result = setter(descriptor, os.fsencode(name), buffer, len(value), 0)
    if result != 0:
        number = ctypes.get_errno()
        raise FileOperationError("COPY_ATTRIBUTES_UNSUPPORTED") from _system_call_failure(number)


def _darwin_acl(descriptor: int, replacement: bytes | None = None) -> bytes:
    library = ctypes.CDLL(None, use_errno=True)
    library.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    library.acl_get_fd_np.restype = ctypes.c_void_p
    library.acl_free.argtypes = [ctypes.c_void_p]
    library.acl_free.restype = ctypes.c_int
    library.acl_size.argtypes = [ctypes.c_void_p]
    library.acl_size.restype = ctypes.c_ssize_t
    library.acl_copy_ext.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t]
    library.acl_copy_ext.restype = ctypes.c_ssize_t
    if replacement is not None:
        library.acl_copy_int.argtypes = [ctypes.c_void_p]
        library.acl_copy_int.restype = ctypes.c_void_p
        library.acl_set_fd_np.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        library.acl_set_fd_np.restype = ctypes.c_int
        encoded = ctypes.create_string_buffer(replacement)
        acl = library.acl_copy_int(encoded)
        if not acl:
            number = ctypes.get_errno()
            raise FileOperationError("COPY_ACL_UNAVAILABLE") from _system_call_failure(number)
        try:
            if library.acl_set_fd_np(descriptor, acl, 0x100) != 0:
                number = ctypes.get_errno()
                raise FileOperationError("COPY_ACL_UNSUPPORTED") from _system_call_failure(number)
        finally:
            if library.acl_free(acl) != 0:
                number = ctypes.get_errno()
                record_exception(logging.getLogger(__name__), "file_attributes.acl_free_failed", _system_call_failure(number), context={"step": "free_acl"})
    acl = library.acl_get_fd_np(descriptor, 0x100)
    if not acl and ctypes.get_errno() == errno.ENOENT:
        # Darwin reports absent extended ACLs as ENOENT for an otherwise valid FD.
        # Canonicalize absence to an empty ACL so inherited target ACLs are cleared.
        library.acl_init.argtypes = [ctypes.c_int]
        library.acl_init.restype = ctypes.c_void_p
        acl = library.acl_init(0)
    if not acl:
        number = ctypes.get_errno()
        raise FileOperationError("COPY_ACL_UNAVAILABLE") from _system_call_failure(number)
    try:
        size = library.acl_size(acl)
        if size < 0:
            number = ctypes.get_errno()
            raise FileOperationError("COPY_ACL_UNAVAILABLE") from _system_call_failure(number)
        if size > MAX_ATTRIBUTE_BYTES:
            raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
        buffer = ctypes.create_string_buffer(size)
        count = library.acl_copy_ext(buffer, acl, size)
        if count < 0:
            number = ctypes.get_errno()
            raise FileOperationError("COPY_ACL_UNAVAILABLE") from _system_call_failure(number)
        if count > size:
            raise FileOperationError("COPY_ACL_UNAVAILABLE") from ValueError(f"acl_copy_ext returned {count} bytes for {size}-byte buffer")
        return buffer.raw[:count]
    finally:
        if library.acl_free(acl) != 0:
            number = ctypes.get_errno()
            record_exception(logging.getLogger(__name__), "file_attributes.acl_free_failed", _system_call_failure(number), context={"step": "free_acl"})


def read_copy_attributes(descriptor: int) -> CopiedFileAttributes | None:
    # Descriptor identity remains mandatory at the publication/copy boundary.
    try:
        value = os.fstat(descriptor)
    except OSError as error:
        record_exception(logging.getLogger(__name__), "infrastructure.copied_file_attributes.read_copy_attributes.failed", error,
                         context={"step": "read_copy_attributes"})
        return None
    attributes: list[tuple[str, bytes]] = []
    total = 0
    names: tuple[str, ...] = ()
    try:
        names = _list_attributes(descriptor)
    except (OSError, FileOperationError) as error:
        record_exception(logging.getLogger(__name__), "file_attributes.list_xattrs_failed", error, context={"step": "list_xattrs"})
    for name in names:
        # A protected or disappearing attribute must not prevent other copies.
        try:
            data = _get_attribute(descriptor, name)
            if total + len(data) <= MAX_ATTRIBUTE_BYTES:
                total += len(data)
                attributes.append((name, data))
        except (OSError, FileOperationError) as error:
            record_exception(logging.getLogger(__name__), "file_attributes.get_xattr_failed", error, context={"step": "get_xattr"})
    acl = None
    if sys.platform == "darwin":
        try:
            acl = _darwin_acl(descriptor)
        except (OSError, FileOperationError) as error:
            record_exception(logging.getLogger(__name__), "file_attributes.read_acl_failed", error, context={"step": "read_acl"})
    return CopiedFileAttributes(
        value.st_uid,
        value.st_gid,
        stat.S_IMODE(value.st_mode),
        value.st_mtime_ns,
        getattr(value, "st_flags", 0),
        tuple(attributes),
        acl,
    )


def apply_copy_attributes(
    descriptor: int, expected: CopiedFileAttributes | None
) -> None:
    """Attempt each attribute independently, without read-back equality gates.

    Attribute failures are optional here only; callers still verify content,
    source identity, persistence and publication. Do not remove destination
    xattrs because the source snapshot may omit unreadable attributes.
    """
    if expected is None:
        return
    try:
        observed = os.fstat(descriptor)
        if (observed.st_uid, observed.st_gid) != (expected.uid, expected.gid):
            os.fchown(descriptor, expected.uid, expected.gid)
    except (OSError) as error:
        record_exception(logging.getLogger(__name__), "file_attributes.set_owner_failed", error, context={"step": "set_owner"})
    try:
        os.fchmod(descriptor, expected.mode)
    except (OSError) as error:
        record_exception(logging.getLogger(__name__), "file_attributes.set_mode_failed", error, context={"step": "set_mode"})
    for name, value in expected.attributes:
        try:
            _set_attribute(descriptor, name, value)
        except (OSError, FileOperationError) as error:
            record_exception(logging.getLogger(__name__), "file_attributes.set_xattr_failed", error, context={"step": "set_xattr"})
    if expected.acl is not None:
        try:
            _darwin_acl(descriptor, expected.acl)
        except (OSError, FileOperationError) as error:
            record_exception(logging.getLogger(__name__), "file_attributes.set_acl_failed", error, context={"step": "set_acl"})
    # Set time before flags, which can make a file immutable on Darwin.
    try:
        observed = os.fstat(descriptor)
        os.utime(descriptor, ns=(observed.st_atime_ns, expected.mtime_ns))
    except (OSError) as error:
        record_exception(logging.getLogger(__name__), "file_attributes.set_timestamps_failed", error, context={"step": "set_timestamps"})
    if sys.platform == "darwin":
        try:
            library = ctypes.CDLL(None, use_errno=True)
            library.fchflags.argtypes = [ctypes.c_int, ctypes.c_uint]
            library.fchflags.restype = ctypes.c_int
            if library.fchflags(descriptor, expected.flags) != 0:
                number = ctypes.get_errno()
                raise _system_call_failure(number)
        except (OSError) as error:
            record_exception(logging.getLogger(__name__), "file_attributes.set_flags_failed", error, context={"step": "set_flags"})
