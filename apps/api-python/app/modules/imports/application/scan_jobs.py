"""Preparation contracts for set-based library-root scan scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class PreparedImportScanJob:
    job_id: str
    work_item_id: str
    library_id: str
    actor_user_id: str | None
    root_path: str
    trigger: str
    dedupe_key: str
    available_at: datetime
    created_at: datetime


def prepare_import_scan_job(
    *,
    job_id: str,
    work_item_id: str,
    library_id: str,
    actor_user_id: str | None,
    canonical_root_path: str,
    trigger: str,
    available_at: datetime | None,
    created_at: datetime,
) -> PreparedImportScanJob:
    """Build a complete scan/work row pair before a database Session is opened."""

    path_key = sha256(canonical_root_path.encode("utf-8")).hexdigest()
    return PreparedImportScanJob(
        job_id=job_id,
        work_item_id=work_item_id,
        library_id=library_id,
        actor_user_id=actor_user_id,
        root_path=canonical_root_path,
        trigger=trigger,
        dedupe_key=f"scan:{library_id}:{path_key}",
        available_at=available_at or created_at,
        created_at=created_at,
    )
