"""Application DTOs for organize read use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

OrganizeStatusCategory = Literal["SUCCESS", "FAILED", "RECOGNIZING", "WAITING"]


@dataclass(frozen=True)
class OrganizeBookListItem:
    id: str
    title: str
    author: str
    available_media_kinds: list[str]


@dataclass(frozen=True)
class OrganizeJobListItem:
    id: str
    trigger: str
    status_category: OrganizeStatusCategory
    issue_codes: list[str]
    reason_codes: list[str]
    metadata_sources: list[str]
    created_at: datetime
    updated_at: datetime
    book: OrganizeBookListItem


@dataclass(frozen=True)
class PreparedOrganizeJobEnqueue:
    job_id: str
    task_id: str
    work_id: str
    volume_id: str | None
    version_id: str | None
    provider_order: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PreparedOrganizePolicyUpdate:
    enabled: bool
    schedule_mode: str
    interval_minutes: int
    auto_run_on_new: bool
    auto_run_on_new_since: datetime | None
    rules_json: str
    write_metadata_to_files: bool
    prefer_local_metadata: bool
    local_metadata_priority_json: str
    next_run_at: datetime | None
    updated_at: datetime
