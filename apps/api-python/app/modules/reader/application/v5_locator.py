"""Immutable value object for a Reader v5 opaque Locator JSON object."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

MAX_OPAQUE_LOCATOR_BYTES = 65_536


def _compact_json(value: object, *, sort_keys: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        sort_keys=sort_keys,
    )


@dataclass(frozen=True, slots=True)
class OpaqueLocator:
    """Serialized Locator with no API for reading arbitrary Locator members.

    ``from_object`` is called by the HTTP mapper after the recursive JSON
    boundary has validated the incoming object.  Persistence rehydrates the
    compact serialized form with ``from_serialized``; neither application path
    needs to inspect Locator keys.
    """

    _serialized: str
    _size_bytes: int
    _digest: str

    @classmethod
    def from_object(cls, value: object) -> OpaqueLocator:
        if not isinstance(value, dict):
            raise TypeError("Reader v5 Locator must be a JSON object")
        serialized = _compact_json(value, sort_keys=True)
        size_bytes = len(serialized.encode("utf-8"))
        if size_bytes > MAX_OPAQUE_LOCATOR_BYTES:
            raise ValueError("Reader v5 Locator exceeds 64 KiB")
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(serialized, size_bytes, digest)

    @classmethod
    def from_serialized(cls, serialized: str) -> OpaqueLocator:
        """Rehydrate trusted storage without opening the Locator object."""

        size_bytes = len(serialized.encode("utf-8"))
        if size_bytes > MAX_OPAQUE_LOCATOR_BYTES:
            raise ValueError("Stored Reader v5 Locator exceeds 64 KiB")
        # Stored v5 rows contain the exact canonical compact representation
        # emitted by ``from_object``. Hashing those bytes is deterministic and
        # avoids making a persistence adapter a Locator-aware parser.
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(serialized, size_bytes, digest)

    @property
    def serialized(self) -> str:
        return self._serialized

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def digest(self) -> str:
        return self._digest


__all__ = ["MAX_OPAQUE_LOCATOR_BYTES", "OpaqueLocator"]
