from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ImportJob:
    id: uuid.UUID
    source_path: str
    status: str
    attempt: int
    next_attempt_at: datetime

    def claim(self) -> ImportJob:
        if self.status not in {"queued", "retry"}:
            raise ValueError("only queued jobs can be claimed")
        return replace(self, status="running", attempt=self.attempt + 1)
