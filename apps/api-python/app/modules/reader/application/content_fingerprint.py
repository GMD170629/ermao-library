from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence


def build_volume_content_fingerprint(
    volume: Mapping[str, object],
    files: Sequence[Mapping[str, object]],
) -> str:
    """Build a fingerprint whose identity and inputs are strictly volume-scoped."""

    tokens: list[dict[str, object | None]] = [
        {
            "id": item.get("id"),
            "hash": item.get("fingerprint")
            or item.get("fullHash")
            or item.get("full_hash"),
            "size": item.get("sizeBytes") or item.get("size_bytes"),
            "mtime": item.get("mtimeMs") or item.get("mtime_ms"),
        }
        for item in files
    ]
    if not tokens:
        tokens = [
            {
                "volume": volume.get("id"),
                "updated": str(
                    volume.get("updatedAt") or volume.get("updated_at") or ""
                ),
            }
        ]
    serialized = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
