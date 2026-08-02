from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MoveVolumeResult:
    source_media_version_id: str
    target_media_version_id: str
    target_work_id: str
    transfer_mode: str
