from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ExternalSource:
    id: uuid.UUID
    name: str
    base_url: str
    enabled: bool

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source URL must use HTTP or HTTPS")
