"""Pure library ACL values and grant policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.catalog.domain.errors import (
    FinalAdministratorRequired,
    InvalidGrantLevel,
    ScopeEpochInvalid,
)

MAX_SCOPE_EPOCH = (1 << 63) - 1


class GrantLevel(StrEnum):
    READ = "READ"
    CURATE = "CURATE"
    ADMIN = "ADMIN"

    @property
    def rank(self) -> int:
        return {GrantLevel.READ: 1, GrantLevel.CURATE: 2, GrantLevel.ADMIN: 3}[self]

    @classmethod
    def parse(cls, value: object) -> GrantLevel:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().upper())
        except ValueError as exc:
            raise InvalidGrantLevel() from exc


@dataclass(frozen=True, slots=True)
class LibraryGrant:
    user_id: str
    library_id: str
    level: GrantLevel
    scope_epoch: int

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.library_id.strip():
            raise InvalidGrantLevel("empty identifier")
        if isinstance(self.scope_epoch, bool) or not (
            1 <= self.scope_epoch <= MAX_SCOPE_EPOCH
        ):
            raise ScopeEpochInvalid()


def grant_allows(actual: LibraryGrant | None, required: GrantLevel) -> bool:
    return actual is not None and actual.level.rank >= required.rank


def ensure_not_last_administrator(
    *, target: LibraryGrant, active_administrator_count: int
) -> None:
    if target.level is GrantLevel.ADMIN and active_administrator_count <= 1:
        raise FinalAdministratorRequired()
