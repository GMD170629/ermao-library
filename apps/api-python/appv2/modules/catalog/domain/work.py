from __future__ import annotations

import uuid
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Work:
    id: uuid.UUID
    title: str
    author: str | None
    media_type: str
    status: str = "active"

    def rename(self, title: str) -> Work:
        normalized = " ".join(title.split())
        if not normalized:
            raise ValueError("title cannot be empty")
        return replace(self, title=normalized)

    def archive(self) -> Work:
        return replace(self, status="archived")
