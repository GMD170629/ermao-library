"""Authenticated grant secrets with an independently persisted, immutable key."""

import base64
import binascii
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.automation.domain.access import AutomationAccessError


class AutomationTokenVault:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._key_path = directory / "automation-token.key"

    def _read_key(self) -> bytes:
        before = self._key_path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise AutomationAccessError("TOKEN_KEY_INVALID")
        fd = os.open(self._key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            key = stream.read(33)
            after = self._key_path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or not stat.S_ISREG(after.st_mode)
                or not os.path.samestat(before, info)
                or not os.path.samestat(after, info)
                or len(key) != 32
            ):
                raise AutomationAccessError("TOKEN_KEY_INVALID")
            return key

    def _key(self, *, initialize: bool) -> bytes:
        try:
            try:
                return self._read_key()
            except FileNotFoundError as error:
                # diagnostics-control-flow: Only an explicitly authorized first initialization may create the absent key; decrypt/non-initializing calls preserve FileNotFoundError as their cause, covered by immutable-key tests.
                if not initialize:
                    raise AutomationAccessError("TOKEN_KEY_UNAVAILABLE") from error
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=".automation-key-", dir=self._directory
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(os.urandom(32))
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, self._key_path)
                except FileExistsError:
                    # diagnostics-control-flow: A concurrent first issuer already published the authoritative immutable key; tested by concurrent key creation.
                    pass  # A concurrent first issuer published the authoritative key.
                # Windows does not expose directory handles through os.open.
                # The key file itself is flushed on every supported platform.
                if sys.platform != "win32":
                    directory_fd = os.open(self._directory, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                os.unlink(temporary)
            return self._read_key()
        except OSError as error:
            raise AutomationAccessError("TOKEN_KEY_UNAVAILABLE") from error

    @staticmethod
    def _binding(user_id: str, grant_id: str) -> bytes:
        return json.dumps(["ermao-automation-token-v1", user_id, grant_id]).encode()

    def encrypt(
        self, user_id: str, grant_id: str, token: str, *, initialize: bool
    ) -> str:
        cipher = AESGCM(self._key(initialize=initialize))
        nonce = os.urandom(12)
        encrypted = cipher.encrypt(
            nonce, token.encode(), self._binding(user_id, grant_id)
        )
        return "v1:" + base64.b64encode(nonce + encrypted).decode("ascii")

    def decrypt(self, user_id: str, grant_id: str, ciphertext: str) -> str:
        cipher = AESGCM(self._key(initialize=False))
        try:
            if not ciphertext.startswith("v1:"):
                raise ValueError("Unknown envelope")
            payload = base64.b64decode(ciphertext[3:], validate=True)
            return cipher.decrypt(
                payload[:12], payload[12:], self._binding(user_id, grant_id)
            ).decode("utf-8")
        except (ValueError, binascii.Error, InvalidTag) as error:
            raise AutomationAccessError("TOKEN_DECRYPTION_FAILED") from error
