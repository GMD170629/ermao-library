"""Stable application contracts for the Kindle capability."""

from app.modules.kindle.application.commands import (
    KindleUnitOfWork,
    execute_kindle_write,
)

__all__ = ["KindleUnitOfWork", "execute_kindle_write"]
