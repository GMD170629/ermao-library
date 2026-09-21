"""Detect the fixed deployment and read its build-time environment outside runtime."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..application.models import Environment

FIXED_ENVIRONMENT = Path("/opt/shuku-launcher/environment.json")


def fixed_environment(storage: Path) -> Environment | None:
    # Fixed build metadata is outside the application directory being updated.
    fixed = FIXED_ENVIRONMENT
    runtime = storage / "runtime"
    if (
        sys.platform != "linux"
        or not fixed.is_file()
        or fixed.is_symlink()
        or not (fixed.parent / "container_install.py").is_file()
        or runtime.is_symlink()
        or Path(__file__).resolve().parents[4] != runtime.resolve() / "apps/api-python"
    ):
        return None
    import fcntl

    try:
        with (storage / "update-tmp/launcher.lock").open("r") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return Environment.model_validate(
                    json.loads(fixed.read_bytes())["environment"]
                )
    except (OSError, ValueError, KeyError):
        return None
    return None


def fixed_protocol() -> int:
    try:
        value = json.loads(FIXED_ENVIRONMENT.read_bytes())["inventory"][
            "launcher_protocol"
        ]
        return 2 if value == 2 else 1
    except (OSError, ValueError, KeyError):
        return 1


def fixed_install_protocol() -> int:
    """D1/D2 protocol metadata alone does not advertise the D3 executor."""
    if fixed_protocol() != 2:
        return 1
    return (
        2
        if all(
            (FIXED_ENVIRONMENT.parent / name).is_file()
            and not (FIXED_ENVIRONMENT.parent / name).is_symlink()
            for name in ("dependency_install.py", "shuku_dependencies/installed.py")
        )
        else 0
    )
