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
    tags: list[str] | None = None
    authors: list[str] | None = None
    publishers: list[str] | None = None
    combinator: Literal["ALL", "ANY"] | None = None
    conditions: list[ShelfCondition] | None = None
    included_book_ids: list[str] | None = Field(default=None, alias="includedBookIds")


class ShelfWriteRequest(HttpContractModel):
    name: str | None = None
    description: str | None = None
    kind: Literal["STATIC", "SMART", "COLLECTION"] | None = None
    rules: ShelfRules | None = None
    pinned: bool | None = None
    book_ids: list[str] | None = Field(default=None, alias="bookIds")
    collection_ids: list[str] | None = Field(default=None, alias="collectionIds")
    member_shelf_ids: list[str] | None = Field(
        default=None,
        alias="memberShelfIds",
    )


class ShelfBook(HttpContractModel):
    id: str
    title: str
    author: str
    cover_url: str = Field(alias="coverUrl")
    progress: float = Field(ge=0, le=100)


class ShelfMemberView(HttpContractModel):
    id: str
    name: str
    description: str | None
    kind: Literal["STATIC", "SMART"]
    pinned: bool
    book_count: int = Field(alias="bookCount")
    books: list[ShelfBook]
    collection_ids: list[str] = Field(alias="collectionIds")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ShelfView(HttpContractModel):
    id: str
    owner_user_id: str | None = Field(default=None, alias="ownerUserId")
    name: str
    description: str | None
    kind: Literal["STATIC", "SMART", "COLLECTION"]
    rules_json: str = Field(alias="rulesJson")
    pinned: bool
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    rules: ShelfRules
    rules_status: Literal["VALID", "UNSUPPORTED"] = Field(alias="rulesStatus")
    unsupported_rule_fields: list[str] = Field(alias="unsupportedRuleFields")
    book_count: int | None = Field(
        default=None,
        alias="bookCount",
        exclude_if=lambda value: value is None,
    )
    books: list[ShelfBook] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    collection_ids: list[str] | None = Field(
        default=None,
        alias="collectionIds",
        exclude_if=lambda value: value is None,
    )
    shelf_count: int | None = Field(
        default=None,
        alias="shelfCount",
        exclude_if=lambda value: value is None,
    )
    shelves: list[ShelfMemberView] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    member_shelf_ids: list[str] | None = Field(
        default=None,
        alias="memberShelfIds",
        exclude_if=lambda value: value is None,
    )
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
