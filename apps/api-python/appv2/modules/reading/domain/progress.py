from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReadingProgress:
    position: dict[str, object]
    percentage: float
    version: int
    updated_at: datetime

    def advance(
        self,
        *,
        position: dict[str, object],
        percentage: float,
        occurred_at: datetime,
        expected_version: int | None,
    ) -> ReadingProgress:
        if not 0 <= percentage <= 1:
            raise ValueError("percentage must be between 0 and 1")
        if expected_version is not None and expected_version != self.version:
            raise ValueError("progress version conflict")
        if occurred_at < self.updated_at:
            return self
        return replace(
            self,
            position=position,
            percentage=percentage,
            version=self.version + 1,
            updated_at=occurred_at,
        )
