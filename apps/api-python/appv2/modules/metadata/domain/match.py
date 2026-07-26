from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidateScore:
    title: float
    author: float
    identifier: float

    @property
    def total(self) -> float:
        return max(0.0, min(1.0, self.title * 0.6 + self.author * 0.25 + self.identifier * 0.15))
