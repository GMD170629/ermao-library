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
