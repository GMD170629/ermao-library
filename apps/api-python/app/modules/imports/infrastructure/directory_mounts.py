"""Read visible Linux mounts without exposing host filesystem paths."""

import logging
import os
import re
from pathlib import Path, PurePath, PurePosixPath

from app.core.exception_diagnostics import record_exception
from app.modules.imports.application.library_paths import DirectoryMountSnapshot

_SYSTEM_FILESYSTEMS = frozenset({
    "proc", "sysfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
    "securityfs", "debugfs", "tracefs", "configfs", "pstore", "mqueue",
    "hugetlbfs", "fusectl", "rpc_pipefs", "binfmt_misc",
})


def directory_mount_resolver(
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
    *,
    containerized: bool | None = None,
) -> DirectoryMountSnapshot:
    # One snapshot per directory request, including bind mounts on the same device.
    mounts: dict[PurePosixPath, bool] = {}
    try:
        content = mountinfo_path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        # diagnostics-control-flow: Linux mount metadata is an optional capability probe on other hosts.
        content = ""  # Mount metadata is optional on non-Linux/restricted hosts.
    for line in content.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError as error:
            record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.directory_mounts.directory_mount_resolver.failed", error,
                             context={"step": "directory_mount_resolver"})
            continue
        if separator < 6 or len(fields) < separator + 4:
            continue
        point = PurePosixPath(re.sub(
            r"\\(040|011|012|134)",
            lambda match: chr(int(match.group(1), 8)),
            fields[4],
        ))
        if not point.is_absolute():
            continue
        mounts[point] = (
            point != PurePosixPath("/")
            and fields[separator + 1] not in _SYSTEM_FILESYSTEMS
            and not any(point.is_relative_to(root) for root in ("/proc", "/sys", "/dev"))
        )
    ordered = sorted(mounts.items(), key=lambda item: len(item[0].parts), reverse=True)

    def resolve(path: PurePath) -> str | None:
        target = PurePosixPath(path.as_posix())
        for point, is_data in ordered:
            if target.is_relative_to(point):
                return str(point) if is_data else None
        return None

    if containerized is None:
        containerized = os.environ.get("SHUKU_CONTAINER") == "1" or Path("/.dockerenv").is_file()
    roots = tuple(sorted(
        (Path(str(point)) for point, is_data in mounts.items() if is_data),
        key=str,
    )) if containerized else None
    return DirectoryMountSnapshot(resolve=resolve, browse_roots=roots)
