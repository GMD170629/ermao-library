from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.shelf.domain.errors import ShelfCollectionPolicyError
from app.modules.shelf.domain.policies import (
    ShelfKind,
    validate_collection_members,
)


@dataclass(frozen=True)
class ShelfReference:
    id: str
    kind: ShelfKind
    owner_id: str | None


class ShelfBookMembershipPort(Protocol):
    """Public shelf capability for changing a static shelf's Book links."""

    def add_books(
        self,
        *,
        shelf_id: str,
        book_ids: tuple[str, ...],
        now: datetime,
    ) -> None: ...

    def remove_books(
        self,
        *,
        shelf_id: str,
        book_ids: tuple[str, ...],
    ) -> None: ...


def validate_member_replacement(
    *,
    owner_id: str,
    members: tuple[ShelfReference, ...],
) -> None:
    validate_collection_members(
        collection_owner_id=owner_id,
        members=tuple((member.id, member.kind, member.owner_id) for member in members),
    )


def validate_collection_replacement(
    *,
    owner_id: str,
    collections: tuple[ShelfReference, ...],
) -> None:
    if any(
        collection.kind is not ShelfKind.COLLECTION or collection.owner_id != owner_id
        for collection in collections
    ):
        raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
