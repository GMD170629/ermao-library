"""Deterministic identity rules for text-conversion retries."""

from __future__ import annotations

import hashlib


def conversion_idempotency_key(
    source_volume_id: str,
    source_hash: str,
    target_format: str = "EPUB",
) -> str:
    """Build the stable identity for one derived-format conversion scope."""

    normalized_target = target_format.strip().upper()
    return hashlib.sha256(
        f"{source_volume_id}|{source_hash.lower()}|{normalized_target}".encode()
    ).hexdigest()
