"""Preserve and verify ownership, mode, xattrs and Darwin ACLs on staged copies."""

import ctypes
import errno
import os
import stat
import sys
from dataclasses import dataclass

from app.contracts.file_operation import FileOperationError

MAX_ATTRIBUTE_BYTES = 2 * 1024 * 1024


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
        raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE")
    if size > MAX_ATTRIBUTE_BYTES:
        raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
    buffer = ctypes.create_string_buffer(size)
    observed = getter(*arguments, buffer, size, *suffix)
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
        raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE")
    if size > MAX_ATTRIBUTE_BYTES:
        raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
    buffer = ctypes.create_string_buffer(size)
    if function(descriptor, buffer, size, *suffix) != size:
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
        raise FileOperationError("COPY_ATTRIBUTES_UNSUPPORTED")


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
            raise FileOperationError("COPY_ACL_UNAVAILABLE")
        try:
            if library.acl_set_fd_np(descriptor, acl, 0x100) != 0:
                raise FileOperationError("COPY_ACL_UNSUPPORTED")
        finally:
            library.acl_free(acl)
    acl = library.acl_get_fd_np(descriptor, 0x100)
    if not acl and ctypes.get_errno() == errno.ENOENT:
        # Darwin reports absent extended ACLs as ENOENT for an otherwise valid FD.
        # Canonicalize absence to an empty ACL so inherited target ACLs are cleared.
        library.acl_init.argtypes = [ctypes.c_int]
        library.acl_init.restype = ctypes.c_void_p
        acl = library.acl_init(0)
    if not acl:
        raise FileOperationError("COPY_ACL_UNAVAILABLE")
    try:
        size = library.acl_size(acl)
        if not 0 <= size <= MAX_ATTRIBUTE_BYTES:
            raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
        buffer = ctypes.create_string_buffer(size)
        count = library.acl_copy_ext(buffer, acl, size)
        if count < 0 or count > size:
            raise FileOperationError("COPY_ACL_UNAVAILABLE")
        return buffer.raw[:count]
    finally:
        library.acl_free(acl)


def read_copy_attributes(descriptor: int) -> CopiedFileAttributes:
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise FileOperationError("COPY_ATTRIBUTES_UNSUPPORTED")
    value = os.fstat(descriptor)
    attributes: list[tuple[str, bytes]] = []
    total = 0
    for name in _list_attributes(descriptor):
        data = _get_attribute(descriptor, name)
        total += len(data)
        if total > MAX_ATTRIBUTE_BYTES:
            raise FileOperationError("COPY_ATTRIBUTE_LIMIT")
        attributes.append((name, data))
    return CopiedFileAttributes(
        value.st_uid,
        value.st_gid,
        stat.S_IMODE(value.st_mode),
        value.st_mtime_ns,
        getattr(value, "st_flags", 0),
        tuple(attributes),
        _darwin_acl(descriptor) if sys.platform == "darwin" else None,
    )


def apply_copy_attributes(descriptor: int, expected: CopiedFileAttributes) -> None:
    observed = os.fstat(descriptor)
    if (observed.st_uid, observed.st_gid) != (expected.uid, expected.gid):
        os.fchown(descriptor, expected.uid, expected.gid)
    os.fchmod(descriptor, expected.mode)
    wanted = dict(expected.attributes)
    for name in _list_attributes(descriptor):
        if name not in wanted:
            _set_attribute(descriptor, name, None)
    for name, value in expected.attributes:
        _set_attribute(descriptor, name, value)
    if expected.acl is not None:
        _darwin_acl(descriptor, expected.acl)
    if expected.flags:
        if sys.platform != "darwin":
            raise FileOperationError("COPY_FLAGS_UNSUPPORTED")
        library = ctypes.CDLL(None, use_errno=True)
        library.fchflags.argtypes = [ctypes.c_int, ctypes.c_uint]
        library.fchflags.restype = ctypes.c_int
        if library.fchflags(descriptor, expected.flags) != 0:
            raise FileOperationError("COPY_FLAGS_UNSUPPORTED")
    os.utime(descriptor, ns=(observed.st_atime_ns, expected.mtime_ns))
    if read_copy_attributes(descriptor) != expected:
        raise FileOperationError("COPY_ATTRIBUTES_NOT_PRESERVED")
