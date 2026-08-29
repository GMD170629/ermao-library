"""Cross-platform shared and exclusive locks for database sidecar files."""

from __future__ import annotations

import sys
from typing import BinaryIO

if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    _LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    _ERROR_LOCK_VIOLATION = 33

    class _Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        )

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock_file_ex = _kernel32.LockFileEx
    _lock_file_ex.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    )
    _lock_file_ex.restype = wintypes.BOOL
    _unlock_file_ex = _kernel32.UnlockFileEx
    _unlock_file_ex.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    )
    _unlock_file_ex.restype = wintypes.BOOL

    def try_file_lock(handle: BinaryIO, *, exclusive: bool) -> bool:
        """Try to lock the first byte without waiting."""

        flags = _LOCKFILE_FAIL_IMMEDIATELY
        if exclusive:
            flags |= _LOCKFILE_EXCLUSIVE_LOCK
        overlapped = _Overlapped()
        os_handle = wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno()))
        if _lock_file_ex(os_handle, flags, 0, 1, 0, ctypes.byref(overlapped)):
            return True
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_LOCK_VIOLATION:
            return False
        raise OSError(error_code, ctypes.FormatError(error_code))

    def unlock_file(handle: BinaryIO) -> None:
        """Unlock the first byte previously locked through this handle."""

        overlapped = _Overlapped()
        os_handle = wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno()))
        if _unlock_file_ex(os_handle, 0, 1, 0, ctypes.byref(overlapped)):
            return
        error_code = ctypes.get_last_error()
        raise OSError(error_code, ctypes.FormatError(error_code))

else:
    import fcntl

    def try_file_lock(handle: BinaryIO, *, exclusive: bool) -> bool:
        """Try to acquire a POSIX advisory lock without waiting."""

        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(handle.fileno(), operation | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock_file(handle: BinaryIO) -> None:
        """Release a POSIX advisory lock."""

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["try_file_lock", "unlock_file"]
