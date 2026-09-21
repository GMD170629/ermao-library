"""File identity and safe error codes shared by moves and metadata replacement."""

from dataclasses import dataclass


class FileOperationError(ValueError):
    """Stable operation error without private filesystem diagnostics."""


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    link_count: int
