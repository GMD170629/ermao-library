from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class User:
    id: uuid.UUID
    email: str
    display_name: str
    role: str

    @staticmethod
    def normalize_email(value: str) -> str:
        email = value.strip().casefold()
        if not _EMAIL.fullmatch(email):
            raise ValueError("invalid email address")
        return email

    @staticmethod
    def normalize_display_name(value: str) -> str:
        name = " ".join(value.split())
        if not 1 <= len(name) <= 80:
            raise ValueError("display name must contain 1 to 80 characters")
        return name
