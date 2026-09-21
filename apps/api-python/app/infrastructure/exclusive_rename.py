"""Descriptor-relative exclusive rename for durable file publication."""

import ctypes
import errno
import os
import sys

from app.contracts.file_operation import FileOperationError


def exclusive_rename(
    source_fd: int, source: str, destination_fd: int, destination: str
) -> None:
    """No fallback to overwrite-capable rename, even on unsupported mounts.

    Linux: https://man7.org/linux/man-pages/man2/rename.2.html
    Darwin: renameatx_np RENAME_EXCL, defined as 0x00000004 in stdio.h.
    """
    if any(
        name in ("", ".", "..") or "/" in name or "\\" in name or "\x00" in name
        for name in (source, destination)
    ):
        raise FileOperationError("INVALID_FILE_NAME")
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        flag = 4
    elif sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        flag = 1
    else:
        raise FileOperationError("EXCLUSIVE_RENAME_UNSUPPORTED")
    if function is None:
        raise FileOperationError("EXCLUSIVE_RENAME_UNSUPPORTED")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if (
        function(
            source_fd,
            os.fsencode(source),
            destination_fd,
            os.fsencode(destination),
            flag,
        )
        != 0
    ):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileOperationError("DESTINATION_EXISTS")
        if code in (errno.ENOSYS, errno.ENOTSUP, errno.EINVAL):
            raise FileOperationError("EXCLUSIVE_RENAME_UNSUPPORTED")
        raise FileOperationError("FILE_PUBLISH_FAILED") from OSError(
            code, os.strerror(code)
        )
