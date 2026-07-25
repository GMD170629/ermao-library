from __future__ import annotations

import hashlib
import secrets


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str, secret: str) -> str:
    return hashlib.blake2b(
        token.encode(),
        key=secret.encode(),
        digest_size=32,
    ).hexdigest()
