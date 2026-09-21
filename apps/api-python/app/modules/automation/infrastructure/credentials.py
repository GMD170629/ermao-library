"""Opaque 256-bit secrets; persist only their SHA-256 digests."""

import hashlib
import re
import secrets
from uuid import uuid4

from app.modules.automation.application.grants import IssuedCredential

_TOKEN = re.compile(r"ermao_mcp_[A-Za-z0-9_-]{43}\Z")


class AutomationCredentials:
    def issue(self) -> IssuedCredential:
        token = f"ermao_mcp_{secrets.token_urlsafe(32)}"
        return IssuedCredential(
            grant_id=f"grant_{uuid4().hex}",
            token=token,
            digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
        )

    def digest(self, token: str) -> str | None:
        if not _TOKEN.fullmatch(token):
            return None
        return hashlib.sha256(token.encode("ascii")).hexdigest()
