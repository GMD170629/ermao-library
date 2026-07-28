from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope


FilterValue = str | int | float | bool | list[str] | None


class ShelfCondition(HttpContractModel):
    field: str
    operator: str
    value: FilterValue = None


class ShelfRules(HttpContractModel):
    search: str | None = None
    statuses: list[str] | None = None
    media_kinds: list[str] | None = Field(default=None, alias="mediaKinds")
    tags: list[str] | None = None
    authors: list[str] | None = None
    publishers: list[str] | None = None
    combinator: Literal["ALL", "ANY"] | None = None
    conditions: list[ShelfCondition] | None = None
    included_work_ids: list[str] | None = Field(default=None, alias="includedWorkIds")


class ShelfBook(HttpContractModel):
    id: str
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")


class ShelfView(HttpContractModel):
    id: str
    owner_user_id: str | None = Field(default=None, alias="ownerUserId")
    name: str
    description: str | None
    kind: Literal["STATIC", "SMART"]
    rules_json: str = Field(alias="rulesJson")
    pinned: bool
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    rules: ShelfRules
    book_count: int = Field(alias="bookCount")
    books: list[ShelfBook]
    page: int | None = None
    page_size: int | None = Field(default=None, alias="pageSize")
    total: int | None = None
    total_pages: int | None = Field(default=None, alias="totalPages")
    book_ids: list[str] | None = Field(
        default=None,
        alias="bookIds",
        exclude_if=lambda value: value is None,
    )


class ShelvesPayload(HttpContractModel):
    shelves: list[ShelfView]


class ShelfPayload(HttpContractModel):
    shelf: ShelfView


class DeletedShelfPayload(HttpContractModel):
    deleted: bool
    id: str


ShelvesResponse = SuccessEnvelope[ShelvesPayload]
ShelfResponse = SuccessEnvelope[ShelfPayload]
DeletedShelfResponse = SuccessEnvelope[DeletedShelfPayload]
