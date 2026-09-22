"""Library-root path helpers."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from app.contracts.diagnostics import FailureDiagnostics


class InvalidTargetDirectory(ValueError):
    """The explicitly selected destination violates a directory rule."""


@dataclass(frozen=True)
class DirectoryMountSnapshot:
    resolve: Callable[[PurePath], str | None]
    browse_roots: tuple[Path, ...] | None

    def __call__(self, path: PurePath) -> str | None:
        return self.resolve(path)


class LibraryPathError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def is_inside_path(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        # diagnostics-control-flow: relative_to is the containment predicate; outside paths return False.
        return False


def library_directory_tree_node(
    requested_path: str | None,
    *,
    mount_root_for_path: Callable[[Path], str | None],
    diagnostics: FailureDiagnostics,
    browse_roots: tuple[Path, ...] | None = None,
) -> tuple[dict[str, Any] | None, str | None, int]:
    def rejected(rule: str, message: str, status: int) -> tuple[None, str, int]:
        failure = LibraryPathError(
            rule, status_code=status, code="LIBRARY_DIRECTORY_REJECTED"
        )
        diagnostic = diagnostics.prepare(
            failure,
            event="library.directory.rejected",
            context={"step": "validate_directory"},
        )
        diagnostics.persist(diagnostic)
        return None, message, status

    raw_path = str(requested_path or "").strip()
    if raw_path:
        target = Path(raw_path).expanduser()
        if not target.is_absolute() and not (
            browse_roots is not None and raw_path == "/"
        ):
            return rejected(
                "Requested directory path is not absolute",
                "目录路径必须是绝对路径",
                400,
            )
    else:
        target = Path("/")

    if browse_roots is not None and (
        not raw_path
        or target == Path("/")
        or any(target != root and target in root.parents for root in browse_roots)
    ):
        # A virtual root exposes nested mount points without exposing their
        # unmounted parent directories. It cannot itself be selected.
        return (
            {
                "name": "/",
                "path": "/",
                "readable": False,
                "mountRoot": None,
                "mountedOnly": True,
                "error": None,
                "children": [
                    {
                        "name": str(root),
                        "path": str(root),
                        "readable": os.access(root, os.R_OK),
                        "mountRoot": str(root),
                    }
                    for root in browse_roots
                    if root.is_dir()
                ],
            },
            None,
            200,
        )

    if not target.exists():
        return rejected(
            "Path.exists returned False for the requested directory",
            "路径不存在或不可读",
            404,
        )

    try:
        real_target = target.resolve()
    except (OSError, RuntimeError) as error:
        diagnostic = diagnostics.prepare(
            error,
            event="library.directory.resolve_failed",
            context={"step": "resolve_directory"},
        )
        diagnostics.persist(diagnostic)
        return None, "路径不存在或不可读", 404

    if not real_target.is_dir():
        return rejected(
            "Path.is_dir returned False for the requested directory",
            "书库路径必须是目录",
            400,
        )

    if browse_roots is not None and mount_root_for_path(real_target) is None:
        return rejected(
            "Requested directory is outside the configured browse mounts",
            "路径不存在或不可读",
            404,
        )

    children: list[dict[str, Any]] = []
    readable = os.access(real_target, os.R_OK)
    error: str | None = None
    if readable:
        try:
            for child in sorted(
                real_target.iterdir(), key=lambda item: item.name.lower()
            ):
                try:
                    real_child = child.resolve()
                except (OSError, RuntimeError) as resolution_error:
                    diagnostic = diagnostics.prepare(
                        resolution_error,
                        event="library.directory.child_resolve_failed",
                        context={"step": "resolve_child"},
                    )
                    diagnostics.persist(diagnostic)
                    continue
                if not real_child.is_dir():
                    continue
                if browse_roots is not None and mount_root_for_path(real_child) is None:
                    continue
                children.append(
                    {
                        "name": child.name,
                        "path": str(real_child),
                        "readable": os.access(real_child, os.R_OK),
                        "mountRoot": mount_root_for_path(real_child),
                    }
                )
        except OSError as failure:
            diagnostic = diagnostics.prepare(
                failure,
                event="library.directory.list_failed",
                context={"step": "list_directory"},
            )
            diagnostics.persist(diagnostic)
            readable = False
            error = "目录不可读取"
    else:
        failure = LibraryPathError(
            "os.access(R_OK) returned False for the requested directory",
            status_code=200,
            code="LIBRARY_DIRECTORY_UNREADABLE",
        )
        diagnostic = diagnostics.prepare(
            failure,
            event="library.directory.unreadable",
            context={"step": "check_directory_read_access"},
        )
        diagnostics.persist(diagnostic)
        error = "目录不可读取"

    return (
        {
            "name": real_target.name or str(real_target),
            "path": str(real_target),
            "readable": readable,
            "mountRoot": mount_root_for_path(real_target),
            "mountedOnly": browse_roots is not None,
            "error": error,
            "children": children[:200],
        },
        None,
        200,
    )


def target_directory_from_path(target_path: Any, action_label: str) -> Path:
    raw_path = str(target_path or "").strip()
    if not raw_path:
        raise InvalidTargetDirectory(f"请选择{action_label}目录")
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise InvalidTargetDirectory(f"请选择绝对{action_label}目录")
    try:
        real_target = target.resolve()
    except OSError as error:
        raise InvalidTargetDirectory(f"所选{action_label}目录不存在或不可读") from error
    if not real_target.exists() or not real_target.is_dir():
        raise InvalidTargetDirectory(f"所选{action_label}目录不存在或不可读")
    if not os.access(real_target, os.W_OK):
        raise InvalidTargetDirectory(f"无法写入所选{action_label}目录，请检查 NAS 目录权限。")
    return real_target
