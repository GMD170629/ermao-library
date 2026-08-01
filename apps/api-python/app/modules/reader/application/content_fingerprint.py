from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence


def build_content_fingerprint(
    edition: Mapping[str, object],
    files: Sequence[Mapping[str, object]],
    volume_id: str | None,
) -> str:
    """Build the stable reader content scope shared by bootstrap and projections."""

    volume_files = [item for item in files if item.get("volumeId") == volume_id]
    selected_files = volume_files if volume_id and volume_files else files
    tokens: list[dict[str, object | None]] = [
        {
            "id": item.get("id"),
            "hash": item.get("fingerprint") or item.get("fullHash"),
            "size": item.get("sizeBytes"),
            "mtime": item.get("mtimeMs"),
        }
        for item in selected_files
    ]
    if not tokens:
        tokens = [
            {
                "edition": edition.get("id"),
                "updated": str(edition.get("updatedAt") or ""),
                "volume": volume_id,
            }
        ]
    serialized = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
