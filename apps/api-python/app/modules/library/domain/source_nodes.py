"""Pure SourceNode path identity, physical kind, and direct-parent tree rules.

These rules implement ADR 0018 LibrarySourceNode identity without ORM, FastAPI,
filesystem access, or OS path normalization.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class SourceNodePhysicalKind(str, Enum):
    REGULAR_FILE = "REGULAR_FILE"
    DIRECTORY = "DIRECTORY"
    SYMLINK = "SYMLINK"
    OTHER = "OTHER"


class SourceNodeViolationCode(str, Enum):
    INVALID_RELATIVE_PATH = "INVALID_RELATIVE_PATH"
    PATH_KEY_COLLISION = "PATH_KEY_COLLISION"
    CROSS_LIBRARY_PARENT = "CROSS_LIBRARY_PARENT"
    PARENT_NOT_DIRECTORY = "PARENT_NOT_DIRECTORY"
    PARENT_PATH_MISMATCH = "PARENT_PATH_MISMATCH"
    SELF_PARENT = "SELF_PARENT"


class InvalidSourceNodeRelativePathError(Exception):
    """Programmer error: constructed SourceNodeRelativePath with an illegal path."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.code = SourceNodeViolationCode.INVALID_RELATIVE_PATH
        super().__init__(
            f"invalid library-relative path: {relative_path!r}"
        )


@dataclass(frozen=True, slots=True)
class SourceNodeViolation:
    code: SourceNodeViolationCode
    relative_path: str


@dataclass(frozen=True, slots=True)
class SourceNodeRelativePath:
    """Validated Library-relative path slot preserved exactly as supplied."""

    value: str

    def __post_init__(self) -> None:
        if not _is_valid_library_relative_path(self.value):
            raise InvalidSourceNodeRelativePathError(self.value)

    @property
    def name(self) -> str:
        return self.value.rsplit("/", 1)[-1]

    @property
    def parent_relative_path(self) -> str | None:
        if "/" not in self.value:
            return None
        return self.value.rsplit("/", 1)[0]

    @property
    def path_key(self) -> str:
        digest = hashlib.sha256(self.value.encode("utf-8")).hexdigest()
        return f"v1:{digest}"

    @property
    def is_root_child(self) -> bool:
        return self.parent_relative_path is None


@dataclass(frozen=True, slots=True)
class SourceNodeTreeNode:
    """Minimal node facts required to check direct-parent tree invariants."""

    library_id: str
    relative_path: SourceNodeRelativePath
    physical_kind: SourceNodePhysicalKind


_DRIVE_PREFIX_LENGTH = 2
_FORBIDDEN_SEGMENTS = frozenset({"", ".", ".."})


def parse_source_node_relative_path(
    relative_path: str,
) -> SourceNodeRelativePath | SourceNodeViolation:
    """Validate and wrap a Library-relative path without normalizing spelling."""

    try:
        return SourceNodeRelativePath(relative_path)
    except InvalidSourceNodeRelativePathError as error:
        return SourceNodeViolation(
            code=error.code,
            relative_path=error.relative_path,
        )


def validate_source_node_direct_parent(
    *,
    node: SourceNodeTreeNode,
    parent: SourceNodeTreeNode | None,
) -> tuple[SourceNodeViolation, ...]:
    """Validate the direct parent link for one SourceNode."""

    expected_parent_path = node.relative_path.parent_relative_path
    path = node.relative_path.value

    if parent is None:
        if expected_parent_path is not None:
            return (
                SourceNodeViolation(
                    code=SourceNodeViolationCode.PARENT_PATH_MISMATCH,
                    relative_path=path,
                ),
            )
        return ()

    if (
        parent.library_id == node.library_id
        and parent.relative_path.value == node.relative_path.value
    ):
        return (
            SourceNodeViolation(
                code=SourceNodeViolationCode.SELF_PARENT,
                relative_path=path,
            ),
        )

    if parent.library_id != node.library_id:
        return (
            SourceNodeViolation(
                code=SourceNodeViolationCode.CROSS_LIBRARY_PARENT,
                relative_path=path,
            ),
        )

    if parent.physical_kind is not SourceNodePhysicalKind.DIRECTORY:
        return (
            SourceNodeViolation(
                code=SourceNodeViolationCode.PARENT_NOT_DIRECTORY,
                relative_path=path,
            ),
        )

    parent_path = parent.relative_path.value
    if expected_parent_path is None or parent_path != expected_parent_path:
        return (
            SourceNodeViolation(
                code=SourceNodeViolationCode.PARENT_PATH_MISMATCH,
                relative_path=path,
            ),
        )

    return ()


def evaluate_path_key_occupancy(
    *,
    occupied_relative_path: SourceNodeRelativePath,
    candidate_relative_path: SourceNodeRelativePath,
) -> SourceNodeViolation | None:
    """Decide occupancy for an already-matched ``(libraryId, pathKey)`` slot.

    Callers must only invoke this when the candidate pathKey equals the occupied
    pathKey within the same library. Identical original paths are idempotent;
    any other original path is a digest collision.
    """

    if occupied_relative_path.value == candidate_relative_path.value:
        return None
    return SourceNodeViolation(
        code=SourceNodeViolationCode.PATH_KEY_COLLISION,
        relative_path=candidate_relative_path.value,
    )


def _is_valid_library_relative_path(relative_path: str) -> bool:
    if relative_path == "" or "\x00" in relative_path:
        return False
    if relative_path.startswith("/"):
        return False
    if _is_windows_unc_form(relative_path):
        return False
    if _has_windows_drive_prefix(relative_path):
        return False
    segments = relative_path.split("/")
    if any(segment in _FORBIDDEN_SEGMENTS for segment in segments):
        return False
    return True


def _is_windows_unc_form(relative_path: str) -> bool:
    return relative_path.startswith("//") or relative_path.startswith("\\\\")


def _has_windows_drive_prefix(relative_path: str) -> bool:
    return (
        len(relative_path) >= _DRIVE_PREFIX_LENGTH
        and relative_path[0].isascii()
        and relative_path[0].isalpha()
        and relative_path[1] == ":"
    )
