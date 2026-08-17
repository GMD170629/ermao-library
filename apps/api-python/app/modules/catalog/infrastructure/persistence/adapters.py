"""Small runtime adapters used to compose current Catalog commands."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.catalog.application.ports import (
    Clock,
    IdGenerator,
    ScopeEpochGenerator,
)
from app.modules.catalog.domain.errors import ScopeEpochExhausted


class UtcClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator(IdGenerator):
    def new_id(self) -> str:
        return f"catalog_{uuid4().hex}"


class SecureScopeEpochGenerator(ScopeEpochGenerator):
    """Opaque positive scope epoch source for command wiring.

    Callers persist the generated value in the same UoW as the grant mutation.
    The value is intentionally not derived from wall-clock time or process
    state.
    """

    def next_scope_epoch(self) -> int:
        candidate = secrets.randbelow((1 << 63) - 1) + 1
        if not 1 <= candidate <= (1 << 63) - 1:
            raise ScopeEpochExhausted()
        return candidate


__all__ = [
    "SecureScopeEpochGenerator",
    "UtcClock",
    "UuidIdGenerator",
]
