"""Password hashing adapter for the current authentication boundary."""

from __future__ import annotations

import hashlib
from secrets import token_hex

from app.modules.auth.application.first_admin import PasswordHasher


class ScryptPasswordHasher(PasswordHasher):
    def hash(self, password: str) -> str:
        salt = token_hex(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=16_384,
            r=8,
            p=1,
            dklen=64,
        ).hex()
        return f"{salt}:{digest}"
