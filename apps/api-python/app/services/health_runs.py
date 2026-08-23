"""Stable service facade for health runs (owned by modules.system)."""

from app.bootstrap.system import (
    create_or_reuse_health_run,
    fail_abandoned_health_runs,
    health_run_snapshot,
    prune_old_health_runs,
    start_health_run,
)

__all__ = [
    "create_or_reuse_health_run",
    "fail_abandoned_health_runs",
    "health_run_snapshot",
    "prune_old_health_runs",
    "start_health_run",
]
