"""Compatibility re-export for system health probes (owned by modules.system)."""

from app.bootstrap.system import run_system_health_checks

__all__ = ["run_system_health_checks"]
