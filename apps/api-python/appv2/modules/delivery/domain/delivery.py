from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Delivery:
    status: str
    attempt: int

    def retry(self, max_attempts: int = 5) -> Delivery:
        if self.status not in {"failed", "cancelled"}:
            raise ValueError("only failed or cancelled deliveries can be retried")
        if self.attempt >= max_attempts:
            raise ValueError("delivery exhausted retry attempts")
        return replace(self, status="queued")
