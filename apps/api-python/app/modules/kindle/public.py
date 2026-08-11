"""Stable application contracts for the Kindle capability."""

from app.modules.kindle.application.commands import (
    KindleUnitOfWork,
    KindleWriteTransaction,
)

__all__ = ["KindleUnitOfWork", "KindleWriteTransaction"]
