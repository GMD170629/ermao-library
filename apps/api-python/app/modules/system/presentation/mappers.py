"""System event HTTP projection re-exports."""

from app.modules.system.application.projections import serialize_system_event

__all__ = ["serialize_system_event"]
