"""Canonical filesystem identity for journalled file operations."""

import os

from app.contracts.file_operation import FileIdentity


def file_identity(value: os.stat_result) -> FileIdentity:
    return FileIdentity(
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )
