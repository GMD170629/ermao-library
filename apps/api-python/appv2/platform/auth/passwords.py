from __future__ import annotations

import base64
import hashlib
import hmac
import os


class PasswordHasher:
    _algorithm = "scrypt"
    _n = 2**15
    _r = 8
    _p = 1
    _length = 64
    _max_memory = 64 * 1024 * 1024

    def hash(self, password: str) -> str:
        self._validate(password)
        salt = os.urandom(16)
        digest = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=self._n,
            r=self._r,
            p=self._p,
            dklen=self._length,
            maxmem=self._max_memory,
        )
        return "$".join(
            (
                self._algorithm,
                str(self._n),
                str(self._r),
                str(self._p),
                base64.urlsafe_b64encode(salt).decode(),
                base64.urlsafe_b64encode(digest).decode(),
            )
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt, expected = encoded.split("$", 5)
            if algorithm != self._algorithm:
                return False
            digest = hashlib.scrypt(
                password.encode(),
                salt=base64.urlsafe_b64decode(salt),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=self._length,
                maxmem=self._max_memory,
            )
            return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _validate(password: str) -> None:
        if len(password) < 10:
            raise ValueError("password must contain at least 10 characters")
        if len(password.encode()) > 1024:
            raise ValueError("password is too long")
