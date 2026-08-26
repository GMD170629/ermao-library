"""Composition root exports for OPDS HTTP dependencies."""

from app.infrastructure.opds_runtime import build_opds_router, get_opds_settings

__all__ = ["build_opds_router", "get_opds_settings"]
